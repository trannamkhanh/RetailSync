"""Copy original sale lines and mark its status; never commits."""

from decimal import Decimal

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.domain.models import PosTransaction, TransactionItem


def sale_items(session: Session, txn_id: str) -> list[tuple[str, int, Decimal]]:
    return list(session.execute(select(
        TransactionItem.sku, TransactionItem.qty, TransactionItem.unit_price,
    ).where(TransactionItem.txn_id == txn_id).order_by(TransactionItem.item_id)).tuples())


def mark_cancelled(session: Session, txn_id: str) -> None:
    session.execute(update(PosTransaction).where(
        PosTransaction.txn_id == txn_id, PosTransaction.txn_type == "SALE",
    ).values(status="CANCELLED"))
