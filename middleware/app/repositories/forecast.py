"""Load daily net sales and identify forecasts already settled today."""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from itertools import groupby

from sqlalchemy import BigInteger, Date, case, cast, func, literal_column, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.domain.models import Forecast, PosTransaction, Product, TransactionItem


@dataclass(frozen=True)
class Demand:
    store: str
    sku: str
    category: str
    unit_price: float
    start: date
    values: tuple[int, ...]


def utc_start(day: date) -> datetime:
    return datetime.combine(day, time.min) - timedelta(hours=settings.business_utc_offset_hours)


def load_demand(session: Session, end: date, *, history_only: bool = False) -> list[Demand]:
    transaction = PosTransaction
    item = TransactionItem
    local_day = cast(func.dateadd(
        literal_column("hour"),
        literal_column(str(int(settings.business_utc_offset_hours))), transaction.created_at,
    ), Date)
    quantity = cast(item.qty, BigInteger)
    net = func.sum(case((transaction.txn_type == "SALE", quantity), else_=-quantity))
    rows = (
        select(transaction.store_id, item.sku, Product.category, Product.unit_price, local_day, net)
        .select_from(transaction)
        .join(item, transaction.txn_id == item.txn_id)
        .join(Product, Product.sku == item.sku)
        .where(transaction.created_at < utc_start(end))
        .group_by(transaction.store_id, item.sku, Product.category, Product.unit_price, local_day)
        .order_by(transaction.store_id, item.sku, local_day)
    )
    if history_only:
        rows = rows.where(transaction.txn_id.startswith("HIST-"))

    series = []
    for (store, sku, category, price), group in groupby(session.execute(rows), lambda row: tuple(row[:4])):
        daily = {row[4]: max(0, int(row[5])) for row in group}
        start = min(daily)
        values = tuple(daily.get(start + timedelta(days=index), 0) for index in range((end - start).days))
        series.append(Demand(store, sku, category, float(price), start, values))
    return series


def settled_skus(session: Session, store: str, today: date) -> set[str]:
    return set(session.scalars(select(Forecast.sku).where(
        Forecast.store_id == store,
        Forecast.created_at >= utc_start(today),
        Forecast.created_at < utc_start(today + timedelta(days=1)),
    )))
