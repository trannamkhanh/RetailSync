"""Audit across SALE, RETURN and CANCELLATION through the real router (PB-04-5).

PS04-1 to PS04-7 are already used by tests on main, so these are named after
the backlog item. The POS account is committed for real, so the separate audit
session can write EVENT_REJECTED and DUPLICATE_EVENT for it; it is deleted
afterwards with its audit rows. Every query filters on that account.
"""

from collections.abc import Generator
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine, delete, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import create_token
from app.domain.models import AuditLog, PosTransaction, StaffUser
from app.main import app
from tests.pos_test_support import (
    World, assert_error, count, movements, post, return_payload, sale_payload, seed_sale, stock,
    transaction_items, uid,
)


SECRET = "test-only-secret-with-enough-length-for-hs256"
AUDIT_URL = "/api/v1/audit-logs"
EVENT_TYPES = ["SALE", "RETURN", "CANCELLATION"]


@pytest.fixture(autouse=True)
def jwt_secret(monkeypatch):
    monkeypatch.setattr(settings, "jwt_secret", SecretStr(SECRET))


@pytest.fixture(autouse=True)
def account(test_engine: Engine) -> Generator[StaffUser, None, None]:
    """Committed for real; autouse, so it is torn down after db_session rolls back."""
    with Session(test_engine) as session:
        user = StaffUser(username=f"TEST-AC-{uid()}", full_name="Audit coverage POS", role="POS_SYSTEM")
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
def world(db_session: Session) -> World:
    return seed_sale(db_session, sold={f"TEST-SKU-{uid(8)}": 2}, stock=10)


@pytest.fixture
def token(world: World, account: StaffUser) -> str:
    return create_token(account.username, "POS", store_id=world.store_id, pos_id=world.pos_id)


def cancellation(world: World, **overrides) -> dict:
    return {
        "event_type": "CANCELLATION", "transaction_id": f"TEST-CAN-{uid(12)}",
        "original_transaction_id": world.sale_txn, "store_id": world.store_id,
        "pos_id": world.pos_id, "timestamp": "2026-11-14T03:15:00Z", **overrides,
    }


def event(event_type: str, world: World) -> dict:
    sku = world.skus[0]
    if event_type == "SALE":
        return sale_payload(world, [(sku, 1, "10.00")])
    if event_type == "RETURN":
        return return_payload(world, [(sku, 1, "10.00")])
    return cancellation(world)


def audit_rows(session: Session, user_id: int, txn_id: str | None = None) -> list[tuple]:
    query = select(AuditLog.action, AuditLog.entity_key, AuditLog.details).where(AuditLog.user_id == user_id)
    if txn_id is not None:
        query = query.where(AuditLog.entity_key == txn_id)
    return [tuple(row) for row in session.execute(query.order_by(AuditLog.audit_id))]


def actions(session: Session, user_id: int, txn_id: str) -> list[str]:
    return [action for action, _, _ in audit_rows(session, user_id, txn_id)]


# Applied, duplicate and rejected, for every event type


@pytest.mark.parametrize("event_type", EVENT_TYPES)
def test_pb04_5_applied_event_writes_one_stock_change(client, db_session, world, token, account, event_type):
    body = event(event_type, world)

    response = post(client, body, token)

    assert response.json()["outcome"] == "OK", response.text
    rows = audit_rows(db_session, account.user_id, body["transaction_id"])
    assert [(action, key) for action, key, _ in rows] == [("STOCK_CHANGE", body["transaction_id"])]
    assert event_type in rows[0][2]


@pytest.mark.parametrize("event_type", EVENT_TYPES)
def test_pb04_5_duplicate_writes_one_duplicate_event_and_no_new_stock_change(client, db_session, world, token,
                                                                            account, event_type):
    body = event(event_type, world)
    assert post(client, body, token).json()["outcome"] == "OK"

    response = post(client, body, token)

    assert response.json()["outcome"] == "DUPLICATE"
    assert sorted(actions(db_session, account.user_id, body["transaction_id"])) == [
        "DUPLICATE_EVENT", "STOCK_CHANGE",
    ]


def rejected_event(event_type: str, client, world: World, token: str) -> tuple[dict, int, str]:
    """An event of this type that passes validation and is rejected by a business rule."""
    sku = world.skus[0]
    if event_type == "SALE":
        return sale_payload(world, [(sku, 999, "10.00")]), 409, "INSUFFICIENT_STOCK"
    if event_type == "RETURN":
        return return_payload(world, [(sku, 3, "10.00")]), 409, "RETURN_QTY_EXCEEDED"
    assert post(client, cancellation(world), token).json()["outcome"] == "OK"
    return cancellation(world), 409, "SALE_ALREADY_CANCELLED"


@pytest.mark.parametrize("event_type", EVENT_TYPES)
def test_pb04_5_rejection_writes_one_event_rejected_and_no_stock_change(client, db_session, world, token,
                                                                       account, event_type):
    body, status, code = rejected_event(event_type, client, world, token)

    response = post(client, body, token)

    assert_error(response, status, code)
    rows = audit_rows(db_session, account.user_id, body["transaction_id"])
    assert [(action, key) for action, key, _ in rows] == [("EVENT_REJECTED", body["transaction_id"])]
    assert rows[0][2].startswith(f"{code}: ")


def test_pb04_5_unsafe_transaction_id_is_audited_without_key(client, db_session, world, token, account):
    unsafe = f"TEST-Đ-{uid(4)}"
    body = sale_payload(world, [(world.skus[0], 1, "10.00")], txn_id=unsafe)

    response = post(client, body, token)

    assert_error(response, 422, "INVALID_EVENT")
    rows = audit_rows(db_session, account.user_id)
    assert [(action, key) for action, key, _ in rows] == [("EVENT_REJECTED", None)]
    assert rows[0][2].endswith(f' [transaction_id: "{unsafe}"]')


@pytest.mark.parametrize("event_type", EVENT_TYPES)
def test_pb04_5_failure_after_stock_update_leaves_no_row(client, db_session, world, token, account,
                                                         event_type, monkeypatch):
    body = event(event_type, world)
    txn_id = body["transaction_id"]

    def fail() -> None:
        raise OperationalError("simulated commit failure", {}, RuntimeError("offline"))

    with monkeypatch.context() as patch:
        patch.setattr(db_session, "commit", fail)
        with TestClient(app, raise_server_exceptions=False) as failing_client:
            response = post(failing_client, body, token)

    assert_error(response, 503, "SERVICE_UNAVAILABLE")
    db_session.expire_all()
    assert count(db_session, PosTransaction, txn_id=txn_id) == 0
    assert transaction_items(db_session, txn_id) == []
    assert movements(db_session, txn_id) == []
    assert stock(db_session, world, world.skus[0]) == 10
    assert db_session.get(PosTransaction, world.sale_txn).status == "OK"
    assert audit_rows(db_session, account.user_id) == []


# The audit query finds them


@pytest.fixture
def auditor_headers(db_session: Session) -> dict[str, str]:
    username = f"TEST-AC-AUD-{uid()}"
    db_session.add(StaffUser(username=username, full_name="Audit coverage auditor", role="AUDITOR"))
    db_session.flush()
    return {"Authorization": f"Bearer {create_token(username, 'Auditor')}"}


def query_keys(client, headers: dict, account: StaffUser, action: str, start: datetime, end: datetime) -> list:
    response = client.get(AUDIT_URL, headers=headers, params={
        "user_id": account.user_id, "action": action, "limit": 500,
        "from": start.isoformat(), "to": end.isoformat(),
    })
    assert response.status_code == 200, response.text
    return [item["entity_key"] for item in response.json()["items"]]


def test_pb04_5_audit_query_finds_each_action_by_time_newest_first(client, world, token, account, auditor_headers):
    start = datetime.now(timezone.utc) - timedelta(seconds=5)
    sale = event("SALE", world)
    returned = event("RETURN", world)
    rejected = sale_payload(world, [(world.skus[0], 999, "10.00")])
    assert post(client, sale, token).json()["outcome"] == "OK"
    assert post(client, sale, token).json()["outcome"] == "DUPLICATE"
    assert post(client, returned, token).json()["outcome"] == "OK"
    assert post(client, returned, token).json()["outcome"] == "DUPLICATE"
    assert post(client, rejected, token).status_code == 409
    end = datetime.now(timezone.utc) + timedelta(seconds=5)

    def keys(action: str) -> list:
        return query_keys(client, auditor_headers, account, action, start, end)

    assert keys("STOCK_CHANGE") == [returned["transaction_id"], sale["transaction_id"]]
    assert keys("DUPLICATE_EVENT") == [returned["transaction_id"], sale["transaction_id"]]
    assert keys("EVENT_REJECTED") == [rejected["transaction_id"]]
    assert query_keys(client, auditor_headers, account, "STOCK_CHANGE",
                      start - timedelta(hours=1), start - timedelta(minutes=30)) == []


@pytest.mark.parametrize(("db_role", "api_role"), [
    ("STORE_STAFF", "Staff"), ("STORE_MANAGER", "Manager"), ("HQ_OPERATOR", "HQ"),
    ("ADMIN", "Admin"), ("POS_SYSTEM", "POS"),
])
def test_pb04_5_audit_query_refuses_every_role_but_auditor(client, db_session, db_role, api_role):
    username = f"TEST-AC-{api_role}-{uid()}"
    db_session.add(StaffUser(username=username, full_name="Audit coverage role", role=db_role))
    db_session.flush()

    response = client.get(AUDIT_URL, headers={"Authorization": f"Bearer {create_token(username, api_role)}"})

    assert_error(response, 403, "FORBIDDEN")


def test_pb04_5_audit_query_needs_a_token(client):
    assert_error(client.get(AUDIT_URL), 401, "UNAUTHORIZED")


@pytest.mark.parametrize("method", ["put", "delete"])
def test_pb04_5_audit_log_is_read_only(client, auditor_headers, method):
    response = getattr(client, method)(AUDIT_URL, headers=auditor_headers)

    assert response.status_code == 405
    assert response.json()["code"] == "METHOD_NOT_ALLOWED"
