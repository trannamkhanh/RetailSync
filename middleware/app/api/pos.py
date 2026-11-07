"""POS event endpoint (PB-05, PB-04-3, PB-48-4, PB-04-5): receive an event from a registered terminal."""

from collections.abc import Callable, Generator
import logging
from typing import Any

from fastapi import APIRouter, Body, Depends
from pydantic import ValidationError
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.api.schemas.pos import PosEvent, PosEventResult
from app.core.client_cert import require_gateway, require_terminal_certificate
from app.core.config import settings
from app.core.db import get_db
from app.core.errors import ApiError
from app.core.security import Principal, require_role
from app.services.event_audit import audit_duplicate_event, audit_rejected_event, bound_lock_waits
from app.services.pos_events import process_event


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/pos", tags=["POS"])

# SQL Server: "Lock request time out period exceeded."
LOCK_TIMEOUT_ERROR = 1222


def _invalid_event(error: ValidationError) -> ApiError:
    first = error.errors()[0]
    field = ".".join(str(part) for part in first["loc"]) or "body"
    return ApiError(422, "INVALID_EVENT", f"Invalid field '{field}': {first['msg']}")


def _invalid_body(message: str) -> ApiError:
    return ApiError(422, "INVALID_EVENT", f"Invalid field 'body': {message}")


def _parse_event(payload: Any) -> PosEvent:
    if payload is None:
        raise _invalid_body("event body is required.")
    if not isinstance(payload, dict):
        raise _invalid_body("event body must be a JSON object.")
    try:
        return PosEvent.model_validate(payload)
    except ValidationError as error:
        raise _invalid_event(error) from None


def _is_lock_timeout(error: DBAPIError) -> bool:
    return f"({LOCK_TIMEOUT_ERROR})" in str(error.orig)


def _busy() -> ApiError:
    return ApiError(503, "SERVICE_UNAVAILABLE",
                    "The database is busy and nothing was stored. Retry with the same transaction_id.",
                    outcome="ERROR")


def _log_lock_timeout(stage: str) -> None:
    """One line per lock timeout, without a traceback, so they can be counted."""
    logger.warning("POS request timed out after %s ms waiting for a lock (SQL %s) %s; rolled back, answered 503",
                   settings.pos_lock_timeout_ms, LOCK_TIMEOUT_ERROR, stage)


def bounded_lock_waits(session: Session = Depends(get_db)) -> Generator[Callable[[], None], None, None]:
    """Bound each lock wait from the start of the request (PB-04-5).

    Declared before ``require_role`` on the route, so the account lookup there
    runs under ``POS_LOCK_TIMEOUT_MS`` too; FastAPI gives both the same session.
    Yields the restore function: the route calls it before it commits or rolls
    back. On a 401, 403 or error raised before that, it runs here instead,
    while ``get_db`` still holds the connection.
    """
    restore = bound_lock_waits(session, settings.pos_lock_timeout_ms)
    try:
        yield restore
    except DBAPIError as error:
        if not _is_lock_timeout(error):
            raise
        _log_lock_timeout("during the account lookup")
        raise _busy() from None
    finally:
        restore()


def _raw_transaction_id(payload: Any) -> str | None:
    """The transaction id as sent, even when the body failed validation.

    The audit writer decides whether it is a usable key (PB-04-3).
    """
    value = payload.get("transaction_id") if isinstance(payload, dict) else None
    return value if isinstance(value, str) else None


@router.post("/events", response_model=PosEventResult)
def receive_pos_event(payload: Any = Body(default=None),
                      fingerprint: str | None = Depends(require_gateway),
                      restore_lock_timeout: Callable[[], None] = Depends(bounded_lock_waits),
                      principal: Principal = Depends(require_role("POS")),
                      session: Session = Depends(get_db)) -> dict:
    """Validate the body, apply the event and commit one transaction.

    The body is taken as plain JSON so an empty body, an array or a bad field
    becomes 422 ``INVALID_EVENT`` (DS-04), not the global ``VALIDATION_ERROR``.
    Malformed JSON is rejected by FastAPI before authentication and keeps the
    global handler's ``VALIDATION_ERROR`` code.

    A rejection rolls the event back and is audited in its own transaction, as
    is a duplicate (PB-04-3). A 401 or 403 from ``require_role`` never reaches
    this body, and a database failure is not an ``ApiError``: neither is audited.

    With ``MTLS_REQUIRED`` on, ``require_gateway`` runs before ``require_role``
    and refuses a request that skipped the gateway. Once the body is parsed, the
    certificate must belong to the event's terminal; that 403 is audited (PB-48-4).

    Each single lock wait, from the account lookup to the STOCK_CHANGE insert,
    lasts at most ``POS_LOCK_TIMEOUT_MS`` (NFR01); a request that meets several
    held locks can wait longer in total. A lock timeout rolls the event back
    and answers 503, so the POS resends the same ``transaction_id``; it is not
    a rejection and is not audited (PB-04-5).
    """
    try:
        try:
            event = _parse_event(payload)
            require_terminal_certificate(session, event.pos_id, fingerprint)
            result = process_event(session, event, principal)
            session.flush()
        finally:
            restore_lock_timeout()
    except ApiError as error:
        session.rollback()
        audit_rejected_event(principal, _raw_transaction_id(payload), error)
        raise
    except DBAPIError as error:
        if not _is_lock_timeout(error):
            raise
        session.rollback()
        _log_lock_timeout(f"for event {_raw_transaction_id(payload)!r}")
        raise _busy() from None
    session.commit()
    if result["outcome"] == "DUPLICATE":
        audit_duplicate_event(principal, event.transaction_id)
    return result
