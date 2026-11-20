"""Transaction claims and item queries; callers own the transaction."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.models import PosTransaction, TransactionItem


def find_payload_hash(session: Session, txn_id: str) -> str | None:
    return session.scalar(
        select(PosTransaction.payload_hash).where(PosTransaction.txn_id == txn_id)
    )


def find_occurred_at(session: Session, txn_id: str) -> datetime | None:
    """The stored ``occurred_at``, so a duplicate can answer with the first one.

    The Dashboard classifies a transaction from this value, not from the one on a
    later resend: the claim returns before any timestamp is compared.
    """
    return session.scalar(
        select(PosTransaction.occurred_at).where(PosTransaction.txn_id == txn_id)
    )


def insert_transaction(
    session: Session, txn_id: str, store_id: str, pos_id: str, txn_type: str,
    ref_txn_id: str | None, payload_hash: str, occurred_at: datetime | None = None,
) -> None:
    session.add(PosTransaction(
        txn_id=txn_id, store_id=store_id, pos_id=pos_id, txn_type=txn_type,
        ref_txn_id=ref_txn_id, payload_hash=payload_hash, status="OK",
        occurred_at=occurred_at,
    ))
    session.flush()


def transaction_skus(session: Session, store_id: str, txn_id: str) -> list[str]:
    return list(session.scalars(
        select(TransactionItem.sku)
        .join(PosTransaction, TransactionItem.txn_id == PosTransaction.txn_id)
        .where(PosTransaction.txn_id == txn_id, PosTransaction.store_id == store_id)
        .distinct().order_by(TransactionItem.sku)
    ))
