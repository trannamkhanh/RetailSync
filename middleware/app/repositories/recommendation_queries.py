"""Queries for recommendations and staff decisions (PB-32, PB-33).

Read-only, never commits, except the decision helper which owns its caller's
transaction and writes the decision together with the recommendation status.
"""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import clock
from app.domain.models import (
    GuardrailResult,
    GuardrailRule,
    ProductBatch,
    Recommendation,
    StaffDecision,
)


@dataclass(frozen=True)
class GuardrailResultWithRule:
    """One guardrail result with the rule type (PB-32)."""

    result_id: int
    rec_id: int
    rule_id: int
    rule_type: str
    outcome: str
    original_value: Decimal | None
    adjusted_value: Decimal | None
    message: str | None
    checked_at: datetime


def list_recommendations(session: Session, store_id: str) -> list[Recommendation]:
    """The PENDING recommendations of one store that are still valid.

    A recommendation is hidden when its batch has no sellable quantity left or
    has expired (DS-06, "Validity at decision time"). The list never writes:
    the daily job and the guardrails own the rows. Ordered by ``rec_id``.
    """
    today: date = clock.today_local()
    return list(
        session.scalars(
            select(Recommendation)
            .where(
                Recommendation.store_id == store_id,
                Recommendation.status == "PENDING",
                Recommendation.batch_id.is_not(None),
            )
            .join(
                ProductBatch,
                ProductBatch.batch_id == Recommendation.batch_id,
            )
            .where(
                ProductBatch.quantity > 0,
                ProductBatch.expiry_date >= today,
            )
            .order_by(Recommendation.rec_id)
        )
    )


def get_recommendation(session: Session, rec_id: int, store_id: str) -> Recommendation | None:
    """One PENDING, still-valid recommendation of one store, or ``None``.

    ``None`` covers: not found, another store's row, a decided row, and an
    invalid row (batch sold out or expired). The detail endpoint hides them
    all the same way, as DS-06 says.
    """
    today: date = clock.today_local()
    return session.scalar(
        select(Recommendation)
        .where(
            Recommendation.rec_id == rec_id,
            Recommendation.store_id == store_id,
            Recommendation.status == "PENDING",
            Recommendation.batch_id.is_not(None),
        )
        .join(ProductBatch, ProductBatch.batch_id == Recommendation.batch_id)
        .where(ProductBatch.quantity > 0, ProductBatch.expiry_date >= today)
    )


def list_guardrail_results(session: Session, rec_id: int) -> list[GuardrailResultWithRule]:
    """The guardrail results of one recommendation, in check order, with the
    rule type of each rule (PB-32)."""
    rows = session.execute(
        select(
            GuardrailResult.result_id,
            GuardrailResult.rec_id,
            GuardrailResult.rule_id,
            GuardrailRule.rule_type,
            GuardrailResult.outcome,
            GuardrailResult.original_value,
            GuardrailResult.adjusted_value,
            GuardrailResult.message,
            GuardrailResult.checked_at,
        )
        .join(GuardrailRule, GuardrailRule.rule_id == GuardrailResult.rule_id)
        .where(GuardrailResult.rec_id == rec_id)
        .order_by(GuardrailResult.result_id)
    ).all()
    return [
        GuardrailResultWithRule(
            int(result_id), int(rec_id_), int(rule_id), str(rule_type), str(outcome),
            original_value, adjusted_value, message, checked_at,
        )
        for result_id, rec_id_, rule_id, rule_type, outcome, original_value, adjusted_value, message, checked_at in rows
    ]


def find_staff_decision(session: Session, rec_id: int) -> StaffDecision | None:
    """The decision already stored for one recommendation, if any."""
    return session.scalar(
        select(StaffDecision).where(StaffDecision.rec_id == rec_id)
    )


def decide_recommendation(
    session: Session,
    rec_id: int,
    store_id: str,
    user_id: int,
    decision: str,
) -> tuple[datetime, str | None]:
    """Decide one recommendation, atomically and safely under concurrency.

    The recommendation row is locked with ``UPDLOCK, HOLDLOCK`` until the
    caller's transaction ends, so two parallel decisions of the same row
    serialize: the first wins, the second gets ``ALREADY_DECIDED`` and nothing
    changes. Returns ``(decided_at, None)`` on success, or
    ``(None, code)`` with one of ``NOT_FOUND``, ``ALREADY_DECIDED`` or
    ``RECOMMENDATION_EXPIRED``.

    Args:
        session: SQLAlchemy session; the caller commits or rolls back.
        rec_id: Recommendation to decide.
        store_id: The caller's store; another store's row is 404.
        user_id: The staff member deciding.
        decision: ``ACCEPT`` or ``REJECT``.

    Raises:
        ValueError: ``decision`` is not ``ACCEPT`` or ``REJECT``.
    """
    if decision not in ("ACCEPT", "REJECT"):
        raise ValueError("decision must be ACCEPT or REJECT")

    today: date = clock.today_local()
    row = session.execute(
        select(Recommendation)
        .where(Recommendation.rec_id == rec_id)
        .with_hint(Recommendation.__table__, "WITH (UPDLOCK, HOLDLOCK)")
    ).scalar_one_or_none()
    if row is None:
        return None, "NOT_FOUND"
    if row.store_id != store_id:
        return None, "NOT_FOUND"
    if row.status != "PENDING":
        # EXPIRED means the batch is sold out or expired; anything else was
        # already decided by this or another staff member.
        if row.status == "EXPIRED":
            return None, "RECOMMENDATION_EXPIRED"
        return None, "ALREADY_DECIDED"

    # Validity at decision time: the batch must still be sellable.
    # A recommendation without a batch (REDISTRIBUTION advice) has nothing to
    # expire, so it stays valid.
    if row.batch_id is not None:
        batch = session.get(ProductBatch, row.batch_id)
        if batch is None or batch.quantity <= 0 or batch.expiry_date < today:
            row.status = "EXPIRED"
            session.flush()
            return None, "RECOMMENDATION_EXPIRED"

    if find_staff_decision(session, rec_id) is not None:
        return None, "ALREADY_DECIDED"

    status = "ACCEPTED" if decision == "ACCEPT" else "REJECTED"
    row.status = status
    decided_at = datetime.now().replace(microsecond=0)
    session.add(
        StaffDecision(
            rec_id=rec_id,
            user_id=user_id,
            decision=decision,
            decided_at=decided_at,
        )
    )
    session.flush()
    return decided_at, None


def recommendation_exists(session: Session, rec_id: int) -> bool:
    """Whether a recommendation with this id exists at all (any store)."""
    return session.scalar(
        select(Recommendation.rec_id).where(Recommendation.rec_id == rec_id)
    ) is not None