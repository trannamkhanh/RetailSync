"""Audit writer. Adds to the caller's transaction and never commits."""

from sqlalchemy.orm import Session

from app.domain.models import AuditLog


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
