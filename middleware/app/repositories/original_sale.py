"""Queries for the SALE that a RETURN or CANCELLATION refers to."""

from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session


def find_sale(session: Session, store_id: str, txn_id: str) -> Any | None:
    """Read a SALE of this store without taking a lock."""
    return session.execute(
        text(
            """
            SELECT txn_id, status
            FROM dbo.pos_transaction
            WHERE txn_id = :txn_id AND store_id = :store_id AND txn_type = 'SALE'
            """
        ),
        {"txn_id": txn_id, "store_id": store_id},
    ).first()


def lock_sale(session: Session, store_id: str, txn_id: str) -> Any | None:
    """Read the SALE under an update lock for the rest of the transaction.

    A RETURN and a CANCELLATION of the same sale therefore run one after the
    other: the second waits here until the first commits or rolls back.
    """
    return session.execute(
        text(
            """
            SELECT txn_id, status
            FROM dbo.pos_transaction WITH (UPDLOCK, ROWLOCK)
            WHERE txn_id = :txn_id AND store_id = :store_id AND txn_type = 'SALE'
            """
        ),
        {"txn_id": txn_id, "store_id": store_id},
    ).first()


def sold_quantities(session: Session, txn_id: str) -> dict[str, int]:
    """Quantity per SKU recorded on the original sale."""
    rows = session.execute(
        text(
            """
            SELECT sku, SUM(qty) AS quantity
            FROM dbo.transaction_item
            WHERE txn_id = :txn_id
            GROUP BY sku
            """
        ),
        {"txn_id": txn_id},
    )
    return {str(sku): int(quantity) for sku, quantity in rows}


def returned_quantities(session: Session, store_id: str, txn_id: str) -> dict[str, int]:
    """Quantity per SKU already returned by applied RETURN events of this sale."""
    rows = session.execute(
        text(
            """
            SELECT item.sku, SUM(item.qty) AS quantity
            FROM dbo.transaction_item AS item
            JOIN dbo.pos_transaction AS txn ON txn.txn_id = item.txn_id
            WHERE txn.ref_txn_id = :txn_id
              AND txn.txn_type = 'RETURN'
              AND txn.store_id = :store_id
            GROUP BY item.sku
            """
        ),
        {"txn_id": txn_id, "store_id": store_id},
    )
    return {str(sku): int(quantity) for sku, quantity in rows}
