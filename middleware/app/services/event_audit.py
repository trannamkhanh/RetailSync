"""Audit of rejected and duplicate POS events (PB-04-3).

Each write opens its own short transaction, apart from the event's, so a
rejection that rolled the event back is still recorded. A failed write is
logged and swallowed: it never changes the response (DS-05 section 3).
"""

import logging

from app.core.db import SessionLocal
from app.core.errors import ApiError
from app.core.security import Principal
from app.repositories.registry import find_user_id
from app.services.audit import record_audit


logger = logging.getLogger(__name__)

session_factory = SessionLocal


def _write(principal: Principal, action: str, transaction_id: str | None, details: str | None) -> None:
    try:
        with session_factory() as session:
            user_id = find_user_id(session, principal.sub)
            record_audit(session, action, "pos_transaction", transaction_id, user_id, details)
            session.commit()
    except Exception:
        logger.exception("Could not write %s audit for transaction %s", action, transaction_id)


def audit_rejected_event(principal: Principal, transaction_id: str | None, error: ApiError) -> None:
    _write(principal, "EVENT_REJECTED", transaction_id, f"{error.code}: {error.message}")


def audit_duplicate_event(principal: Principal, transaction_id: str) -> None:
    _write(principal, "DUPLICATE_EVENT", transaction_id, None)
