"""POS event endpoint (PB-05): receive a SALE from a registered terminal."""

from typing import Any

from fastapi import APIRouter, Body, Depends
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.api.schemas.pos import PosEvent, PosEventResult
from app.core.db import get_db
from app.core.errors import ApiError
from app.core.security import Principal, require_role
from app.services.pos_events import process_event


router = APIRouter(prefix="/pos", tags=["POS"])


def _invalid_event(error: ValidationError) -> ApiError:
    first = error.errors()[0]
    field = ".".join(str(part) for part in first["loc"]) or "body"
    return ApiError(422, "INVALID_EVENT", f"Invalid field '{field}': {first['msg']}")


def _invalid_body(message: str) -> ApiError:
    return ApiError(422, "INVALID_EVENT", f"Invalid field 'body': {message}")


@router.post("/events", response_model=PosEventResult)
def receive_pos_event(payload: Any = Body(default=None),
                      principal: Principal = Depends(require_role("POS")),
                      session: Session = Depends(get_db)) -> dict:
    """Validate the body, apply the event and commit one transaction.

    The body is taken as plain JSON so an empty body, an array or a bad field
    becomes 422 ``INVALID_EVENT`` (DS-04), not the global ``VALIDATION_ERROR``.
    Malformed JSON is rejected by FastAPI before authentication and keeps the
    global handler's ``VALIDATION_ERROR`` code.
    """
    if payload is None:
        raise _invalid_body("event body is required.")
    if not isinstance(payload, dict):
        raise _invalid_body("event body must be a JSON object.")

    try:
        event = PosEvent.model_validate(payload)
    except ValidationError as error:
        raise _invalid_event(error) from None

    result = process_event(session, event, principal)
    session.commit()
    return result
