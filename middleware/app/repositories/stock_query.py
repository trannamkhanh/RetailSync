"""Stock query SQL for one store (PB-12). Read-only: never commits."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.models import Inventory, Product


def list_store_stock(session: Session, store_id: str) -> list[tuple[str, int]]:
    """Every inventory row of a store, ordered by SKU."""
    rows = session.execute(
        select(Inventory.sku, Inventory.quantity)
        .where(Inventory.store_id == store_id)
        .order_by(Inventory.sku)
    ).all()
    return [(sku, int(quantity)) for sku, quantity in rows]


def find_catalogue_sku(session: Session, sku: str) -> str | None:
    """The SKU as stored in the catalogue, or ``None`` when it is not there.

    SQL Server compares varchar values case-insensitively and ignores trailing
    spaces, so the caller must answer with this value, not with its own input.
    """
    return session.scalar(select(Product.sku).where(Product.sku == sku))
