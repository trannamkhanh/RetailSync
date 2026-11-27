"""PB-37: a real mTLS POS -> middleware -> HQ chain, followed by reconciliation.

Run inside the middleware container against your own RTS_DB_DEMO stack:
python scripts/e2e/e2e_check.py --db RTS_DB_DEMO
Use --opening STORE=QTY after a documented replenishment. Never targets RTS_DB.
"""
import argparse
from decimal import Decimal
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "middleware"))

from sqlalchemy import bindparam, create_engine, text
from app.core.config import settings
from app.core.db import database_url
from scripts.demo import sprint2_smoke as api


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="RTS_DB_DEMO", choices=["RTS_DB_DEMO"])
    parser.add_argument("--hq-db", default=os.environ.get("HQ_DB_NAME", "RTS_HQ"))
    parser.add_argument("--tokens", type=Path, default=api.TOKENS_FILE)
    parser.add_argument("--hq-url", default="https://hq-demo:9000/api/v1")
    parser.add_argument("--opening", action="append", default=[])
    args = parser.parse_args(argv)
    if not re.fullmatch(r"[A-Za-z0-9_]{1,64}", args.hq_db) or args.hq_db.upper() == "RTS_DB":
        parser.error("HQ database must be a safe database name other than RTS_DB")
    if settings.db_name.casefold() != args.db.casefold():
        parser.error("DB_NAME must match --db RTS_DB_DEMO before any live request")
    for opening in args.opening:
        if not re.fullmatch(r"[A-Za-z0-9_-]+=\d+", opening):
            parser.error("--opening needs STORE=nonnegative_integer")
    return args


def stock_expectations(opening):
    """Two independent sales: partial RETURN of A, then cancellation of B."""
    return [opening - 3, opening - 2, opening - 4, opening - 2]


def hq_totals(body, store, sku):
    matches = [row for row in body["totals"] if row["store_id"] == store and row["sku"] == sku]
    if not matches:
        return 0, 0, Decimal(0)
    if len(matches) != 1:
        raise ValueError("Duplicate store/SKU HQ totals")
    row = matches[0]
    return int(row["sold_qty"]), int(row["returned_qty"]), Decimal(str(row["net_revenue"]))


def delta(after, before):
    return tuple(a - b for a, b in zip(after, before, strict=True))


def verify(label, ok, detail):
    print(f"{'PASS' if ok else 'FAIL'} {label}: {detail}", flush=True)
    if not ok:
        raise RuntimeError(label)


def request(method, url, body=None, token=None):
    status, answer = api.call(method, url, body, token=token)
    verify(method + " " + url, status in (200, 202), f"HTTP {status} {answer if status not in (200, 202) else ''}")
    return answer


def send(event):
    for attempt in range(5):
        status, body = api.pos_call(event)
        if status == 503 and attempt < 4:
            print(f"RETRY {event['transaction_id']}: HTTP 503, same transaction id", flush=True)
            time.sleep(0.5)
            continue
        verify(event["event_type"] + " through mTLS gateway", status == 200,
               f"{event['transaction_id']} HTTP {status} {api.code_of(body)}")
        return


def settle_older_traffic(admin):
    """A 202 can mean a busy job or pending backoff, not a drained queue."""
    for attempt in range(30):
        answer = request("POST", api.MIDDLEWARE + "/sync/run", token=admin)
        if isinstance(answer, dict) and answer.get("batches_pending") == 0:
            verify("older sync traffic drained", True, "batches_pending=0 before HQ baseline")
            return
        if attempt < 29:
            time.sleep(1)
    verify("older sync traffic drained", False, f"no zero-pending response after 30 polls: {answer}")


def run(args):
    api.TOKENS = json.loads(args.tokens.read_text(encoding="utf-8"))
    admin = api.TOKENS["admin"]
    # Settle older traffic before taking the HQ baseline; this is not a reset.
    settle_older_traffic(admin)
    before = request("GET", args.hq_url.rstrip("/") + "/demo/batches")
    opening = api.stock()
    verify("stock available", opening >= 5, f"{api.STORE_DN1}/{api.STOCK}={opening}")
    prefix = "E2E-" + uuid4().hex[:12]
    events = [
        api.event("SALE", prefix + "-A", [(api.STOCK, 3, 32000)]),
        api.event("RETURN", prefix + "-R", [(api.STOCK, 1, 32000)], original=prefix + "-A"),
        api.event("SALE", prefix + "-B", [(api.STOCK, 2, 32000)]),
        api.event("CANCELLATION", prefix + "-C", original=prefix + "-B"),
    ]
    for event, expected in zip(events, stock_expectations(opening)):
        send(event)
        actual = api.stock()
        verify("stock after " + event["event_type"], actual == expected, f"expected={expected}, actual={actual}")
    ids = [event["transaction_id"] for event in events]
    engine = create_engine(database_url(args.db), hide_parameters=True)
    statement = text(
        "SELECT t.txn_id,b.sync_batch_id,b.status FROM dbo.pos_transaction t "
        "LEFT JOIN dbo.sync_batch b ON b.sync_batch_id=t.sync_batch_id "
        "WHERE t.txn_id IN :ids"
    ).bindparams(bindparam("ids", expanding=True))
    try:
        rows = []
        for _ in range(30):
            request("POST", api.MIDDLEWARE + "/sync/run", token=admin)
            with engine.connect() as connection:
                rows = connection.execute(statement, {"ids": ids}).all()
            if len(rows) == 4 and all(row.status == "ACKED" for row in rows):
                break
            time.sleep(1)
        verify("all four transactions ACKED", len(rows) == 4 and all(row.status == "ACKED" for row in rows),
               str([(row.txn_id, row.sync_batch_id, row.status) for row in rows]))
        after = request("GET", args.hq_url.rstrip("/") + "/demo/batches")
        acked = {row.sync_batch_id for row in rows}
        remote = {row["batch_id"] for row in after["batches"]}
        verify("ACKED batch present at HQ", acked <= remote, str(sorted(acked)))
        difference = delta(hq_totals(after, api.STORE_DN1, api.STOCK),
                           hq_totals(before, api.STORE_DN1, api.STOCK))
        verify("HQ totals match SALE/RETURN/CANCELLATION", difference == (5, 3, Decimal(64000)),
               f"sold/returned/net revenue delta={difference}")
    finally:
        engine.dispose()
    command = [sys.executable, str(ROOT / "scripts/sync_reconcile.py"), "--db", args.db, "--hq-db", args.hq_db]
    for value in args.opening:
        command += ["--opening", value]
    result = subprocess.run(command, check=False)
    verify("sync_reconcile", result.returncode == 0, f"exit={result.returncode}")
    print("E2E PASS", flush=True)
    return 0


def main(argv=None):
    args = parse_args(argv)
    try:
        return run(args)
    except Exception as error:
        print(f"FAIL E2E: {error}", flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
