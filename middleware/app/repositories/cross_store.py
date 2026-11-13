"""Read-only cross-store stock query (PB-35). Never commits.

One query returns every store with the sellable quantity of one SKU, so the
lookup costs one round trip whatever the number of stores. Distance is computed
in Python, because SQL Server has no haversine function that the contract needs.
"""

from dataclasses import dataclass
from datetime import date

from sqlalchemy import and_, case, func, select
from sqlalchemy.orm import Session

from app.domain.models import Product, ProductBatch, Store


@dataclass(frozen=True)
class StoreStock:
    """One store's sellable quantity of the SKU, with its coordinates."""

    store_id: str
    name: str
    latitude: float
    longitude: float
    is_active: bool
    quantity: int


def find_product(session: Session, barcode: str) -> Product | None:
    """The catalogue product of a barcode, compared case-exactly as in PB-31."""
    return session.scalar(select(Product).where(
        Product.barcode == barcode,
        Product.barcode.collate("Latin1_General_100_BIN2") == barcode,
    ))


def list_store_stock(session: Session, sku: str, today: date) -> list[StoreStock]:
    """Every store of this Middleware with its sellable quantity of ``sku``.

    A batch is sellable while ``expiry_date >= today``; expired stock is left
    out, as ``sellable_stock`` does. A store with no batch of the SKU reports 0
    rather than disappearing, because the contract lists the stores that are
    available for lookup.
    """
    sellable = func.coalesce(
        func.sum(case((ProductBatch.expiry_date >= today, ProductBatch.quantity), else_=0)), 0)
    rows = session.execute(
        select(
            Store.store_id,
            Store.name,
            Store.latitude,
            Store.longitude,
            Store.is_active,
            sellable,
        )
        .outerjoin(ProductBatch, and_(
            ProductBatch.store_id == Store.store_id,
            ProductBatch.sku == sku,
        ))
        .group_by(Store.store_id, Store.name, Store.latitude, Store.longitude, Store.is_active)
        .order_by(Store.store_id)
    ).all()
    return [
        StoreStock(
            store_id=str(store_id),
            name=str(name),
            latitude=float(latitude),
            longitude=float(longitude),
            is_active=bool(is_active),
            quantity=int(quantity),
        )
        for store_id, name, latitude, longitude, is_active, quantity in rows
    ]
