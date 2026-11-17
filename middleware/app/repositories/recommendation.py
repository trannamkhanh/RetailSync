"""Read inputs for the daily recommendation job."""

from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.models import Forecast, NearExpiryAlert, ProductBatch
from app.repositories.forecast import utc_start


def recent_forecasts(session: Session, today: date) -> list[Forecast]:
    ranked = select(
        Forecast.forecast_id,
        func.row_number().over(
            partition_by=(Forecast.store_id, Forecast.sku),
            order_by=(Forecast.created_at.desc(), Forecast.forecast_id.desc()),
        ).label("position"),
    ).where(
        Forecast.created_at >= utc_start(today - timedelta(days=2)),
        Forecast.created_at < utc_start(today + timedelta(days=1)),
    ).subquery()
    return list(session.scalars(
        select(Forecast).join(ranked, ranked.c.forecast_id == Forecast.forecast_id)
        .where(ranked.c.position == 1).order_by(Forecast.store_id, Forecast.sku)
    ))


def open_alerts(session: Session, store: str) -> list[tuple[NearExpiryAlert, ProductBatch]]:
    return [
        (alert, batch) for alert, batch in session.execute(
            select(NearExpiryAlert, ProductBatch)
            .join(ProductBatch, ProductBatch.batch_id == NearExpiryAlert.batch_id)
            .where(NearExpiryAlert.store_id == store, NearExpiryAlert.status == "OPEN")
            .order_by(NearExpiryAlert.alert_id)
        )
    ]
