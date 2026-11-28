"""Read-only forecasts for Staff and Manager, scoped to the token's store."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.api.schemas.forecasts import StaffForecastList
from app.core.db import get_db
from app.core.errors import ApiError
from app.core.security import Principal, require_role
from app.services.staff_forecasts import list_forecasts

router = APIRouter(tags=["Staff"])


@router.get("/staff/forecasts", response_model=StaffForecastList)
def get_forecasts(
    principal: Principal = Depends(require_role("Staff", "Manager")),
    session: Session = Depends(get_db),
) -> dict:
    if principal.store_id is None:
        raise ApiError(403, "FORBIDDEN", "A store is required for forecasts.")
    return list_forecasts(session, principal.store_id)
