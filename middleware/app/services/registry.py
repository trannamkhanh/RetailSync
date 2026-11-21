"""Store and POS terminal registration (PB-08-1). Adds rows; the router commits."""

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.core.security import Principal
from app.domain.models import PosTerminal, Store
from app.repositories import registry as repository
from app.services.audit import record_audit


def _already_exists(entity: str, key: str) -> ApiError:
    return ApiError(409, "ALREADY_EXISTS", f"{entity} '{key}' is already registered.")


def _error_text(error: IntegrityError) -> str:
    return str(error.orig or error).casefold()


def _flush_store(session: Session, store: Store) -> None:
    """The uniqueness pre-check races; the constraint is the final authority.

    Never rolls back here: the router owns the transaction boundary.
    """
    try:
        session.flush()
    except IntegrityError as error:
        detail = _error_text(error)
        if "pk_store" in detail or "(2627)" in detail or "(2601)" in detail:
            raise _already_exists("Store", store.store_id) from None
        raise


def _flush_terminal(session: Session, terminal: PosTerminal) -> None:
    """Map terminal constraint failures without rolling back the caller's session."""
    try:
        session.flush()
    except IntegrityError as error:
        detail = _error_text(error)
        if "uq_pos_terminal_cert" in detail or "cert_fingerprint" in detail:
            raise _already_exists("Certificate fingerprint",
                                  terminal.cert_fingerprint or "") from None
        if "fk_pos_terminal_store" in detail or ("(547)" in detail and "pos_terminal" in detail):
            raise ApiError(422, "VALIDATION_ERROR",
                           f"Store '{terminal.store_id}' does not exist.") from None
        if "pk_pos_terminal" in detail or "(2627)" in detail:
            raise _already_exists("POS terminal", terminal.pos_id) from None
        raise


def register_store(session: Session, store: Store, principal: Principal) -> Store:
    # Resolve the auditor before adding rows: a query after an insert would
    # autoflush outside the guard below.
    user_id = repository.find_user_id(session, principal.sub)
    if repository.find_store(session, store.store_id) is not None:
        raise _already_exists("Store", store.store_id)
    repository.add_store(session, store)
    record_audit(session, "STORE_REGISTERED", "store", store.store_id, user_id,
                 f"Registered {store.name} in region {store.region_id}.")
    _flush_store(session, store)
    return store


def register_pos_terminal(session: Session, terminal: PosTerminal, principal: Principal) -> PosTerminal:
    user_id = repository.find_user_id(session, principal.sub)
    store = repository.find_store(session, terminal.store_id)
    if store is None:
        raise ApiError(404, "NOT_FOUND", f"Store '{terminal.store_id}' does not exist.")
    terminal.store_id = store.store_id
    if repository.find_pos_terminal(session, terminal.pos_id) is not None:
        raise _already_exists("POS terminal", terminal.pos_id)
    if terminal.cert_fingerprint is not None and \
            repository.find_terminal_by_fingerprint(session, terminal.cert_fingerprint) is not None:
        raise _already_exists("Certificate fingerprint", terminal.cert_fingerprint)
    repository.add_pos_terminal(session, terminal)
    record_audit(session, "POS_REGISTERED", "pos_terminal", terminal.pos_id, user_id,
                 f"Registered terminal {terminal.pos_id} for store {terminal.store_id}.")
    _flush_terminal(session, terminal)
    return terminal
