"""Store stock queries (PB-12). Read-only: never commits."""

from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.repositories import stock_query as repository
from app.services.inventory import get_stock


def stock_lines(session: Session, store_id: str, sku: str | None = None) -> list[tuple[str, int]]:
    """Stock lines of one store, ordered by SKU.

    Without ``sku`` every inventory row of the store is returned. With ``sku``
    exactly one line comes back: quantity 0 for a catalogue product that has no
    stock row in this store.

    Args:
        session: SQLAlchemy session; this is a read, so nothing is committed.
        store_id: Store to read.
        sku: Optional single SKU.

    Returns:
        ``(sku, quantity)`` pairs, ordered by SKU when ``sku`` is omitted.

    Raises:
        ApiError(404, "NOT_FOUND"): the requested SKU is not in the catalogue.
    """
    if sku is None:
        return repository.list_store_stock(session, store_id)
    catalogue_sku = repository.find_catalogue_sku(session, sku)
    if catalogue_sku is None:
        raise ApiError(404, "NOT_FOUND", f"SKU '{sku}' is not in the product catalogue.")
    return [(catalogue_sku, get_stock(session, store_id, catalogue_sku))]
