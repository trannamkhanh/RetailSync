#!/usr/bin/env python3
"""Read-only snapshot for the demo terminals (PB-45).

Run inside the middleware container from the repository root:

    docker compose run --rm --no-deps --volume "${PWD}:/repo:ro" \
        --workdir /repo middleware python clients/demo-pos/tools/db_snapshot.py \
        --store STORE-DN1 --watch 2

It uses app.core.db.SessionLocal and only runs SELECT statements.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "middleware"))

from sqlalchemy import text  # noqa: E402
from app.core.db import SessionLocal  # noqa: E402


TRANSACTIONS_SQL = text(
    """
    SELECT TOP (5) txn_id, txn_type, status, pos_id, created_at
    FROM dbo.pos_transaction
    ORDER BY created_at DESC, txn_id DESC
    """
)
STOCK_SQL = text(
    """
    SELECT i.sku, p.name, i.quantity
    FROM dbo.inventory AS i
    JOIN dbo.product AS p ON p.sku = i.sku
    WHERE i.store_id = :store
    ORDER BY i.sku
    """
)
AUDIT_SQL = text(
    """
    SELECT TOP (5) created_at, action, entity_key, details
    FROM dbo.audit_log
    ORDER BY created_at DESC, audit_id DESC
    """
)


def _time(value: Any) -> str:
    if value is None:
        return "-"
    try:
        return value.strftime("%H:%M:%S")
    except AttributeError:
        return str(value)


def _text(value: Any, width: int) -> str:
    if value is None:
        return "-"
    value = str(value).replace("\r", " ").replace("\n", " ")
    return value if len(value) <= width else value[: width - 1] + "~"


def _row(cells: list[str], widths: list[int]) -> str:
    return " | ".join(_text(cell, width).ljust(width) for cell, width in zip(cells, widths))


def read_snapshot(store_id: str) -> tuple[list[Any], list[Any], list[Any]]:
    with SessionLocal() as session:
        transactions = session.execute(TRANSACTIONS_SQL).all()
        stock = session.execute(STOCK_SQL, {"store": store_id}).all()
        audit = session.execute(AUDIT_SQL).all()
    return transactions, stock, audit


def print_snapshot(store_id: str) -> None:
    transactions, stock, audit = read_snapshot(store_id)
    print(f"RetailSync demo snapshot - {store_id} - {time.strftime('%H:%M:%S')}")
    print()

    print("LAST 5 POS TRANSACTIONS")
    widths = [34, 13, 10, 14, 10]
    print(_row(["txn_id", "txn_type", "status", "pos_id", "time"], widths))
    print("-" * (sum(widths) + 3 * len(widths)))
    for row in transactions:
        print(_row([row.txn_id, row.txn_type, row.status, row.pos_id, _time(row.created_at)], widths))
    if not transactions:
        print("(none)")
    print()

    print("STOCK")
    widths = [10, 24, 8]
    print(_row(["sku", "name", "qty"], widths))
    print("-" * (sum(widths) + 3 * len(widths)))
    for row in stock:
        print(_row([row.sku, row.name, str(row.quantity)], widths))
    if not stock:
        print("(none)")
    print()

    print("LAST 5 AUDIT ROWS")
    widths = [10, 16, 34, 48]
    print(_row(["time", "action", "entity_key", "details"], widths))
    print("-" * (sum(widths) + 3 * len(widths)))
    for row in audit:
        print(_row([_time(row.created_at), row.action, row.entity_key, row.details], widths))
    if not audit:
        print("(none)")
    print()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only RetailSync demo snapshot.")
    parser.add_argument("--store", default="STORE-DN1", help="store id (default: STORE-DN1)")
    parser.add_argument(
        "--watch",
        type=float,
        default=0,
        help="repeat every N seconds (default: print once)",
    )
    args = parser.parse_args(argv)

    try:
        if args.watch and args.watch > 0:
            while True:
                print("\033[2J\033[H", end="")
                print_snapshot(args.store)
                time.sleep(args.watch)
        print_snapshot(args.store)
        return 0
    except KeyboardInterrupt:
        return 0
    except Exception as error:  # noqa: BLE001 - the demo terminal shows the reason
        print(f"db_snapshot failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
