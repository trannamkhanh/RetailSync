"""Near-expiry thresholds and the daily check (PB-21, EXP21-1 to EXP21-10).

The job tests point ``app.jobs.near_expiry.session_factory`` at RTS_DB_TEST and
fix ``app.core.clock.today_local``, as ``tests/test_aggregation.py`` does, so no
run touches the database the middleware serves. Every row they create has a
``TEST-`` id and is deleted afterwards.

Each run is limited to the test's own stores, so the test database keeps no
alerts for the seeded demo stores either.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.core import clock
from app.core.config import settings
from app.core.security import create_token
from app.domain.models import (
    Inventory,
    NearExpiryAlert,
    NearExpiryConfig,
    Product,
    ProductBatch,
    StaffUser,
    Store,
)
from app.jobs import near_expiry as job
from app.repositories import near_expiry as repository
from app.services import near_expiry as service
from tests.pos_test_support import add_stock

TODAY = date(2026, 11, 14)
SECRET = "test-only-secret-with-enough-length-for-hs256"
ADMIN = "TEST-ne-admin"
THRESHOLDS_URL = "/api/v1/admin/near-expiry-thresholds"
THRESHOLD_URL = "/api/v1/admin/near-expiry-thresholds/{category}"


def _uid(length: int = 6) -> str:
    return uuid4().hex[:length].upper()


@pytest.fixture(autouse=True)
def business_date(monkeypatch) -> None:
    """A fixed business date, so every expiry comparison is deterministic."""
    monkeypatch.setattr(clock, "today_local", lambda: TODAY)


@pytest.fixture(autouse=True)
def job_database(monkeypatch, test_engine) -> None:
    """The job writes to RTS_DB_TEST, never to DB_NAME."""

    def factory() -> Session:
        return Session(bind=test_engine)

    monkeypatch.setattr(job, "session_factory", factory)


@pytest.fixture
def admin(db_session: Session) -> StaffUser:
    user = StaffUser(username=ADMIN, full_name="Near-expiry admin", role="ADMIN")
    db_session.add(user)
    db_session.flush()
    db_session.commit()
    return user


@pytest.fixture
def admin_headers(monkeypatch, admin: StaffUser) -> dict[str, str]:
    monkeypatch.setattr(settings, "jwt_secret", SecretStr(SECRET))
    return {"Authorization": f"Bearer {create_token(ADMIN, 'Admin')}"}


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def assert_rejected(response, status: int, code: str) -> dict:
    assert response.status_code == status, response.text
    body = response.json()
    assert set(body) == {"outcome", "code", "message"}
    assert (body["outcome"], body["code"]) == ("REJECTED", code)
    assert body["message"]
    return body


@dataclass(frozen=True)
class Shop:
    """One test store with one product and one batch per entry."""

    store_id: str
    category: str
    skus: tuple[str, ...]


def _create_shop(batches: list[tuple[int, int]], *, category: str,
                 threshold_days: int | None) -> Shop:
    """Commit a store whose batches are ``(days_from_today, quantity)``.

    A category with ``threshold_days`` gets a ``near_expiry_config`` row, so the
    test controls the window instead of relying on the seeded categories.
    """
    store_id = f"TEST-{_uid(5)}"
    skus = []
    with job.session_factory() as session:
        session.add(Store(store_id=store_id, name="Near-expiry test store",
                          latitude=Decimal("16.000000"), longitude=Decimal("108.000000"),
                          region_id="TEST"))
        session.flush()
        for days, quantity in batches:
            sku = f"TEST-{_uid(6)}"
            skus.append(sku)
            session.add(Product(sku=sku, barcode=f"BC-{sku}", name="Near-expiry product",
                                category=category, unit_price=Decimal("10.00")))
            session.flush()
            add_stock(session, store_id, sku, quantity,
                      expiry_date=TODAY + timedelta(days=days))
        if threshold_days is not None:
            session.merge(NearExpiryConfig(category=category, threshold_days=threshold_days))
        session.commit()
    return Shop(store_id, category, tuple(skus))


def _delete_test_rows(store_ids: list[str], skus: list[str], categories: list[str]) -> None:
    """Delete everything a job test committed, children first."""
    with job.session_factory() as session:
        if store_ids:
            session.execute(delete(NearExpiryAlert).where(
                NearExpiryAlert.batch_id.in_(select(ProductBatch.batch_id).where(
                    ProductBatch.store_id.in_(store_ids)))))
            session.execute(delete(ProductBatch).where(
                ProductBatch.store_id.in_(store_ids)))
            session.execute(delete(Inventory).where(Inventory.store_id.in_(store_ids)))
            session.execute(delete(Store).where(Store.store_id.in_(store_ids)))
        if skus:
            session.execute(delete(Product).where(Product.sku.in_(skus)))
        if categories:
            session.execute(delete(NearExpiryConfig).where(
                NearExpiryConfig.category.in_(categories)))
        session.commit()


def _run_job(monkeypatch, store_ids: list[str]) -> dict[str, service.StoreCheck]:
    """Run the job over the given stores only."""
    monkeypatch.setattr(repository, "list_store_ids", lambda session: list(store_ids))
    return job.run_near_expiry_check()


def _alerts(store_id: str) -> list[NearExpiryAlert]:
    with job.session_factory() as session:
        return list(session.scalars(
            select(NearExpiryAlert)
            .where(NearExpiryAlert.store_id == store_id)
            .order_by(NearExpiryAlert.batch_id)
        ))


def _stock_snapshot(store_ids: list[str]) -> list[tuple]:
    with job.session_factory() as session:
        inventory = session.execute(
            select(Inventory.store_id, Inventory.sku, Inventory.quantity)
            .where(Inventory.store_id.in_(store_ids))
            .order_by(Inventory.store_id, Inventory.sku)
        ).all()
        batches = session.execute(
            select(ProductBatch.store_id, ProductBatch.batch_id, ProductBatch.quantity)
            .where(ProductBatch.store_id.in_(store_ids))
            .order_by(ProductBatch.store_id, ProductBatch.batch_id)
        ).all()
        return [tuple(row) for row in inventory] + [tuple(row) for row in batches]


def _set_expiry(store_id: str, expiry: date) -> None:
    with job.session_factory() as session:
        session.execute(update(ProductBatch)
                        .where(ProductBatch.store_id == store_id)
                        .values(expiry_date=expiry))
        session.commit()


def _sell_out(shop: Shop) -> None:
    with job.session_factory() as session:
        session.execute(update(ProductBatch)
                        .where(ProductBatch.store_id == shop.store_id)
                        .values(quantity=0))
        session.execute(update(Inventory)
                        .where(Inventory.store_id == shop.store_id)
                        .values(quantity=0))
        session.commit()


def _restock(shop: Shop, extra: int) -> None:
    """A RETURN puts units back into the batch without changing its expiry."""
    with job.session_factory() as session:
        session.execute(update(ProductBatch)
                        .where(ProductBatch.store_id == shop.store_id)
                        .values(quantity=ProductBatch.quantity + extra))
        session.execute(update(Inventory)
                        .where(Inventory.store_id == shop.store_id)
                        .values(quantity=Inventory.quantity + extra))
        session.commit()


# Threshold Admin API: EXP21-1 to EXP21-3


def test_exp21_1_admin_sets_a_threshold(client, db_session, admin_headers):
    category = f"TEST-{_uid(5)}"

    response = client.put(THRESHOLD_URL.format(category=category), headers=admin_headers,
                          json={"threshold_days": 3})

    assert response.status_code == 200, response.text
    assert response.json() == {"category": category, "threshold_days": 3}
    db_session.expire_all()
    stored = db_session.scalar(
        select(NearExpiryConfig).where(NearExpiryConfig.category == category))
    assert stored is not None and stored.threshold_days == 3
    assert stored.updated_by is not None and stored.updated_at is not None


def test_exp21_1_an_existing_threshold_is_listed_and_updated(client, db_session, admin_headers):
    category = f"TEST-{_uid(5)}"
    db_session.add(NearExpiryConfig(category=category, threshold_days=5))
    db_session.commit()

    listed = client.get(THRESHOLDS_URL, headers=admin_headers)
    updated = client.put(THRESHOLD_URL.format(category=category), headers=admin_headers,
                         json={"threshold_days": 7})

    assert listed.status_code == 200, listed.text
    items = {item["category"]: item["threshold_days"] for item in listed.json()["items"]}
    assert items[category] == 5
    assert updated.status_code == 200, updated.text
    assert updated.json()["threshold_days"] == 7


@pytest.mark.parametrize("value", [-1, 3651, 3.5, "3", True, None, [3], {"days": 3}])
def test_exp21_2_invalid_thresholds_are_rejected_and_change_nothing(
        client, db_session, admin_headers, value):
    category = f"TEST-{_uid(5)}"
    db_session.add(NearExpiryConfig(category=category, threshold_days=4))
    db_session.commit()

    response = client.put(THRESHOLD_URL.format(category=category), headers=admin_headers,
                          json={"threshold_days": value})

    assert_rejected(response, 422, "VALIDATION_ERROR")
    db_session.expire_all()
    assert db_session.scalar(
        select(NearExpiryConfig.threshold_days)
        .where(NearExpiryConfig.category == category)) == 4


def test_exp21_2_a_missing_body_is_rejected(client, db_session, admin_headers):
    category = f"TEST-{_uid(5)}"
    db_session.add(NearExpiryConfig(category=category, threshold_days=4))
    db_session.commit()

    response = client.put(THRESHOLD_URL.format(category=category), headers=admin_headers,
                          json={})

    assert_rejected(response, 422, "VALIDATION_ERROR")
    db_session.expire_all()
    assert db_session.scalar(
        select(NearExpiryConfig.threshold_days)
        .where(NearExpiryConfig.category == category)) == 4


def test_exp21_2_the_boundaries_are_accepted(client, admin_headers):
    category = f"TEST-{_uid(5)}"

    for value in (0, 3650):
        response = client.put(THRESHOLD_URL.format(category=category), headers=admin_headers,
                              json={"threshold_days": value})
        assert response.status_code == 200, response.text
        assert response.json()["threshold_days"] == value


def test_exp21_2_a_bad_category_is_rejected(client, admin_headers):
    response = client.put(THRESHOLD_URL.format(category="bad_category!"), headers=admin_headers,
                          json={"threshold_days": 3})

    assert_rejected(response, 422, "VALIDATION_ERROR")


def test_exp21_3_only_admin_may_set_a_threshold(client, db_session):
    staff = StaffUser(username=f"TEST-staff-{_uid(5)}", full_name="Store staff",
                      role="STORE_STAFF", store_id=None)
    db_session.add(staff)
    db_session.commit()
    headers = bearer(create_token(staff.username, "Staff"))

    response = client.put(THRESHOLD_URL.format(category="Dairy"), headers=headers,
                          json={"threshold_days": 3})

    assert_rejected(response, 403, "FORBIDDEN")
    assert client.get(THRESHOLDS_URL, headers=headers).json()["code"] == "FORBIDDEN"


# The daily check: EXP21-4 to EXP21-10


def test_exp21_4_a_batch_inside_the_threshold_gets_one_open_alert(monkeypatch):
    category = f"TEST-{_uid(5)}"
    shop = _create_shop([(2, 5)], category=category, threshold_days=3)
    try:
        result = _run_job(monkeypatch, [shop.store_id])

        alerts = _alerts(shop.store_id)
        assert len(alerts) == 1
        alert = alerts[0]
        assert (alert.status, alert.alert_type, alert.days_to_expiry) == (
            "OPEN", "NEAR_EXPIRY", 2)
        assert (alert.remaining_qty, alert.sku) == (5, shop.skus[0])
        assert result[shop.store_id].created == 1
    finally:
        _delete_test_rows([shop.store_id], list(shop.skus), [category])


def test_exp21_5_a_batch_outside_the_threshold_gets_no_alert(monkeypatch):
    category = f"TEST-{_uid(5)}"
    shop = _create_shop([(10, 5)], category=category, threshold_days=3)
    try:
        result = _run_job(monkeypatch, [shop.store_id])

        assert _alerts(shop.store_id) == []
        assert result[shop.store_id].created == 0
    finally:
        _delete_test_rows([shop.store_id], list(shop.skus), [category])


def test_exp21_6_a_second_run_adds_no_duplicate_open_alert(monkeypatch):
    category = f"TEST-{_uid(5)}"
    shop = _create_shop([(2, 5)], category=category, threshold_days=3)
    try:
        _run_job(monkeypatch, [shop.store_id])
        first = _alerts(shop.store_id)

        result = _run_job(monkeypatch, [shop.store_id])

        second = _alerts(shop.store_id)
        assert [alert.alert_id for alert in second] == [alert.alert_id for alert in first]
        assert result[shop.store_id] == service.StoreCheck()
    finally:
        _delete_test_rows([shop.store_id], list(shop.skus), [category])


def test_exp21_7_an_expired_batch_gets_an_expired_alert(monkeypatch):
    category = f"TEST-{_uid(5)}"
    shop = _create_shop([(-1, 5)], category=category, threshold_days=3)
    try:
        _run_job(monkeypatch, [shop.store_id])

        alerts = _alerts(shop.store_id)
        assert [(alert.alert_type, alert.status, alert.days_to_expiry) for alert in alerts] == [
            ("EXPIRED", "OPEN", -1)]
    finally:
        _delete_test_rows([shop.store_id], list(shop.skus), [category])


def test_exp21_8_an_open_alert_becomes_expired(monkeypatch):
    category = f"TEST-{_uid(5)}"
    shop = _create_shop([(2, 5)], category=category, threshold_days=3)
    try:
        _run_job(monkeypatch, [shop.store_id])
        assert [alert.alert_type for alert in _alerts(shop.store_id)] == ["NEAR_EXPIRY"]

        _set_expiry(shop.store_id, TODAY - timedelta(days=1))
        result = _run_job(monkeypatch, [shop.store_id])

        alerts = _alerts(shop.store_id)
        assert len(alerts) == 1
        assert (alerts[0].alert_type, alerts[0].status, alerts[0].days_to_expiry) == (
            "EXPIRED", "OPEN", -1)
        assert result[shop.store_id].expired == 1
    finally:
        _delete_test_rows([shop.store_id], list(shop.skus), [category])


def test_exp21_9_an_alert_is_resolved_when_the_batch_sells_out(monkeypatch):
    category = f"TEST-{_uid(5)}"
    shop = _create_shop([(2, 5)], category=category, threshold_days=3)
    try:
        _run_job(monkeypatch, [shop.store_id])

        _sell_out(shop)
        result = _run_job(monkeypatch, [shop.store_id])

        alerts = _alerts(shop.store_id)
        assert [(alert.status, alert.remaining_qty) for alert in alerts] == [("RESOLVED", 0)]
        assert result[shop.store_id].resolved == 1
    finally:
        _delete_test_rows([shop.store_id], list(shop.skus), [category])


def test_exp21_10_a_failed_store_rolls_back_without_touching_stock(monkeypatch):
    category = f"TEST-{_uid(5)}"
    failing = _create_shop([(2, 5)], category=category, threshold_days=3)
    healthy = _create_shop([(2, 4)], category=category, threshold_days=3)
    stores = [failing.store_id, healthy.store_id]
    try:
        before = _stock_snapshot(stores)
        real = repository.list_batches_in_stock

        def broken(session, store_id):
            batches = real(session, store_id)
            if store_id == failing.store_id:
                # An unknown SKU breaks the alert's foreign key when the store's
                # transaction flushes, so that store has to roll back.
                batches.append(repository.StockBatch(
                    batch_id=f"TEST-{_uid(8)}", sku=f"TEST-NOSKU-{_uid(4)}",
                    category=category, expiry_date=TODAY + timedelta(days=1), quantity=1))
            return batches

        monkeypatch.setattr(repository, "list_batches_in_stock", broken)
        result = _run_job(monkeypatch, stores)

        assert _alerts(failing.store_id) == []
        assert len(_alerts(healthy.store_id)) == 1
        assert failing.store_id not in result
        assert result[healthy.store_id].created == 1
        assert _stock_snapshot(stores) == before
    finally:
        _delete_test_rows(stores, [*failing.skus, *healthy.skus], [category])


# PB-21 scenarios without a sheet id


def test_pb21_a_batch_expiring_today_is_near_expiry_with_zero_days(monkeypatch):
    category = f"TEST-{_uid(5)}"
    shop = _create_shop([(0, 3)], category=category, threshold_days=3)
    try:
        _run_job(monkeypatch, [shop.store_id])

        alert = _alerts(shop.store_id)[0]
        assert (alert.alert_type, alert.days_to_expiry) == ("NEAR_EXPIRY", 0)
    finally:
        _delete_test_rows([shop.store_id], list(shop.skus), [category])


def test_pb21_a_threshold_of_zero_alerts_only_today(monkeypatch):
    category = f"TEST-{_uid(5)}"
    shop = _create_shop([(0, 3), (1, 3)], category=category, threshold_days=0)
    try:
        _run_job(monkeypatch, [shop.store_id])

        alerts = _alerts(shop.store_id)
        assert [(alert.sku, alert.days_to_expiry, alert.alert_type) for alert in alerts] == [
            (shop.skus[0], 0, "NEAR_EXPIRY")]
    finally:
        _delete_test_rows([shop.store_id], list(shop.skus), [category])


def test_pb21_a_category_without_config_uses_the_default(monkeypatch):
    monkeypatch.setattr(settings, "near_expiry_default_days", 3)
    category = f"TEST-{_uid(5)}"
    shop = _create_shop([(3, 3), (4, 3)], category=category, threshold_days=None)
    try:
        _run_job(monkeypatch, [shop.store_id])

        alerts = _alerts(shop.store_id)
        assert [(alert.sku, alert.days_to_expiry) for alert in alerts] == [(shop.skus[0], 3)]
    finally:
        _delete_test_rows([shop.store_id], list(shop.skus), [category])


def test_pb21_a_restocked_batch_keeps_its_one_open_alert(monkeypatch):
    category = f"TEST-{_uid(5)}"
    shop = _create_shop([(2, 2)], category=category, threshold_days=3)
    try:
        _run_job(monkeypatch, [shop.store_id])

        _restock(shop, extra=4)
        result = _run_job(monkeypatch, [shop.store_id])

        alerts = _alerts(shop.store_id)
        assert len(alerts) == 1
        assert (alerts[0].status, alerts[0].remaining_qty) == ("OPEN", 6)
        assert result[shop.store_id] == service.StoreCheck()
    finally:
        _delete_test_rows([shop.store_id], list(shop.skus), [category])


def test_pb21_the_registry_runs_the_check_at_00_30():
    import importlib

    from app.jobs.scheduler import registered_jobs

    importlib.import_module("app.jobs.registry")  # importing registers the jobs
    definition = next(entry for entry in registered_jobs() if entry.name == "near-expiry")
    assert definition.daily_at == time(0, 30)
    assert definition.run is job.run_near_expiry_check


def test_pb21_a_rejected_threshold_writes_no_row(client, admin_headers):
    category = f"TEST-{_uid(5)}"

    client.put(THRESHOLD_URL.format(category=category), headers=admin_headers,
               json={"threshold_days": -2})

    with job.session_factory() as session:
        assert session.scalar(select(NearExpiryConfig).where(
            NearExpiryConfig.category == category)) is None
