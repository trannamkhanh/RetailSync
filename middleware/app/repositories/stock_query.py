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


def product_exists(session: Session, sku: str) -> bool:
    return session.scalar(select(Product.sku).where(Product.sku == sku)) is not None
