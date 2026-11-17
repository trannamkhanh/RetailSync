"""Staff recommendation list, detail and decision (PB-32, PB-33).

The list and the detail are read-only; the decision commits the recommendation
status, the staff decision row and the audit row together.
"""

from fastapi import APIRouter, Depends, Path
from sqlalchemy.orm import Session

from app.api.schemas.recommendations import (
    DecisionRequest,
    DecisionResponse,
    RecommendationDetail,
    RecommendationSummary,
)
from app.core.db import get_db
from app.core.errors import ApiError
from app.core.security import Principal, require_role
from app.repositories import registry
from app.services import decisions
from app.services import recommendation_queries as service


router = APIRouter(tags=["Staff"])

REC_ID = Path()


@router.get("/recommendations", response_model=list[RecommendationSummary])
def list_recommendations(
    principal: Principal = Depends(require_role("Staff")),
    session: Session = Depends(get_db),
) -> list[RecommendationSummary]:
    """The PENDING recommendations of the caller's store (PB-32).

    Invalid rows (batch sold out or expired) are hidden, as DS-06 says.
    """
    if principal.store_id is None:
        raise ApiError(403, "FORBIDDEN", "A store is required for recommendations.")
    return service.list_recommendations(session, principal.store_id)


@router.get("/recommendations/{rec_id}", response_model=RecommendationDetail)
def get_recommendation(
    rec_id: int = REC_ID,
    principal: Principal = Depends(require_role("Staff")),
    session: Session = Depends(get_db),
) -> RecommendationDetail:
    """One PENDING recommendation with its guardrail results (PB-32).

    Recommendations of another store or invalid rows are 404.
    """
    if principal.store_id is None:
        raise ApiError(403, "FORBIDDEN", "A store is required for recommendations.")
    detail = service.get_recommendation_detail(session, rec_id, principal.store_id)
    if detail is None:
        raise ApiError(404, "NOT_FOUND", "This recommendation does not exist.")
    return detail


@router.post("/recommendations/{rec_id}/decision", response_model=DecisionResponse)
def decide_recommendation(
    payload: DecisionRequest,
    rec_id: int = REC_ID,
    principal: Principal = Depends(require_role("Staff")),
    session: Session = Depends(get_db),
) -> DecisionResponse:
    """Accept or reject one recommendation; the decision is final and audited (PB-33)."""
    if principal.store_id is None:
        from app.core.errors import ApiError

        raise ApiError(403, "FORBIDDEN", "A store is required for recommendations.")
    user_id = registry.find_user_id(session, principal.sub)
    if user_id is None:
        from app.core.errors import ApiError

        raise ApiError(403, "FORBIDDEN", "A staff account is required to decide.")
    decision = decisions.decide(session, rec_id, principal.store_id, user_id, payload.decision)
    session.commit()
    return decision