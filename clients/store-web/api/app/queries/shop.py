"""Read-only queries for the customer shop: product search and store stock.

Still SELECT-only against the store database. The nearest-store ranking lives in
``app.recommend`` so it can be tested without a database.
"""

from datetime import date

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

ACTIVE_STORES = text(
    """
    SELECT store_id, name, region_id, address_text, latitude, longitude
    FROM dbo.store
    WHERE is_active = 1
    ORDER BY store_id
"""
)

SEARCH_PRODUCTS = text(
    """
    SELECT p.sku, p.barcode, p.name, p.category, p.unit_price, p.image_url
    FROM dbo.product AS p
    WHERE (:q IS NULL
           OR p.name LIKE :q_like ESCAPE '\\'
           OR p.sku LIKE CAST(:q_like AS varchar(120)) ESCAPE '\\'
           OR p.barcode LIKE CAST(:q_like AS varchar(120)) ESCAPE '\\')
      AND (:category IS NULL OR p.category = CAST(:category AS varchar(50)))
    ORDER BY p.name, p.sku
    OFFSET 0 ROWS FETCH NEXT :limit ROWS ONLY
"""
)

STORE_STOCK_FOR_SKUS = text(
    """
    SELECT b.store_id, b.sku,
           SUM(CASE WHEN b.expiry_date >= CAST(:today AS date) THEN b.quantity ELSE 0 END) AS sellable_quantity
    FROM dbo.product_batch AS b
    WHERE b.sku IN :skus
      AND b.quantity > 0
    GROUP BY b.store_id, b.sku
"""
).bindparams(bindparam("skus", expanding=True))


def active_stores_with_coordinates(session: Session) -> list[dict]:
    """Every active store with the coordinates needed for a distance."""
    return [
        {
            "store_id": row["store_id"],
            "name": row["name"],
            "region_id": row["region_id"],
            "address_text": row["address_text"],
            "latitude": float(row["latitude"]),
            "longitude": float(row["longitude"]),
        }
        for row in session.execute(ACTIVE_STORES).mappings().all()
    ]


def search_products(session: Session, *, q: str | None, q_like: str | None,
                    category: str | None, limit: int) -> list[dict]:
    """Products whose name, SKU or barcode matches, in catalog order."""
    rows = session.execute(
        SEARCH_PRODUCTS,
        {
            "q": q or None,
            "q_like": q_like,
            "category": category or None,
            "limit": limit,
        },
    ).mappings().all()
    return [
        {
            "sku": row["sku"],
            "barcode": row["barcode"],
            "name": row["name"],
            "category": row["category"],
            "unit_price": f"{row['unit_price']:.2f}",
            "image_url": row["image_url"],
        }
        for row in rows
    ]


def store_stock_for_skus(session: Session, skus: list[str], today: date) -> dict[str, dict[str, int]]:
    """``{sku: {store_id: sellable_quantity}}`` for the given SKUs."""
    if not skus:
        return {}
    rows = session.execute(
        STORE_STOCK_FOR_SKUS, {"skus": skus, "today": today}
    ).mappings().all()
    stock: dict[str, dict[str, int]] = {}
    for row in rows:
        quantity = int(row["sellable_quantity"] or 0)
        if quantity <= 0:
            continue
        stock.setdefault(row["sku"], {})[row["store_id"]] = quantity
    return stock
