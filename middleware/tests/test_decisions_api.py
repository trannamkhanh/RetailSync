"""Staff accept or reject a recommendation (PB-33, STF33-1 to STF33-6).

Every test creates its own stores, products, batches, recommendations and
staff users with ``TEST-`` ids and commits inside the ``db_session`` savepoint,
which the fixture rolls back, so nothing stays behind.
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
    AuditLog,
    GuardrailResult,
    Product,
    ProductBatch,
    Recommendation,
    StaffDecision,
    StaffUser,
    Store,
)

TODAY = date(2026, 11, 17)
SECRET = "test-only-secret-with-enough-length-for-hs256"
DECISION_URL = "/api/v1/recommendations/{rec_id}/decision"


def _uid(length: int = 5) -> str:
    return uuid4().hex[:length].upper()


@pytest.fixture(autouse=True)
def business_date(monkeypatch) -> None:
    monkeypatch.setattr(clock, "today_local", lambda: TODAY)


@pytest.fixture(autouse=True)
def jwt_secret(monkeypatch) -> None:
    monkeypatch.setattr(settings, "jwt_secret", SecretStr(SECRET))


class World:
    """The caller's store and its staff account."""

    def __init__(self, store_id: str, token: str) -> None:
        self.store_id = store_id
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
    _add_store(db_session, store_id)
    username = f"TEST-staff-{suffix}"
    db_session.add(StaffUser(username=username, full_name="Deciding staff",
                             role="STORE_STAFF", store_id=store_id))
    db_session.commit()
    return World(store_id, create_token(username, "Staff", store_id=store_id))


@pytest.fixture
def world(db_session) -> World:
    return _make_world(db_session)


def add_pending_recommendation(db_session, world: World, *,
                               store_id: str | None = None,
                               sku: str | None = None, batch_id: str | None = None,
                               action_type: str = "DISCOUNT",
                               discount_pct: Decimal | None = Decimal("50"),
                               proposed_qty: int | None = None,
                               reason: str = "Near expiry",
                               status: str = "PENDING") -> Recommendation:
    """One recommendation with one guardrail result, as PB-27 leaves it."""
    store_id = world.store_id if store_id is None else store_id
    sku = f"TEST-SKU-{_uid()}" if sku is None else sku
    db_session.add(Product(sku=sku, barcode=f"BC-{sku}", name="Decision product",
                           category="TEST", unit_price=Decimal("10.00")))
    db_session.flush()
    if batch_id is None:
        batch_id = f"TEST-BATCH-{_uid()}"
        db_session.add(ProductBatch(batch_id=batch_id, sku=sku, store_id=store_id,
                                    expiry_date=TODAY + timedelta(days=5), quantity=10))
        db_session.flush()
    rec = Recommendation(store_id=store_id, sku=sku, batch_id=batch_id,
                         action_type=action_type, discount_pct=discount_pct,
                         proposed_qty=proposed_qty, reason=reason, status=status)
    db_session.add(rec)
    db_session.flush()
    db_session.add(GuardrailResult(rec_id=rec.rec_id, rule_id=1, outcome="PASSED",
                                   original_value=None, adjusted_value=None,
                                   message=None))
    db_session.flush()
    return rec


def decide(client, world: World, rec_id: int, decision: str):
    return client.post(DECISION_URL.format(rec_id=rec_id),
                       headers=world.headers(), json={"decision": decision})


def assert_rejected(response, status: int, code: str) -> None:
    assert response.status_code == status, response.text
    body = response.json()
    assert set(body) == {"outcome", "code", "message"}
    assert (body["outcome"], body["code"]) == ("REJECTED", code)


def decision_row(db_session, rec_id: int) -> StaffDecision | None:
    return db_session.scalar(select(StaffDecision).where(StaffDecision.rec_id == rec_id))


def audit_row(db_session, rec_id: int) -> AuditLog | None:
    return db_session.scalar(
        select(AuditLog).where(AuditLog.action == "STAFF_DECISION",
                               AuditLog.entity_key == str(rec_id)))


# STF33-1


def test_stf33_1_accept_is_final_and_audited(client, db_session, world):
    rec = add_pending_recommendation(db_session, world)
    db_session.commit()

    response = decide(client, world, rec.rec_id, "ACCEPT")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body == {"rec_id": rec.rec_id, "status": "ACCEPTED",
                    "decided_at": body["decided_at"]}

    db_session.expire_all()
    assert db_session.get(Recommendation, rec.rec_id).status == "ACCEPTED"
    assert decision_row(db_session, rec.rec_id) is not None
    assert decision_row(db_session, rec.rec_id).decision == "ACCEPT"
    assert audit_row(db_session, rec.rec_id) is not None


# STF33-2


def test_stf33_2_reject_is_stored(client, db_session, world):
    rec = add_pending_recommendation(db_session, world)
    db_session.commit()

    response = decide(client, world, rec.rec_id, "REJECT")

    assert response.status_code == 200, response.text
    assert response.json() == {"rec_id": rec.rec_id, "status": "REJECTED",
                               "decided_at": response.json()["decided_at"]}

    db_session.expire_all()
    assert db_session.get(Recommendation, rec.rec_id).status == "REJECTED"
    assert decision_row(db_session, rec.rec_id).decision == "REJECT"


# STF33-3


def test_stf33_3_a_decision_is_final(client, db_session, world):
    rec = add_pending_recommendation(db_session, world, status="ACCEPTED")
    db_session.commit()

    response = decide(client, world, rec.rec_id, "REJECT")

    assert_rejected(response, 409, "ALREADY_DECIDED")
    db_session.expire_all()
    assert db_session.get(Recommendation, rec.rec_id).status == "ACCEPTED"
    assert decision_row(db_session, rec.rec_id) is None


# STF33-4


def test_stf33_4_an_expired_recommendation_is_refused(client, db_session, world):
    rec = add_pending_recommendation(db_session, world)
    batch = db_session.get(ProductBatch, rec.batch_id)
    batch.quantity = 0  # sold out: no sellable quantity left
    db_session.flush()

    response = decide(client, world, rec.rec_id, "ACCEPT")

    assert_rejected(response, 409, "RECOMMENDATION_EXPIRED")
    assert decision_row(db_session, rec.rec_id) is None


# STF33-5


def test_stf33_5_another_store_is_404(client, db_session, world):
    suffix = _uid()
    foreign_store = f"TEST-B{suffix[:4]}"
    db_session.add(Store(store_id=foreign_store, name="Foreign store",
                         latitude=16.0, longitude=108.0, region_id="TEST"))
    rec = add_pending_recommendation(db_session, world, store_id=foreign_store)
    db_session.commit()

    response = decide(client, world, rec.rec_id, "ACCEPT")

    assert_rejected(response, 404, "NOT_FOUND")
    assert decision_row(db_session, rec.rec_id) is None


# STF33-6


def test_stf33_6_an_invalid_decision_is_422(client, db_session, world):
    rec = add_pending_recommendation(db_session, world)
    db_session.commit()

    response = client.post(DECISION_URL.format(rec_id=rec.rec_id),
                           headers=world.headers(), json={"decision": "MAYBE"})

    assert_rejected(response, 422, "VALIDATION_ERROR")
    assert decision_row(db_session, rec.rec_id) is None


# PB-33 cases without a sheet id


def test_pb33_an_unknown_recommendation_is_404(client, db_session, world):
    db_session.commit()

    response = decide(client, world, 987654321, "ACCEPT")

    assert_rejected(response, 404, "NOT_FOUND")


def test_pb33_two_parallel_decisions_of_one_row_serialize(client, db_session, world):
    """The first decision wins; the second gets ALREADY_DECIDED and changes
    nothing. This is the single-threaded image of the concurrency contract."""
    rec = add_pending_recommendation(db_session, world)
    db_session.commit()

    first = decide(client, world, rec.rec_id, "ACCEPT")
    assert first.status_code == 200, first.text

    second = decide(client, world, rec.rec_id, "REJECT")
    assert_rejected(second, 409, "ALREADY_DECIDED")

    db_session.expire_all()
    assert db_session.get(Recommendation, rec.rec_id).status == "ACCEPTED"
    assert decision_row(db_session, rec.rec_id) is not None
    assert decision_row(db_session, rec.rec_id).decision == "ACCEPT"