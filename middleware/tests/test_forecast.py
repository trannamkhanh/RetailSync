from datetime import date, timedelta
import logging

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import clock
from app.domain.models import Forecast, PosTerminal, PosTransaction, Product, Store, TransactionItem
from app.jobs import forecast as job
from app.repositories import forecast as repository
from app.repositories.forecast import load_demand
from app.services import forecast
from tests.pos_test_support import add_stock, uid


TODAY = date(2026, 11, 23)


def make_world(db_session, *, store_prefix="TEST-A"):
    suffix = uid(4)
    store = f"{store_prefix}{suffix}"
    pos, sku = f"TEST-POS-{suffix}", f"TEST-SKU-{suffix}"
    db_session.add_all([
        Store(store_id=store, name="Forecast", latitude=0, longitude=0, region_id="TEST"),
        Product(sku=sku, barcode=sku, name="Forecast SKU", category="TEST", unit_price=10),
    ])
    db_session.flush()
    db_session.add(PosTerminal(pos_id=pos, store_id=store, status="ACTIVE"))
    db_session.flush()
    return store, pos, sku


@pytest.fixture
def world(db_session, monkeypatch):
    world = make_world(db_session)
    store = world[0]
    monkeypatch.setattr(clock, "today_local", lambda: TODAY)
    connection = db_session.connection()
    db_session.commit()
    monkeypatch.setattr(job, "session_factory", lambda: Session(bind=connection, join_transaction_mode="create_savepoint"))
    load = repository.load_demand
    monkeypatch.setattr(repository, "load_demand",
                        lambda session, end: [d for d in load(session, end) if d.store == store])
    return world


def seed(session, world, days=42, *, prefix="TEST-", qty=10):
    store, pos, sku = world
    for age in range(days, 0, -1):
        txn = f"{prefix}{store}-{age}"
        session.add(PosTransaction(txn_id=txn, store_id=store, pos_id=pos, txn_type="SALE",
                                   status="OK", payload_hash="a" * 64,
                                   created_at=repository.utc_start(TODAY - timedelta(days=age))))
        session.flush()
        session.add(TransactionItem(txn_id=txn, sku=sku, qty=qty, unit_price=10))
    session.commit()


def saved(session, world):
    session.expire_all()
    return session.scalar(select(Forecast).where(Forecast.store_id == world[0]))


def test_exp22_1_job_stores_seven_day_forecast(db_session, world):
    seed(db_session, world)
    assert job.run_forecast()[world[0]] == 1
    row = saved(db_session, world)
    assert (row.sku, row.horizon_days, row.predicted_demand) == (world[2], 7, 70)


def test_exp22_2_persists_supported_model_version(db_session, world):
    seed(db_session, world)
    assert job.run_forecast()[world[0]] == 1
    assert saved(db_session, world).model_version in {"hgb-v1", "seasonal-naive-v1"}


def test_exp22_3_short_history_is_logged(db_session, world, caplog):
    seed(db_session, world, 27)
    with caplog.at_level(logging.INFO):
        job.run_forecast()
    assert saved(db_session, world) is None
    assert f"{world[0]}/{world[2]} with 27 days" in caplog.text


def test_pb22_daily_demand_fills_missing_days_and_subtracts_reversals(db_session, world):
    seed(db_session, world, 2)
    store, pos, sku = world
    for kind, quantity in [("RETURN", 3), ("CANCELLATION", 2)]:
        txn = f"TEST-{kind}-{store}"
        db_session.add(PosTransaction(txn_id=txn, store_id=store, pos_id=pos, txn_type=kind,
                                      status="OK", payload_hash="a" * 64,
                                      ref_txn_id=f"TEST-{store}-2",
                                      created_at=repository.utc_start(TODAY - timedelta(days=2))))
        db_session.flush()
        db_session.add(TransactionItem(txn_id=txn, sku=sku, qty=quantity, unit_price=10))
    db_session.commit()
    assert repository.load_demand(db_session, TODAY + timedelta(days=1))[0].values == (5, 10, 0)


def test_exp22_4_seasonal_naive_wins_on_weekly_pattern():
    data = repository.Demand("TEST-STORE", "TEST-SKU", "TEST", 10, TODAY, (1, 2, 4, 1, 8, 1, 3) * 6)
    assert forecast.predict_demand([data]) == (forecast.NAIVE, [20])


def test_exp22_5_failed_store_rolls_back_and_keeps_earlier_forecast(db_session, world, monkeypatch, caplog):
    seed(db_session, world)
    assert job.run_forecast()[world[0]] == 1
    prior_id = saved(db_session, world).forecast_id
    db_session.commit()
    other = make_world(db_session, store_prefix="TEST-Z")
    seed(db_session, other)
    monkeypatch.setattr(repository, "load_demand", lambda session, end: [
        demand for demand in load_demand(session, end)
        if demand.store in {world[0], other[0]}
    ])
    monkeypatch.setattr(clock, "today_local", lambda: TODAY + timedelta(days=1))
    save = job._save_store

    def fail_after_flush(session, store, *args):
        count = save(session, store, *args)
        if store == world[0]:
            session.flush()
            raise RuntimeError("forced failure")
        return count

    monkeypatch.setattr(job, "_save_store", fail_after_flush)
    assert job.run_forecast() == {other[0]: 1}
    assert list(db_session.scalars(select(Forecast.forecast_id).where(Forecast.store_id == world[0]))) == [prior_id]
    assert world[0] in caplog.text
    assert saved(db_session, other).sku == other[2]


@pytest.mark.parametrize(("stock", "balance", "status"), [
    (90, 20, "SURPLUS"), (50, -20, "SHORTAGE"), (70, 0, "BALANCED"),
], ids=["EXP23-1", "EXP23-2", "EXP23-3"])
def test_exp23_1_to_3_surplus_shortage_and_balance(db_session, world, stock, balance, status):
    seed(db_session, world)
    add_stock(db_session, world[0], world[2], stock)
    db_session.commit()
    job.run_forecast()
    row = saved(db_session, world)
    assert (row.surplus_shortage, row.balance_status) == (balance, status)


def test_exp23_4_expired_stock_is_excluded(db_session, world):
    seed(db_session, world)
    add_stock(db_session, world[0], world[2], 50)
    add_stock(db_session, world[0], world[2], 40, expiry_date=TODAY - timedelta(days=1))
    db_session.commit()
    job.run_forecast()
    assert saved(db_session, world).surplus_shortage == -20


def test_pb22_same_business_day_keeps_existing_forecast(db_session, world):
    seed(db_session, world)
    assert job.run_forecast()[world[0]] == 1
    first = saved(db_session, world)
    key = first.forecast_id
    db_session.commit()
    assert job.run_forecast()[world[0]] == 0
    assert saved(db_session, world).forecast_id == key


def test_pb22_includes_historical_transactions(db_session, world):
    seed(db_session, world, prefix="HIST-")
    job.run_forecast()
    assert saved(db_session, world).predicted_demand == 70
