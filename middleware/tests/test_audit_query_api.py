"""GET /api/v1/audit-logs on real SQL Server (PB-04-4, PS04-5 to PS04-7)."""

from datetime import datetime, timedelta
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import create_token
from app.domain.models import AuditLog, StaffUser


SECRET = "test-only-secret-with-enough-length-for-hs256"
URL = "/api/v1/audit-logs"
AUDITOR = "TEST-audit-auditor"
ACTION = "TEST-AUDIT-QUERY"
OTHER_ACTION = "TEST-AUDIT-OTHER"
# Far in the future, so these rows sort before anything else in the table.
T0 = datetime(2099, 1, 1, 10, 0, 0)


@pytest.fixture(autouse=True)
def jwt_secret(monkeypatch):
    monkeypatch.setattr(settings, "jwt_secret", SecretStr(SECRET))


def account(session: Session, username: str, role: str) -> StaffUser:
    user = StaffUser(username=username, full_name="Audit test account", role=role)
    session.add(user)
    session.flush()
    return user


@pytest.fixture
def auditor(db_session: Session) -> StaffUser:
    return account(db_session, AUDITOR, "AUDITOR")


@pytest.fixture
def headers(auditor: StaffUser) -> dict[str, str]:
    return bearer(create_token(AUDITOR, "Auditor"))


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def add_row(session: Session, key: str, created_at: datetime = T0, action: str = ACTION,
            user_id: int | None = None) -> AuditLog:
    row = AuditLog(action=action, entity_name="test", entity_key=key, created_at=created_at,
                   user_id=user_id, details=f"details of {key}")
    session.add(row)
    session.flush()
    return row


def keys(response) -> list[str]:
    assert response.status_code == 200
    return [item["entity_key"] for item in response.json()["items"]]


def assert_rejected(response, status: int, code: str) -> None:
    assert response.status_code == status
    body = response.json()
    assert set(body) == {"outcome", "code", "message"}
    assert (body["outcome"], body["code"]) == ("REJECTED", code)


# PS04-5


def test_ps04_5_auditor_filters_by_action_and_time_newest_first(client, db_session, headers):
    add_row(db_session, "TEST-OLD", T0)
    add_row(db_session, "TEST-NEW", T0 + timedelta(hours=1))
    add_row(db_session, "TEST-OTHER", T0 + timedelta(minutes=30), action=OTHER_ACTION)
    add_row(db_session, "TEST-LATE", T0 + timedelta(days=1))

    response = client.get(URL, headers=headers, params={
        "action": ACTION, "from": "2099-01-01T10:00:00Z", "to": "2099-01-01T11:00:00Z",
    })

    assert keys(response) == ["TEST-NEW", "TEST-OLD"]


def test_entry_has_every_contract_field(client, db_session, headers, auditor):
    row = add_row(db_session, "TEST-FIELDS", T0.replace(microsecond=123456), user_id=auditor.user_id)

    response = client.get(URL, headers=headers, params={"action": ACTION})

    assert response.json() == {"items": [{
        "audit_id": row.audit_id,
        "user_id": auditor.user_id,
        "action": ACTION,
        "entity_name": "test",
        "entity_key": "TEST-FIELDS",
        "details": "details of TEST-FIELDS",
        "created_at": "2099-01-01T10:00:00.123456Z",
    }]}


def test_nullable_fields_are_returned_as_null(client, db_session, headers):
    db_session.add(AuditLog(action=ACTION, entity_name="test", created_at=T0))
    db_session.flush()

    item = client.get(URL, headers=headers, params={"action": ACTION}).json()["items"][0]

    assert item["user_id"] is None and item["entity_key"] is None and item["details"] is None


# PS04-6, 401


@pytest.mark.parametrize(("db_role", "api_role"), [
    ("STORE_STAFF", "Staff"), ("STORE_MANAGER", "Manager"), ("HQ_OPERATOR", "HQ"),
    ("ADMIN", "Admin"), ("POS_SYSTEM", "POS"),
])
def test_ps04_6_every_other_role_gets_403(client, db_session, db_role, api_role):
    account(db_session, "TEST-audit-other", db_role)

    response = client.get(URL, headers=bearer(create_token("TEST-audit-other", api_role)))

    assert_rejected(response, 403, "FORBIDDEN")


def test_missing_token_gets_401(client):
    assert_rejected(client.get(URL), 401, "UNAUTHORIZED")


def test_authentication_runs_before_validation(client):
    assert_rejected(client.get(URL, params={"limit": 0}), 401, "UNAUTHORIZED")


# PS04-7


@pytest.mark.parametrize("method", ["put", "delete", "post", "patch"])
def test_ps04_7_log_is_read_only(client, db_session, headers, method):
    add_row(db_session, "TEST-KEEP")
    count = db_session.scalar(select(func.count()).select_from(AuditLog))

    response = getattr(client, method)(URL, headers=headers)

    assert_rejected(response, 405, "METHOD_NOT_ALLOWED")
    assert db_session.scalar(select(func.count()).select_from(AuditLog)) == count


def test_query_never_commits(client, db_session, headers, monkeypatch):
    commit = Mock()
    monkeypatch.setattr(db_session, "commit", commit)

    assert client.get(URL, headers=headers).status_code == 200

    commit.assert_not_called()


# Single filters and the combination


def test_filter_by_user_id_alone(client, db_session, headers, auditor):
    add_row(db_session, "TEST-MINE", user_id=auditor.user_id)
    add_row(db_session, "TEST-NOBODY")

    assert keys(client.get(URL, headers=headers, params={"user_id": auditor.user_id})) == ["TEST-MINE"]


def test_filter_by_action_alone(client, db_session, headers):
    add_row(db_session, "TEST-A")
    add_row(db_session, "TEST-B", action=OTHER_ACTION)

    assert keys(client.get(URL, headers=headers, params={"action": ACTION})) == ["TEST-A"]


def test_from_alone_is_inclusive(client, db_session, headers):
    add_row(db_session, "TEST-BEFORE", T0 - timedelta(seconds=1))
    add_row(db_session, "TEST-AT", T0)
    add_row(db_session, "TEST-AFTER", T0 + timedelta(seconds=1))

    response = client.get(URL, headers=headers, params={"from": "2099-01-01T10:00:00Z"})

    assert keys(response) == ["TEST-AFTER", "TEST-AT"]


def test_to_alone_is_inclusive(client, db_session, headers):
    add_row(db_session, "TEST-BEFORE", T0 - timedelta(seconds=1))
    add_row(db_session, "TEST-AT", T0)
    add_row(db_session, "TEST-AFTER", T0 + timedelta(seconds=1))

    response = client.get(URL, headers=headers, params={"action": ACTION, "to": "2099-01-01T10:00:00Z"})

    assert keys(response)[:2] == ["TEST-AT", "TEST-BEFORE"]


def test_to_includes_a_row_returned_at_lower_precision(client, db_session, headers):
    """datetime2 keeps seven digits; Python and the response keep six."""
    db_session.execute(text(
        "INSERT dbo.audit_log (action, entity_name, entity_key, created_at) "
        "VALUES (:action, 'test', 'TEST-7DIGITS', CAST('2099-01-01T10:00:00.1234567' AS datetime2))"
    ), {"action": ACTION})
    returned = client.get(URL, headers=headers, params={"action": ACTION}).json()["items"][0]["created_at"]

    response = client.get(URL, headers=headers, params={"action": ACTION, "from": returned, "to": returned})

    assert keys(response) == ["TEST-7DIGITS"]


def test_all_filters_combine_with_and(client, db_session, headers, auditor):
    add_row(db_session, "TEST-MATCH", user_id=auditor.user_id)
    add_row(db_session, "TEST-WRONG-USER")
    add_row(db_session, "TEST-WRONG-ACTION", action=OTHER_ACTION, user_id=auditor.user_id)
    add_row(db_session, "TEST-WRONG-TIME", T0 + timedelta(days=1), user_id=auditor.user_id)

    response = client.get(URL, headers=headers, params={
        "user_id": auditor.user_id, "action": ACTION,
        "from": "2099-01-01T00:00:00Z", "to": "2099-01-01T23:59:59Z",
    })

    assert keys(response) == ["TEST-MATCH"]


def test_empty_result_is_200_with_no_items(client, headers):
    response = client.get(URL, headers=headers, params={"action": "TEST-NO-SUCH-ACTION"})

    assert response.status_code == 200
    assert response.json() == {"items": []}


# Ordering and limit


def test_same_time_orders_by_audit_id_newest_first(client, db_session, headers):
    first = add_row(db_session, "TEST-FIRST")
    second = add_row(db_session, "TEST-SECOND")

    items = client.get(URL, headers=headers, params={"action": ACTION}).json()["items"]

    assert [item["audit_id"] for item in items] == [second.audit_id, first.audit_id]


def test_time_outranks_audit_id(client, db_session, headers):
    add_row(db_session, "TEST-LATER-TIME", T0 + timedelta(hours=1))
    add_row(db_session, "TEST-LATER-ID", T0)

    assert keys(client.get(URL, headers=headers, params={"action": ACTION})) == [
        "TEST-LATER-TIME", "TEST-LATER-ID",
    ]


def add_many(session: Session, count: int) -> None:
    session.add_all(
        AuditLog(action=ACTION, entity_name="test", entity_key=f"TEST-{number}", created_at=T0)
        for number in range(count)
    )
    session.flush()


def test_limit_defaults_to_100(client, db_session, headers):
    add_many(db_session, 101)

    assert len(keys(client.get(URL, headers=headers, params={"action": ACTION}))) == 100


def test_limit_one_returns_the_newest(client, db_session, headers):
    add_row(db_session, "TEST-OLD", T0)
    add_row(db_session, "TEST-NEW", T0 + timedelta(hours=1))

    assert keys(client.get(URL, headers=headers, params={"action": ACTION, "limit": 1})) == ["TEST-NEW"]


def test_limit_500_is_allowed(client, db_session, headers):
    add_many(db_session, 501)

    response = client.get(URL, headers=headers, params={"action": ACTION, "limit": 500})

    assert len(keys(response)) == 500


@pytest.mark.parametrize("limit", [0, 501, -1, "", "abc", 1.5])
def test_limit_out_of_range_is_rejected(client, headers, limit):
    response = client.get(URL, headers=headers, params={"limit": limit})

    assert_rejected(response, 422, "VALIDATION_ERROR")
    assert "limit" in response.json()["message"]


# Time conversion


def test_filter_with_offset_is_converted_to_utc(client, db_session, headers):
    add_row(db_session, "TEST-AT", T0)
    add_row(db_session, "TEST-EARLIER", T0 - timedelta(seconds=1))

    response = client.get(URL, headers=headers, params={"action": ACTION, "from": "2099-01-01T17:00:00+07:00"})

    assert keys(response) == ["TEST-AT"]


def test_negative_offset_is_converted_to_utc(client, db_session, headers):
    add_row(db_session, "TEST-AT", T0)
    add_row(db_session, "TEST-LATER", T0 + timedelta(seconds=1))

    response = client.get(URL, headers=headers, params={
        "action": ACTION, "from": "2099-01-01T05:00:00-05:00", "to": "2099-01-01T05:00:00-05:00",
    })

    assert keys(response) == ["TEST-AT"]


def test_filter_without_offset_is_treated_as_utc(client, db_session, headers):
    add_row(db_session, "TEST-AT", T0)

    response = client.get(URL, headers=headers, params={
        "action": ACTION, "from": "2099-01-01T10:00:00", "to": "2099-01-01T10:00:00",
    })

    assert keys(response) == ["TEST-AT"]


def test_created_at_is_returned_with_z(client, db_session, headers):
    add_row(db_session, "TEST-Z", T0)

    item = client.get(URL, headers=headers, params={"action": ACTION}).json()["items"][0]

    assert item["created_at"] == "2099-01-01T10:00:00Z"


def test_equal_from_and_to_is_allowed(client, db_session, headers):
    add_row(db_session, "TEST-AT", T0)

    response = client.get(URL, headers=headers, params={
        "action": ACTION, "from": "2099-01-01T10:00:00Z", "to": "2099-01-01T17:00:00+07:00",
    })

    assert keys(response) == ["TEST-AT"]


def test_from_later_than_to_is_rejected(client, headers):
    response = client.get(URL, headers=headers, params={
        "from": "2099-01-02T00:00:00Z", "to": "2099-01-01T00:00:00Z",
    })

    assert_rejected(response, 422, "VALIDATION_ERROR")
    assert "from" in response.json()["message"]


def test_order_of_from_and_to_is_compared_in_utc(client, headers):
    response = client.get(URL, headers=headers, params={
        "from": "2099-01-01T10:00:00Z", "to": "2099-01-01T12:00:00+07:00",
    })

    assert_rejected(response, 422, "VALIDATION_ERROR")


def test_mixed_offset_and_plain_values_compare(client, headers):
    response = client.get(URL, headers=headers, params={
        "from": "2099-01-01T10:00:00", "to": "2099-01-01T17:00:00+07:00",
    })

    assert response.status_code == 200


def test_latest_possible_to_is_accepted(client, db_session, headers):
    add_row(db_session, "TEST-AT", T0)

    response = client.get(URL, headers=headers, params={"action": ACTION, "to": "9999-12-31T23:59:59.999999Z"})

    assert keys(response) == ["TEST-AT"]


@pytest.mark.parametrize(("name", "value"), [
    ("from", "0001-01-01T00:00:00+07:00"),
    ("to", "9999-12-31T23:59:59-07:00"),
])
def test_time_outside_the_utc_range_is_rejected(client, headers, name, value):
    response = client.get(URL, headers=headers, params={name: value})

    assert_rejected(response, 422, "VALIDATION_ERROR")
    assert name in response.json()["message"]


@pytest.mark.parametrize("value", ["", "   ", "not-a-time", "2099-13-01T00:00:00Z"])
@pytest.mark.parametrize("name", ["from", "to"])
def test_invalid_time_is_rejected(client, headers, name, value):
    response = client.get(URL, headers=headers, params={name: value})

    assert_rejected(response, 422, "VALIDATION_ERROR")
    assert name in response.json()["message"]


# Input bounds


@pytest.mark.parametrize("value", ["", "   ", "HÀNH_ĐỘNG", "a" * 51, "A B"])
def test_invalid_action_is_rejected(client, headers, value):
    response = client.get(URL, headers=headers, params={"action": value})

    assert_rejected(response, 422, "VALIDATION_ERROR")
    assert "action" in response.json()["message"]


def test_action_of_fifty_characters_is_accepted(client, headers):
    assert client.get(URL, headers=headers, params={"action": "A" * 50}).status_code == 200


@pytest.mark.parametrize("value", ["", "abc", 0, -1, 2147483648, 10 ** 30])
def test_invalid_user_id_is_rejected(client, headers, value):
    response = client.get(URL, headers=headers, params={"user_id": value})

    assert_rejected(response, 422, "VALIDATION_ERROR")
    assert "user_id" in response.json()["message"]


def test_largest_user_id_is_accepted(client, headers):
    assert client.get(URL, headers=headers, params={"user_id": 2147483647}).json() == {"items": []}
