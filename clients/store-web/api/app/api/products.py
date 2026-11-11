"""GET /api/stores/{store_id}/products and its detail route."""

from typing import Literal

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.orm import Session

from app import clock
from app.config import settings
from app.db import get_db
from app.errors import ApiError
from app.queries import products as product_queries
from app.queries import shop as shop_queries
from app.recommend import attach_nearest_stores
from app.routing import store_distances
from app.schemas import ProductDetail, ProductPage

router = APIRouter()

ID_PATTERN = r"^[A-Za-z0-9-]{1,10}$"
SKU_PATTERN = r"^[A-Za-z0-9-]{1,20}$"


def _not_found_store(store_id: str) -> ApiError:
    return ApiError(404, "NOT_FOUND", f"Store '{store_id}' does not exist.")


@router.get("/stores/{store_id}/products", response_model=ProductPage)
def list_products(
    store_id: str = Path(pattern=ID_PATTERN),
    q: str | None = Query(None, max_length=100),
    category: str | None = Query(None, max_length=50),
    in_stock: bool | None = Query(None),
    sort: Literal["name", "price", "sellable"] = Query("name"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    latitude: float | None = Query(None, ge=-90, le=90),
    longitude: float | None = Query(None, ge=-180, le=180),
    session: Session = Depends(get_db),
) -> ProductPage:
    """One page of the catalog, with where else each product can be bought.

    The page lists the whole catalogue, not only what this branch stocks, so a
    customer can discover an item and be sent to the branch that has it. When the
    request carries ``latitude``/``longitude``, each row gains ``nearest_store``;
    without coordinates the API cannot measure anything and omits the suggestion
    rather than inventing a distance.
    """
    today = clock.today_local()
    result = product_queries.product_page(
        session,
        store_id,
        today,
        q=q,
        category=category,
        in_stock=in_stock,
        sort=sort,
        limit=limit,
        offset=offset,
    )
    if result is None:
        raise _not_found_store(store_id)
    items, total = result

    if items and latitude is not None and longitude is not None:
        stock_by_sku = product_queries.sellable_stock_by_sku(
            session, [item["sku"] for item in items], today
        )
        stores = shop_queries.active_stores_with_coordinates(session)
        distances = {
            entry.store_id: (entry.km, entry.kind)
            for entry in store_distances(
                stores,
                latitude=latitude,
                longitude=longitude,
                base_url=settings.osrm_url,
                timeout=settings.store_web_osrm_timeout_seconds,
            )
        }
        items = attach_nearest_stores(
            items,
            view_store_id=store_id,
            stock_by_sku=stock_by_sku,
            stores=stores,
            distances=distances,
        )

    return ProductPage(store_id=store_id, total=total, limit=limit, offset=offset, items=items)


@router.get("/stores/{store_id}/products/{sku}", response_model=ProductDetail)
def get_product(
    store_id: str = Path(pattern=ID_PATTERN),
    sku: str = Path(pattern=SKU_PATTERN),
    include_empty: bool = Query(False),
    session: Session = Depends(get_db),
) -> ProductDetail:
    """One catalog product with every batch at this store."""
    item = product_queries.product_detail(
        session,
        store_id,
        sku,
        clock.today_local(),
        include_empty=include_empty,
    )
    if item is None:
        raise ApiError(404, "NOT_FOUND", f"Product '{sku}' does not exist at store '{store_id}'.")
    return ProductDetail(store_id=store_id, item=item)
