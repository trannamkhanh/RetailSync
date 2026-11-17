"""Staff recommendation list and detail (PB-32, STF32-1 to STF32-6).

Every test creates its own stores, products, batches, recommendations and
guardrail results with ``TEST-`` ids and commits inside the ``db_session``
savepoint, which the fixture rolls back, so nothing stays behind.
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
from app.domain.models import (
    GuardrailResult,
    GuardrailRule,
    Product,
    ProductBatch,
    Recommendation,
    StaffUser,
    Store,
)

TODAY = date(2026, 11, 17)
SECRET = "test-only-secret-with-enough-length-for-hs256"
LIST_URL = "/api/v1/recommendations"


def _uid(length: int = 5) -> str:
    return uuid4().hex[:length].upper()


@pytest.fixture(autouse=True)
def business_date(monkeypatch) -> None:
    monkeypatch.setattr(clock, "today_local", lambda: TODAY)


@pytest.fixture(autouse=True)
def jwt_secret(monkeypatch) -> None:
    monkeypatch.setattr(settings, "jwt_secret", SecretStr(SECRET))


class World:
    """The caller's store, another store, and the staff account of the caller."""

    def __init__(self, store_id: str, other_store_id: str, token: str) -> None:
        self.store_id = store_id
        self.other_store_id = other_store_id
        self.token = token

    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}


def _add_store(session, store_id: str) -> Store:
    store = Store(store_id=store_id, name=f"Store {store_id}",
                  latitude=16.0678, longitude=108.2208, region_id="TEST")
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
    db_session.add(StaffUser(username=username, full_name="Recommendation staff",
                             role="STORE_STAFF", store_id=store_id))
    db_session.commit()
    return World(store_id, other_store_id,
                 create_token(username, "Staff", store_id=store_id))


@pytest.fixture
def world(db_session) -> World:
    return _make_world(db_session)


def add_recommendation(db_session, world: World, *, rec_id: int | None = None,
                       store_id: str | None = None, sku: str | None = None,
                       batch_id: str | None = None, action_type: str = "DISCOUNT",
                       discount_pct: Decimal | None = Decimal("50"),
                       proposed_qty: int | None = None, reason: str = "Near expiry",
                       status: str = "PENDING", guardrail: bool = True) -> Recommendation:
    """One recommendation, optionally with one guardrail result, as PB-27 leaves it.

    ``rec_id`` is normally assigned by the identity column; pass one only when a
    test needs to address the row before it exists.
    """
    store_id = world.store_id if store_id is None else store_id
    sku = f"TEST-SKU-{_uid()}" if sku is None else sku
    db_session.add(Product(sku=sku, barcode=f"BC-{sku}", name="Recommendation product",
                           category="TEST", unit_price=Decimal("10.00")))
    db_session.flush()
    if batch_id is None and action_type != "REDISTRIBUTION":
        batch_id = f"TEST-BATCH-{_uid()}"
        db_session.add(ProductBatch(batch_id=batch_id, sku=sku, store_id=store_id,
                                    expiry_date=TODAY + timedelta(days=5), quantity=10))
        db_session.flush()
    rec = Recommendation(
        store_id=store_id, sku=sku, batch_id=batch_id, action_type=action_type,
        discount_pct=discount_pct, proposed_qty=proposed_qty, reason=reason,
        status=status,
    )
    if rec_id is not None:
        rec.rec_id = rec_id
    db_session.add(rec)
    db_session.flush()
    if guardrail:
        rule = GuardrailRule(rule_type="MAX_DISCOUNT", threshold=Decimal("10.00"),
                             category="TEST", is_active=True)
        db_session.add(rule)
        db_session.flush()
        db_session.add(GuardrailResult(
            rec_id=rec.rec_id, rule_id=rule.rule_id, outcome="PASSED",
            original_value=None, adjusted_value=None, message=None,
        ))
    db_session.flush()
    return rec


def get_recommendations(client, world: World):
    return client.get(LIST_URL, headers=world.headers())


def assert_rejected(response, status: int, code: str) -> None:
    assert response.status_code == status, response.text
    body = response.json()
    assert set(body) == {"outcome", "code", "message"}
    assert (body["outcome"], body["code"]) == ("REJECTED", code)


# STF32-1


def test_stf32_1_the_list_shows_pending_only(client, db_session, world):
    pending = add_recommendation(db_session, world, action_type="DISCOUNT",
                                 discount_pct=Decimal("30"))
    add_recommendation(db_session, world, status="GENERATED")
    add_recommendation(db_session, world, status="BLOCKED")
    add_recommendation(db_session, world, status="ACCEPTED")
    add_recommendation(db_session, world, status="REJECTED")
    db_session.commit()

    body = get_recommendations(client, world).json()

    assert [item["rec_id"] for item in body] == [pending.rec_id]
    assert body[0]["status"] == "PENDING"


def test_stf32_1_another_store_is_not_listed(client, db_session, world):
    own = add_recommendation(db_session, world)
    add_recommendation(db_session, world, store_id=world.other_store_id)
    db_session.commit()

    body = get_recommendations(client, world).json()

    assert [item["rec_id"] for item in body] == [own.rec_id]


# STF32-2


def test_stf32_2_the_detail_carries_reason_action_expiry_and_guardrails(
        client, db_session, world):
    rec = add_recommendation(db_session, world, action_type="DISCOUNT",
                             discount_pct=Decimal("50"))
    db_session.commit()

    response = client.get(f"/api/v1/recommendations/{rec.rec_id}",
                          headers=world.headers())

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["rec_id"] == rec.rec_id
    assert body["sku"] == rec.sku
    assert body["action_type"] == "DISCOUNT"
    assert body["discount_pct"] == "50.00"
    assert body["status"] == "PENDING"
    assert body["reason"] == "Near expiry"
    assert body["expiry_date"] == (TODAY + timedelta(days=5)).isoformat()
    assert body["guardrail_results"] == [{
        "rule_type": "MAX_DISCOUNT", "outcome": "PASSED",
        "original_value": None, "adjusted_value": None, "message": None,
    }]


# STF32-3


def test_stf32_3_no_pending_returns_an_empty_list(client, db_session, world):
    add_recommendation(db_session, world, status="ACCEPTED")
    add_recommendation(db_session, world, status="BLOCKED")
    db_session.commit()

    response = get_recommendations(client, world)

    assert response.status_code == 200, response.text
    assert response.json() == []


# STF32-4


def test_stf32_4_another_store_is_404(client, db_session, world):
    foreign = add_recommendation(db_session, world, store_id=world.other_store_id)
    db_session.commit()

    response = client.get(f"/api/v1/recommendations/{foreign.rec_id}",
                          headers=world.headers())

    assert_rejected(response, 404, "NOT_FOUND")


# STF32-5


def test_stf32_5_a_sold_out_batch_is_hidden(client, db_session, world):
    rec = add_recommendation(db_session, world)
    batch = db_session.get(ProductBatch, rec.batch_id)
    batch.quantity = 0
    db_session.commit()

    body = get_recommendations(client, world).json()

    assert body == []

    response = client.get(f"/api/v1/recommendations/{rec.rec_id}",
                          headers=world.headers())
    assert_rejected(response, 404, "NOT_FOUND")


# STF32-6


def test_stf32_6_a_missing_token_is_unauthorized(client, db_session, world):
    add_recommendation(db_session, world)
    db_session.commit()

    response = client.get(LIST_URL)

    assert_rejected(response, 401, "UNAUTHORIZED")


def test_stf32_6_a_manager_is_forbidden(client, db_session, world):
    add_recommendation(db_session, world)
    db_session.commit()
    username = f"TEST-manager-{_uid()}"
    db_session.add(StaffUser(username=username, full_name="Manager",
                             role="STORE_MANAGER", store_id=world.store_id))
    db_session.commit()

    response = client.get(LIST_URL, headers={
        "Authorization": f"Bearer {create_token(username, 'Manager', store_id=world.store_id)}"})

    assert_rejected(response, 403, "FORBIDDEN")


# PB-32 cases without a sheet id


def test_pb32_a_listed_recommendation_keeps_its_proposed_qty_for_clearance(
        client, db_session, world):
    rec = add_recommendation(db_session, world, action_type="CLEARANCE",
                             discount_pct=None, proposed_qty=7)
    db_session.commit()

    body = get_recommendations(client, world).json()

    assert body[0]["proposed_qty"] == 7
    assert body[0]["discount_pct"] is None


def test_pb32_the_list_is_read_only(client, db_session, world):
    add_recommendation(db_session, world)
    before = db_session.execute(
        select(Recommendation.rec_id, Recommendation.status)
        .order_by(Recommendation.rec_id)
    ).all()

    response = get_recommendations(client, world)

    assert response.status_code == 200, response.text
    assert db_session.execute(
        select(Recommendation.rec_id, Recommendation.status)
        .order_by(Recommendation.rec_id)
    ).all() == before
    assert not db_session.new and not db_session.dirty and not db_session.deleted