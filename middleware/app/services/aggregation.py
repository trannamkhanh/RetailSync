"""Aggregate one store's unbatched transactions into a sync_batch (PB-14).

The caller owns the transaction and commits; the job in ``app/jobs/aggregation``
calls this once per store.

``raw_bytes`` (PB-40, TST40-3) is what the batch's transactions would cost if
they were sent to HQ one by one: the sum, over every transaction of the batch
(SALE, RETURN and CANCELLATION), of the UTF-8 byte length of
``json.dumps(event, separators=(",", ":"))``, where ``event`` is the POS event
as the POS sends it (DS-04): ``event_type``, ``transaction_id``, ``store_id``,
``pos_id``, ``timestamp`` (ISO 8601 UTC, seconds, ``Z``), ``items`` with
``sku``, ``quantity`` and ``unit_price`` (a string with two decimals), plus
``original_transaction_id`` for RETURN and CANCELLATION only. A CANCELLATION
carries no items on the wire (its stored items are copied from the sale). It is
measured like ``payload_bytes``, the UTF-8 length of the body sent to HQ.
"""

from collections.abc import Iterable
from datetime import datetime, timezone
from decimal import Decimal
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.domain.models import PosTransaction, SalesSummaryLine, SyncBatch, TransactionItem
from app.repositories import aggregation as repository
from app.services.event_audit import lock_wait_limited


def _utc(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def batch_id_for(store_id: str, moment: datetime) -> str:
    """DS-05 section 2: SB-<store_id>-<yyyyMMddHHmmss UTC>, at most 28 characters."""
    return f"SB-{store_id}-{_utc(moment):%Y%m%d%H%M%S}"


def pos_event(transaction: PosTransaction, items: Iterable[TransactionItem]) -> dict:
    """The DS-04 POS event of a stored transaction, as the POS sends it."""
    event: dict = {"event_type": transaction.txn_type, "transaction_id": transaction.txn_id}
    if transaction.txn_type != "SALE":
        event["original_transaction_id"] = transaction.ref_txn_id
    event.update({
        "store_id": transaction.store_id,
        "pos_id": transaction.pos_id,
        "timestamp": f"{_utc(transaction.created_at):%Y-%m-%dT%H:%M:%SZ}",
        "items": [] if transaction.txn_type == "CANCELLATION" else [
            {"sku": item.sku, "quantity": item.qty, "unit_price": f"{Decimal(item.unit_price):.2f}"}
            for item in items
        ],
    })
    return event


def event_bytes(event: dict) -> int:
    return len(json.dumps(event, separators=(",", ":")).encode("utf-8"))


def raw_bytes_of(session: Session, sync_batch_id: str) -> int:
    """Sum of ``event_bytes`` over the batch's transactions (see the module docstring)."""
    transactions = session.scalars(
        select(PosTransaction).where(PosTransaction.sync_batch_id == sync_batch_id)
        .order_by(PosTransaction.txn_id)).all()
    items: dict[str, list[TransactionItem]] = {}
    for item in session.scalars(
            select(TransactionItem).join(PosTransaction, PosTransaction.txn_id == TransactionItem.txn_id)
            .where(PosTransaction.sync_batch_id == sync_batch_id).order_by(TransactionItem.item_id)):
        items.setdefault(item.txn_id, []).append(item)
    return sum(event_bytes(pos_event(txn, items.get(txn.txn_id, []))) for txn in transactions)


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
        batch.raw_bytes = raw_bytes_of(session, sync_batch_id)
        batch.period_start = min(created_at for _, created_at in claimed)
        batch.period_end = max(created_at for _, created_at in claimed)
        session.flush()
    return sync_batch_id
