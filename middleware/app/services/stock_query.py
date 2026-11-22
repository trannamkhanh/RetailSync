"""Store stock queries (PB-12, PB-20). Read-only: never commits."""

from datetime import date

from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.repositories import stock_query as repository

# ``(sku, quantity, batches)`` with each batch as ``(batch_id, expiry_date, quantity)``.
StockLineRow = tuple[str, int, list[tuple[str, date, int]]]


def stock_lines(session: Session, store_id: str, sku: str | None = None) -> list[StockLineRow]:
    """Stock lines of one store, ordered by SKU, each with its batches.

    Without ``sku`` every inventory row of the store is returned. With ``sku``
    exactly one line comes back: quantity 0 for a catalogue product that has no
    stock row in this store.

    Each case is one statement (review of PR #78): inventory and its batches come
    from the same read, so a sale committing in between cannot return a quantity
    that disagrees with the ``batches`` list beside it, and the requested SKU is
    filtered in SQL instead of after reading every batch of the store.

    ``quantity`` stays ``inventory.quantity``, which also counts stock whose
    batches have expired; ``batches`` carries the per-batch detail.

    Args:
        session: SQLAlchemy session; this is a read, so nothing is committed.
        store_id: Store to read.
        sku: Optional single SKU.

    Returns:
        ``(sku, quantity, batches)`` rows, ordered by SKU when ``sku`` is omitted.

    Raises:
        ApiError(404, "NOT_FOUND"): the requested SKU is not in the catalogue.
    """
    if sku is None:
        return list(repository.store_stock_lines(session, store_id))
    line = repository.sku_stock_line(session, store_id, sku)
    if line is None:
        raise ApiError(404, "NOT_FOUND", f"SKU '{sku}' is not in the product catalogue.")
    return [line]
