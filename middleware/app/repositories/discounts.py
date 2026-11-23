"""Read-only queries for active discounts (PB-50). Never commits.

One query returns every active discount of the given stores, with whether the
store already sold the SKU below its list price today, so both endpoints cost
one round trip whatever the number of stores.
"""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import and_, case, exists, or_, select
from sqlalchemy.orm import Session

from app.domain.models import (
    PosTransaction,
    Product,
    ProductBatch,
    Recommendation,
    StaffDecision,
    Store,
    TransactionItem,
)


@dataclass(frozen=True)
class StoreRow:
    store_id: str
    name: str
    latitude: float
    longitude: float
    is_active: bool


@dataclass(frozen=True)
class DiscountRow:
    store_id: str
    sku: str
    name: str
    list_price: Decimal
    batch_id: str | None
    expiry_date: date | None
    discount_pct: Decimal
    decided_at: datetime
    sold_at_discount: bool


def list_stores(session: Session) -> list[StoreRow]:
    """Every store of this Middleware (one database = one Middleware)."""
    rows = session.execute(select(Store.store_id, Store.name, Store.latitude, Store.longitude,
                                  Store.is_active).order_by(Store.store_id)).all()
    return [StoreRow(str(store_id), str(name), float(lat), float(lon), bool(active))
            for store_id, name, lat, lon, active in rows]


def active_discounts(session: Session, store_ids: list[str], today: date,
                     day_start: datetime, day_end: datetime) -> list[DiscountRow]:
    """Accepted DISCOUNT recommendations of the active ``store_ids`` that still apply.

    ``day_start`` and ``day_end`` bound today's business date in UTC, half-open.
    A batch discount applies while the batch has stock and is not expired; a
    SKU-level one only on the business date it was decided.
    """
    if not store_ids:
        return []
    sold = exists().where(
        PosTransaction.store_id == Recommendation.store_id,
        PosTransaction.txn_type == "SALE",
        PosTransaction.status == "OK",
        PosTransaction.effective_at > StaffDecision.decided_at,
        PosTransaction.effective_at >= day_start,
        PosTransaction.effective_at < day_end,
        TransactionItem.txn_id == PosTransaction.txn_id,
        TransactionItem.sku == Recommendation.sku,
        TransactionItem.unit_price < Product.unit_price,
    ).correlate(Recommendation, StaffDecision, Product)
    rows = session.execute(
        select(
            Recommendation.store_id,
            Recommendation.sku,
            Product.name,
            Product.unit_price,
            Recommendation.batch_id,
            ProductBatch.expiry_date,
            Recommendation.discount_pct,
            StaffDecision.decided_at,
            # SQL Server cannot select EXISTS as a column.
            case((sold, 1), else_=0),
        )
        .join(StaffDecision, StaffDecision.rec_id == Recommendation.rec_id)
        .join(Store, Store.store_id == Recommendation.store_id)
        .join(Product, Product.sku == Recommendation.sku)
        .outerjoin(ProductBatch, ProductBatch.batch_id == Recommendation.batch_id)
        .where(
            Recommendation.store_id.in_(store_ids),
            Recommendation.action_type == "DISCOUNT",
            Recommendation.status == "ACCEPTED",
            Recommendation.discount_pct.is_not(None),
            Store.is_active == True,  # noqa: E712 (SQL Server has no IS TRUE)
            or_(
                and_(Recommendation.batch_id.is_not(None),
                     ProductBatch.quantity > 0,
                     ProductBatch.expiry_date >= today),
                and_(Recommendation.batch_id.is_(None),
                     StaffDecision.decided_at >= day_start,
                     StaffDecision.decided_at < day_end),
            ),
        )
    ).all()
    return [DiscountRow(*row[:8], bool(row[8])) for row in rows]
