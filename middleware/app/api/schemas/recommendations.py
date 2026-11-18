"""DS-04 Recommendation bodies for the Staff API (PB-32, PB-33).

The schemas mirror ``docs/design/openapi.yaml``: ``RecommendationSummary`` for
the list, ``RecommendationDetail`` for one recommendation with its guardrail
results, and the decision request/response for
``POST /recommendations/{rec_id}/decision``.
"""

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class GuardrailResultRead(BaseModel):
    """One guardrail rule result shown in a recommendation detail."""

    rule_type: Literal["MAX_DISCOUNT", "MIN_PRICE", "MIN_SHELF_LIFE"]
    outcome: Literal["PASSED", "ADJUSTED"]
    original_value: Decimal | None = None
    adjusted_value: Decimal | None = None
    message: str | None = None


class RecommendationSummary(BaseModel):
    """One PENDING recommendation of the caller's store (PB-32)."""

    rec_id: int
    sku: str
    action_type: Literal["DISCOUNT", "CLEARANCE", "REDISTRIBUTION"]
    discount_pct: Decimal | None = Field(default=None, description="Only for DISCOUNT")
    proposed_qty: int | None = Field(
        default=None, description="Only for CLEARANCE and REDISTRIBUTION")
    status: Literal["PENDING"]


class RecommendationList(BaseModel):
    """The list response: DS-04 wraps the rows in ``items``."""

    items: list[RecommendationSummary]


class RecommendationDetail(RecommendationSummary):
    """One recommendation with its reason, expiry and guardrail results (PB-32).

    ``batch_id`` and ``expiry_date`` are ``None`` for a recommendation without
    a batch (a REDISTRIBUTION, or the surplus DISCOUNT of DS-06 rule S2); such a
    recommendation never expires.
    """

    batch_id: str | None = None
    expiry_date: str | None = None
    reason: str
    guardrail_results: list[GuardrailResultRead] = Field(default_factory=list)


class DecisionRequest(BaseModel):
    """Accept or reject a recommendation (PB-33).

    The enum rejects ``MAYBE`` and friends with 422 before anything reaches the
    service.
    """

    model_config = ConfigDict(extra="forbid")

    decision: Literal["ACCEPT", "REJECT"]


class DecisionResponse(BaseModel):
    """The stored decision (PB-33); ``decided_at`` is UTC with an offset."""

    rec_id: int
    status: Literal["ACCEPTED", "REJECTED"]
    decided_at: datetime