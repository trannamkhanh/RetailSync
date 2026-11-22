"""Stock query SQL for one store (PB-12, PB-20). Read-only: never commits.

Each public function is one statement, so ``inventory.quantity`` and the batch
rows it is supposed to equal always come from the same read: the two used to be
separate SELECTs, and a sale committing between them could return a quantity
that no longer matched its own ``batches`` list. The batch predicate
(``quantity > 0``) therefore lives in the JOIN, not in a WHERE, so a SKU whose
batches are all sold out keeps its inventory row.

Every string parameter is cast to the column's ``varchar`` length, as in
``repositories/original_sale.py``: the driver binds a Python ``str`` as
``nvarchar``, and SQLAlchemy does not call ``setinputsizes`` for ``text()``, so
without the cast the predicate needs ``CONVERT_IMPLICIT`` and the index is not
seeked.
"""

from datetime import date

from sqlalchemy import text
from sqlalchemy.orm import Session

# One joined row: the line's SKU and quantity, then its batch columns, which are
# NULL when the SKU has no batch with stock left.
Row = tuple[str, int, str | None, date | None, int | None]

# ``(sku, quantity, batches)`` with each batch as ``(batch_id, expiry_date, quantity)``.
StockLine = tuple[str, int, list[tuple[str, date, int]]]


def _lines(rows: list[Row]) -> list[StockLine]:
    """Fold the joined rows into one entry per SKU, batches ordered and compacted."""
    lines: dict[str, StockLine] = {}
    for sku, quantity, batch_id, expiry_date, batch_quantity in rows:
        line = lines.get(str(sku))
        if line is None:
            line = (str(sku), int(quantity), [])
            lines[str(sku)] = line
        if batch_id is not None:
            line[2].append((str(batch_id), expiry_date, int(batch_quantity)))
    return list(lines.values())


def store_stock_lines(session: Session, store_id: str) -> list[StockLine]:
    """Every inventory row of a store with its batches, in one statement.

    Ordered by SKU, then each line's batches by expiry date and batch id, so the
    FEFO order the console shows is decided by the database.
    """
    rows = session.execute(
        text(
            """
            SELECT i.sku, i.quantity, b.batch_id, b.expiry_date, b.quantity
            FROM dbo.inventory AS i
            LEFT JOIN dbo.product_batch AS b
                   ON b.store_id = i.store_id
                  AND b.sku = i.sku
                  AND b.quantity > 0
            WHERE i.store_id = CAST(:store_id AS varchar(10))
            ORDER BY i.sku, b.expiry_date, b.batch_id
            """
        ),
        {"store_id": store_id},
    ).all()
    return _lines(rows)


def sku_stock_line(session: Session, store_id: str, sku: str) -> StockLine | None:
    """One catalogue SKU's quantity and batches for a store, in one statement.

    Reads through ``dbo.product`` so the answer carries the SKU as the catalogue
    stores it (SQL Server compares varchar case-insensitively and ignores
    trailing spaces) and so a catalogue SKU with no inventory row still returns
    a line with quantity 0. Returns ``None`` when the SKU is not in the
    catalogue; the caller turns that into 404.
    """
    rows = session.execute(
        text(
            """
            SELECT p.sku, COALESCE(i.quantity, 0), b.batch_id, b.expiry_date, b.quantity
            FROM dbo.product AS p
            LEFT JOIN dbo.inventory AS i
                   ON i.sku = p.sku
                  AND i.store_id = CAST(:store_id AS varchar(10))
            LEFT JOIN dbo.product_batch AS b
                   ON b.store_id = CAST(:store_id AS varchar(10))
                  AND b.sku = p.sku
                  AND b.quantity > 0
            WHERE p.sku = CAST(:sku AS varchar(20))
            ORDER BY b.expiry_date, b.batch_id
            """
        ),
        {"store_id": store_id, "sku": sku},
    ).all()
    lines = _lines(rows)
    return lines[0] if lines else None
