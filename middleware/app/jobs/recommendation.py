"""Generate and release recommendations in independent store transactions."""

from collections.abc import Callable
from datetime import date
from decimal import Decimal
import logging
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import clock
from app.core.db import SessionLocal
from app.domain.models import Forecast, ProductBatch, Store
from app.repositories import recommendation as repository
from app.services.recommendation import Proposal, near_expiry_proposal, surplus_proposal

if TYPE_CHECKING:
    from app.domain.models import Recommendation


logger = logging.getLogger(__name__)
session_factory: Callable[[], Session] = SessionLocal


def _create(session: Session, model: type["Recommendation"], store: str, sku: str,
            proposal: Proposal, **source) -> "Recommendation":
    recommendation = model(
        store_id=store, sku=sku, action_type=proposal.action_type, reason=proposal.reason,
        proposed_qty=proposal.proposed_qty, discount_pct=proposal.discount_pct,
        status="GENERATED", **source,
    )
    session.add(recommendation)
    return recommendation


def _generate(session: Session, model: type["Recommendation"], store: str, today: date,
              forecasts: list[Forecast], active: list["Recommendation"]) -> list["Recommendation"]:
    batches = {row.batch_id for row in active if row.batch_id is not None}
    skus = {row.sku for row in active}
    own = {row.sku: row for row in forecasts if row.store_id == store}
    alerts = repository.open_alerts(session, store)
    alert_skus = {alert.sku for alert, _ in alerts}
    created = []
    for alert, batch in alerts:
        if alert.alert_type == "EXPIRED" or batch.batch_id in batches:
            continue
        forecast = own.get(alert.sku)
        demand = forecast.predicted_demand / forecast.horizon_days if forecast else Decimal(0)
        proposal = near_expiry_proposal(batch.batch_id, (batch.expiry_date - today).days, batch.quantity, demand)
        if proposal:
            created.append(_create(session, model, store, alert.sku, proposal, batch_id=batch.batch_id,
                                   alert_id=alert.alert_id))
    for sku, forecast in own.items():
        if sku in alert_skus or sku in skus or forecast.balance_status != "SURPLUS":
            continue
        shortages = [
            (row.store_id, -row.surplus_shortage) for row in forecasts
            if row.store_id != store and row.sku == sku and row.balance_status == "SHORTAGE"
        ]
        shortage = max(shortages, key=lambda pair: pair[1], default=None)
        proposal = surplus_proposal(forecast.predicted_demand, forecast.surplus_shortage, shortage)
        if proposal:
            created.append(_create(session, model, store, sku, proposal, forecast_id=forecast.forecast_id))
    return created


def _process_store(session: Session, store: str, today: date, forecasts: list[Forecast]) -> int:
    # PB-27 supplies these dependencies. Keep their import local until it lands.
    from app.domain.models import Recommendation
    from app.services.guardrails import GuardrailRulesUnavailable, apply_guardrails

    active = list(session.scalars(select(Recommendation).where(
        Recommendation.store_id == store, Recommendation.status.in_(("PENDING", "GENERATED")),
    ).order_by(Recommendation.rec_id)))
    for row in active:
        if row.status == "PENDING" and row.batch_id is not None:
            batch = session.get(ProductBatch, row.batch_id)
            if batch is None or batch.quantity <= 0 or batch.expiry_date < today:
                row.status = "EXPIRED"

    # Suppress a new proposal for a source that was already queued on entry,
    # even when the earlier GENERATED proposal is blocked during this run.
    existing = [row for row in active if row.status != "EXPIRED"]
    available = True
    for row in existing:
        if row.status != "GENERATED":
            continue
        try:
            apply_guardrails(session, row)
        except GuardrailRulesUnavailable:
            available = False
            logger.warning("Recommendation guardrails unavailable for store %s", store)
            break
    created = _generate(session, Recommendation, store, today, forecasts, existing)
    if available:
        for row in created:
            try:
                apply_guardrails(session, row)
            except GuardrailRulesUnavailable:
                logger.warning("Recommendation guardrails unavailable for store %s", store)
                break
    return len(created)


def run_recommendations() -> dict[str, int]:
    today = clock.today_local()
    with session_factory() as session:
        stores = list(session.scalars(select(Store.store_id).order_by(Store.store_id)))
        forecasts = repository.recent_forecasts(session, today)
    created = {}
    for store in stores:
        try:
            with session_factory() as session, session.begin():
                count = _process_store(session, store, today, forecasts)
            created[store] = count
        except Exception:
            logger.exception("Recommendation job failed for store %s", store)
    return created
