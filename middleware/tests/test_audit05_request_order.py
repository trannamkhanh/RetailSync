"""Audit #5 (request order): authenticate and validate before touching the database.

Two endpoints opened a pooled database connection before they knew whether the
request was even theirs to serve:

- ``POST /pos/events`` depended on ``get_db`` for the account lookup and for the
  three ``SET LOCK_TIMEOUT`` statements, so a request with a bad or missing
  token still took a connection and ran three round trips before the 401.
- ``POST /hq/snapshot`` depended on ``get_db`` before reading the body, so a
  body over 1 MB -- refused without ever being applied -- still held a session.

The order is now: check the bearer token, then read and check the body, then
open the session. The observable answers do not change, so these tests pin the
order itself: with a refused request, the database dependency must never run.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import SecretStr

from app.core.config import settings
from app.core.db import get_db
from app.core.security import create_token
from app.domain.models import StaffUser, Store
from app.main import app
from app.services.hq_snapshot import MAX_SNAPSHOT_BYTES
from tests.pos_test_support import add_stock, uid

SECRET = "test-only-secret-with-enough-length-for-hs256"
POS_URL = "/api/v1/pos/events"
SNAPSHOT_URL = "/api/v1/hq/snapshot"


class DependencyRecorder:
    """Replaces ``get_db`` for one test and records whether anything opened it."""

    def __init__(self) -> None:
        self.opened = 0

    def __call__(self):
        self.opened += 1
        raise AssertionError("the database dependency ran for a request already refused")


@pytest.fixture(autouse=True)
def jwt_secret(monkeypatch) -> None:
    monkeypatch.setattr(settings, "jwt_secret", SecretStr(SECRET))


@pytest.fixture
def recorder() -> DependencyRecorder:
    record = DependencyRecorder()
    previous = app.dependency_overrides.copy()
    app.dependency_overrides[get_db] = record
    try:
        yield record
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_audit05_pos_without_a_token_never_opens_the_database(client, recorder):
    response = client.post(POS_URL, json={
        "event_type": "SALE", "transaction_id": f"TEST-TXN-{uid(8)}",
        "store_id": "TEST-Q5", "pos_id": "TEST-Q5-POS",
        "timestamp": "2026-11-14T03:15:00Z",
        "items": [{"sku": "TEST-Q5-SKU", "quantity": 1, "unit_price": "10.00"}],
    })

    assert response.status_code == 401, response.text
    assert recorder.opened == 0


def test_audit05_pos_with_a_bad_token_never_opens_the_database(client, recorder):
    response = client.post(POS_URL, headers=bearer("not-a-token"), json={
        "event_type": "SALE", "transaction_id": f"TEST-TXN-{uid(8)}",
        "store_id": "TEST-Q5", "pos_id": "TEST-Q5-POS",
        "timestamp": "2026-11-14T03:15:00Z",
        "items": [{"sku": "TEST-Q5-SKU", "quantity": 1, "unit_price": "10.00"}],
    })

    assert response.status_code == 401, response.text
    assert recorder.opened == 0


def test_audit05_a_snapshot_over_the_limit_never_opens_the_database(client, recorder, db_session):
    account = StaffUser(username=f"TEST-hq-{uid(8)}", full_name="Audit HQ",
                        role="HQ_OPERATOR", store_id=None)
    db_session.add(account)
    db_session.commit()
    token = create_token(account.username, "HQ")

    response = client.post(SNAPSHOT_URL, headers={**bearer(token),
                                                  "Content-Type": "application/json"},
                           content=b"x" * (MAX_SNAPSHOT_BYTES + 1))

    assert response.status_code == 413, response.text
    assert response.json()["code"] == "PAYLOAD_TOO_LARGE"
    assert recorder.opened == 0
