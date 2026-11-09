"""Aggregation SQL for one store (PB-14). Never commits; the job owns that."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.domain.models import PosTransaction


def set_lock_timeout(session: Session, milliseconds: int) -> None:
    """Bound every lock wait of this transaction, so a POS request is not held."""
    session.execute(text(f"SET LOCK_TIMEOUT {int(milliseconds)}"))


def count_unassigned(session: Session, store_id: str) -> int:
    return int(session.scalar(
        select(func.count()).select_from(PosTransaction).where(
            PosTransaction.store_id == store_id,
            PosTransaction.sync_batch_id.is_(None),
        )
    ) or 0)


def link_transactions(session: Session, store_id: str,
                      sync_batch_id: str) -> list[tuple[str, datetime]]:
    """Claim the store's unbatched transactions in one UPDATE ... OUTPUT.

    A transaction committed after this statement keeps a null ``sync_batch_id``
    and goes to the next batch, which is what DS-05 section 4 asks for.
    """
    rows = session.execute(
        text("""
            UPDATE dbo.pos_transaction
            SET sync_batch_id = :sync_batch_id
            OUTPUT inserted.txn_id, inserted.created_at
            WHERE store_id = :store_id AND sync_batch_id IS NULL
        """),
        {"sync_batch_id": sync_batch_id, "store_id": store_id},
    ).all()
    return [(str(txn_id), created_at) for txn_id, created_at in rows]


def line_totals(session: Session, sync_batch_id: str) -> list[tuple[str, int, int, Decimal]]:
    """Per SKU: sold quantity, returned quantity and net revenue of the batch."""
    rows = session.execute(
        text("""
            SELECT ti.sku,
                   SUM(CASE WHEN t.txn_type = 'SALE' THEN ti.qty ELSE 0 END),
                   SUM(CASE WHEN t.txn_type IN ('RETURN', 'CANCELLATION')
                            THEN ti.qty ELSE 0 END),
                   SUM(CASE WHEN t.txn_type = 'SALE' THEN ti.qty * ti.unit_price
                            ELSE -ti.qty * ti.unit_price END)
            FROM dbo.transaction_item ti
            JOIN dbo.pos_transaction t ON t.txn_id = ti.txn_id
            WHERE t.sync_batch_id = :sync_batch_id
            GROUP BY ti.sku
            ORDER BY ti.sku
        """),
        {"sync_batch_id": sync_batch_id},
    ).all()
    return [(str(sku), int(sold), int(returned), Decimal(net))
            for sku, sold, returned, net in rows]
