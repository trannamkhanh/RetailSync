"""Staff near-expiry alert list (PB-34, STF34-1 to STF34-5).

Every test creates its own stores, batches and alerts with ``TEST-`` ids and
commits inside the ``db_session`` savepoint, which the fixture rolls back, so
nothing stays behind. The listing is read-only, so no cleanup is needed.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import select

from app.core import clock
from app.core.config import settings
from app.core.security import create_token
from app.domain.models import NearExpiryAlert, Product, StaffUser, Store
from tests.pos_test_support import add_stock

TODAY = date(2026, 11, 14)
SECRET = "test-only-secret-with-enough-length-for-hs256"
URL = "/api/v1/near-expiry-alerts"


def _uid(length: int = 5) -> str:
    return uuid4().hex[:length].upper()


@pytest.fixture(autouse=True)
def business_date(monkeypatch) -> None:
    monkeypatch.setattr(clock, "today_local", lambda: TODAY)


@pytest.fixture(autouse=True)
def jwt_secret(monkeypatch) -> None:
    monkeypatch.setattr(settings, "jwt_secret", SecretStr(SECRET))


class World:
    """The caller's store, a second store, and the staff account of the caller."""

    def __init__(self, store_id: str, other_store_id: str, token: str) -> None:
        self.store_id = store_id
        self.other_store_id = other_store_id
        self.token = token

    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}


def _add_store(session, store_id: str) -> Store:
    store = Store(store_id=store_id, name=f"Store {store_id}",
                  latitude=Decimal("16.000000"), longitude=Decimal("108.000000"),
                  region_id="TEST")
    session.add(store)
    session.flush()
    return store


def _make_world(db_session) -> World:
    suffix = _uid()
    store_id = f"TEST-A{suffix[:4]}"
    other_store_id = f"TEST-B{suffix[:4]}"
    _add_store(db_session, store_id)
    _add_store(db_session, other_store_id)
    username = f"TEST-staff-{suffix}"
    db_session.add(StaffUser(username=username, full_name="Alert list staff",
                             role="STORE_STAFF", store_id=store_id))
    db_session.commit()
    return World(store_id, other_store_id,
                 create_token(username, "Staff", store_id=store_id))


@pytest.fixture
def world(db_session) -> World:
    return _make_world(db_session)


def add_alert(db_session, world: World, *, days_left: int, quantity: int = 5,
              stored_days: int | None = None, alert_type: str = "NEAR_EXPIRY",
              status: str = "OPEN", store_id: str | None = None,
              sku: str | None = None) -> NearExpiryAlert:
    """One batch in stock and its alert row, as the daily check would leave them.

    ``stored_days`` is what the last daily check wrote into
    ``days_to_expiry``; it defaults to ``days_left``, the value a check run on
    the business date would have stored.
    """
    store_id = world.store_id if store_id is None else store_id
    sku = f"TEST-SKU-{_uid()}" if sku is None else sku
    db_session.add(Product(sku=sku, barcode=f"BC-{sku}", name="Alert product",
                           category="TEST", unit_price=Decimal("9.50")))
    db_session.flush()
    batch_id = add_stock(db_session, store_id, sku, quantity,
                         expiry_date=TODAY + timedelta(days=days_left))
    alert = NearExpiryAlert(
        batch_id=batch_id, store_id=store_id, sku=sku,
        days_to_expiry=days_left if stored_days is None else stored_days,
        remaining_qty=quantity, alert_type=alert_type, status=status,
    )
    db_session.add(alert)
    db_session.flush()
    return alert


def list_alerts(client, world: World, *, token: str | None = None):
    return client.get(URL, headers={"Authorization": f"Bearer {token or world.token}"})


def assert_rejected(response, status: int, code: str) -> None:
    assert response.status_code == status, response.text
    body = response.json()
    assert set(body) == {"outcome", "code", "message"}
    assert (body["outcome"], body["code"]) == ("REJECTED", code)


# STF34-1


def test_stf34_1_alerts_are_ordered_expired_first_then_fewest_days(client, db_session, world):
    expired = add_alert(db_session, world, days_left=-2, alert_type="EXPIRED")
    soon = add_alert(db_session, world, days_left=1)
    later = add_alert(db_session, world, days_left=3)
    tie = add_alert(db_session, world, days_left=1)
    db_session.commit()

    body = list_alerts(client, world).json()

    assert [item["alert_id"] for item in body["items"]] == [
        expired.alert_id, soon.alert_id, tie.alert_id, later.alert_id,
    ]
    assert body["items"][0]["alert_type"] == "EXPIRED"
    assert [item["days_to_expiry"] for item in body["items"]] == [-2, 1, 1, 3]


def test_stf34_1_every_row_carries_the_batch_fields(client, db_session, world):
    alert = add_alert(db_session, world, days_left=2, quantity=7)
    db_session.commit()

    body = list_alerts(client, world).json()

    assert body["items"] == [{
        "alert_id": alert.alert_id,
        "batch_id": alert.batch_id,
        "sku": alert.sku,
        "expiry_date": (TODAY + timedelta(days=2)).isoformat(),
        "remaining_qty": 7,
        "days_to_expiry": 2,
        "alert_type": "NEAR_EXPIRY",
    }]


# STF34-2


def test_stf34_2_days_are_recalculated_when_the_date_moves(client, db_session, world,
                                                           monkeypatch):
    alert = add_alert(db_session, world, days_left=5)
    db_session.commit()

    first = list_alerts(client, world).json()["items"][0]
    monkeypatch.setattr(clock, "today_local", lambda: TODAY + timedelta(days=2))
    second = list_alerts(client, world).json()["items"][0]

    assert first["days_to_expiry"] == 5
    assert second["days_to_expiry"] == 3
    assert second["alert_type"] == "NEAR_EXPIRY"


# STF34-3


def test_stf34_3_only_the_caller_store_is_listed(client, db_session, world):
    own = add_alert(db_session, world, days_left=1)
    add_alert(db_session, world, days_left=2, store_id=world.other_store_id)
    db_session.commit()

    body = list_alerts(client, world).json()

    assert [item["alert_id"] for item in body["items"]] == [own.alert_id]


# STF34-4


def test_stf34_4_no_open_alert_returns_an_empty_list(client, db_session, world):
    db_session.commit()

    response = list_alerts(client, world)

    assert response.status_code == 200, response.text
    assert response.json() == {"items": []}


# STF34-5


def test_stf34_5_a_missing_token_is_unauthorized(client, db_session, world):
    db_session.commit()

    response = client.get(URL)

    assert_rejected(response, 401, "UNAUTHORIZED")


def test_stf34_5_an_auditor_is_forbidden(client, db_session, world):
    suffix = _uid()
    db_session.add(StaffUser(username=f"TEST-auditor-{suffix}", full_name="Auditor",
                             role="AUDITOR"))
    db_session.commit()

    response = list_alerts(client, world,
                           token=create_token(f"TEST-auditor-{suffix}", "Auditor"))

    assert_rejected(response, 403, "FORBIDDEN")


def test_stf34_5_a_staff_account_without_a_store_is_forbidden(client, db_session, world):
    suffix = _uid()
    db_session.add(StaffUser(username=f"TEST-nostore-{suffix}", full_name="No store",
                             role="STORE_STAFF"))
    db_session.commit()

    response = list_alerts(client, world,
                           token=create_token(f"TEST-nostore-{suffix}", "Staff"))

    assert_rejected(response, 403, "FORBIDDEN")


# PB-34 cases without a sheet id


def test_pb34_an_alert_whose_batch_expired_after_the_last_check_is_shown_as_expired(
        client, db_session, world):
    """The last daily check saw one day left; the batch has expired since."""
    alert = add_alert(db_session, world, days_left=-1, stored_days=1,
                      alert_type="NEAR_EXPIRY")
    db_session.commit()

    body = list_alerts(client, world).json()

    assert body["items"] == [{
        "alert_id": alert.alert_id,
        "batch_id": alert.batch_id,
        "sku": alert.sku,
        "expiry_date": (TODAY - timedelta(days=1)).isoformat(),
        "remaining_qty": 5,
        "days_to_expiry": -1,
        "alert_type": "EXPIRED",
    }]


def test_pb34_a_resolved_alert_is_not_listed(client, db_session, world):
    resolved = add_alert(db_session, world, days_left=1, status="RESOLVED")
    open_alert = add_alert(db_session, world, days_left=4)
    db_session.commit()

    body = list_alerts(client, world).json()

    assert [item["alert_id"] for item in body["items"]] == [open_alert.alert_id]
    assert resolved.alert_id not in [item["alert_id"] for item in body["items"]]


def test_pb34_the_listing_changes_nothing(client, db_session, world):
    add_alert(db_session, world, days_left=1)
    add_alert(db_session, world, days_left=-3, alert_type="EXPIRED")
    db_session.commit()
    before = db_session.execute(
        select(NearExpiryAlert.alert_id, NearExpiryAlert.days_to_expiry,
               NearExpiryAlert.remaining_qty, NearExpiryAlert.alert_type,
               NearExpiryAlert.status)
        .where(NearExpiryAlert.store_id == world.store_id)
        .order_by(NearExpiryAlert.alert_id)
    ).all()

    response = list_alerts(client, world)

    assert response.status_code == 200, response.text
    assert db_session.execute(
        select(NearExpiryAlert.alert_id, NearExpiryAlert.days_to_expiry,
               NearExpiryAlert.remaining_qty, NearExpiryAlert.alert_type,
               NearExpiryAlert.status)
        .where(NearExpiryAlert.store_id == world.store_id)
        .order_by(NearExpiryAlert.alert_id)
    ).all() == before
    assert not db_session.new and not db_session.dirty and not db_session.deleted
