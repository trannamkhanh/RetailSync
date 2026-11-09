"""Store stock queries (PB-12, PB-20). Read-only: never commits."""

from datetime import date

from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.repositories import stock_query as repository
from app.services.inventory import get_stock

# ``(sku, quantity, batches)`` with each batch as ``(batch_id, expiry_date, quantity)``.
StockLineRow = tuple[str, int, list[tuple[str, date, int]]]


def stock_lines(session: Session, store_id: str, sku: str | None = None) -> list[StockLineRow]:
    """Stock lines of one store, ordered by SKU, each with its batches.

    Without ``sku`` every inventory row of the store is returned. With ``sku``
    exactly one line comes back: quantity 0 for a catalogue product that has no
    stock row in this store.

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
    batches = repository.list_store_batches(session, store_id)
    if sku is None:
        return [
            (line_sku, quantity, batches.get(line_sku, []))
            for line_sku, quantity in repository.list_store_stock(session, store_id)
        ]
    catalogue_sku = repository.find_catalogue_sku(session, sku)
    if catalogue_sku is None:
        raise ApiError(404, "NOT_FOUND", f"SKU '{sku}' is not in the product catalogue.")
    return [(
        catalogue_sku,
        get_stock(session, store_id, catalogue_sku),
        batches.get(catalogue_sku, []),
    )]
