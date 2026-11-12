"""Cross-store stock lookup (PB-35-1 to PB-35-4). Read-only: never commits.

The lookup answers the stock of one barcode in the other active stores of this
Middleware, nearest first. Distance is haversine on the store coordinates, with
the Earth radius of 6371 km, and is rounded to two decimals as DS-04 says.
"""

import math

from sqlalchemy.orm import Session

from app.core import clock
from app.core.errors import ApiError
from app.repositories import cross_store as repository

# Mean Earth radius in km, as the contract fixes it.
EARTH_RADIUS_KM = 6371.0


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km between two points, to full precision."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = (math.sin(delta_phi / 2) ** 2
         + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2)
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def lookup(session: Session, barcode: str, from_store: str) -> dict:
    """The SKU of ``barcode`` with the other active stores that have it, nearest first.

    Every active store other than ``from_store`` is listed, a store with no
    sellable stock included, so the caller can tell "none in stock" from "no
    store". A tie in distance keeps the stores in ``store_id`` order.

    Args:
        session: SQLAlchemy session; this is a read, so nothing is committed.
        barcode: Barcode as the caller sent it, matched case-exactly.
        from_store: The caller's store; it is left out of the answer.

    Returns:
        ``{"sku": ..., "stores": [{"store_id", "name", "qty", "distance_km"}, ...]}``.

    Raises:
        ApiError(404, "NOT_FOUND"): the barcode is not in the catalogue.
        ApiError(403, "FORBIDDEN"): the caller's store is not in this database.
    """
    product = repository.find_product(session, barcode)
    if product is None:
        raise ApiError(404, "NOT_FOUND", "Product barcode was not found.")
    rows = repository.list_store_stock(session, product.sku, clock.today_local())
    origin = next((row for row in rows if row.store_id == from_store), None)
    if origin is None:
        raise ApiError(403, "FORBIDDEN", "A known store is required for the lookup.")
    stores = [
        {
            "store_id": row.store_id,
            "name": row.name,
            "qty": row.quantity,
            "distance_km": round(haversine_km(origin.latitude, origin.longitude,
                                              row.latitude, row.longitude), 2),
        }
        for row in rows
        if row.store_id != from_store and row.is_active
    ]
    stores.sort(key=lambda store: (store["distance_km"], store["store_id"]))
    return {"sku": product.sku, "stores": stores}
