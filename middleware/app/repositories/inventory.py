"""Inventory SQL: read stock, change it atomically, record a movement.

Every function takes a session and never commits. The caller owns the
transaction, so a later failure rolls the stock change and its movement back
together.

The driver binds Python ``str`` as ``nvarchar``; SQLAlchemy does not call
``setinputsizes`` for ``text()``. Every string parameter is therefore cast to
the column's ``varchar`` length, so the key is seekable instead of scanned with
``CONVERT_IMPLICIT`` and its rows locked (issue #25).
"""

from datetime import date
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


def get_stock(session: Session, store_id: str, sku: str) -> int:
    """Return the current quantity for one store and SKU.

    Returns 0 when no inventory row exists, so callers never have to handle
    ``None``.
    """
    quantity = session.execute(
        text(
            """
            SELECT quantity
            FROM dbo.inventory
            WHERE store_id = CAST(:store_id AS varchar(10))
              AND sku = CAST(:sku AS varchar(20))
            """
        ),
        {"store_id": store_id, "sku": sku},
    ).scalar_one_or_none()
    return int(quantity) if quantity is not None else 0


def update_stock_with_guard(
    session: Session, store_id: str, sku: str, delta: int
) -> int | None:
    """Add ``delta`` to quantity in one statement, never going negative.

    The guard lives in the ``WHERE`` clause, so two concurrent deductions are
    serialised by SQL Server and can never pass a stale read. Returns the new
    quantity, or ``None`` when no row was updated (the row is missing or the
    guard rejected the change).

    The output row is read to the end with ``one_or_none`` for the same reason
    as ``lock_sale``: losing a late deadlock (1205) here would leave the rest of
    the basket running in autocommit, where a later SKU could change stock
    without its movement.
    """
    row = session.execute(
        text(
            """
            UPDATE dbo.inventory
            SET quantity = quantity + :delta, updated_at = SYSUTCDATETIME()
            OUTPUT inserted.quantity
            WHERE store_id = CAST(:store_id AS varchar(10))
              AND sku = CAST(:sku AS varchar(20))
              AND quantity + :delta >= 0
            """
        ),
        {"store_id": store_id, "sku": sku, "delta": delta},
    ).one_or_none()
    return int(row.quantity) if row is not None else None


def insert_stock_row(session: Session, store_id: str, sku: str, quantity: int) -> int:
    """Create an inventory row for a positive change and return the quantity.

    A concurrent transaction may create the same row first; the primary key
    then rejects this insert. The savepoint keeps the session usable, and the
    change is retried as an atomic update so the caller's delta is not lost.
    """
    if quantity < 0:
        raise ValueError("quantity must be >= 0")

    last_error: IntegrityError | None = None
    for _ in range(2):
        try:
            with session.begin_nested():
                session.execute(
                    text(
                        """
                        INSERT INTO dbo.inventory (store_id, sku, quantity, updated_at)
                        VALUES (CAST(:store_id AS varchar(10)),
                                CAST(:sku AS varchar(20)),
                                :quantity, SYSUTCDATETIME())
                        """
                    ),
                    {"store_id": store_id, "sku": sku, "quantity": quantity},
                )
            return quantity
        except IntegrityError as error:
            last_error = error
            # Another session may have created the row already. If it is
            # visible now, add the delta on top of it; otherwise retry once.
            existing = update_stock_with_guard(session, store_id, sku, quantity)
            if existing is not None:
                return existing

    if last_error is not None:
        raise last_error
    raise RuntimeError("inventory insert failed without an error")  # pragma: no cover


def add_movement(
    session: Session,
    store_id: str,
    sku: str,
    movement_type: str,
    quantity: int,
    txn_id: str | None = None,
    batch_id: str | None = None,
    reason: str | None = None,
    created_by: int | None = None,
) -> None:
    """Insert one ``inventory_movement`` row. Never commits.

    ``quantity`` is the signed change applied to stock: negative for a SALE,
    positive for a restock or a reversal.
    """
    session.execute(
        text(
            """
            INSERT INTO dbo.inventory_movement
                (store_id, sku, movement_type, quantity, txn_id, batch_id,
                 reason, created_by, created_at)
            VALUES
                (CAST(:store_id AS varchar(10)),
                 CAST(:sku AS varchar(20)),
                 CAST(:movement_type AS varchar(20)),
                 :quantity,
                 CAST(:txn_id AS varchar(40)),
                 CAST(:batch_id AS varchar(30)),
                 CAST(:reason AS nvarchar(200)),
                 :created_by, SYSUTCDATETIME())
            """
        ),
        {
            "store_id": store_id,
            "sku": sku,
            "movement_type": movement_type,
            "quantity": quantity,
            "txn_id": txn_id,
            "batch_id": batch_id,
            "reason": reason,
            "created_by": created_by,
        },
    )


# ---- batches (PB-20) --------------------------------------------------------


def lock_batches(session: Session, store_id: str, sku: str, *,
                 sellable_only: bool, today: date | None = None) -> list[Any]:
    """Read the batches of one store and SKU under an update lock, earliest first.

    ``sellable_only`` keeps the batches that are still sellable
    (``expiry_date >= today``). The restore path passes ``False``, so an expired
    batch gets its stock back too; the contract only says it is then not
    sellable.

    Rows always come back in ``(expiry_date, batch_id)`` order and are locked in
    that order. A sale locks the sellable subset, a restore locks all of them,
    and any subset of the same order locks in the same relative order, so two
    writers of the same store and SKU cannot deadlock on these rows.

    ``today`` is cast to ``date`` instead of the indexed column being converted
    (issue #25); the two call shapes are separate statements so the plan can
    seek the visible range instead of scanning.
    """
    if sellable_only and today is None:
        raise ValueError("today is required when sellable_only is True")
    sellable_filter = "AND expiry_date >= CAST(:today AS date)" if sellable_only else ""
    rows = session.execute(
        text(
            f"""
            SELECT batch_id, sku, store_id, expiry_date, quantity
            FROM dbo.product_batch WITH (UPDLOCK, ROWLOCK)
            WHERE store_id = CAST(:store_id AS varchar(10))
              AND sku = CAST(:sku AS varchar(20))
              {sellable_filter}
            ORDER BY expiry_date, batch_id
            """
        ),
        {"store_id": store_id, "sku": sku, "today": today},
    ).all()
    return list(rows)


def sum_sellable(session: Session, store_id: str, sku: str, today: date) -> int:
    """Sum of the batches of one store and SKU that are still sellable."""
    total = session.execute(
        text(
            """
            SELECT COALESCE(SUM(quantity), 0)
            FROM dbo.product_batch
            WHERE store_id = CAST(:store_id AS varchar(10))
              AND sku = CAST(:sku AS varchar(20))
              AND expiry_date >= CAST(:today AS date)
            """
        ),
        {"store_id": store_id, "sku": sku, "today": today},
    ).scalar_one()
    return int(total)


def deduct_batch(session: Session, batch_id: str, quantity: int) -> int:
    """Remove ``quantity`` from one batch, never below zero, and return the rest.

    The guard lives in the ``WHERE`` clause, so a batch whose quantity moved
    under its lock is rejected instead of going negative. The result is read to
    the end with ``one_or_none`` for the reason given in ``update_stock_with_guard``.
    """
    if quantity <= 0:
        raise ValueError("quantity must be above zero")
    row = session.execute(
        text(
            """
            UPDATE dbo.product_batch
            SET quantity = quantity - :quantity
            OUTPUT inserted.quantity
            WHERE batch_id = CAST(:batch_id AS varchar(30))
              AND quantity - :quantity >= 0
            """
        ),
        {"batch_id": batch_id, "quantity": quantity},
    ).one_or_none()
    if row is None:
        raise RuntimeError(f"batch {batch_id} cannot take {quantity} more units")
    return int(row.quantity)


def add_batch_quantity(session: Session, batch_id: str, quantity: int) -> int:
    """Put ``quantity`` back into one batch and return its new quantity."""
    if quantity <= 0:
        raise ValueError("quantity must be above zero")
    row = session.execute(
        text(
            """
            UPDATE dbo.product_batch
            SET quantity = quantity + :quantity
            OUTPUT inserted.quantity
            WHERE batch_id = CAST(:batch_id AS varchar(30))
            """
        ),
        {"batch_id": batch_id, "quantity": quantity},
    ).one_or_none()
    if row is None:
        raise RuntimeError(f"batch {batch_id} does not exist")
    return int(row.quantity)


def insert_batch(session: Session, store_id: str, sku: str, batch_id: str,
                 quantity: int, expiry_date: date) -> None:
    """Create one batch row. The caller owns the id and the commit."""
    if quantity < 0:
        raise ValueError("quantity must be >= 0")
    session.execute(
        text(
            """
            INSERT INTO dbo.product_batch (batch_id, sku, store_id, expiry_date, quantity)
            VALUES (CAST(:batch_id AS varchar(30)),
                    CAST(:sku AS varchar(20)),
                    CAST(:store_id AS varchar(10)),
                    CAST(:expiry_date AS date),
                    :quantity)
            """
        ),
        {"batch_id": batch_id, "sku": sku, "store_id": store_id,
         "expiry_date": expiry_date, "quantity": quantity},
    )


def sale_batch_quantities(session: Session, store_id: str,
                          txn_id: str) -> dict[tuple[str, str | None], int]:
    """Units the original sale took from each batch, keyed by ``(sku, batch_id)``.

    A movement without ``batch_id`` comes from a sale recorded before PB-20 and
    is keyed with ``None``.
    """
    rows = session.execute(
        text(
            """
            SELECT sku, batch_id, SUM(-quantity) AS taken
            FROM dbo.inventory_movement
            WHERE store_id = CAST(:store_id AS varchar(10))
              AND txn_id = CAST(:txn_id AS varchar(40))
              AND movement_type = 'SALE'
            GROUP BY sku, batch_id
            """
        ),
        {"store_id": store_id, "txn_id": txn_id},
    )
    return {(str(sku), None if batch_id is None else str(batch_id)): int(taken)
            for sku, batch_id, taken in rows}


def restored_batch_quantities(session: Session, store_id: str,
                              txn_id: str) -> dict[tuple[str, str | None], int]:
    """Units earlier RETURN and CANCELLATION events already put back per batch."""
    rows = session.execute(
        text(
            """
            SELECT movement.sku, movement.batch_id, SUM(movement.quantity) AS restored
            FROM dbo.pos_transaction AS txn WITH (INDEX(ix_pos_transaction_ref))
            JOIN dbo.inventory_movement AS movement ON movement.txn_id = txn.txn_id
            WHERE txn.ref_txn_id = CAST(:txn_id AS varchar(40))
              AND txn.store_id = CAST(:store_id AS varchar(10))
              AND txn.txn_type IN ('RETURN', 'CANCELLATION')
              AND movement.movement_type IN ('RETURN', 'CANCELLATION')
            GROUP BY movement.sku, movement.batch_id
            """
        ),
        {"store_id": store_id, "txn_id": txn_id},
    )
    return {(str(sku), None if batch_id is None else str(batch_id)): int(restored)
            for sku, batch_id, restored in rows}
