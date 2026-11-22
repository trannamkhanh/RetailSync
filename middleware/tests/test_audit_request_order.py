"""Phase 8 Q5 (request order): authenticate and validate before touching the database.

Two endpoints opened a pooled database connection before they knew whether the
request was even theirs to serve:

- ``POST /pos/events`` depended on ``get_db`` for the account lookup and for the
  three ``SET LOCK_TIMEOUT`` statements, so a request with a bad or missing
  token still took a connection and ran three round trips before the 401.
- ``POST /hq/snapshot`` depended on ``get_db`` before reading the body, so a
  body over 1 MB -- refused without ever being applied -- still held a session.

The order is now: check the bearer token and its role, then read and check the
body, then open the session. The observable answers do not change, so these
tests pin the order itself: with a refused request, the database dependency must
never run, and a token for another role must not have its body read at all.

These tests are the unnumbered "Minor backend/POS" group of PR Q5, not audit
finding #5 (Kiệt's `SYNC_SEND_POLL_SECONDS`); the `test_q5_` prefix keeps the two
apart (review of PR #78).
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


def test_q5_pos_without_a_token_never_opens_the_database(client, recorder):
    response = client.post(POS_URL, json={
        "event_type": "SALE", "transaction_id": f"TEST-TXN-{uid(8)}",
        "store_id": "TEST-Q5", "pos_id": "TEST-Q5-POS",
        "timestamp": "2026-11-14T03:15:00Z",
        "items": [{"sku": "TEST-Q5-SKU", "quantity": 1, "unit_price": "10.00"}],
    })

    assert response.status_code == 401, response.text
    assert recorder.opened == 0


def test_q5_pos_with_a_bad_token_never_opens_the_database(client, recorder):
    response = client.post(POS_URL, headers=bearer("not-a-token"), json={
        "event_type": "SALE", "transaction_id": f"TEST-TXN-{uid(8)}",
        "store_id": "TEST-Q5", "pos_id": "TEST-Q5-POS",
        "timestamp": "2026-11-14T03:15:00Z",
        "items": [{"sku": "TEST-Q5-SKU", "quantity": 1, "unit_price": "10.00"}],
    })

    assert response.status_code == 401, response.text
    assert recorder.opened == 0


def test_q5_a_snapshot_over_the_limit_never_opens_the_database(client, recorder, db_session):
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


def test_q5_a_non_hq_token_is_403_without_reading_the_body(client, recorder, db_session):
    """A Staff token must be refused by role, not by a 1 MB size check.

    The size limit is enforced while the body is read, so a non-HQ caller had its
    whole body read and was told 413 -- the wrong reason, and work done for a
    request that was never allowed (review of PR #78).
    """
    account = StaffUser(username=f"TEST-staff-{uid(8)}", full_name="Q5 staff",
                        role="STORE_STAFF", store_id=None)
    db_session.add(account)
    db_session.commit()
    token = create_token(account.username, "Staff")

    response = client.post(SNAPSHOT_URL, headers={**bearer(token),
                                                  "Content-Type": "application/json"},
                           content=b"x" * (MAX_SNAPSHOT_BYTES + 1))

    assert response.status_code == 403, response.text
    assert response.json()["code"] == "FORBIDDEN"
    assert recorder.opened == 0


def test_q5_a_small_body_from_a_non_hq_token_is_still_403(client, recorder, db_session):
    """The role check does not depend on the size, and the DB is still untouched."""
    account = StaffUser(username=f"TEST-staff-{uid(8)}", full_name="Q5 staff",
                        role="STORE_STAFF", store_id=None)
    db_session.add(account)
    db_session.commit()
    token = create_token(account.username, "Staff")

    response = client.post(SNAPSHOT_URL, headers={**bearer(token),
                                                  "Content-Type": "application/json"},
                           content=b'{"store_id":"TEST-Q5"}')

    assert response.status_code == 403, response.text
    assert recorder.opened == 0


def test_q5_an_admin_token_is_403_too(client, recorder, db_session):
    account = StaffUser(username=f"TEST-admin-{uid(8)}", full_name="Q5 admin",
                        role="ADMIN", store_id=None)
    db_session.add(account)
    db_session.commit()
    token = create_token(account.username, "Admin")

    response = client.post(SNAPSHOT_URL, headers={**bearer(token),
                                                 "Content-Type": "application/json"},
                           content=b"x" * (MAX_SNAPSHOT_BYTES + 1))

    assert response.status_code == 403, response.text
    assert recorder.opened == 0
