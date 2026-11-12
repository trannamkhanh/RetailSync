"""The daily near-expiry check (PB-21-3, PB-21-4): one transaction per store.

Each store is checked in its own session and committed on its own, so a database
error rolls that store back and leaves no partial alerts; the other stores still
run and the job logs the failure. The next schedule repeats a failed store.

``session_factory`` and ``clock`` are module attributes so a test can point the
job at RTS_DB_TEST and a fixed business date, the way ``app.jobs.aggregation``
does; production uses ``SessionLocal`` and ``app.core.clock``.
"""

from collections.abc import Callable
import logging

from sqlalchemy.orm import Session

from app.core import clock
from app.core.config import settings
from app.core.db import SessionLocal
from app.repositories import near_expiry as repository
from app.services import near_expiry

logger = logging.getLogger(__name__)

session_factory: Callable[[], Session] = SessionLocal


def run_near_expiry_check() -> dict[str, near_expiry.StoreCheck]:
    """Check every store and return what each run changed.

    Safe to run twice on one business date: the service creates no duplicate
    OPEN alert and writes only values that moved.
    """
    today = clock.today_local()
    default_days = settings.near_expiry_default_days
    with session_factory() as session:
        store_ids = repository.list_store_ids(session)
        thresholds = repository.threshold_map(session)

    results: dict[str, near_expiry.StoreCheck] = {}
    for store_id in store_ids:
        session = session_factory()
        try:
            results[store_id] = near_expiry.check_store(
                session, store_id, today, thresholds, default_days)
            session.commit()
        except Exception:
            session.rollback()
            logger.warning(
                "Near-expiry check failed for store %s; the next run repeats it.",
                store_id, exc_info=True)
        finally:
            session.close()
    return results
