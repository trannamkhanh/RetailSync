"""Queries for the SALE that a RETURN or CANCELLATION refers to.

The driver binds Python ``str`` as ``nvarchar``; SQLAlchemy does not call
``setinputsizes`` for ``text()``. Every string parameter is therefore cast to
the column's ``varchar`` length, so the predicate can use the key instead of
``CONVERT_IMPLICIT`` on the column, which scans the index and takes a lock on
every row it reads (issue #25).
"""

from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session


def find_sale(session: Session, store_id: str, txn_id: str) -> Any | None:
    """Read a SALE of this store without taking a lock.

    The whole result is read, as in ``lock_sale``, so an error SQL Server
    reports after the first row is not discarded.
    """
    return session.execute(
        text(
            """
            SELECT txn_id, status
            FROM dbo.pos_transaction
            WHERE txn_id = CAST(:txn_id AS varchar(40))
              AND store_id = CAST(:store_id AS varchar(10))
              AND txn_type = 'SALE'
            """
        ),
        {"txn_id": txn_id, "store_id": store_id},
    ).one_or_none()


def lock_sale(session: Session, store_id: str, txn_id: str) -> Any | None:
    """Read the SALE under an update lock for the rest of the transaction.

    A RETURN and a CANCELLATION of the same sale therefore run one after the
    other: the second waits here until the first commits or rolls back.

    The result is read to the end with ``one_or_none`` on purpose. The plan can
    scan, stream the matching row and only then report the deadlock victim
    (1205) while it finishes. ``first()`` closes the cursor after that row and
    loses the error, so the request would continue in the transaction SQL
    Server already rolled back; the claim is gone and the item insert then
    fails with FK 547. Reading to the end makes the 1205 reach the handler,
    which rolls the request back and answers 503 SERVICE_UNAVAILABLE.
    """
    return session.execute(
        text(
            """
            SELECT txn_id, status
            FROM dbo.pos_transaction WITH (UPDLOCK, ROWLOCK)
            WHERE txn_id = CAST(:txn_id AS varchar(40))
              AND store_id = CAST(:store_id AS varchar(10))
              AND txn_type = 'SALE'
            """
        ),
        {"txn_id": txn_id, "store_id": store_id},
    ).one_or_none()


def sold_quantities(session: Session, txn_id: str) -> dict[str, int]:
    """Quantity per SKU recorded on the original sale."""
    rows = session.execute(
        text(
            """
            SELECT sku, SUM(qty) AS quantity
            FROM dbo.transaction_item
            WHERE txn_id = CAST(:txn_id AS varchar(40))
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
            FROM dbo.pos_transaction AS txn WITH (INDEX(ix_pos_transaction_ref))
            JOIN dbo.transaction_item AS item ON item.txn_id = txn.txn_id
            WHERE txn.ref_txn_id = CAST(:txn_id AS varchar(40))
              AND txn.txn_type = 'RETURN'
              AND txn.store_id = CAST(:store_id AS varchar(10))
            GROUP BY item.sku
            """
        ),
        {"txn_id": txn_id, "store_id": store_id},
    )
    return {str(sku): int(quantity) for sku, quantity in rows}
