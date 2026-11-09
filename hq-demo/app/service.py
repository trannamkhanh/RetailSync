"""Apply one batch in the caller's transaction (PB-18-2, PB-18-3)."""

from decimal import Decimal

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import NackError
from app.models import HqSalesTotal, HqSyncBatch
from app.schemas import SalesLine, SyncBatchMessage


def _duplicate(session: Session, row: HqSyncBatch, payload_hash: str) -> bool:
    if row.payload_hash != payload_hash:
        raise NackError(409, "CONFLICT",
                        f"Batch {row.sync_batch_id} already recorded with different content.",
                        row.sync_batch_id)
    row.duplicate_count += 1
    session.flush()
    return True


def _add(session: Session, store_id: str, sku: str, sold_qty: int, returned_qty: int,
         net_revenue: Decimal) -> None:
    session.execute(
        update(HqSalesTotal)
        .where(HqSalesTotal.store_id == store_id, HqSalesTotal.sku == sku)
        .values(sold_qty=HqSalesTotal.sold_qty + sold_qty,
                returned_qty=HqSalesTotal.returned_qty + returned_qty,
                net_revenue=HqSalesTotal.net_revenue + net_revenue))


def _add_totals(session: Session, store_id: str, lines: list[SalesLine]) -> None:
    for line in lines:
        result = session.execute(
            update(HqSalesTotal)
            .where(HqSalesTotal.store_id == store_id, HqSalesTotal.sku == line.sku)
            .values(sold_qty=HqSalesTotal.sold_qty + line.sold_qty,
                    returned_qty=HqSalesTotal.returned_qty + line.returned_qty,
                    net_revenue=HqSalesTotal.net_revenue + line.net_revenue))
        if result.rowcount:
            continue
        try:
            with session.begin_nested():
                session.add(HqSalesTotal(store_id=store_id, sku=line.sku,
                                         sold_qty=line.sold_qty,
                                         returned_qty=line.returned_qty,
                                         net_revenue=line.net_revenue))
                session.flush()
        except IntegrityError:
            # Another batch inserted the same (store, sku) row between the
            # update and the insert; add to its totals instead.
            _add(session, store_id, line.sku, line.sold_qty, line.returned_qty,
                 line.net_revenue)


def apply_batch(session: Session, message: SyncBatchMessage, payload_hash: str) -> bool:
    """Store the batch and its totals once. Return True when it was a duplicate."""
    existing = session.get(HqSyncBatch, message.batch_id)
    if existing is not None:
        return _duplicate(session, existing, payload_hash)
    try:
        with session.begin_nested():
            session.add(HqSyncBatch(sync_batch_id=message.batch_id,
                                    store_id=message.store_id,
                                    txn_count=message.txn_count,
                                    payload_hash=payload_hash))
            session.flush()
            _add_totals(session, message.store_id, message.lines)
    except IntegrityError:
        # Two identical batches arrived at the same moment: the primary key
        # decided, and the loser answers duplicate (PB-18-3).
        session.expire_all()
        existing = session.get(HqSyncBatch, message.batch_id)
        if existing is None:
            raise
        return _duplicate(session, existing, payload_hash)
    return False
