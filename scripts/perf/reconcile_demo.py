"""Capture demo inventory and reconcile movement deltas after a simulator run."""

import argparse
import json
from hashlib import sha256
from pathlib import Path

from sqlalchemy import create_engine, text

from app.core.db import database_url


def snapshot() -> dict:
    engine = create_engine(database_url("RTS_DB_DEMO"))
    try:
        with engine.connect() as connection:
            stock = [list(row) for row in connection.execute(text(
                "SELECT store_id, sku, quantity FROM dbo.inventory ORDER BY store_id, sku"
            ))]
            movement = connection.scalar(text(
                "SELECT COALESCE(MAX(movement_id), 0) FROM dbo.inventory_movement"
            ))
        return {"inventory": stock, "movement_id": movement}
    finally:
        engine.dispose()


def reconcile(opening: dict, *, run_id: str | None = None, seed: int = 42) -> int:
    engine = create_engine(database_url("RTS_DB_DEMO"))
    try:
        with engine.connect() as connection:
            expected = {(store, sku): quantity for store, sku, quantity in opening["inventory"]}
            for store, sku, quantity in connection.execute(text(
                "SELECT store_id, sku, SUM(CAST(quantity AS bigint)) FROM dbo.inventory_movement "
                "WHERE movement_id > :opening GROUP BY store_id, sku"
            ), {"opening": opening["movement_id"]}):
                expected[store, sku] = expected.get((store, sku), 0) + quantity
            actual = {(store, sku): qty for store, sku, qty in connection.execute(text(
                "SELECT store_id, sku, quantity FROM dbo.inventory"
            ))}
            if run_id:
                prefix = sha256(f"{run_id}/{seed}".encode()).hexdigest()[:16]
                difference = connection.scalar(text("""
                    WITH expected AS (
                        SELECT t.txn_id, i.sku,
                               SUM(CAST(i.qty AS bigint) *
                                   CASE WHEN t.txn_type = 'SALE' THEN -1 ELSE 1 END) AS quantity
                        FROM dbo.pos_transaction t
                        JOIN dbo.transaction_item i ON i.txn_id = t.txn_id
                        WHERE t.txn_id LIKE :pattern GROUP BY t.txn_id, i.sku
                    ), actual AS (
                        SELECT txn_id, sku, SUM(CAST(quantity AS bigint)) AS quantity
                        FROM dbo.inventory_movement
                        WHERE txn_id LIKE :pattern GROUP BY txn_id, sku
                    )
                    SELECT COUNT(*) FROM expected e
                    FULL JOIN actual a ON a.txn_id = e.txn_id AND a.sku = e.sku
                    WHERE e.quantity IS NULL OR a.quantity IS NULL OR e.quantity <> a.quantity
                """), {"pattern": f"SIM-{prefix}-%"})
                if difference:
                    raise ValueError(f"{difference} transaction/SKU movement totals differ from their items")
        for key in expected.keys() | actual.keys():
            quantity = actual.get(key, 0)
            if quantity < 0 or quantity != expected.get(key, 0):
                raise ValueError(f"{key}: actual stock {quantity}, expected {expected.get(key, 0)}")
        return len(expected.keys() | actual.keys())
    finally:
        engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("snapshot", "reconcile"))
    parser.add_argument("file", type=Path)
    parser.add_argument("--run-id", help="Verify per-transaction movement totals for this simulator run")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    if args.mode == "snapshot":
        with args.file.open("x", encoding="utf-8") as handle:
            json.dump(snapshot(), handle)
    else:
        opening = json.loads(args.file.read_text(encoding="utf-8"))
        count = reconcile(opening, run_id=args.run_id, seed=args.seed)
        print(f"Ledger balanced for {count} store/SKU pairs")


if __name__ == "__main__":
    main()
