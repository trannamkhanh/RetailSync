"""Sync reconciliation after a DS-09 scenario (PB-17, SYNC17-5).

Checks the three DS-09 section 7 rules on a middleware database and the HQ
database, prints PASS or FAIL per rule, and exits 1 if any rule fails:

1. Stock in each store equals its opening stock plus all its movements.
2. HQ totals equal the summary lines of the ACKED batches (``SB-HIST-``
   history batches excluded: they never go to HQ), and HQ holds exactly the
   ACKED batches.
3. Each transaction is in at most one batch: every batch counts exactly the
   transactions linked to it, and its lines equal the sum of their items.

The opening stock is the seed's (STORE-DN1 40, STORE-DN2 25, STORE-DN3 15 per
SKU); ``--opening STORE=QTY`` adds or changes a store. Stores without an
opening are listed and not checked by rule 1. The script only reads.

Run it in the middleware image from the repository root:

    docker compose run --rm --volume "${PWD}:/repo" --workdir /repo middleware python scripts/sync_reconcile.py --db RTS_DB_DEMO --hq-db RTS_HQ

It refuses RTS_DB, the development database, unless ``--allow-dev`` is given.
"""

import argparse
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "middleware"))

from sqlalchemy import Connection, create_engine, text  # noqa: E402

from app.core.db import database_url  # noqa: E402


DEV_DATABASE = "RTS_DB"
SEED_OPENING = {"STORE-DN1": 40, "STORE-DN2": 25, "STORE-DN3": 15}
HISTORY = "SB-HIST-%"
SHOWN = 10

Totals = tuple[int, int, Decimal]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check the DS-09 sync reconciliation rules.")
    parser.add_argument("--db", default="RTS_DB_DEMO", help="middleware database (default RTS_DB_DEMO)")
    parser.add_argument("--hq-db", default="RTS_HQ", help="HQ database (default RTS_HQ)")
    parser.add_argument("--opening", action="append", default=[], metavar="STORE=QTY",
                        help="opening stock per SKU of a store; repeat for more stores")
    parser.add_argument("--allow-dev", action="store_true", help="allow reading RTS_DB")
    args = parser.parse_args(argv)
    for name in (args.db, args.hq_db):
        if not re.fullmatch(r"[A-Za-z0-9_]{1,64}", name):
            parser.error(f"'{name}' is not a plain database name")
    if args.db.upper() == DEV_DATABASE and not args.allow_dev:
        parser.error("refusing RTS_DB, the development database; pass --allow-dev to read it")
    args.openings = dict(SEED_OPENING)
    for item in args.opening:
        store, _, quantity = item.partition("=")
        if not store or not quantity.isdigit():
            parser.error(f"--opening needs STORE=QTY, got '{item}'")
        args.openings[store] = int(quantity)
    return args


def report(rule: str, problems: list[str], summary: str) -> bool:
    print(f"{'PASS' if not problems else 'FAIL'} {rule}: {summary}")
    for problem in problems[:SHOWN]:
        print(f"    {problem}")
    if len(problems) > SHOWN:
        print(f"    ... {len(problems) - SHOWN} more")
    return not problems


def check_stock(connection: Connection, openings: dict[str, int]) -> bool:
    rows = connection.execute(text(
        """
        SELECT i.store_id, i.sku, i.quantity, COALESCE(SUM(m.quantity), 0) AS moved
        FROM dbo.inventory i
        LEFT JOIN dbo.inventory_movement m ON m.store_id = i.store_id AND m.sku = i.sku
        GROUP BY i.store_id, i.sku, i.quantity
        ORDER BY i.store_id, i.sku
        """
    )).all()
    problems, checked, unknown = [], 0, set()
    for store_id, sku, quantity, moved in rows:
        if store_id not in openings:
            unknown.add(store_id)
            continue
        checked += 1
        expected = openings[store_id] + int(moved)
        if quantity != expected:
            problems.append(f"{store_id}/{sku}: stock {quantity} != opening {openings[store_id]} "
                            f"+ movements {int(moved)}")
        if quantity < 0:
            problems.append(f"{store_id}/{sku}: negative stock {quantity}")
    summary = f"{checked} inventory rows"
    if unknown:
        summary += f"; not checked (no opening): {', '.join(sorted(unknown))}"
    return report("1 stock = opening + movements", problems, summary)


def _totals(rows) -> dict[tuple[str, str], Totals]:
    return {(store, sku): (int(sold), int(returned), Decimal(net)) for store, sku, sold, returned, net in rows}


def check_hq_totals(connection: Connection, hq: Connection) -> bool:
    local = _totals(connection.execute(text(
        """
        SELECT b.store_id, l.sku, SUM(l.sold_qty), SUM(l.returned_qty), SUM(l.net_revenue)
        FROM dbo.sync_batch b
        JOIN dbo.sales_summary_line l ON l.sync_batch_id = b.sync_batch_id
        WHERE b.status = 'ACKED' AND b.sync_batch_id NOT LIKE :history
        GROUP BY b.store_id, l.sku
        """
    ), {"history": HISTORY}).all())
    remote = _totals(hq.execute(text(
        "SELECT store_id, sku, sold_qty, returned_qty, net_revenue FROM dbo.hq_sales_total"
    )).all())
    acked = set(connection.execute(text(
        "SELECT sync_batch_id FROM dbo.sync_batch WHERE status = 'ACKED' AND sync_batch_id NOT LIKE :history"
    ), {"history": HISTORY}).scalars())
    received = set(hq.execute(text("SELECT sync_batch_id FROM dbo.hq_sync_batch")).scalars())

    problems = [f"HQ holds batch {batch_id}, which is not ACKED here" for batch_id in sorted(received - acked)]
    problems += [f"batch {batch_id} is ACKED here but missing at HQ" for batch_id in sorted(acked - received)]
    zero: Totals = (0, 0, Decimal("0"))
    for key in sorted(local.keys() | remote.keys()):
        if local.get(key, zero) != remote.get(key, zero):
            problems.append(f"{key[0]}/{key[1]}: ACKED lines {local.get(key, zero)} != HQ {remote.get(key, zero)}")
    summary = f"{len(acked)} ACKED batches, {len(local)} store/SKU totals"
    return report("2 HQ totals = lines of ACKED batches", problems, summary)


def check_one_batch_per_transaction(connection: Connection) -> bool:
    counts = connection.execute(text(
        """
        SELECT b.sync_batch_id, b.txn_count, COUNT(t.txn_id)
        FROM dbo.sync_batch b
        LEFT JOIN dbo.pos_transaction t ON t.sync_batch_id = b.sync_batch_id
        WHERE b.sync_batch_id NOT LIKE :history
        GROUP BY b.sync_batch_id, b.txn_count
        """
    ), {"history": HISTORY}).all()
    lines = connection.execute(text(
        """
        SELECT sync_batch_id, sku, sold_qty, returned_qty, net_revenue
        FROM dbo.sales_summary_line WHERE sync_batch_id NOT LIKE :history
        """
    ), {"history": HISTORY}).all()
    items = connection.execute(text(
        """
        SELECT t.sync_batch_id, ti.sku,
               SUM(CASE WHEN t.txn_type = 'SALE' THEN ti.qty ELSE 0 END),
               SUM(CASE WHEN t.txn_type IN ('RETURN', 'CANCELLATION') THEN ti.qty ELSE 0 END),
               SUM(CASE WHEN t.txn_type = 'SALE' THEN ti.qty * ti.unit_price ELSE -ti.qty * ti.unit_price END)
        FROM dbo.pos_transaction t
        JOIN dbo.transaction_item ti ON ti.txn_id = t.txn_id
        WHERE t.sync_batch_id IS NOT NULL AND t.sync_batch_id NOT LIKE :history
        GROUP BY t.sync_batch_id, ti.sku
        """
    ), {"history": HISTORY}).all()

    problems = [f"batch {batch_id}: txn_count {declared} != {linked} linked transactions"
                for batch_id, declared, linked in counts if declared != linked]
    by_line = _totals(lines)
    by_items = _totals(items)
    for key in sorted(by_line.keys() | by_items.keys()):
        if by_line.get(key) != by_items.get(key):
            problems.append(f"batch {key[0]}/{key[1]}: lines {by_line.get(key)} != items {by_items.get(key)}")
    unbatched = connection.execute(text(
        "SELECT COUNT(*) FROM dbo.pos_transaction WHERE sync_batch_id IS NULL")).scalar_one()
    linked = sum(row[2] for row in counts)
    summary = f"{len(counts)} batches, {linked} linked transactions, {unbatched} not batched yet"
    return report("3 each transaction in at most one batch", problems, summary)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    print(f"Reconciling {args.db} with {args.hq_db}")
    engine = create_engine(database_url(args.db), hide_parameters=True)
    hq_engine = create_engine(database_url(args.hq_db), hide_parameters=True)
    with engine.connect() as connection, hq_engine.connect() as hq:
        results = [check_stock(connection, args.openings),
                   check_hq_totals(connection, hq),
                   check_one_batch_per_transaction(connection)]
    print("RECONCILIATION PASS" if all(results) else "RECONCILIATION FAIL")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
