"""Staff decisions on recommendations (PB-33).

A decision is final, audited and safe under concurrency: the repository locks
the recommendation row, so two parallel decisions serialize and only the first
stores. The caller's router commits the transaction.
"""

from app.api.schemas.recommendations import DecisionResponse
from app.core.errors import ApiError
from app.repositories import recommendation_queries as repository
from app.services import audit

AUDIT_ACTION = "RECOMMENDATION_DECIDED"
AUDIT_ENTITY = "recommendation"


def _not_found() -> ApiError:
    return ApiError(404, "NOT_FOUND", "This recommendation does not exist.")


def decide(session, rec_id: int, store_id: str, user_id: int,
           decision: str) -> DecisionResponse:
    """Store one staff decision and return it (PB-33).

    Raises:
        ApiError(404, "NOT_FOUND"): the recommendation does not exist, belongs
            to another store, or is not PENDING (GENERATED or BLOCKED): an
            answer that does not disclose which of them applies.
        ApiError(409, "ALREADY_DECIDED"): it was already decided.
        ApiError(409, "RECOMMENDATION_EXPIRED"): its batch is sold out or
            expired. The status EXPIRED is committed before this error is
            raised, so the row shows the state the answer describes.
    """
    decided_at, code = repository.decide_recommendation(
        session, rec_id, store_id, user_id, decision)
    if code == "NOT_FOUND":
        raise _not_found()
    if code == "ALREADY_DECIDED":
        session.rollback()
        raise ApiError(
            409, "ALREADY_DECIDED", "This recommendation has already been decided.")
    if code == "RECOMMENDATION_EXPIRED":
        # The repository already turned the row EXPIRED in this transaction;
        # commit it before refusing, or get_db would roll the change back.
        session.commit()
        raise ApiError(
            409, "RECOMMENDATION_EXPIRED",
            "This recommendation is no longer valid; its batch is sold out or expired.")

    audit.record_audit(
        session, AUDIT_ACTION, AUDIT_ENTITY, str(rec_id),
        user_id=user_id, details=f"{decision} for recommendation {rec_id}")
    session.flush()

    status = "ACCEPTED" if decision == "ACCEPT" else "REJECTED"
    return DecisionResponse(rec_id=rec_id, status=status, decided_at=decided_at)