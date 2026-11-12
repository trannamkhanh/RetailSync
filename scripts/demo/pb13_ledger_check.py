"""Ledger check after the PB-13 live run on RTS_DB_DEMO.

Compares every inventory row with the seeded opening stock plus its movement
ledger, and with the sum of its batches. Prints a summary and exits non-zero on
any mismatch.

Run it in the middleware image from any directory; the repository's
``middleware/`` package is added to the path.
"""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "middleware"))

from sqlalchemy import create_engine, text  # noqa: E402

from app.core.db import database_url  # noqa: E402


OPENING = {"STORE-DN1": 40, "STORE-DN2": 25, "STORE-DN3": 15}


def main() -> int:
    engine = create_engine(database_url("RTS_DB_DEMO"))
    with engine.connect() as connection:
        inventory = connection.execute(text(
            "SELECT store_id, sku, quantity FROM dbo.inventory ORDER BY store_id, sku"
        )).all()
        movements = dict(connection.execute(text(
            "SELECT CONCAT(store_id, '|', sku), SUM(quantity) "
            "FROM dbo.inventory_movement GROUP BY store_id, sku"
        )).all())
        batches = dict(connection.execute(text(
            "SELECT CONCAT(store_id, '|', sku), SUM(quantity) "
            "FROM dbo.product_batch GROUP BY store_id, sku"
        )).all())
        transactions = connection.execute(text(
            "SELECT COUNT(*) FROM dbo.pos_transaction")).scalar()
        snapshots = connection.execute(text(
            "SELECT COUNT(*) FROM dbo.audit_log WHERE action = 'SNAPSHOT_REJECTED'"
        )).scalar()

    problems = []
    for store_id, sku, quantity in inventory:
        key = f"{store_id}|{sku}"
        expected = OPENING[store_id] + int(movements.get(key, 0))
        in_batches = int(batches.get(key, 0))
        if quantity != expected:
            problems.append(f"{key}: inventory {quantity} != opening+movements {expected}")
        if quantity != in_batches:
            problems.append(f"{key}: inventory {quantity} != batches {in_batches}")
        if quantity < 0:
            problems.append(f"{key}: negative stock {quantity}")

    print(f"inventory rows={len(inventory)} transactions={transactions} "
          f"snapshot_audits={snapshots}")
    print("mismatches:", problems if problems else "none")
    print("LEDGER OK" if not problems else "LEDGER FAILED")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
