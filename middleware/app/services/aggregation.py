"""Aggregate one store's unbatched transactions into a sync_batch (PB-14).

The caller owns the transaction and commits; the job in ``app/jobs/aggregation``
calls this once per store.
"""

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.config import settings
from app.domain.models import SalesSummaryLine, SyncBatch
from app.repositories import aggregation as repository
from app.services.event_audit import lock_wait_limited


def _utc(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def batch_id_for(store_id: str, moment: datetime) -> str:
    """DS-05 section 2: SB-<store_id>-<yyyyMMddHHmmss UTC>, at most 28 characters."""
    return f"SB-{store_id}-{_utc(moment):%Y%m%d%H%M%S}"


def aggregate_store(session: Session, store_id: str, now: datetime) -> str | None:
    """Create one PENDING batch for the store, or return None when it has none.

    Steps follow DS-05 section 4: check for unbatched transactions, insert the
    batch, claim the transactions with one UPDATE ... OUTPUT, compute the lines
    from exactly the claimed rows, insert them and set the batch fields.
    ``lock_wait_limited`` restores the connection's previous LOCK_TIMEOUT, so
    the pool never hands a 2000 ms limit to a POS request.
    """
    moment = _utc(now)
    sync_batch_id = batch_id_for(store_id, moment)
    with lock_wait_limited(session, settings.pos_lock_timeout_ms):
        if repository.count_unassigned(session, store_id) == 0:
            return None

        stored_moment = moment.replace(tzinfo=None)
        batch = SyncBatch(sync_batch_id=sync_batch_id, store_id=store_id,
                          period_start=stored_moment, period_end=stored_moment,
                          txn_count=0, status="PENDING")
        session.add(batch)
        session.flush()

        claimed = repository.link_transactions(session, store_id, sync_batch_id)
        if not claimed:
            # Another aggregation took them between the check and the claim.
            session.delete(batch)
            session.flush()
            return None

        for sku, sold_qty, returned_qty, net_revenue in repository.line_totals(
                session, sync_batch_id):
            session.add(SalesSummaryLine(
                sync_batch_id=sync_batch_id,
                sku=sku,
                sold_qty=sold_qty,
                returned_qty=returned_qty,
                net_revenue=Decimal(net_revenue).quantize(Decimal("0.01")),
            ))

        batch.txn_count = len(claimed)
        batch.period_start = min(created_at for _, created_at in claimed)
        batch.period_end = max(created_at for _, created_at in claimed)
        session.flush()
    return sync_batch_id
