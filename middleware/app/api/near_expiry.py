"""Admin near-expiry threshold endpoints (PB-21-1, PB-21-2). The update commits here."""

from fastapi import APIRouter, Depends, Path
from sqlalchemy.orm import Session

from app.api.schemas.near_expiry import (
    CATEGORY_MAX_LENGTH,
    CATEGORY_PATTERN,
    NearExpiryThresholdList,
    NearExpiryThresholdRead,
    NearExpiryThresholdUpdate,
)
from app.core.db import get_db
from app.core.security import Principal, require_role
from app.services import near_expiry


router = APIRouter(prefix="/admin", tags=["Admin"])

CATEGORY = Path(min_length=1, max_length=CATEGORY_MAX_LENGTH, pattern=CATEGORY_PATTERN)


@router.get("/near-expiry-thresholds", response_model=NearExpiryThresholdList)
def list_near_expiry_thresholds(
    session: Session = Depends(get_db),
    _: Principal = Depends(require_role("Admin")),
) -> NearExpiryThresholdList:
    thresholds = near_expiry.list_thresholds(session)
    return NearExpiryThresholdList(
        items=[NearExpiryThresholdRead.model_validate(item) for item in thresholds]
    )


@router.put("/near-expiry-thresholds/{category}", response_model=NearExpiryThresholdRead)
def set_near_expiry_threshold(
    payload: NearExpiryThresholdUpdate,
    category: str = CATEGORY,
    session: Session = Depends(get_db),
    principal: Principal = Depends(require_role("Admin")),
) -> NearExpiryThresholdRead:
    config = near_expiry.set_threshold(session, category, payload.threshold_days, principal)
    stored = NearExpiryThresholdRead.model_validate(config)
    session.commit()
    return stored
