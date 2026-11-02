"""Primary-key lookups for the event source check.

That check runs on every POS event, so it must stay two cheap lookups.
"""

from sqlalchemy.orm import Session

from app.domain.models import PosTerminal, Store


def get_store(session: Session, store_id: str) -> Store | None:
    return session.get(Store, store_id)


def get_pos_terminal(session: Session, pos_id: str) -> PosTerminal | None:
    return session.get(PosTerminal, pos_id)
