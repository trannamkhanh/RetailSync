"""Audit of rejected and duplicate POS events (PB-04-3, PS04-3, PS04-4).

The audit writes commit in RTS_DB_TEST in their own session, so the POS
account they reference is committed for real here and deleted afterwards,
together with the audit rows. Every query filters on this test's own ids.
"""

from collections.abc import Generator
from dataclasses import dataclass
from decimal import Decimal
import logging
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine, delete, func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.api import pos as pos_api
from app.core.config import settings
from app.core.security import create_token
from app.domain.models import AuditLog, Inventory, PosTerminal, PosTransaction, Product, StaffUser, Store
from app.main import app
from app.services import event_audit


SECRET = "test-only-secret-with-enough-length-for-hs256"
URL = "/api/v1/pos/events"


def _uid(length: int = 8) -> str:
    return uuid4().hex[:length].upper()


@dataclass(frozen=True)
class World:
    store_id: str
    pos_id: str
    sku: str
    user_id: int
    token: str


@pytest.fixture(autouse=True)
def jwt_secret(monkeypatch):
    monkeypatch.setattr(settings, "jwt_secret", SecretStr(SECRET))


@pytest.fixture(autouse=True)
def pos_account(test_engine: Engine) -> Generator[StaffUser, None, None]:
    """Committed for real; autouse, so it is torn down after db_session rolls back."""
    with Session(test_engine) as session:
        user = StaffUser(username=f"TEST-EA-{_uid()}", full_name="Event audit POS", role="POS_SYSTEM")
        session.add(user)
        session.commit()
        user_id, username = user.user_id, user.username
    try:
        yield StaffUser(user_id=user_id, username=username)
    finally:
        with Session(test_engine) as session:
            session.execute(delete(AuditLog).where(AuditLog.user_id == user_id))
            session.execute(delete(StaffUser).where(StaffUser.user_id == user_id))
            session.commit()


@pytest.fixture
def world(db_session: Session, pos_account: StaffUser) -> World:
    store_id, pos_id, sku = f"TEST-{_uid(5)}", f"TEST-POS-{_uid()}", f"TEST-SKU-{_uid()}"
    db_session.add(Store(store_id=store_id, name="Event audit store", latitude=Decimal("16.000000"),
                         longitude=Decimal("108.000000"), region_id="TEST"))
    db_session.add(Product(sku=sku, barcode=f"BC-{sku}", name="Event audit product",
                           category="TEST", unit_price=Decimal("10.00")))
    db_session.flush()
    db_session.add(PosTerminal(pos_id=pos_id, store_id=store_id, status="ACTIVE"))
    db_session.add(Inventory(store_id=store_id, sku=sku, quantity=10))
    # The router rolls the event back on a rejection; committing keeps these rows.
    # The fixture's outer transaction still removes them after the test.
    db_session.commit()
    token = create_token(pos_account.username, "POS", store_id=store_id, pos_id=pos_id)
    return World(store_id, pos_id, sku, pos_account.user_id, token)


def sale(world: World, txn_id: str | None = None, quantity: int = 1, sku: str | None = None,
         **overrides) -> dict:
    payload = {
        "event_type": "SALE", "transaction_id": txn_id or f"TEST-TXN-{_uid(10)}",
        "store_id": world.store_id, "pos_id": world.pos_id, "timestamp": "2026-11-14T03:15:00Z",
        "items": [{"sku": sku or world.sku, "quantity": quantity, "unit_price": "10.00"}],
    }
    payload.update(overrides)
    return payload


def post(client: TestClient, world: World, body, token: str | None = None):
    headers = {"Authorization": f"Bearer {token or world.token}"}
    return client.post(URL, json=body, headers=headers)


def audit_rows(db_session: Session, user_id: int, action: str | None = None) -> list[AuditLog]:
    """Rows the audit session wrote for this user.

    Read through the test's own session: another connection would wait on its
    uncommitted rows. It sees another connection's rows only once committed,
    which is what proves the separate transaction. STOCK_CHANGE belongs to the
    event's own transaction and is left out.
    """
    actions = [action] if action else ["EVENT_REJECTED", "DUPLICATE_EVENT"]
    query = (select(AuditLog).where(AuditLog.user_id == user_id, AuditLog.action.in_(actions))
             .order_by(AuditLog.audit_id))
    return list(db_session.scalars(query))


def assert_one_rejection(db_session: Session, world: World, txn_id: str | None, response) -> AuditLog:
    body = response.json()
    rows = audit_rows(db_session, world.user_id)
    assert [(row.action, row.entity_name, row.entity_key) for row in rows] == [
        ("EVENT_REJECTED", "pos_transaction", txn_id),
    ]
    assert rows[0].details == f"{body['code']}: {body['message']}"
    return rows[0]


# PS04-3 and the other rejections


def test_ps04_3_insufficient_stock_is_audited(client, db_session, world):
    txn_id = f"TEST-TXN-{_uid(10)}"

    response = post(client, world, sale(world, txn_id, quantity=999))

    assert response.status_code == 409
    assert response.json()["code"] == "INSUFFICIENT_STOCK"
    assert_one_rejection(db_session, world, txn_id, response)
    assert db_session.get(PosTransaction, txn_id) is None


def test_unknown_sku_is_audited(client, db_session, world):
    txn_id = f"TEST-TXN-{_uid(10)}"

    response = post(client, world, sale(world, txn_id, sku="TEST-SKU-MISSING"))

    assert (response.status_code, response.json()["code"]) == (422, "INVALID_EVENT")
    assert_one_rejection(db_session, world, txn_id, response)


def test_invalid_body_is_audited_with_its_transaction_id(client, db_session, world):
    txn_id = f"TEST-TXN-{_uid(10)}"
    body = sale(world, txn_id)
    del body["timestamp"]

    response = post(client, world, body)

    assert (response.status_code, response.json()["code"]) == (422, "INVALID_EVENT")
    assert_one_rejection(db_session, world, txn_id, response)


def test_unregistered_pos_is_audited(client, db_session, world, pos_account):
    txn_id = f"TEST-TXN-{_uid(10)}"
    unknown_pos = f"TEST-POS-{_uid()}"
    token = create_token(pos_account.username, "POS", store_id=world.store_id, pos_id=unknown_pos)

    response = post(client, world, sale(world, txn_id, pos_id=unknown_pos), token)

    assert (response.status_code, response.json()["code"]) == (422, "UNREGISTERED_STORE_OR_POS")
    assert_one_rejection(db_session, world, txn_id, response)


def test_conflict_is_audited(client, db_session, world):
    txn_id = f"TEST-TXN-{_uid(10)}"
    assert post(client, world, sale(world, txn_id, quantity=1)).status_code == 200

    response = post(client, world, sale(world, txn_id, quantity=2))

    assert (response.status_code, response.json()["code"]) == (409, "CONFLICT")
    assert_one_rejection(db_session, world, txn_id, response)


def test_return_of_unknown_sale_is_audited(client, db_session, world):
    txn_id = f"TEST-TXN-{_uid(10)}"
    body = sale(world, txn_id, event_type="RETURN", original_transaction_id=f"TEST-TXN-{_uid(10)}")

    response = post(client, world, body)

    assert response.json()["code"] == "ORIGINAL_SALE_NOT_FOUND"
    assert_one_rejection(db_session, world, txn_id, response)


def test_rejection_records_the_principal_user_id(client, db_session, world):
    post(client, world, sale(world, quantity=999))

    assert [row.user_id for row in audit_rows(db_session, world.user_id)] == [world.user_id]


# Transaction id taken from the raw body


@pytest.mark.parametrize("body", [None, [], ["x"], "text"], ids=["empty", "empty-list", "list", "string"])
def test_body_without_an_object_is_audited_without_key(client, db_session, world, body):
    response = client.post(URL, json=body, headers={"Authorization": f"Bearer {world.token}"})

    assert (response.status_code, response.json()["code"]) == (422, "INVALID_EVENT")
    assert_one_rejection(db_session, world, None, response)


@pytest.mark.parametrize("txn_id", [123, None, ["TXN"], {"id": 1}, "T" * 41],
                         ids=["number", "null", "list", "object", "41-chars"])
def test_unusable_transaction_id_is_audited_as_null(client, db_session, world, txn_id):
    body = sale(world)
    body["transaction_id"] = txn_id

    response = post(client, world, body)

    assert response.status_code == 422
    assert_one_rejection(db_session, world, None, response)


def test_transaction_id_of_forty_characters_is_kept(client, db_session, world):
    txn_id = "T" * 30 + _uid(10)
    response = post(client, world, sale(world, txn_id, sku="TEST-SKU-MISSING"))

    assert_one_rejection(db_session, world, txn_id, response)


def test_invalid_but_short_transaction_id_is_kept_as_sent(client, db_session, world):
    txn_id = f"BAD ID {_uid(6)}"

    response = post(client, world, sale(world, txn_id))

    assert response.status_code == 422
    assert_one_rejection(db_session, world, txn_id, response)


# PS04-4: duplicates


def test_ps04_4_duplicate_is_audited(client, db_session, world):
    txn_id = f"TEST-TXN-{_uid(10)}"
    assert post(client, world, sale(world, txn_id)).json()["outcome"] == "OK"

    response = post(client, world, sale(world, txn_id))

    assert response.json()["outcome"] == "DUPLICATE"
    rows = audit_rows(db_session, world.user_id)
    assert [(row.action, row.entity_name, row.entity_key, row.details) for row in rows] == [
        ("DUPLICATE_EVENT", "pos_transaction", txn_id, None),
    ]


def test_each_duplicate_attempt_is_audited(client, db_session, world):
    txn_id = f"TEST-TXN-{_uid(10)}"
    for _ in range(3):
        post(client, world, sale(world, txn_id))

    assert len(audit_rows(db_session, world.user_id, "DUPLICATE_EVENT")) == 2


def test_applied_event_writes_no_rejection_or_duplicate(client, db_session, world):
    assert post(client, world, sale(world)).json()["outcome"] == "OK"

    assert audit_rows(db_session, world.user_id) == []


# What is not audited


def test_missing_token_is_not_audited(client, db_session, world):
    response = client.post(URL, json=sale(world))

    assert response.status_code == 401
    assert audit_rows(db_session, world.user_id) == []


def test_wrong_role_is_not_audited(client, db_session, world):
    staff = StaffUser(username=f"TEST-EA-STAFF-{_uid()}", full_name="Event audit staff",
                      role="STORE_STAFF", store_id=world.store_id)
    db_session.add(staff)
    db_session.commit()
    token = create_token(staff.username, "Staff", store_id=world.store_id)
    txn_id = f"TEST-TXN-{_uid(10)}"

    response = post(client, world, sale(world, txn_id), token)

    assert response.status_code == 403
    assert db_session.scalar(select(func.count()).select_from(AuditLog)
                             .where(AuditLog.entity_key == txn_id)) == 0


def test_database_failure_is_not_audited(db_session, world, monkeypatch):
    def broken(*_args, **_kwargs):
        raise OperationalError("SELECT 1", {}, Exception("database down"))
    monkeypatch.setattr(pos_api, "process_event", broken)
    from app.core.db import get_db
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        response = TestClient(app, raise_server_exceptions=False).post(
            URL, json=sale(world), headers={"Authorization": f"Bearer {world.token}"})
    finally:
        app.dependency_overrides.pop(get_db)

    assert (response.status_code, response.json()["code"]) == (503, "SERVICE_UNAVAILABLE")
    assert audit_rows(db_session, world.user_id) == []


# A failing audit write never changes the response


def _broken_session():
    raise OperationalError("INSERT audit_log", {}, Exception("audit database down"))


def test_failing_rejection_audit_keeps_the_response(client, world, monkeypatch, caplog):
    txn_id = f"TEST-TXN-{_uid(10)}"
    expected = post(client, world, sale(world, txn_id, quantity=999))
    monkeypatch.setattr(event_audit, "session_factory", _broken_session)

    with caplog.at_level(logging.ERROR, logger=event_audit.__name__):
        response = post(client, world, sale(world, txn_id, quantity=999))

    assert (response.status_code, response.json()) == (expected.status_code, expected.json())
    assert any("EVENT_REJECTED" in record.getMessage() and record.exc_info for record in caplog.records)


def test_failing_duplicate_audit_keeps_the_response(client, world, monkeypatch, caplog):
    txn_id = f"TEST-TXN-{_uid(10)}"
    post(client, world, sale(world, txn_id))
    expected = post(client, world, sale(world, txn_id))
    monkeypatch.setattr(event_audit, "session_factory", _broken_session)

    with caplog.at_level(logging.ERROR, logger=event_audit.__name__):
        response = post(client, world, sale(world, txn_id))

    assert (response.status_code, response.json()) == (expected.status_code, expected.json())
    assert any("DUPLICATE_EVENT" in record.getMessage() for record in caplog.records)


def test_audit_failing_at_commit_keeps_the_response(client, db_session, world, monkeypatch):
    test_factory = event_audit.session_factory

    def session_failing_on_commit():
        session = test_factory()
        session.commit = _broken_session
        return session
    monkeypatch.setattr(event_audit, "session_factory", session_failing_on_commit)

    response = post(client, world, sale(world, quantity=999))

    assert (response.status_code, response.json()["code"]) == (409, "INSUFFICIENT_STOCK")
    assert audit_rows(db_session, world.user_id) == []
