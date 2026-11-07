"""Audit of rejected and duplicate POS events (PB-04-3).

Each write opens its own short transaction, apart from the event's, so a
rejection that rolled the event back is still recorded. A failed write is
logged and swallowed: it never changes the response (DS-05 section 3).
"""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
import json
import logging
import re

from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.core.errors import ApiError
from app.core.security import Principal
from app.repositories.registry import find_user_id
from app.services.audit import record_audit


logger = logging.getLogger(__name__)

session_factory = SessionLocal

# NFR01 wants a POS answer within 500 ms at p95, so a write that meets a held
# lock gives up after this long instead of holding the response.
LOCK_TIMEOUT_MS = 200
# entity_key is varchar, which would turn "Đ" into "D" and an emoji into "?".
# Only an id the event schema accepts becomes the key.
_AUDIT_KEY = re.compile(r"[A-Za-z0-9_-]{1,40}")


def bound_lock_waits(session: Session, timeout_ms: int) -> Callable[[], None]:
    """Set LOCK_TIMEOUT on the session's connection; return a function that restores it.

    Call the function before the session commits or rolls back, while it still
    holds the connection: the raw cursor works even after a failed flush, and
    the connection then goes back to the pool with its previous setting. A
    second call does nothing. Also used by the POS router.
    """
    cursor = session.connection().connection.cursor()
    try:
        previous = int(cursor.execute("SELECT @@LOCK_TIMEOUT").fetchone()[0])
        cursor.execute(f"SET LOCK_TIMEOUT {int(timeout_ms)}")
    except BaseException:
        cursor.close()
        raise
    restored = False

    def restore() -> None:
        nonlocal restored
        if restored:
            return
        restored = True
        try:
            cursor.execute(f"SET LOCK_TIMEOUT {previous}")
        finally:
            cursor.close()

    return restore


@contextmanager
def lock_wait_limited(session: Session, timeout_ms: int) -> Iterator[None]:
    """Bound each lock wait in the block. Flush inside it; commit or roll back after it."""
    restore = bound_lock_waits(session, timeout_ms)
    try:
        yield
    finally:
        restore()


def _write(principal: Principal, action: str, transaction_id: str | None, details: str | None) -> None:
    try:
        with session_factory() as session:
            with lock_wait_limited(session, LOCK_TIMEOUT_MS):
                user_id = find_user_id(session, principal.sub)
                record_audit(session, action, "pos_transaction", transaction_id, user_id, details)
                session.flush()
            session.commit()
    except Exception:
        logger.exception("Could not write %s audit for transaction %s", action, transaction_id)


def audit_rejected_event(principal: Principal, transaction_id: str | None, error: ApiError) -> None:
    """``transaction_id`` is the raw value from the body; an unusable one goes to details."""
    details = f"{error.code}: {error.message}"
    if transaction_id is not None and not _AUDIT_KEY.fullmatch(transaction_id):
        details += f" [transaction_id: {json.dumps(transaction_id, ensure_ascii=False)}]"
        transaction_id = None
    _write(principal, "EVENT_REJECTED", transaction_id, details)


def audit_duplicate_event(principal: Principal, transaction_id: str) -> None:
    _write(principal, "DUPLICATE_EVENT", transaction_id, None)
