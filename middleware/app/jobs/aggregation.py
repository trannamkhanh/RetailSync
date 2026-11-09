"""The hourly aggregation job (PB-14): one transaction per store.

Each store is aggregated in its own session and committed on its own, so a lock
timeout or a database error rolls that store back and its transactions join the
next run. The shared scheduler calls this function without arguments.

``session_factory`` is a module attribute so a test can point the job at
RTS_DB_TEST, the way ``app.services.event_audit`` does; production uses
``SessionLocal``.
"""

from collections.abc import Callable
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.domain.models import Store
from app.services.aggregation import aggregate_store


logger = logging.getLogger(__name__)

session_factory: Callable[[], Session] = SessionLocal


def run_aggregation(now: datetime | None = None) -> list[str]:
    """Aggregate every store; return the new sync_batch_id values."""
    moment = now or datetime.now(timezone.utc)
    with session_factory() as session:
        store_ids = [str(store) for store in session.scalars(
            select(Store.store_id).order_by(Store.store_id))]

    created: list[str] = []
    for store_id in store_ids:
        session = session_factory()
        try:
            batch_id = aggregate_store(session, store_id, moment)
            session.commit()
            if batch_id is not None:
                created.append(batch_id)
        except Exception:
            session.rollback()
            logger.warning(
                "Aggregation failed for store %s; its transactions join the next run.",
                store_id, exc_info=True)
        finally:
            session.close()
    return created
