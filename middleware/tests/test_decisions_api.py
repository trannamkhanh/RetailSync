"""Staff accept or reject a recommendation (PB-33, STF33-1 to STF33-6).

Every test creates its own stores, products, batches, recommendations and
staff users with ``TEST-`` ids and commits inside the ``db_session`` savepoint,
which the fixture rolls back, so nothing stays behind.

Two tests need a committed state and a second connection: they write rows with
the ``test_engine``, read them back from a separate session, and delete them
again, so nothing stays behind either.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from threading import Barrier, Thread
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine, delete, select
from sqlalchemy.orm import Session

from app.core import clock
from app.core.config import settings
from app.core.security import create_token
from app.domain.models import (
    AuditLog,
    GuardrailResult,
    GuardrailRule,
    Product,
    ProductBatch,
    Recommendation,
    StaffDecision,
    StaffUser,
    Store,
)
from app.main import app

TODAY = date(2026, 11, 17)
SECRET = "test-only-secret-with-enough-length-for-hs256"
DECISION_URL = "/api/v1/recommendations/{rec_id}/decision"
AUDIT_ACTION = "RECOMMENDATION_DECIDED"


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
                  latitude=Decimal("16.067800"), longitude=Decimal("108.220800"),
                  region_id="TEST")
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
                               with_batch: bool = True, batch_quantity: int = 10,
                               action_type: str = "DISCOUNT",
                               discount_pct: Decimal | None = Decimal("50"),
                               proposed_qty: int | None = None,
                               reason: str = "Near expiry",
                               status: str = "PENDING",
                               guardrail: str | None = "MAX_DISCOUNT") -> Recommendation:
    """One recommendation with one guardrail result, as PB-27 leaves it."""
    store_id = world.store_id if store_id is None else store_id
    sku = f"TEST-SKU-{_uid()}" if sku is None else sku
    db_session.add(Product(sku=sku, barcode=f"BC-{sku}", name="Decision product",
                           category="TEST", unit_price=Decimal("10.00")))
    db_session.flush()
    if with_batch and batch_id is None:
        batch_id = f"TEST-BATCH-{_uid()}"
        db_session.add(ProductBatch(batch_id=batch_id, sku=sku, store_id=store_id,
                                    expiry_date=TODAY + timedelta(days=5),
                                    quantity=batch_quantity))
        db_session.flush()
    rec = Recommendation(store_id=store_id, sku=sku,
                         batch_id=batch_id if with_batch else None,
                         action_type=action_type, discount_pct=discount_pct,
                         proposed_qty=proposed_qty, reason=reason, status=status)
    db_session.add(rec)
    db_session.flush()
    if guardrail is not None:
        rule = GuardrailRule(rule_type=guardrail, threshold=Decimal("10.00"),
                             category="TEST", is_active=True)
        db_session.add(rule)
        db_session.flush()
        db_session.add(GuardrailResult(rec_id=rec.rec_id, rule_id=rule.rule_id,
                                       outcome="PASSED", original_value=None,
                                       adjusted_value=None, message=None))
    db_session.flush()
    return rec


def decide(client, world: World, rec_id, decision: str):
    return client.post(DECISION_URL.format(rec_id=rec_id),
                       headers=world.headers(), json={"decision": decision})


def assert_rejected(response, status: int, code: str) -> None:
    assert response.status_code == status, response.text
    body = response.json()
    assert set(body) == {"outcome", "code", "message"}
    assert (body["outcome"], body["code"]) == ("REJECTED", code)


def decision_row(db_session, rec_id: int) -> StaffDecision | None:
    return db_session.scalar(select(StaffDecision).where(StaffDecision.rec_id == rec_id))


def audit_rows(db_session, rec_id: int) -> list[AuditLog]:
    return list(db_session.scalars(
        select(AuditLog).where(AuditLog.action == AUDIT_ACTION,
                               AuditLog.entity_key == str(rec_id))))


# STF33-1


def test_stf33_1_accept_is_final_and_audited(client, db_session, world):
    rec = add_pending_recommendation(db_session, world)
    db_session.commit()

    response = decide(client, world, rec.rec_id, "ACCEPT")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["rec_id"] == rec.rec_id
    assert body["status"] == "ACCEPTED"
    assert body["decided_at"]

    db_session.expire_all()
    assert db_session.get(Recommendation, rec.rec_id).status == "ACCEPTED"
    stored = decision_row(db_session, rec.rec_id)
    assert stored is not None
    assert stored.decision == "ACCEPT"

    audited = audit_rows(db_session, rec.rec_id)
    assert len(audited) == 1
    assert audited[0].entity_name == "recommendation"
    assert audited[0].user_id is not None


def test_stf33_1_the_audit_action_and_entity_follow_the_contract(client, db_session, world):
    rec = add_pending_recommendation(db_session, world)
    db_session.commit()

    decide(client, world, rec.rec_id, "ACCEPT")

    db_session.expire_all()
    audited = audit_rows(db_session, rec.rec_id)
    assert len(audited) == 1
    assert audited[0].action == "RECOMMENDATION_DECIDED"
    assert audited[0].entity_name == "recommendation"
    assert audited[0].entity_key == str(rec.rec_id)
    assert "ACCEPT" in (audited[0].details or "")


# STF33-2


def test_stf33_2_reject_is_stored(client, db_session, world):
    rec = add_pending_recommendation(db_session, world)
    db_session.commit()

    response = decide(client, world, rec.rec_id, "REJECT")

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "REJECTED"

    db_session.expire_all()
    assert db_session.get(Recommendation, rec.rec_id).status == "REJECTED"
    assert decision_row(db_session, rec.rec_id).decision == "REJECT"
    assert len(audit_rows(db_session, rec.rec_id)) == 1


# STF33-3


def test_stf33_3_a_decision_is_final(client, db_session, world):
    rec = add_pending_recommendation(db_session, world, status="ACCEPTED")
    db_session.commit()

    response = decide(client, world, rec.rec_id, "REJECT")

    assert_rejected(response, 409, "ALREADY_DECIDED")
    db_session.expire_all()
    assert db_session.get(Recommendation, rec.rec_id).status == "ACCEPTED"
    assert decision_row(db_session, rec.rec_id) is None
    assert audit_rows(db_session, rec.rec_id) == []


# STF33-4


def test_stf33_4_an_expired_recommendation_is_refused(client, db_session, world):
    rec = add_pending_recommendation(db_session, world, batch_quantity=0)
    db_session.commit()

    response = decide(client, world, rec.rec_id, "ACCEPT")

    assert_rejected(response, 409, "RECOMMENDATION_EXPIRED")
    assert decision_row(db_session, rec.rec_id) is None
    assert audit_rows(db_session, rec.rec_id) == []


# STF33-5


def test_stf33_5_another_store_is_404(client, db_session, world):
    suffix = _uid()
    foreign_store = f"TEST-B{suffix[:4]}"
    db_session.add(Store(store_id=foreign_store, name="Foreign store",
                         latitude=Decimal("16.000000"),
                         longitude=Decimal("108.000000"), region_id="TEST"))
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


@pytest.mark.parametrize("payload", [
    {"decision": "accept"}, {"decision": ""}, {}, {"decision": 1},
    {"decision": "ACCEPT", "extra": True},
])
def test_stf33_6_other_bad_decisions_are_422(client, db_session, world, payload):
    rec = add_pending_recommendation(db_session, world)
    db_session.commit()

    response = client.post(DECISION_URL.format(rec_id=rec.rec_id),
                           headers=world.headers(), json=payload)

    assert_rejected(response, 422, "VALIDATION_ERROR")
    assert decision_row(db_session, rec.rec_id) is None


# PB-33 cases without a sheet id


def test_pb33_an_unknown_recommendation_is_404(client, db_session, world):
    db_session.commit()

    response = decide(client, world, 987654321, "ACCEPT")

    assert_rejected(response, 404, "NOT_FOUND")


@pytest.mark.parametrize("status", ["GENERATED", "BLOCKED"])
def test_pb33_a_recommendation_the_guardrails_never_released_is_404(
        client, db_session, world, status):
    """GENERATED and BLOCKED were never offered to staff; deciding one is 404,
    the same answer as a missing row, so the state is not disclosed."""
    rec = add_pending_recommendation(db_session, world, status=status)
    db_session.commit()

    response = decide(client, world, rec.rec_id, "ACCEPT")

    assert_rejected(response, 404, "NOT_FOUND")
    db_session.expire_all()
    assert db_session.get(Recommendation, rec.rec_id).status == status
    assert decision_row(db_session, rec.rec_id) is None


def test_pb33_a_recommendation_without_a_batch_can_be_decided(client, db_session, world):
    """A REDISTRIBUTION has no batch, so nothing can expire under it."""
    rec = add_pending_recommendation(db_session, world, with_batch=False,
                                     action_type="REDISTRIBUTION",
                                     discount_pct=None, proposed_qty=4)
    db_session.commit()

    response = decide(client, world, rec.rec_id, "ACCEPT")

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "ACCEPTED"

    db_session.expire_all()
    assert db_session.get(Recommendation, rec.rec_id).status == "ACCEPTED"


@pytest.mark.parametrize("rec_id", [0, 2**63, 10**30])
def test_pb33_a_rec_id_outside_bigint_is_a_422(client, db_session, world, rec_id):
    """A value a bigint column cannot hold is refused, never a 503."""
    db_session.commit()

    response = decide(client, world, rec_id, "ACCEPT")

    assert_rejected(response, 422, "VALIDATION_ERROR")


def test_pb33_the_decided_at_is_utc_with_an_offset(client, db_session, world):
    rec = add_pending_recommendation(db_session, world)
    db_session.commit()

    body = decide(client, world, rec.rec_id, "ACCEPT").json()

    assert body["decided_at"].endswith(("+00:00", "Z")), body["decided_at"]


# A committed state, read back from another session: these need the real
# engine, because the db_session savepoint is rolled back after the test.


@pytest.fixture
def committed(test_engine: Engine, monkeypatch):
    """Point the app at the test engine, then clean up what the test wrote.

    These tests need the API's own commit to be visible to a separate session,
    which the ``db_session`` savepoint cannot show. The fixture therefore
    replaces ``get_db`` with sessions on the test engine and removes the rows
    it created afterwards.
    """
    from app.core.db import get_db

    def override_get_db():
        session = Session(bind=test_engine)
        try:
            yield session
        except BaseException:
            session.rollback()
            raise
        finally:
            session.close()

    created: dict[str, list] = {"stores": [], "users": [], "recs": []}
    app.dependency_overrides[get_db] = override_get_db
    try:
        yield created
    finally:
        app.dependency_overrides.pop(get_db, None)
        with Session(test_engine) as session:
            for rec_id in created["recs"]:
                session.execute(delete(StaffDecision).where(
                    StaffDecision.rec_id == rec_id))
                session.execute(delete(GuardrailResult).where(
                    GuardrailResult.rec_id == rec_id))
                session.execute(delete(AuditLog).where(
                    AuditLog.entity_key == str(rec_id),
                    AuditLog.action == AUDIT_ACTION))
                session.execute(delete(Recommendation).where(
                    Recommendation.rec_id == rec_id))
            for store_id in created["stores"]:
                session.execute(delete(ProductBatch).where(
                    ProductBatch.store_id == store_id))
                session.execute(delete(Recommendation).where(
                    Recommendation.store_id == store_id))
            session.execute(delete(Product).where(Product.sku.like("TEST-PB33-%")))
            for username in created["users"]:
                session.execute(delete(StaffUser).where(
                    StaffUser.username == username))
            for store_id in created["stores"]:
                session.execute(delete(Store).where(Store.store_id == store_id))
            session.commit()


def _build_committed(engine: Engine, *, batch_quantity: int = 10) -> tuple[str, str, int]:
    """A store, its staff account and one PENDING recommendation, committed.

    Ids stay inside the column sizes: store_id is varchar(10), sku varchar(20).
    """
    suffix = _uid(4)
    store_id = f"TEST-P{suffix}"
    username = f"TEST-PB33-{suffix}"
    sku = f"TEST-PB33-{suffix}"
    with Session(engine) as session:
        session.add(Store(store_id=store_id, name="Committed store",
                          latitude=Decimal("16.000000"),
                          longitude=Decimal("108.000000"), region_id="TEST"))
        session.flush()
        session.add(StaffUser(username=username, full_name="Committed staff",
                              role="STORE_STAFF", store_id=store_id))
        session.add(Product(sku=sku, barcode=f"BC-{sku}", name="PB33 product",
                            category="TEST", unit_price=Decimal("10.00")))
        session.flush()
        batch_id = f"TEST-PB33-B-{suffix}"
        session.add(ProductBatch(batch_id=batch_id, sku=sku, store_id=store_id,
                                 expiry_date=TODAY + timedelta(days=5),
                                 quantity=batch_quantity))
        session.flush()
        rec = Recommendation(store_id=store_id, sku=sku, batch_id=batch_id,
                             action_type="DISCOUNT", discount_pct=Decimal("50"),
                             proposed_qty=None, reason="Committed", status="PENDING")
        session.add(rec)
        session.flush()
        rec_id = rec.rec_id
        session.commit()
    return store_id, username, rec_id


def test_pb33_4_the_expired_status_is_committed(test_engine: Engine, committed):
    """After a 409 RECOMMENDATION_EXPIRED the row reads EXPIRED from a new
    session, so the status change is not rolled back with the error."""
    store_id, username, rec_id = _build_committed(test_engine, batch_quantity=0)
    committed["stores"].append(store_id)
    committed["users"].append(username)
    committed["recs"].append(rec_id)
    token = create_token(username, "Staff", store_id=store_id)

    with TestClient(app) as api:
        response = api.post(DECISION_URL.format(rec_id=rec_id),
                            headers={"Authorization": f"Bearer {token}"},
                            json={"decision": "ACCEPT"})

    assert_rejected(response, 409, "RECOMMENDATION_EXPIRED")
    with Session(test_engine) as fresh:
        assert fresh.get(Recommendation, rec_id).status == "EXPIRED"
        assert fresh.scalar(select(StaffDecision).where(
            StaffDecision.rec_id == rec_id)) is None


def test_pb33_two_decisions_at_the_same_time_store_only_one(
        test_engine: Engine, committed):
    """Two threads decide the same row together: one 200 and one 409
    ALREADY_DECIDED, and exactly one decision row exists afterwards."""
    store_id, username, rec_id = _build_committed(test_engine)
    committed["stores"].append(store_id)
    committed["users"].append(username)
    committed["recs"].append(rec_id)
    headers = {"Authorization": f"Bearer {create_token(username, 'Staff', store_id=store_id)}"}
    barrier = Barrier(2)
    answers: list[int] = []

    def decide_once(decision: str) -> None:
        with TestClient(app) as api:
            barrier.wait()
            answers.append(api.post(DECISION_URL.format(rec_id=rec_id),
                                    headers=headers,
                                    json={"decision": decision}).status_code)

    threads = [Thread(target=decide_once, args=("ACCEPT",)),
               Thread(target=decide_once, args=("REJECT",))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(answers) == [200, 409], answers
    with Session(test_engine) as fresh:
        stored = fresh.scalars(select(StaffDecision).where(
            StaffDecision.rec_id == rec_id)).all()
        assert len(stored) == 1
        status = fresh.get(Recommendation, rec_id).status
        assert status in {"ACCEPTED", "REJECTED"}
        assert stored[0].decision == ("ACCEPT" if status == "ACCEPTED" else "REJECT")