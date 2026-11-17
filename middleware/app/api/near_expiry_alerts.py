"""Staff near-expiry alert list (PB-34). Read-only, the caller's own store."""

from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.schemas.near_expiry import NearExpiryAlertList, NearExpiryAlertRead
from app.core import clock
from app.core.db import get_db
from app.core.errors import ApiError
from app.core.security import Principal, require_role
from app.repositories import near_expiry as repository


router = APIRouter(tags=["Staff"])


def _read_model(alert: repository.OpenAlertWithExpiry, today: date) -> tuple[
        tuple[int, int, int], NearExpiryAlertRead]:
    """One response row and its DS-04 order key: EXPIRED first, then fewest
    days, then the alert id. ``days_to_expiry`` is recomputed at read time and
    a batch that expired since the last daily check is shown as EXPIRED."""
    days_to_expiry = (alert.expiry_date - today).days
    expired = days_to_expiry < 0
    model = NearExpiryAlertRead(
        alert_id=alert.alert_id,
        batch_id=alert.batch_id,
        sku=alert.sku,
        expiry_date=alert.expiry_date,
        remaining_qty=alert.remaining_qty,
        days_to_expiry=days_to_expiry,
        alert_type="EXPIRED" if expired else alert.alert_type,
    )
    return (0 if expired else 1, days_to_expiry, alert.alert_id), model


@router.get("/near-expiry-alerts", response_model=NearExpiryAlertList)
def list_near_expiry_alerts(
    principal: Principal = Depends(require_role("Staff")),
    session: Session = Depends(get_db),
) -> NearExpiryAlertList:
    """The OPEN near-expiry alerts of the caller's store (PB-34).

    The listing never writes: the daily check owns the alert rows.
    """
    if principal.store_id is None:
        raise ApiError(403, "FORBIDDEN", "A store is required for near-expiry alerts.")
    today: date = clock.today_local()
    rows = [_read_model(alert, today) for alert in
            repository.list_open_alerts_with_expiry(session, principal.store_id)]
    rows.sort(key=lambda row: row[0])
    return NearExpiryAlertList(items=[model for _, model in rows])
