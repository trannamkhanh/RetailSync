"""Staff decisions on recommendations (PB-33).

A decision is final, audited and safe under concurrency: the repository locks
the recommendation row, so two parallel decisions serialize and only the first
stores. The caller's router commits the transaction.
"""

from app.api.schemas.recommendations import DecisionResponse
from app.core.errors import ApiError
from app.services import audit
from app.repositories import recommendation_queries as repository


def decide(session, rec_id: int, store_id: str, user_id: int, decision: str) -> DecisionResponse:
    """Store one staff decision and return it (PB-33).

    Raises:
        ApiError(404, "NOT_FOUND"): the recommendation does not exist or belongs
            to another store.
        ApiError(409, "ALREADY_DECIDED"): it was already decided.
        ApiError(409, "RECOMMENDATION_EXPIRED"): its batch is sold out or
            expired, so the status becomes EXPIRED and no decision is stored.
    """
    decided_at, code = repository.decide_recommendation(
        session, rec_id, store_id, user_id, decision)
    if code == "NOT_FOUND":
        raise ApiError(404, "NOT_FOUND", "This recommendation does not exist.")
    if code == "ALREADY_DECIDED":
        raise ApiError(
            409, "ALREADY_DECIDED", "This recommendation has already been decided.")
    if code == "RECOMMENDATION_EXPIRED":
        raise ApiError(
            409, "RECOMMENDATION_EXPIRED",
            "This recommendation is no longer valid; its batch is sold out or expired.")

    audit.record_audit(
        session, "STAFF_DECISION", "staff_decision", str(rec_id),
        user_id=user_id, details=f"{decision} for recommendation {rec_id}")
    session.flush()

    status = "ACCEPTED" if decision == "ACCEPT" else "REJECTED"
    return DecisionResponse(rec_id=rec_id, status=status, decided_at=decided_at)