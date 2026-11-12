"""Staff-only barcode lookup in the caller's own store, and across stores (PB-35)."""

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.orm import Session

from app.api.schemas.products import CrossStoreStock, ProductLookup
from app.api.schemas.registry import ID_PATTERN
from app.core.db import get_db
from app.core.errors import ApiError
from app.core.security import Principal, require_role
from app.services import cross_store
from app.services.product_lookup import lookup_product


router = APIRouter(tags=["Staff"])

BARCODE = Path(min_length=1, max_length=30, pattern=r"^[A-Za-z0-9-]+$")


@router.get("/products/barcode/{barcode}", response_model=ProductLookup)
def get_product_by_barcode(
    barcode: str = BARCODE,
    principal: Principal = Depends(require_role("Staff")),
    session: Session = Depends(get_db),
) -> ProductLookup:
    if principal.store_id is None:
        raise ApiError(403, "FORBIDDEN", "A store is required for product lookup.")
    return ProductLookup(**lookup_product(session, barcode, principal.store_id))


@router.get("/products/barcode/{barcode}/stock", response_model=CrossStoreStock)
def get_cross_store_stock(
    barcode: str = BARCODE,
    from_store: str = Query(min_length=1, max_length=10, pattern=ID_PATTERN),
    principal: Principal = Depends(require_role("Staff")),
    session: Session = Depends(get_db),
) -> CrossStoreStock:
    """Stock of the product in this Middleware's other active stores, nearest first.

    ``from_store`` must be the caller's own store; another store is 403 before
    any query runs (STF35-6).
    """
    if principal.store_id is None or from_store != principal.store_id:
        raise ApiError(403, "FORBIDDEN", "The lookup must start from the caller's store.")
    return CrossStoreStock(**cross_store.lookup(session, barcode, from_store))
