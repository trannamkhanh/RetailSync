"""Read-only queries for the product page, one product, and categories.

Every statement is a SELECT. The page, the count and the batches of the page are
three fixed statements, so a request never runs one query per product.
"""

from datetime import date
from decimal import Decimal

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from app.queries.stores import store_exists_active

# One definition of the per-store batch figures, shared by the page and the count
# so "sellable" cannot drift between them.
_BATCH_TOTALS = """
    OUTER APPLY (
        SELECT SUM(CASE WHEN bb.expiry_date >= CAST(:today AS date) THEN bb.quantity ELSE 0 END) AS sellable_quantity,
               SUM(CASE WHEN bb.expiry_date <  CAST(:today AS date) THEN bb.quantity ELSE 0 END) AS expired_quantity,
               MIN(CASE WHEN bb.expiry_date >= CAST(:today AS date) THEN bb.expiry_date END) AS nearest_expiry
        FROM dbo.product_batch AS bb
        WHERE bb.store_id = CAST(:store_id AS varchar(10))
          AND bb.sku = p.sku
          AND bb.quantity > 0
    ) AS b
"""

_FROM_PRODUCT = """
    FROM dbo.product AS p
    LEFT JOIN dbo.inventory AS i
           ON i.sku = p.sku
          AND i.store_id = CAST(:store_id AS varchar(10))
""" + _BATCH_TOTALS

_SELECT_PRODUCT = (
    """
    SELECT p.sku, p.barcode, p.name, p.category, p.unit_price, p.image_url,
           COALESCE(i.quantity, 0) AS quantity,
           COALESCE(b.sellable_quantity, 0) AS sellable_quantity,
           COALESCE(b.expired_quantity, 0) AS expired_quantity,
           b.nearest_expiry
"""
    + _FROM_PRODUCT
)

_WHERE_FILTERS = """
    WHERE (:q IS NULL
           OR p.name LIKE :q_like ESCAPE '\\'
           OR p.sku LIKE CAST(:q_like AS varchar(120)) ESCAPE '\\')
      AND (:category IS NULL OR p.category = CAST(:category AS varchar(50)))
      AND (:in_stock IS NULL
           OR (:in_stock = 1 AND COALESCE(b.sellable_quantity, 0) > 0)
           OR (:in_stock = 0 AND COALESCE(b.sellable_quantity, 0) = 0))
"""

_ORDER_BY = {
    "name": "p.name, p.sku",
    "price": "p.unit_price, p.sku",
    "sellable": "COALESCE(b.sellable_quantity, 0) DESC, p.sku",
}

_PRODUCT_PAGE_SQL = (
    _SELECT_PRODUCT
    + _WHERE_FILTERS
    + """
    ORDER BY __ORDER__
    OFFSET :offset ROWS FETCH NEXT :limit ROWS ONLY
"""
)

PRODUCT_COUNT = text("SELECT COUNT(*) AS total\n" + _FROM_PRODUCT + _WHERE_FILTERS)

PRODUCT_ONE = text(
    _SELECT_PRODUCT
    + """
    WHERE p.sku = CAST(:sku AS varchar(20))
"""
)

BATCHES_FOR_SKUS = text(
    """
    SELECT sku, batch_id, expiry_date, quantity
    FROM dbo.product_batch
    WHERE store_id = CAST(:store_id AS varchar(10))
      AND quantity > 0
      AND sku IN :skus
    ORDER BY sku, expiry_date, batch_id
"""
).bindparams(bindparam("skus", expanding=True))

BATCHES_FOR_SKU = text(
    """
    SELECT batch_id, expiry_date, quantity
    FROM dbo.product_batch
    WHERE store_id = CAST(:store_id AS varchar(10))
      AND sku = CAST(:sku AS varchar(20))
      AND (:include_empty = 1 OR quantity > 0)
    ORDER BY expiry_date, batch_id
"""
)

SELLABLE_STOCK_EVERYWHERE = text(
    """
    SELECT b.sku, b.store_id, SUM(b.quantity) AS sellable_quantity
    FROM dbo.product_batch AS b
    WHERE b.sku IN :skus
      AND b.quantity > 0
      AND b.expiry_date >= CAST(:today AS date)
    GROUP BY b.sku, b.store_id
"""
).bindparams(bindparam("skus", expanding=True))

CATEGORIES = text(
    """
    SELECT DISTINCT category
    FROM dbo.product
    ORDER BY category
"""
)


def escape_like(value: str) -> str:
    """Escape the LIKE metacharacters so a search is literal text."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _money(value: object) -> str:
    return f"{Decimal(str(value)):.2f}"


def _batch(row, today: date) -> dict:
    sellable = row["expiry_date"] >= today
    return {
        "batch_id": row["batch_id"],
        "expiry_date": row["expiry_date"],
        "quantity": int(row["quantity"]),
        "sellable": sellable,
    }


def _item(row, batches: list[dict]) -> dict:
    return {
        "sku": row["sku"],
        "barcode": row["barcode"],
        "name": row["name"],
        "category": row["category"],
        "unit_price": _money(row["unit_price"]),
        "image_url": row["image_url"],
        "quantity": int(row["quantity"] or 0),
        "sellable_quantity": int(row["sellable_quantity"] or 0),
        "expired_quantity": int(row["expired_quantity"] or 0),
        "nearest_expiry": row["nearest_expiry"],
        "batches": batches,
    }


def _params(store_id: str, today: date, *, q: str | None, category: str | None,
            in_stock: bool | None) -> dict:
    return {
        "store_id": store_id,
        "today": today,
        "q": q if q else None,
        "q_like": f"%{escape_like(q)}%" if q else None,
        "category": category if category else None,
        "in_stock": None if in_stock is None else int(in_stock),
    }


def sellable_stock_by_sku(session: Session, skus: list[str], today: date) -> dict[str, dict[str, int]]:
    """``{sku: {store_id: sellable_quantity}}`` across every store, for one page."""
    if not skus:
        return {}
    rows = session.execute(
        SELLABLE_STOCK_EVERYWHERE, {"skus": skus, "today": today}
    ).mappings().all()
    stock: dict[str, dict[str, int]] = {}
    for row in rows:
        quantity = int(row["sellable_quantity"] or 0)
        if quantity <= 0:
            continue
        stock.setdefault(row["sku"], {})[row["store_id"]] = quantity
    return stock


def product_page(session: Session, store_id: str, today: date, *, q: str | None,
                 category: str | None, in_stock: bool | None, sort: str,
                 limit: int, offset: int) -> tuple[list[dict], int] | None:
    """One page of products and the total before pagination.

    ``None`` means the store does not exist or is inactive. The store's own
    ``sellable_quantity`` is the "buy it here" number; the page does not look at
    other branches. A suggestion for another branch is added by the caller with
    ``app.recommend.attach_nearest_stores``, which keeps routing out of this module.
    """
    if not store_exists_active(session, store_id):
        return None

    params = _params(store_id, today, q=q, category=category, in_stock=in_stock)
    total = int(session.execute(PRODUCT_COUNT, params).scalar_one())

    order_by = _ORDER_BY[sort]
    statement = text(_PRODUCT_PAGE_SQL.replace("__ORDER__", order_by))
    rows = session.execute(
        statement, {**params, "limit": limit, "offset": offset}
    ).mappings().all()
    if not rows:
        return [], total

    skus = [row["sku"] for row in rows]
    batch_rows = session.execute(
        BATCHES_FOR_SKUS, {"store_id": store_id, "skus": skus}
    ).mappings().all()
    by_sku: dict[str, list[dict]] = {sku: [] for sku in skus}
    for batch in batch_rows:
        by_sku[batch["sku"]].append(_batch(batch, today))

    return [_item(row, by_sku.get(row["sku"], [])) for row in rows], total


def product_detail(session: Session, store_id: str, sku: str, today: date, *,
                   include_empty: bool) -> dict | None:
    """One product with all of its batches.

    ``None`` means the SKU is not in the catalog. A SKU without an inventory row
    at this store is not an error: quantity and sellable quantity are 0.
    """
    if not store_exists_active(session, store_id):
        return None

    row = session.execute(PRODUCT_ONE, {"store_id": store_id, "today": today, "sku": sku}).mappings().first()
    if row is None:
        return None

    batch_rows = session.execute(
        BATCHES_FOR_SKU,
        {"store_id": store_id, "sku": sku, "include_empty": int(include_empty)},
    ).mappings().all()
    batches = [_batch(batch, today) for batch in batch_rows]
    return _item(row, batches)


def categories(session: Session) -> list[str]:
    """Every category in the catalog, sorted."""
    return [row[0] for row in session.execute(CATEGORIES).all()]
