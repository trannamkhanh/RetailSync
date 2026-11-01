"""Lookups and inserts for store and POS terminal registration."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.models import PosTerminal, StaffUser, Store


def find_store(session: Session, store_id: str) -> Store | None:
    return session.get(Store, store_id)


def find_pos_terminal(session: Session, pos_id: str) -> PosTerminal | None:
    return session.get(PosTerminal, pos_id)


def find_terminal_by_fingerprint(session: Session, cert_fingerprint: str) -> PosTerminal | None:
    return session.scalar(select(PosTerminal).where(PosTerminal.cert_fingerprint == cert_fingerprint))


def find_user_id(session: Session, username: str) -> int | None:
    """The audit log stores the numeric user id, not the token subject."""
    return session.scalar(select(StaffUser.user_id).where(StaffUser.username == username))


def add_store(session: Session, store: Store) -> None:
    session.add(store)


def add_pos_terminal(session: Session, terminal: PosTerminal) -> None:
    session.add(terminal)
