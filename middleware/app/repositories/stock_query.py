"""Stock query SQL for one store (PB-12, PB-20). Read-only: never commits."""

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.models import Inventory, Product, ProductBatch


def list_store_stock(session: Session, store_id: str) -> list[tuple[str, int]]:
    """Every inventory row of a store, ordered by SKU."""
    rows = session.execute(
        select(Inventory.sku, Inventory.quantity)
        .where(Inventory.store_id == store_id)
        .order_by(Inventory.sku)
    ).all()
    return [(sku, int(quantity)) for sku, quantity in rows]


def list_store_batches(session: Session, store_id: str) -> dict[str, list[tuple[str, date, int]]]:
    """Batches with stock left, per SKU, ordered by expiry date.

    Expired batches are included: the contract asks the stock query to show them,
    and the reader can tell them apart by their date. Batches with no stock left
    are left out.
    """
    rows = session.execute(
        select(
            ProductBatch.sku,
            ProductBatch.batch_id,
            ProductBatch.expiry_date,
            ProductBatch.quantity,
        )
        .where(ProductBatch.store_id == store_id, ProductBatch.quantity > 0)
        .order_by(ProductBatch.sku, ProductBatch.expiry_date, ProductBatch.batch_id)
    ).all()
    batches: dict[str, list[tuple[str, date, int]]] = {}
    for sku, batch_id, expiry_date, quantity in rows:
        batches.setdefault(str(sku), []).append((str(batch_id), expiry_date, int(quantity)))
    return batches


def find_catalogue_sku(session: Session, sku: str) -> str | None:
    """The SKU as stored in the catalogue, or ``None`` when it is not there.

    SQL Server compares varchar values case-insensitively and ignores trailing
    spaces, so the caller must answer with this value, not with its own input.
    """
    return session.scalar(select(Product.sku).where(Product.sku == sku))
