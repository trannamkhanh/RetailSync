"""Audit writer and query. Adds to the caller's transaction and never commits."""

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.domain.models import AuditLog
from app.repositories import audit as repository


DETAILS_LIMIT = 500


def _fit_details(details: str | None) -> str | None:
    if details is None:
        return None
    # nvarchar(500) counts UTF-16 code units, so an emoji takes two.
    encoded = details.encode("utf-16-le")[:DETAILS_LIMIT * 2]
    return encoded.decode("utf-16-le", errors="ignore")


def record_audit(session, action: str, entity_name: str, entity_key: str | None = None,
                 user_id: int | None = None, details: str | None = None) -> None:
    session.add(AuditLog(user_id=user_id, action=action, entity_name=entity_name,
                         entity_key=entity_key, details=_fit_details(details)))


def _invalid_time(field: str, reason: str) -> ApiError:
    return ApiError(422, "VALIDATION_ERROR", f"Invalid field '{field}': {reason}")


def _to_utc(field: str, value: datetime | None) -> datetime | None:
    """A value without an offset is already UTC."""
    if value is None or value.tzinfo is None:
        return value
    try:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    except OverflowError:
        raise _invalid_time(field, "outside the supported time range.") from None


def list_audit_logs(session: Session, user_id: int | None = None, action: str | None = None,
                    from_time: datetime | None = None, to_time: datetime | None = None,
                    limit: int = 100) -> list[AuditLog]:
    start, end = _to_utc("from", from_time), _to_utc("to", to_time)
    if start is not None and end is not None and start > end:
        raise _invalid_time("from", "must not be later than 'to'.")
    return repository.list_audit_logs(session, user_id, action, start, end, limit)
