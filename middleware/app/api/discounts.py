"""Active discounts for staff and POS (PB-50-1). Read-only, not audited."""

from typing import Literal

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.schemas.discounts import PosDiscountList, StaffDiscountList
from app.core.client_cert import require_gateway
from app.core.db import get_db
from app.core.errors import ApiError
from app.core.security import Principal, require_role
from app.services import discounts as service


router = APIRouter()


@router.get("/staff/discounts", response_model=StaffDiscountList, tags=["Staff"])
def list_staff_discounts(
    scope: Literal["own", "all"] = "own",
    principal: Principal = Depends(require_role("Staff", "Manager")),
    session: Session = Depends(get_db),
) -> dict:
    """Active discounts of the caller's store, or of every active store for ``all``."""
    if principal.store_id is None:
        raise ApiError(403, "FORBIDDEN", "A store is required for discounts.")
    return {"items": service.staff_discounts(session, principal.store_id, scope)}


@router.get("/pos/discounts", response_model=PosDiscountList, tags=["POS"])
def list_pos_discounts(
    fingerprint: str | None = Depends(require_gateway),
    principal: Principal = Depends(require_role("POS")),
    session: Session = Depends(get_db),
) -> dict:
    """Active discounts of the terminal's store; a ``store_id`` parameter is ignored."""
    return service.pos_discounts(session, service.terminal_store(session, principal, fingerprint))
