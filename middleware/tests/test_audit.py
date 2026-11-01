"""record_audit against the real audit_log table."""

from unittest.mock import Mock

import pytest
from sqlalchemy import select

from app.domain.models import AuditLog, StaffUser
from app.services.audit import record_audit


KEY = "TEST-AUDIT-1"


def stored_row(session) -> AuditLog | None:
    session.flush()
    return session.scalar(select(AuditLog).where(AuditLog.entity_key == KEY))


def test_row_is_added_with_all_fields(db_session):
    user = StaffUser(username="TEST-auditee", full_name="Test user", role="ADMIN")
    db_session.add(user)
    db_session.flush()

    record_audit(db_session, "STOCK_ADJUST", "inventory", KEY, user.user_id, "Counted 5")

    row = stored_row(db_session)
    assert (row.action, row.entity_name, row.entity_key, row.user_id, row.details) == (
        "STOCK_ADJUST", "inventory", KEY, user.user_id, "Counted 5",
    )
    assert row.created_at is not None


def test_optional_fields_default_to_null(db_session):
    record_audit(db_session, "SYNC_RUN", "sync_batch", KEY)

    row = stored_row(db_session)
    assert row.user_id is None and row.details is None


def test_key_can_be_omitted(db_session):
    record_audit(db_session, "SYNC_RUN", "sync_batch")

    assert [row.action for row in db_session.new] == ["SYNC_RUN"]


def test_record_audit_does_not_commit(db_session, monkeypatch):
    commit = Mock()
    monkeypatch.setattr(db_session, "commit", commit)

    record_audit(db_session, "SYNC_RUN", "sync_batch", KEY)

    commit.assert_not_called()


def test_rollback_removes_the_row(db_session):
    record_audit(db_session, "SYNC_RUN", "sync_batch", KEY)
    assert stored_row(db_session) is not None

    db_session.rollback()

    assert stored_row(db_session) is None


def test_details_are_truncated_to_column_limit(db_session):
    record_audit(db_session, "SYNC_RUN", "sync_batch", KEY, details="ế" * 501)

    assert stored_row(db_session).details == "ế" * 500


def test_details_at_limit_are_kept(db_session):
    record_audit(db_session, "SYNC_RUN", "sync_batch", KEY, details="x" * 500)

    assert stored_row(db_session).details == "x" * 500


@pytest.mark.parametrize("details", ["😀" * 300, "x" + "😀" * 300], ids=["even", "split-pair"])
def test_characters_outside_bmp_fit_the_nvarchar_limit(db_session, details):
    record_audit(db_session, "SYNC_RUN", "sync_batch", KEY, details=details)

    stored = stored_row(db_session).details
    assert details.startswith(stored)
    assert len(stored.encode("utf-16-le")) in (998, 1000)
