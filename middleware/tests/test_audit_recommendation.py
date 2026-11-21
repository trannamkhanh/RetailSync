"""Regression tests for recommendation audit findings 8 and 9."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core import clock
from app.core.config import settings
from app.domain.models import (
    GuardrailResult, GuardrailRule, Inventory, NearExpiryAlert,
    Product, ProductBatch, Recommendation, StaffDecision, StaffUser, Store,
)
from app.jobs import recommendation as job
from app.repositories.forecast import utc_start
from app.services import guardrail_rules
from tests.pos_test_support import add_stock, uid
from tests.test_recommendation import recommendation_world, recommendations, set_forecast


def test_audit09_exact_rational_demand_clears_batch(db_session, recommendation_world):
    store, sku, batch = recommendation_world
    db_session.get(ProductBatch, batch).quantity = 22
    db_session.get(ProductBatch, batch).expiry_date = clock.today_local() + timedelta(days=13)
    set_forecast(db_session, store, sku, 11)
    db_session.commit()
    assert job.run_recommendations()[store] == 0
    assert recommendations(db_session, store) == []


def test_audit09_expired_alert_does_not_suppress_surplus(db_session, recommendation_world):
    store, sku, batch = recommendation_world
    db_session.get(ProductBatch, batch).expiry_date = clock.today_local() - timedelta(days=1)
    alert = db_session.scalar(select(NearExpiryAlert).where(NearExpiryAlert.batch_id == batch))
    alert.alert_type = "EXPIRED"
    set_forecast(db_session, store, sku, 10, 20)
    db_session.commit()
    assert job.run_recommendations()[store] == 1
    row, = recommendations(db_session, store)
    assert (row.action_type, row.discount_pct, row.batch_id) == ("DISCOUNT", 10, None)


def queued(session, store, sku, batch):
    row = Recommendation(store_id=store, sku=sku, batch_id=batch,
                         action_type="DISCOUNT", discount_pct=15, reason="Test queued",
                         status="GENERATED", created_at=utc_start(clock.today_local() - timedelta(days=1)))
    session.add(row)
    session.commit()
    return row


def test_audit09_sold_out_generated_is_expired(db_session, recommendation_world):
    store, sku, batch = recommendation_world
    row = queued(db_session, store, sku, batch)
    db_session.get(ProductBatch, batch).quantity = 0
    db_session.commit()
    job.run_recommendations()
    db_session.refresh(row)
    assert row.status == "EXPIRED"


def test_audit09_rules_loaded_once_prevents_partial_release(db_session, recommendation_world, monkeypatch):
    store, sku, batch = recommendation_world
    first = queued(db_session, store, sku, batch)
    second = queued(db_session, store, sku, None)
    calls = []
    process = job._process_store
    monkeypatch.setattr(job, "_process_store",
                        lambda session, current, today, forecasts:
                        process(session, current, today, forecasts) if current == store else 0)

    def unstable_rules(session):
        calls.append(1)
        if len(calls) > 1:
            raise RuntimeError("second read failed")
        return []

    monkeypatch.setattr(guardrail_rules, "active_rules", unstable_rules)
    job.run_recommendations()
    db_session.refresh(first)
    db_session.refresh(second)
    assert len(calls) == 1
    assert (first.status, second.status) == ("PENDING", "PENDING")


def test_audit09_first_rule_load_failure_keeps_existing_and_new_rows_generated(
    db_session, recommendation_world, monkeypatch,
):
    store, sku, _ = recommendation_world
    existing = queued(db_session, store, sku, None)
    calls = []

    def unavailable(session):
        calls.append(1)
        raise RuntimeError("first rule read failed")

    monkeypatch.setattr(guardrail_rules, "active_rules", unavailable)
    assert job._process_store(db_session, store, clock.today_local(), []) == 1
    db_session.commit()
    rows = recommendations(db_session, store)
    assert len(calls) == 1
    assert len(rows) == 2
    assert existing.rec_id in {row.rec_id for row in rows}
    assert all(row.status == "GENERATED" for row in rows)
    assert not list(db_session.scalars(select(GuardrailResult).where(
        GuardrailResult.rec_id.in_([row.rec_id for row in rows]),
    )))


def test_audit09_old_generated_blocked_today_is_not_duplicated(db_session, recommendation_world, monkeypatch):
    store, sku, batch = recommendation_world
    today = (datetime.now(timezone.utc) + timedelta(hours=settings.business_utc_offset_hours)).date()
    monkeypatch.setattr(clock, "today_local", lambda: today)
    db_session.get(ProductBatch, batch).expiry_date = today + timedelta(days=1)
    row = queued(db_session, store, sku, batch)
    rule = GuardrailRule(rule_type="MIN_SHELF_LIFE", threshold=2, category=None, is_active=True)
    db_session.add(rule)
    db_session.commit()
    db_session.refresh(rule)
    db_session.expunge(rule)
    db_session.commit()
    monkeypatch.setattr(guardrail_rules, "active_rules", lambda session: [rule])
    assert job.run_recommendations()[store] == 0
    assert job.run_recommendations()[store] == 0
    assert len(recommendations(db_session, store)) == 1


def test_audit08_job_never_overwrites_committed_decision(test_engine, monkeypatch):
    suffix = uid(5)
    store, sku = f"TEST-{suffix}", f"TEST-SKU-{suffix}"
    username = f"TEST-AUDIT-{suffix}"
    today = clock.today_local()
    monkeypatch.setattr(guardrail_rules, "active_rules", lambda session: [])
    with Session(test_engine) as session, session.begin():
        session.add_all([
            Store(store_id=store, name="Audit race", latitude=0, longitude=0, region_id="TEST"),
            Product(sku=sku, barcode=sku, name="Audit", category="TEST", unit_price=10),
        ])
        session.flush()
        session.add(StaffUser(username=username, full_name="Audit staff", role="STORE_STAFF", store_id=store))
        session.flush()
        batch = add_stock(session, store, sku, 0, expiry_date=today - timedelta(days=1))
        row = Recommendation(store_id=store, sku=sku, batch_id=batch, action_type="CLEARANCE",
                             proposed_qty=1, reason="Audit race", status="PENDING")
        session.add(row)
        session.flush()
        rec_id = row.rec_id
        user_id = session.scalar(select(StaffUser.user_id).where(StaffUser.username == username))
    try:
        with Session(test_engine) as session_a:
            get = session_a.get
            decided = []

            def get_after_decision(model, key, *args, **kwargs):
                if model is ProductBatch and not decided:
                    with Session(test_engine) as session_b, session_b.begin():
                        committed = session_b.get(Recommendation, rec_id)
                        committed.status = "ACCEPTED"
                        session_b.add(StaffDecision(rec_id=rec_id, user_id=user_id,
                                                    decision="ACCEPT", decided_at=utc_start(today)))
                    decided.append(True)
                return get(model, key, *args, **kwargs)

            monkeypatch.setattr(session_a, "get", get_after_decision)
            job._process_store(session_a, store, today, [])
            session_a.commit()
            assert decided
        with Session(test_engine) as session:
            assert session.get(Recommendation, rec_id).status == "ACCEPTED"
            assert session.scalar(select(StaffDecision).where(StaffDecision.rec_id == rec_id)) is not None
    finally:
        with Session(test_engine) as session, session.begin():
            session.execute(delete(GuardrailResult).where(GuardrailResult.rec_id == rec_id))
            session.execute(delete(StaffDecision).where(StaffDecision.rec_id == rec_id))
            session.execute(delete(Recommendation).where(Recommendation.rec_id == rec_id))
            session.execute(delete(ProductBatch).where(ProductBatch.store_id == store))
            session.execute(delete(Inventory).where(Inventory.store_id == store))
            session.execute(delete(StaffUser).where(StaffUser.username == username))
            session.execute(delete(Product).where(Product.sku == sku))
            session.execute(delete(Store).where(Store.store_id == store))
