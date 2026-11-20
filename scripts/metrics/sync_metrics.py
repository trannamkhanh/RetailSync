"""Sync metrics (PB-40, TST40-1 and TST40-2, DS-09 section 4).

Reads the sync batches of a middleware database (``RTS_DB_DEMO`` by default)
and prints, per store and in total, as a Markdown table:

- data reduction = 1 - sum(payload_bytes) / sum(raw_bytes) over ACKED batches
  (target at least 90 %, TST40-1). ``raw_bytes`` is the UTF-8 size of the
  batch's transactions sent one by one as compact POS event JSON, and
  ``payload_bytes`` the UTF-8 size of the batch message sent to HQ (see
  ``app/services/aggregation.py``). ACKED batches without ``raw_bytes``
  (aggregated before PB-40) are counted apart and left out of the ratio.
- sync success rate = ACKED batches / all batches (TST40-2).

``SB-HIST-`` history batches are excluded: they never go to HQ. ``--since``
keeps only batches created at or after a UTC time, so one run can be measured
on a database that holds older batches. The script only reads; it refuses
RTS_DB, the development database, unless ``--allow-dev`` is given.

Run it in the middleware image from the repository root:

    docker compose run --rm --no-deps --volume "${PWD}:/repo" --workdir /repo middleware python scripts/metrics/sync_metrics.py --db RTS_DB_DEMO --since 2026-11-21T02:00:00

Exit 1 when the total data reduction is below the target.
"""

import argparse
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "middleware"))

from sqlalchemy import create_engine, text  # noqa: E402

from app.core.db import database_url  # noqa: E402


DEV_DATABASE = "RTS_DB"
TARGET_REDUCTION = 0.90


@dataclass
class Totals:
    batches: int = 0
    acked: int = 0
    failed: int = 0
    open: int = 0  # PENDING or SENT
    payload_bytes: int = 0
    raw_bytes: int = 0
    acked_without_raw: int = 0

    def add(self, status: str, payload_bytes: int | None, raw_bytes: int | None) -> None:
        self.batches += 1
        if status == "FAILED":
            self.failed += 1
        elif status != "ACKED":
            self.open += 1
            return
        if status != "ACKED":
            return
        self.acked += 1
        if raw_bytes is None or payload_bytes is None:
            self.acked_without_raw += 1
            return
        self.payload_bytes += payload_bytes
        self.raw_bytes += raw_bytes

    @property
    def reduction(self) -> float | None:
        return None if not self.raw_bytes else 1 - self.payload_bytes / self.raw_bytes

    @property
    def success_rate(self) -> float | None:
        return None if not self.batches else self.acked / self.batches


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Report data reduction and sync success rate.")
    parser.add_argument("--db", default="RTS_DB_DEMO", help="middleware database (default RTS_DB_DEMO)")
    parser.add_argument("--since", type=datetime.fromisoformat,
                        help="only batches created at or after this UTC time, e.g. 2026-11-21T02:00:00")
    parser.add_argument("--allow-dev", action="store_true", help="allow reading RTS_DB")
    args = parser.parse_args(argv)
    if not re.fullmatch(r"[A-Za-z0-9_]{1,64}", args.db):
        parser.error(f"'{args.db}' is not a plain database name")
    if args.db.upper() == DEV_DATABASE and not args.allow_dev:
        parser.error("refusing RTS_DB, the development database; pass --allow-dev to read it")
    if args.since is not None and args.since.tzinfo is not None:
        args.since = args.since.replace(tzinfo=None) - args.since.utcoffset()
    return args


def collect(rows) -> dict[str, Totals]:
    """Rows of (store_id, status, payload_bytes, raw_bytes) -> totals per store and under 'TOTAL'."""
    totals: dict[str, Totals] = defaultdict(Totals)
    for store_id, status, payload_bytes, raw_bytes in rows:
        totals[store_id].add(status, payload_bytes, raw_bytes)
        totals["TOTAL"].add(status, payload_bytes, raw_bytes)
    return dict(totals)


def _percent(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.2f} %"


def table(totals: dict[str, Totals]) -> str:
    lines = ["| Store | Batches | ACKED | FAILED | PENDING/SENT | Success rate | sum payload_bytes | sum raw_bytes "
             "| Data reduction | ACKED without raw_bytes |",
             "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for store in sorted(name for name in totals if name != "TOTAL") + ["TOTAL"]:
        t = totals.get(store, Totals())
        name = f"**{store}**" if store == "TOTAL" else store
        lines.append(f"| {name} | {t.batches} | {t.acked} | {t.failed} | {t.open} | {_percent(t.success_rate)} "
                     f"| {t.payload_bytes} | {t.raw_bytes} | {_percent(t.reduction)} | {t.acked_without_raw} |")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    query = ("SELECT store_id, status, payload_bytes, raw_bytes FROM dbo.sync_batch "
             "WHERE sync_batch_id NOT LIKE 'SB-HIST-%'")
    params: dict = {}
    if args.since is not None:
        query += " AND created_at >= :since"
        params["since"] = args.since
    engine = create_engine(database_url(args.db), hide_parameters=True)
    with engine.connect() as connection:
        totals = collect(connection.execute(text(query + " ORDER BY store_id"), params).all())
    since = f", batches created since {args.since:%Y-%m-%d %H:%M:%S} UTC" if args.since else ""
    print(f"Sync metrics for {args.db}{since}\n")
    print(table(totals))
    total = totals.get("TOTAL", Totals())
    verdict = total.reduction is not None and total.reduction >= TARGET_REDUCTION
    print(f"\nTST40-1 data reduction {_percent(total.reduction)} (target >= {TARGET_REDUCTION:.0%}): "
          f"{'PASS' if verdict else 'FAIL'}")
    print(f"TST40-2 sync success rate {_percent(total.success_rate)} ({total.acked} of {total.batches} batches ACKED)")
    return 0 if verdict else 1


if __name__ == "__main__":
    sys.exit(main())
