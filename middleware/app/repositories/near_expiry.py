"""Queries for near-expiry thresholds and alerts (PB-21). Read-only, never commits."""

from dataclasses import dataclass
from datetime import date

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.domain.models import NearExpiryAlert, NearExpiryConfig, Product, ProductBatch, Store


def list_thresholds(session: Session) -> list[NearExpiryConfig]:
    """Every category threshold, ordered by category."""
    return list(session.scalars(
        select(NearExpiryConfig).order_by(NearExpiryConfig.category)
    ))


def config_statement(category: str, *, lock: bool = False) -> Select:
    """The lookup of one category, compared as SQL Server compares varchar.

    ``lock`` adds ``UPDLOCK, HOLDLOCK``: the row stays locked until the caller's
    transaction ends, so two updates of one category cannot both read the same
    previous value, and a category that does not exist yet cannot be inserted
    twice. ``category`` is the primary key, so the range lock covers the missing
    row as well.
    """
    statement = select(NearExpiryConfig).where(NearExpiryConfig.category == category)
    if lock:
        statement = statement.with_hint(NearExpiryConfig.__table__, "WITH (UPDLOCK, HOLDLOCK)")
    return statement


def find_config(session: Session, category: str, *, lock: bool = False) -> NearExpiryConfig | None:
    return session.scalar(config_statement(category, lock=lock))


def threshold_map(session: Session) -> dict[str, int]:
    """Category to threshold, read once for a whole job run."""
    return {config.category: config.threshold_days for config in list_thresholds(session)}


def list_store_ids(session: Session) -> list[str]:
    return [str(store_id) for store_id in session.scalars(
        select(Store.store_id).order_by(Store.store_id))]


@dataclass(frozen=True)
class StockBatch:
    """One batch with stock left, with the category of its product."""

    batch_id: str
    sku: str
    category: str
    expiry_date: date
    quantity: int


def list_batches_in_stock(session: Session, store_id: str) -> list[StockBatch]:
    """Batches of one store whose quantity is above zero, ordered by id.

    A batch whose quantity reached zero is left out, so the caller can treat a
    missing batch as stock that is gone. The product join supplies the category
    whose threshold decides the alert.
    """
    rows = session.execute(
        select(
            ProductBatch.batch_id,
            ProductBatch.sku,
            Product.category,
            ProductBatch.expiry_date,
            ProductBatch.quantity,
        )
        .join(Product, Product.sku == ProductBatch.sku)
        .where(ProductBatch.store_id == store_id, ProductBatch.quantity > 0)
        .order_by(ProductBatch.batch_id)
    ).all()
    return [
        StockBatch(str(batch_id), str(sku), str(category), expiry_date, int(quantity))
        for batch_id, sku, category, expiry_date, quantity in rows
    ]


def list_open_alerts(session: Session, store_id: str) -> list[NearExpiryAlert]:
    """The OPEN alerts of one store, in the order they were created."""
    return list(session.scalars(
        select(NearExpiryAlert)
        .where(NearExpiryAlert.store_id == store_id, NearExpiryAlert.status == "OPEN")
        .order_by(NearExpiryAlert.alert_id)
    ))
