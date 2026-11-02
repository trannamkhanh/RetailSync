"""Event source check (PB-08-2, PB-08-3): registered, active and token-scoped.

It runs on every POS event, so it does two primary-key lookups and never
commits. The caller's transaction rolls back if it raises.
"""

from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.core.security import Principal
from app.repositories import event_validation as repository


ACTIVE_STATUS = "ACTIVE"


def _unregistered(store_id: str, pos_id: str) -> ApiError:
    return ApiError(
        422,
        "UNREGISTERED_STORE_OR_POS",
        f"Store '{store_id}' or POS terminal '{pos_id}' is not registered or not active.",
    )


def _forbidden(store_id: str, pos_id: str) -> ApiError:
    return ApiError(
        403,
        "FORBIDDEN",
        f"This token may not send events for store '{store_id}' and POS terminal '{pos_id}'.",
    )


def validate_event_source(session: Session, principal: Principal,
                          store_id: str, pos_id: str) -> None:
    """Reject an event from an unknown, inactive or foreign store or terminal.

    The source check runs before the token check, so an unknown store always
    gets 422, even though the token cannot match it.

    Raises:
        ApiError(422, "UNREGISTERED_STORE_OR_POS"): the store or terminal is
            missing, inactive, or the terminal belongs to another store.
        ApiError(403, "FORBIDDEN"): the token is not scoped to that store and
            terminal, including a POS token without either claim.
    """
    store = repository.get_store(session, store_id)
    terminal = repository.get_pos_terminal(session, pos_id)
    if (
        store is None
        or not store.is_active
        or terminal is None
        or terminal.status != ACTIVE_STATUS
        or terminal.store_id != store_id
    ):
        raise _unregistered(store_id, pos_id)
    if principal.store_id != store_id or principal.pos_id != pos_id:
        raise _forbidden(store_id, pos_id)
