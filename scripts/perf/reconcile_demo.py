"""Capture demo inventory and reconcile movement deltas after a simulator run."""

import argparse
import json
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


def reconcile(opening: dict) -> int:
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
    args = parser.parse_args()
    if args.mode == "snapshot":
        with args.file.open("x", encoding="utf-8") as handle:
            json.dump(snapshot(), handle)
    else:
        print(f"Ledger balanced for {reconcile(json.loads(args.file.read_text(encoding='utf-8')))} store/SKU pairs")


if __name__ == "__main__":
    main()
