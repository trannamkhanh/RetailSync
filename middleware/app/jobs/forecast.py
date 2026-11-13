"""Run the daily forecast and commit each store independently."""

from collections import defaultdict
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
import logging

from sqlalchemy.orm import Session

from app.core import clock
from app.core.db import SessionLocal
from app.domain.models import Forecast
from app.repositories import forecast as repository
from app.services import forecast
from app.services.inventory import sellable_stock

logger = logging.getLogger(__name__)
session_factory: Callable[[], Session] = SessionLocal


def _save_store(session: Session, store: str, today: date, created_at: datetime,
                model: str, forecasts: list[tuple[str, int]]) -> int:
    settled = repository.settled_skus(session, store, today)
    count = 0
    for sku, predicted in forecasts:
        if sku in settled:
            continue
        balance = sellable_stock(session, store, sku) - predicted
        status = "SURPLUS" if balance > 0 else "SHORTAGE" if balance < 0 else "BALANCED"
        session.add(Forecast(store_id=store, sku=sku, horizon_days=forecast.HORIZON,
                             predicted_demand=predicted, surplus_shortage=balance,
                             balance_status=status, model_version=model, created_at=created_at))
        count += 1
    return count


def run_forecast() -> dict[str, int]:
    today = clock.today_local()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    start = repository.utc_start(today)
    created_at = now if start <= now < start + timedelta(days=1) else start
    with session_factory() as session:
        series = forecast.eligible_demand(repository.load_demand(session, today))
    model, predictions = forecast.predict_demand(series)
    by_store = defaultdict(list)
    for demand, predicted in zip(series, predictions, strict=True):
        by_store[demand.store].append((demand.sku, predicted))
    saved = {}
    for store, forecasts in by_store.items():
        try:
            with session_factory() as session, session.begin():
                count = _save_store(session, store, today, created_at, model, forecasts)
            saved[store] = count
        except Exception:
            logger.exception("Forecast failed for store %s", store)
    return saved
