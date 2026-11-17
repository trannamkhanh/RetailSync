"""Read-only recommendation queries for the Staff API (PB-32, PB-33).

Converts repository rows into the DS-04 response schemas. Never commits.
"""

from app.api.schemas.recommendations import (
    GuardrailResultRead,
    RecommendationDetail,
    RecommendationSummary,
)
from app.domain.models import ProductBatch
from app.repositories import recommendation_queries as repository


def list_recommendations(session, store_id: str) -> list[RecommendationSummary]:
    """The PENDING, still-valid recommendations of one store (PB-32)."""
    rows = repository.list_recommendations(session, store_id)
    return [
        RecommendationSummary(
            rec_id=row.rec_id,
            sku=row.sku,
            action_type=row.action_type,
            discount_pct=row.discount_pct,
            proposed_qty=row.proposed_qty,
            status="PENDING",
        )
        for row in rows
    ]


def get_recommendation_detail(session, rec_id: int, store_id: str) -> RecommendationDetail | None:
    """One PENDING, still-valid recommendation with its guardrail results (PB-32)."""
    row = repository.get_recommendation(session, rec_id, store_id)
    if row is None:
        return None
    batch = session.get(ProductBatch, row.batch_id) if row.batch_id else None
    results = [
        GuardrailResultRead(
            rule_type=result.rule_type,
            outcome=result.outcome,
            original_value=result.original_value,
            adjusted_value=result.adjusted_value,
            message=result.message,
        )
        for result in repository.list_guardrail_results(session, rec_id)
    ]
    return RecommendationDetail(
        rec_id=row.rec_id,
        sku=row.sku,
        action_type=row.action_type,
        discount_pct=row.discount_pct,
        proposed_qty=row.proposed_qty,
        status="PENDING",
        batch_id=row.batch_id,
        expiry_date=batch.expiry_date.isoformat() if batch else None,
        reason=row.reason,
        guardrail_results=results,
    )