"""Queries the guardrail validation needs (PB-27). Read-only, never commits."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.models import GuardrailResult, Product, ProductBatch


def get_product(session: Session, sku: str) -> Product | None:
    """The catalogue row that holds the category, list price and discount base."""
    return session.get(Product, sku)


def get_batch(session: Session, batch_id: str) -> ProductBatch | None:
    """The batch whose expiry date decides the remaining shelf life."""
    return session.get(ProductBatch, batch_id)


def list_results(session: Session, rec_id: int) -> list[GuardrailResult]:
    """Results of one recommendation, in the order the rules were checked."""
    return list(session.scalars(
        select(GuardrailResult)
        .where(GuardrailResult.rec_id == rec_id)
        .order_by(GuardrailResult.result_id)
    ))
