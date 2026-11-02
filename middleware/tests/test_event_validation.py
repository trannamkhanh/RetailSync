"""Event source check (PB-08-2, PB-08-3): registered, active and token-scoped.

Service-level tests against the real SQL Server test database. Every test
creates its own ``TEST-`` rows through ``db_session`` and never commits.
"""

from decimal import Decimal
from unittest.mock import Mock

import pytest
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.core.security import Principal
from app.domain.models import PosTerminal, Store
from app.services.event_validation import validate_event_source


STORE_ID = "TEST-EV1"
POS_ID = "TEST-POS-EV1"
OTHER_STORE_ID = "TEST-EV2"
OTHER_POS_ID = "TEST-POS-EV2"
INACTIVE_STORE_ID = "TEST-EV3"
INACTIVE_COUNTERPART_POS_ID = "TEST-POS-EV4"
INACTIVE_POS_ID = "TEST-POS-EV3"
UNKNOWN_STORE_ID = "TEST-NOSTORE"
UNKNOWN_POS_ID = "TEST-NOPOS"


def add_store(session: Session, store_id: str, is_active: bool = True) -> Store:
    store = Store(store_id=store_id, name="Event source store", latitude=Decimal("16.000000"),
                  longitude=Decimal("108.000000"), region_id="TEST", is_active=is_active)
    session.add(store)
    return store


def add_terminal(session: Session, pos_id: str, store_id: str,
                 status: str = "ACTIVE") -> PosTerminal:
    terminal = PosTerminal(pos_id=pos_id, store_id=store_id, status=status)
    session.add(terminal)
    return terminal


@pytest.fixture
def world(db_session: Session) -> None:
    """Two active stores and one inactive store, with terminals for each case."""
    add_store(db_session, STORE_ID)
    add_store(db_session, OTHER_STORE_ID)
    add_store(db_session, INACTIVE_STORE_ID, is_active=False)
    db_session.flush()
    add_terminal(db_session, POS_ID, STORE_ID)
    add_terminal(db_session, OTHER_POS_ID, OTHER_STORE_ID)
    add_terminal(db_session, INACTIVE_POS_ID, STORE_ID, status="INACTIVE")
    add_terminal(db_session, INACTIVE_COUNTERPART_POS_ID, INACTIVE_STORE_ID)
    db_session.flush()


def pos_principal(store_id: str | None = STORE_ID, pos_id: str | None = POS_ID) -> Principal:
    return Principal(sub="pos_system", role="POS", store_id=store_id, pos_id=pos_id)


def assert_rejected(excinfo, status: int, code: str) -> ApiError:
    error = excinfo.value
    assert isinstance(error, ApiError)
    assert (error.status, error.code, error.outcome) == (status, code, "REJECTED")
    return error


# --- accepted --------------------------------------------------------------


def test_registered_active_source_with_a_matching_token_passes(world, db_session):
    validate_event_source(db_session, pos_principal(), STORE_ID, POS_ID)


def test_validation_reads_only_and_never_commits(world, db_session, monkeypatch):
    commit = Mock()
    monkeypatch.setattr(db_session, "commit", commit)

    validate_event_source(db_session, pos_principal(), STORE_ID, POS_ID)

    commit.assert_not_called()
    assert not db_session.new
    assert not db_session.dirty


# --- unregistered or inactive store and terminal: 422 ----------------------


@pytest.mark.parametrize("store_id,pos_id", [
    (STORE_ID, UNKNOWN_POS_ID),
    (STORE_ID, OTHER_POS_ID),
    (INACTIVE_STORE_ID, INACTIVE_COUNTERPART_POS_ID),
    (STORE_ID, INACTIVE_POS_ID),
    (UNKNOWN_STORE_ID, UNKNOWN_POS_ID),
], ids=["unknown-terminal", "terminal-of-another-store", "inactive-store",
        "inactive-terminal", "unknown-store-and-terminal"])
def test_unregistered_or_inactive_source_returns_422(world, db_session, store_id, pos_id):
    with pytest.raises(ApiError) as excinfo:
        validate_event_source(db_session, pos_principal(store_id, pos_id), store_id, pos_id)

    error = assert_rejected(excinfo, 422, "UNREGISTERED_STORE_OR_POS")
    assert store_id in error.message and pos_id in error.message


def test_unknown_store_with_a_mismatched_token_returns_422_not_403(world, db_session):
    with pytest.raises(ApiError) as excinfo:
        validate_event_source(db_session, pos_principal(), UNKNOWN_STORE_ID, POS_ID)

    error = assert_rejected(excinfo, 422, "UNREGISTERED_STORE_OR_POS")
    assert UNKNOWN_STORE_ID in error.message


# --- token scoped to another source: 403 -----------------------------------


@pytest.mark.parametrize("token_store_id,token_pos_id", [
    (OTHER_STORE_ID, POS_ID),
    (STORE_ID, OTHER_POS_ID),
    (None, POS_ID),
    (STORE_ID, None),
    (None, None),
], ids=["another-store", "another-terminal", "no-store-claim", "no-pos-claim",
        "no-scope-claims"])
def test_token_for_another_source_returns_403(world, db_session, token_store_id, token_pos_id):
    with pytest.raises(ApiError) as excinfo:
        validate_event_source(db_session, pos_principal(token_store_id, token_pos_id),
                              STORE_ID, POS_ID)

    error = assert_rejected(excinfo, 403, "FORBIDDEN")
    assert STORE_ID in error.message and POS_ID in error.message
