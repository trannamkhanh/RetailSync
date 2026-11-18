"""Queries for recommendations and staff decisions (PB-32, PB-33).

Read-only, never commits, except the decision helper, which writes the
decision and the recommendation status in its caller's transaction.
"""

from dataclasses import dataclass
from datetime import date, datetime, timezone
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

# rec_id is bigint; a value outside this range cannot name a row and would
# have made the driver fail instead of answering 404.
MIN_REC_ID = 1
MAX_REC_ID = 2**63 - 1

DECIDED = ("ACCEPTED", "REJECTED")
NOT_DECIDABLE = ("GENERATED", "BLOCKED")


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


@dataclass(frozen=True)
class RecommendationRow:
    """One recommendation with the batch facts the reader needs (PB-32).

    ``expiry_date`` is ``None`` when the recommendation has no batch: a
    REDISTRIBUTION, or the surplus DISCOUNT of DS-06 rule S2. Such a
    recommendation never expires, so it stays listed and can be decided.
    """

    rec_id: int
    store_id: str
    sku: str
    action_type: str
    discount_pct: Decimal | None
    proposed_qty: int | None
    reason: str
    status: str
    batch_id: str | None
    expiry_date: date | None
    batch_quantity: int | None


def _to_row(rec: Recommendation, expiry_date: date | None,
            quantity: int | None) -> RecommendationRow:
    return RecommendationRow(
        rec_id=rec.rec_id,
        store_id=rec.store_id,
        sku=rec.sku,
        action_type=rec.action_type,
        discount_pct=rec.discount_pct,
        proposed_qty=rec.proposed_qty,
        reason=rec.reason,
        status=rec.status,
        batch_id=rec.batch_id,
        expiry_date=expiry_date,
        batch_quantity=quantity,
    )


def _is_valid(expiry_date: date | None, quantity: int | None, today: date) -> bool:
    """Whether a recommendation is still valid at the business date.

    A recommendation without a batch is always valid: nothing can sell out or
    expire under it. With a batch, the batch must still have a sellable
    quantity and must not have expired (DS-06, "Validity at decision time").
    """
    if expiry_date is None:
        return True
    return quantity is not None and quantity > 0 and expiry_date >= today


def _row_with_batch(session: Session, rec: Recommendation,
                    today: date) -> RecommendationRow | None:
    """The row for one recommendation, or ``None`` when it is not valid now."""
    expiry_date = quantity = None
    if rec.batch_id is not None:
        batch = session.get(ProductBatch, rec.batch_id)
        if batch is None:
            return None
        expiry_date, quantity = batch.expiry_date, batch.quantity
    if not _is_valid(expiry_date, quantity, today):
        return None
    return _to_row(rec, expiry_date, quantity)


def list_recommendations(session: Session, store_id: str) -> list[RecommendationRow]:
    """The PENDING recommendations of one store that are still valid.

    Rows without a batch are included, because they never expire. The list
    never writes: the daily job and the guardrails own the rows. Ordered by
    ``rec_id``.
    """
    today: date = clock.today_local()
    rows = session.scalars(
        select(Recommendation)
        .where(
            Recommendation.store_id == store_id,
            Recommendation.status == "PENDING",
        )
        .order_by(Recommendation.rec_id)
    )
    shown = []
    for rec in rows:
        row = _row_with_batch(session, rec, today)
        if row is not None:
            shown.append(row)
    return shown


def get_recommendation(session: Session, rec_id: int,
                       store_id: str) -> RecommendationRow | None:
    """One PENDING, still-valid recommendation of one store, or ``None``.

    ``None`` covers: not found, another store's row, a decided row, and an
    invalid row (batch sold out or expired). The detail hides them all the
    same way, as DS-06 says.
    """
    if not MIN_REC_ID <= rec_id <= MAX_REC_ID:
        return None
    rec = session.scalar(
        select(Recommendation).where(
            Recommendation.rec_id == rec_id,
            Recommendation.store_id == store_id,
            Recommendation.status == "PENDING",
        )
    )
    if rec is None:
        return None
    return _row_with_batch(session, rec, clock.today_local())


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
            int(result_id), int(row_rec_id), int(rule_id), str(rule_type), str(outcome),
            original_value, adjusted_value, message, checked_at,
        )
        for (result_id, row_rec_id, rule_id, rule_type, outcome,
             original_value, adjusted_value, message, checked_at) in rows
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
) -> tuple[datetime | None, str | None]:
    """Decide one recommendation, atomically and safely under concurrency.

    The recommendation row is locked with ``UPDLOCK, HOLDLOCK`` until the
    caller's transaction ends, so two parallel decisions of the same row
    serialize: the first wins, the second gets ``ALREADY_DECIDED`` and nothing
    changes.

    A recommendation that was never released by the guardrails, or that the
    guardrails blocked, cannot be decided: it is 404, the same answer as a row
    that does not exist for this store, so the two states are not disclosed.

    Returns:
        ``(decided_at, None)`` on success, otherwise ``(None, code)`` with one
        of ``NOT_FOUND``, ``ALREADY_DECIDED`` or ``RECOMMENDATION_EXPIRED``.
        On ``RECOMMENDATION_EXPIRED`` the recommendation status is already set
        to EXPIRED in the caller's transaction, which the caller commits.

    Raises:
        ValueError: ``decision`` is not ``ACCEPT`` or ``REJECT``.
    """
    if decision not in ("ACCEPT", "REJECT"):
        raise ValueError("decision must be ACCEPT or REJECT")
    if not MIN_REC_ID <= rec_id <= MAX_REC_ID:
        return None, "NOT_FOUND"

    row = session.execute(
        select(Recommendation)
        .where(Recommendation.rec_id == rec_id)
        .with_hint(Recommendation.__table__, "WITH (UPDLOCK, HOLDLOCK)")
    ).scalar_one_or_none()
    if row is None or row.store_id != store_id:
        return None, "NOT_FOUND"
    if row.status in NOT_DECIDABLE:
        return None, "NOT_FOUND"
    if row.status in DECIDED:
        return None, "ALREADY_DECIDED"
    if row.status == "EXPIRED":
        return None, "RECOMMENDATION_EXPIRED"
    if row.status != "PENDING":
        # GENERATED and BLOCKED were handled above; any other value is not a
        # state the staff API may act on.
        return None, "NOT_FOUND"

    today: date = clock.today_local()
    if row.batch_id is not None:
        batch = session.get(ProductBatch, row.batch_id)
        if batch is None or batch.quantity <= 0 or batch.expiry_date < today:
            row.status = "EXPIRED"
            session.flush()
            return None, "RECOMMENDATION_EXPIRED"

    if find_staff_decision(session, rec_id) is not None:
        return None, "ALREADY_DECIDED"

    row.status = "ACCEPTED" if decision == "ACCEPT" else "REJECTED"
    decided_at = datetime.now(timezone.utc).replace(microsecond=0)
    session.add(
        StaffDecision(
            rec_id=rec_id,
            user_id=user_id,
            decision=decision,
            decided_at=decided_at.replace(tzinfo=None),
        )
    )
    session.flush()
    return decided_at, None