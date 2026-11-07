"""Inventory SQL: read stock, change it atomically, record a movement.

Every function takes a session and never commits. The caller owns the
transaction, so a later failure rolls the stock change and its movement back
together.
"""

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
            WHERE store_id = :store_id AND sku = :sku
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
            WHERE store_id = :store_id AND sku = :sku AND quantity + :delta >= 0
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
                        VALUES (:store_id, :sku, :quantity, SYSUTCDATETIME())
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
                (:store_id, :sku, :movement_type, :quantity, :txn_id, :batch_id,
                 :reason, :created_by, SYSUTCDATETIME())
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
