"""Read-only queries for stores. Every statement is a SELECT."""

from datetime import date

from sqlalchemy import text
from sqlalchemy.orm import Session

STORE_LIST = text(
    """
    SELECT store_id, name, region_id, address_text
    FROM dbo.store
    WHERE is_active = 1
    ORDER BY store_id
"""
)

STORE_ONE = text(
    """
    SELECT store_id, name, region_id, address_text
    FROM dbo.store
    WHERE store_id = CAST(:store_id AS varchar(10))
      AND is_active = 1
"""
)

STORE_EXISTS_ACTIVE = text(
    """
    SELECT COUNT(*)
    FROM dbo.store
    WHERE store_id = CAST(:store_id AS varchar(10))
      AND is_active = 1
"""
)

INVENTORY_COUNTS = text(
    """
    SELECT store_id, COUNT(*) AS product_count
    FROM dbo.inventory
    GROUP BY store_id
"""
)

BATCH_TOTALS = text(
    """
    SELECT store_id,
           SUM(CASE WHEN expiry_date >= CAST(:today AS date) THEN quantity ELSE 0 END) AS sellable_units,
           SUM(CASE WHEN expiry_date <  CAST(:today AS date) THEN quantity ELSE 0 END) AS expired_units
    FROM dbo.product_batch
    WHERE quantity > 0
    GROUP BY store_id
"""
)


def _totals(session: Session, today: date) -> dict[str, dict[str, int]]:
    rows = session.execute(BATCH_TOTALS, {"today": today}).mappings().all()
    return {
        row["store_id"]: {
            "sellable_units": int(row["sellable_units"] or 0),
            "expired_units": int(row["expired_units"] or 0),
        }
        for row in rows
    }


def _counts(session: Session) -> dict[str, int]:
    rows = session.execute(INVENTORY_COUNTS).mappings().all()
    return {row["store_id"]: int(row["product_count"]) for row in rows}


def _merge(stores, counts, totals) -> list[dict]:
    merged = []
    for store in stores:
        store_id = store["store_id"]
        merged.append(
            {
                "store_id": store_id,
                "name": store["name"],
                "region_id": store["region_id"],
                "address_text": store["address_text"],
                "product_count": counts.get(store_id, 0),
                "sellable_units": totals.get(store_id, {}).get("sellable_units", 0),
            }
        )
    return merged


def list_stores(session: Session, today: date) -> list[dict]:
    """Every active store with its SKU count and sellable units.

    Three statements, no N+1: the store rows, the inventory counts per store, and
    the batch totals per store, merged in Python by ``store_id``.
    """
    stores = session.execute(STORE_LIST).mappings().all()
    return _merge(stores, _counts(session), _totals(session, today))


def get_store(session: Session, store_id: str, today: date) -> dict | None:
    """One active store with totals, or ``None`` when missing or inactive."""
    row = session.execute(STORE_ONE, {"store_id": store_id}).mappings().first()
    if row is None:
        return None
    totals = _totals(session, today).get(store_id, {})
    return {
        "store_id": row["store_id"],
        "name": row["name"],
        "region_id": row["region_id"],
        "address_text": row["address_text"],
        "product_count": _counts(session).get(store_id, 0),
        "sellable_units": totals.get("sellable_units", 0),
        "expired_units": totals.get("expired_units", 0),
    }


def store_exists_active(session: Session, store_id: str) -> bool:
    """True when the store exists and is active; used by the 404 of /products."""
    found = session.execute(STORE_EXISTS_ACTIVE, {"store_id": store_id}).scalar_one()
    return int(found) > 0
