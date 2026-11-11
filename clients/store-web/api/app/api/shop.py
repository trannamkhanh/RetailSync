"""The customer shop: product search and the nearest store that has it."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import clock
from app.config import settings
from app.customer_db import get_customer_db
from app.customer_models import Customer, CustomerAddress
from app.db import get_db
from app.errors import ApiError
from app.geo import SAMPLE_ADDRESSES
from app.queries import shop as shop_queries
from app.queries.products import escape_like
from app.recommend import nearest_stores_for_product
from app.routing import store_distances
from app.schemas import (
    AddressItem,
    AddressList,
    NewAddress,
    ShopProduct,
    ShopSearch,
    StoreSuggestion,
)
from app.security import current_customer

router = APIRouter()

MAX_SAVED_ADDRESSES = 20


def _coordinate(value: float | None, name: str) -> float:
    """Both coordinates are required: half a position gives no distance."""
    if value is None:
        raise ApiError(422, "VALIDATION_ERROR", f"Thiếu toạ độ '{name}'.")
    return value


@router.get("/shop/addresses", response_model=AddressList)
def sample_addresses() -> AddressList:
    """Suggested addresses for customers who do not share their location."""
    return AddressList(addresses=[AddressItem(**address) for address in SAMPLE_ADDRESSES])


@router.get("/shop/addresses/mine", response_model=AddressList)
def my_addresses(
    customer: Customer = Depends(current_customer),
    session: Session = Depends(get_customer_db),
) -> AddressList:
    """The signed-in customer's saved addresses, newest first."""
    rows = session.execute(
        select(CustomerAddress)
        .where(CustomerAddress.customer_id == customer.customer_id)
        .order_by(CustomerAddress.created_at.desc(), CustomerAddress.address_id.desc())
    ).scalars().all()
    return AddressList(
        addresses=[
            AddressItem(
                address_id=f"SAVED-{row.address_id}",
                label=row.label,
                address_text=row.address_text,
                latitude=row.latitude,
                longitude=row.longitude,
            )
            for row in rows
        ]
    )


@router.post("/shop/addresses/mine", response_model=AddressItem, status_code=201)
def save_address(
    payload: NewAddress,
    customer: Customer = Depends(current_customer),
    session: Session = Depends(get_customer_db),
) -> AddressItem:
    """Save an address for later searches."""
    count = session.execute(
        select(func.count()).select_from(CustomerAddress).where(
            CustomerAddress.customer_id == customer.customer_id
        )
    ).scalar_one()
    if int(count) >= MAX_SAVED_ADDRESSES:
        raise ApiError(
            422, "VALIDATION_ERROR", f"Chỉ lưu được tối đa {MAX_SAVED_ADDRESSES} địa chỉ."
        )

    address = CustomerAddress(
        customer_id=customer.customer_id,
        label=payload.label.strip(),
        address_text=payload.address_text.strip(),
        latitude=payload.latitude,
        longitude=payload.longitude,
        created_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    session.add(address)
    session.commit()

    return AddressItem(
        address_id=f"SAVED-{address.address_id}",
        label=address.label,
        address_text=address.address_text,
        latitude=address.latitude,
        longitude=address.longitude,
    )


@router.delete("/shop/addresses/mine/{address_id}", status_code=204)
def delete_address(
    address_id: str,
    customer: Customer = Depends(current_customer),
    session: Session = Depends(get_customer_db),
) -> None:
    """Remove one saved address; a plain address_id value is also accepted."""
    raw = address_id.removeprefix("SAVED-")
    if not raw.isdigit():
        raise ApiError(404, "NOT_FOUND", "Địa chỉ không tồn tại.")
    row = session.execute(
        select(CustomerAddress).where(
            CustomerAddress.address_id == int(raw),
            CustomerAddress.customer_id == customer.customer_id,
        )
    ).scalar_one_or_none()
    if row is None:
        raise ApiError(404, "NOT_FOUND", "Địa chỉ không tồn tại.")
    session.delete(row)
    session.commit()


@router.get("/shop/search", response_model=ShopSearch)
def search(
    q: str = Query(min_length=1, max_length=100),
    latitude: float | None = Query(None, ge=-90, le=90),
    longitude: float | None = Query(None, ge=-180, le=180),
    category: str | None = Query(None, max_length=50),
    limit: int = Query(20, ge=1, le=50),
    stores: Session = Depends(get_db),
) -> ShopSearch:
    """Find products and tell the customer which store to go to, nearest first."""
    lat = _coordinate(latitude, "latitude")
    lon = _coordinate(longitude, "longitude")

    today = clock.today_local()
    products = shop_queries.search_products(
        stores,
        q=q.strip(),
        q_like=f"%{escape_like(q.strip())}%",
        category=category,
        limit=limit,
    )
    stock = shop_queries.store_stock_for_skus(stores, [item["sku"] for item in products], today)
    active = shop_queries.active_stores_with_coordinates(stores)

    # One routing question per search, not per product: the origin is fixed, so
    # every candidate store gets its distance up front.
    distances = {
        entry.store_id: (entry.km, entry.kind)
        for entry in store_distances(
            active,
            latitude=lat,
            longitude=lon,
            base_url=settings.osrm_url,
            timeout=settings.store_web_osrm_timeout_seconds,
        )
    }

    items = []
    for product in products:
        suggestions = nearest_stores_for_product(
            active, stock.get(product["sku"], {}), distances=distances
        )
        items.append(
            ShopProduct(
                **product,
                stores=[StoreSuggestion(**suggestion) for suggestion in suggestions],
                nearest=StoreSuggestion(**suggestions[0]) if suggestions else None,
            )
        )

    return ShopSearch(q=q.strip(), latitude=lat, longitude=lon, total=len(items), items=items)
