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
                  latitude=Decimal("16.067800"), longitude=Decimal("108.220800"),
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
    db_session.add(StaffUser(username=username, full_name="Recommendation staff",
                             role="STORE_STAFF", store_id=store_id))
    db_session.commit()
    return World(store_id, other_store_id,
                 create_token(username, "Staff", store_id=store_id))


@pytest.fixture
def world(db_session) -> World:
    return _make_world(db_session)


def add_recommendation(db_session, world: World, *, store_id: str | None = None,
                       sku: str | None = None, batch_id: str | None = None,
                       with_batch: bool = True, batch_quantity: int = 10,
                       batch_days: int = 5, action_type: str = "DISCOUNT",
                       discount_pct: Decimal | None = Decimal("50"),
                       proposed_qty: int | None = None, reason: str = "Near expiry",
                       status: str = "PENDING",
                       guardrail: str | None = "MAX_DISCOUNT") -> Recommendation:
    """One recommendation, optionally with a batch and one guardrail result.

    ``with_batch=False`` builds the row DS-06 makes without a batch: a
    REDISTRIBUTION, or the surplus DISCOUNT of rule S2.
    """
    store_id = world.store_id if store_id is None else store_id
    sku = f"TEST-SKU-{_uid()}" if sku is None else sku
    db_session.add(Product(sku=sku, barcode=f"BC-{sku}", name="Recommendation product",
                           category="TEST", unit_price=Decimal("10.00")))
    db_session.flush()
    if with_batch and batch_id is None:
        batch_id = f"TEST-BATCH-{_uid()}"
        db_session.add(ProductBatch(batch_id=batch_id, sku=sku, store_id=store_id,
                                    expiry_date=TODAY + timedelta(days=batch_days),
                                    quantity=batch_quantity))
        db_session.flush()
    rec = Recommendation(
        store_id=store_id, sku=sku, batch_id=batch_id if with_batch else None,
        action_type=action_type, discount_pct=discount_pct, proposed_qty=proposed_qty,
        reason=reason, status=status,
    )
    db_session.add(rec)
    db_session.flush()
    if guardrail is not None:
        rule = GuardrailRule(rule_type=guardrail, threshold=Decimal("10.00"),
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
    add_recommendation(db_session, world, status="EXPIRED")
    db_session.commit()

    body = get_recommendations(client, world).json()

    assert [item["rec_id"] for item in body["items"]] == [pending.rec_id]
    assert body["items"][0]["status"] == "PENDING"


def test_stf32_1_another_store_is_not_listed(client, db_session, world):
    own = add_recommendation(db_session, world)
    add_recommendation(db_session, world, store_id=world.other_store_id)
    db_session.commit()

    body = get_recommendations(client, world).json()

    assert [item["rec_id"] for item in body["items"]] == [own.rec_id]


# STF32-2


def test_stf32_2_the_detail_carries_reason_action_expiry_and_guardrails(
        client, db_session, world):
    rec = add_recommendation(db_session, world, action_type="DISCOUNT",
                             discount_pct=Decimal("50"))
    db_session.commit()

    response = client.get(f"{LIST_URL}/{rec.rec_id}", headers=world.headers())

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["rec_id"] == rec.rec_id
    assert body["sku"] == rec.sku
    assert body["action_type"] == "DISCOUNT"
    # DS-04 says number: the audit fix of #7 serialises the Decimal to a JSON number.
    assert body["discount_pct"] == 50.0
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
    assert response.json() == {"items": []}


# STF32-4


def test_stf32_4_another_store_is_404(client, db_session, world):
    foreign = add_recommendation(db_session, world, store_id=world.other_store_id)
    db_session.commit()

    response = client.get(f"{LIST_URL}/{foreign.rec_id}", headers=world.headers())

    assert_rejected(response, 404, "NOT_FOUND")


# STF32-5


def test_stf32_5_a_sold_out_batch_is_hidden(client, db_session, world):
    rec = add_recommendation(db_session, world, batch_quantity=0)
    db_session.commit()

    assert get_recommendations(client, world).json() == {"items": []}

    response = client.get(f"{LIST_URL}/{rec.rec_id}", headers=world.headers())
    assert_rejected(response, 404, "NOT_FOUND")


def test_stf32_5_an_expired_batch_is_hidden(client, db_session, world):
    add_recommendation(db_session, world, batch_days=-1)
    db_session.commit()

    assert get_recommendations(client, world).json() == {"items": []}


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


def test_pb32_the_list_is_wrapped_in_items(client, db_session, world):
    """DS-04 wraps the rows in ``items``; it is not a bare array."""
    add_recommendation(db_session, world)
    db_session.commit()

    body = get_recommendations(client, world).json()

    assert set(body) == {"items"}
    assert isinstance(body["items"], list)


def test_pb32_a_redistribution_without_a_batch_is_listed_and_readable(
        client, db_session, world):
    """DS-06 REDISTRIBUTION has no batch and never expires."""
    rec = add_recommendation(db_session, world, with_batch=False,
                             action_type="REDISTRIBUTION", discount_pct=None,
                             proposed_qty=4, reason="STORE-X thiếu 4 đơn vị")
    db_session.commit()

    body = get_recommendations(client, world).json()

    assert [item["rec_id"] for item in body["items"]] == [rec.rec_id]
    assert body["items"][0]["action_type"] == "REDISTRIBUTION"
    assert body["items"][0]["proposed_qty"] == 4
    assert body["items"][0]["discount_pct"] is None

    detail = client.get(f"{LIST_URL}/{rec.rec_id}", headers=world.headers())
    assert detail.status_code == 200, detail.text
    assert detail.json()["batch_id"] is None
    assert detail.json()["expiry_date"] is None
    assert detail.json()["reason"] == "STORE-X thiếu 4 đơn vị"


def test_pb32_a_surplus_discount_without_a_batch_is_listed_and_readable(
        client, db_session, world):
    """The surplus DISCOUNT of DS-06 rule S2 also has no batch."""
    rec = add_recommendation(db_session, world, with_batch=False,
                             action_type="DISCOUNT", discount_pct=Decimal("10"),
                             reason="Dự báo cần 20 đơn vị trong 7 ngày")
    db_session.commit()

    body = get_recommendations(client, world).json()

    assert [item["rec_id"] for item in body["items"]] == [rec.rec_id]
    assert body["items"][0]["discount_pct"] == 10.0

    detail = client.get(f"{LIST_URL}/{rec.rec_id}", headers=world.headers())
    assert detail.status_code == 200, detail.text
    assert detail.json()["expiry_date"] is None


def test_pb32_no_batch_row_stays_listed_when_the_others_sell_out(
        client, db_session, world):
    no_batch = add_recommendation(db_session, world, with_batch=False,
                                  action_type="REDISTRIBUTION", discount_pct=None)
    sold_out = add_recommendation(db_session, world, batch_quantity=0)
    db_session.commit()

    body = get_recommendations(client, world).json()

    assert [item["rec_id"] for item in body["items"]] == [no_batch.rec_id]
    assert sold_out.rec_id not in [item["rec_id"] for item in body["items"]]


def test_pb32_a_listed_clearance_keeps_its_proposed_qty(client, db_session, world):
    add_recommendation(db_session, world, action_type="CLEARANCE",
                       discount_pct=None, proposed_qty=7)
    db_session.commit()

    body = get_recommendations(client, world).json()

    assert body["items"][0]["proposed_qty"] == 7
    assert body["items"][0]["discount_pct"] is None


@pytest.mark.parametrize("rec_id", [0, -1, 2**63, 2**64, 10**30])
def test_pb32_a_rec_id_outside_bigint_is_a_422(client, db_session, world, rec_id):
    """A value a bigint column cannot hold is refused, never a 503."""
    db_session.commit()

    response = client.get(f"{LIST_URL}/{rec_id}", headers=world.headers())

    assert_rejected(response, 422, "VALIDATION_ERROR")


def test_pb32_the_list_is_read_only(client, db_session, world):
    add_recommendation(db_session, world)
    db_session.commit()
    db_session.expire_all()

    response = get_recommendations(client, world)

    assert response.status_code == 200, response.text
    assert not db_session.new and not db_session.dirty and not db_session.deleted