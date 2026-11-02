"""Read queries on audit_log. Times are naive UTC, as the table stores them."""

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.models import AuditLog


# datetime2 keeps seven fractional digits and Python six, so an inclusive end
# covers its whole microsecond.
_RESOLUTION = timedelta(microseconds=1)


def list_audit_logs(session: Session, user_id: int | None, action: str | None,
                    from_time: datetime | None, to_time: datetime | None, limit: int) -> list[AuditLog]:
    query = select(AuditLog)
    if user_id is not None:
        query = query.where(AuditLog.user_id == user_id)
    if action is not None:
        query = query.where(AuditLog.action == action)
    if from_time is not None:
        query = query.where(AuditLog.created_at >= from_time)
    if to_time is not None and to_time < datetime.max:
        query = query.where(AuditLog.created_at < to_time + _RESOLUTION)
    query = query.order_by(AuditLog.created_at.desc(), AuditLog.audit_id.desc()).limit(limit)
    return list(session.scalars(query))
