"""Staff-only barcode lookup in the caller's own store."""

from fastapi import APIRouter, Depends, Path
from sqlalchemy.orm import Session

from app.api.schemas.products import ProductLookup
from app.core.db import get_db
from app.core.errors import ApiError
from app.core.security import Principal, require_role
from app.services.product_lookup import lookup_product


router = APIRouter(tags=["Staff"])


@router.get("/products/barcode/{barcode}", response_model=ProductLookup)
def get_product_by_barcode(
    barcode: str = Path(min_length=1, max_length=30, pattern=r"^[A-Za-z0-9-]+$"),
    principal: Principal = Depends(require_role("Staff")),
    session: Session = Depends(get_db),
) -> ProductLookup:
    if principal.store_id is None:
        raise ApiError(403, "FORBIDDEN", "A store is required for product lookup.")
    return ProductLookup(**lookup_product(session, barcode, principal.store_id))
