"""Read-only catalogue and own-store stock queries for barcode lookup."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.models import Inventory, Product, ProductBatch


def find_product(session: Session, barcode: str) -> Product | None:
    return session.scalar(select(Product).where(
        Product.barcode == barcode,
        Product.barcode.collate("Latin1_General_100_BIN2") == barcode,
    ))


def quantity(session: Session, store_id: str, sku: str) -> int:
    value = session.scalar(select(Inventory.quantity).where(
        Inventory.store_id == store_id, Inventory.sku == sku,
    ))
    return value if value is not None else 0


def batches(session: Session, store_id: str, sku: str) -> list[ProductBatch]:
    return list(session.scalars(
        select(ProductBatch)
        .where(ProductBatch.store_id == store_id, ProductBatch.sku == sku, ProductBatch.quantity > 0)
        .order_by(ProductBatch.expiry_date, ProductBatch.batch_id)
    ))
