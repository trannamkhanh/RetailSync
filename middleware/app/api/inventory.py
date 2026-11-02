"""Store stock query endpoint (PB-12). Read-only: it never commits."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.schemas.inventory import StockLine, StoreInventory
from app.core.db import get_db
from app.core.errors import ApiError
from app.core.security import Principal, require_role
from app.services import stock_query


router = APIRouter(tags=["Inventory"])


@router.get("/stores/{store_id}/inventory", response_model=StoreInventory)
def get_store_inventory(store_id: str,
                        sku: str | None = Query(default=None, max_length=20),
                        session: Session = Depends(get_db),
                        principal: Principal = Depends(require_role("Staff", "Manager"))) -> StoreInventory:
    # The caller's own store is checked before any lookup, so an unknown store
    # is 403 rather than 404 (INV12-4).
    if store_id != principal.store_id:
        raise ApiError(403, "FORBIDDEN", f"This account may not read stock of store '{store_id}'.")
    lines = stock_query.stock_lines(session, store_id, sku)
    return StoreInventory(store_id=store_id,
                          items=[StockLine(sku=line_sku, quantity=quantity)
                                 for line_sku, quantity in lines])
