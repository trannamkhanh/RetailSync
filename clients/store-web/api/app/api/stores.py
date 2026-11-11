"""GET /api/stores and GET /api/stores/{store_id}."""

from fastapi import APIRouter, Depends, Path
from sqlalchemy.orm import Session

from app import clock
from app.db import get_db
from app.errors import ApiError
from app.queries import stores as store_queries
from app.schemas import StoreDetail, StoreList

router = APIRouter()

ID_PATTERN = r"^[A-Za-z0-9-]{1,10}$"


@router.get("/stores", response_model=StoreList)
def list_stores(session: Session = Depends(get_db)) -> StoreList:
    """Every active store with its SKU count and sellable units."""
    rows = store_queries.list_stores(session, clock.today_local())
    return StoreList(stores=rows)


@router.get("/stores/{store_id}", response_model=StoreDetail)
def get_store(
    store_id: str = Path(pattern=ID_PATTERN),
    session: Session = Depends(get_db),
) -> StoreDetail:
    """One active store, or 404 when it is missing or inactive."""
    row = store_queries.get_store(session, store_id, clock.today_local())
    if row is None:
        raise ApiError(404, "NOT_FOUND", f"Store '{store_id}' does not exist.")
    return StoreDetail(**row)
