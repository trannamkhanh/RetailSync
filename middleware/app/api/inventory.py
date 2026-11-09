"""Store stock query endpoint (PB-12, PB-20). Read-only: it never commits."""

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.schemas.inventory import BatchInfo, StockLine, StoreInventory
from app.api.schemas.registry import ID_PATTERN
from app.core.db import get_db
from app.core.errors import ApiError
from app.core.security import Principal, require_role
from app.services import stock_query


router = APIRouter(tags=["Inventory"])


def require_own_store(store_id: str,
                      principal: Principal = Depends(require_role("Staff", "Manager"))) -> Principal:
    """Reject another store before the query parameters are validated.

    As a dependency it runs before the endpoint's own `sku` check, so another
    store, or an unknown one, is 403 even when `sku` is invalid (INV12-3, INV12-4).
    """
    if store_id != principal.store_id:
        raise ApiError(403, "FORBIDDEN", f"This account may not read stock of store '{store_id}'.")
    return principal


def _batch_info(batches: list[tuple[str, date, int]]) -> list[BatchInfo]:
    return [
        BatchInfo(batch_id=batch_id, expiry_date=expiry_date, quantity=quantity)
        for batch_id, expiry_date, quantity in batches
    ]


@router.get("/stores/{store_id}/inventory", response_model=StoreInventory)
def get_store_inventory(store_id: str,
                        sku: str | None = Query(default=None, min_length=1, max_length=20,
                                                pattern=ID_PATTERN),
                        session: Session = Depends(get_db),
                        principal: Principal = Depends(require_own_store)) -> StoreInventory:
    lines = stock_query.stock_lines(session, store_id, sku)
    return StoreInventory(
        store_id=store_id,
        items=[
            StockLine(sku=line_sku, quantity=quantity, batches=_batch_info(batches))
            for line_sku, quantity, batches in lines
        ],
    )
