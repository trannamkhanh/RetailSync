"""Near-expiry accuracy measurement (PB-43, DS-09 section 6, EXP43-1 to 43-3).

Builds a dataset of batches whose expected result is known -- alert
NEAR_EXPIRY, alert EXPIRED, or no alert -- in bands around every category
threshold, loads it into RTS_DB_TEST or RTS_DB_DEMO, runs the real daily
near-expiry job, and counts correct, missed and false alerts:
- correct: the job flagged the batch as expected, or left it unflagged;
- missed:  an expected alert is absent, or has the wrong type;
- false:   an alert exists where none is expected.

The script owns one store, ``TEST-PB43``, and resets its own rows before it
loads the dataset, so it is safe to run twice. It runs the daily check for its
own store only, so no other store of the database is touched. It writes only
to ``RTS_DB_DEMO`` or to a database whose name ends in ``_TEST``; every other
name, the development ``RTS_DB`` included, is refused.

After the run the store ``TEST-PB43`` and its 32 batches and alerts stay in
the database, so the next run measures the same rows again. On
``RTS_DB_DEMO`` the daily recommendation job would then see those batches, so
reset the demo database after a measurement there
(``scripts/demo/reset_demo_db.ps1``). ``--cleanup`` deletes the store again
and leaves the database as it was.

Run it in the middleware image from the repository root:

    docker compose run --rm --volume "${PWD}:/repo" --workdir /repo middleware python scripts/metrics/near_expiry_accuracy.py --db RTS_DB_TEST

The job runs for the dataset's store only, as one per-store transaction of the
daily job. Exit 1 when any alert is missed or false, so the report can cite a
clean run.
"""

import argparse
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "middleware"))

from decimal import Decimal  # noqa: E402

from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402

from app.core import clock  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.core.db import database_url  # noqa: E402
from app.domain.models import (  # noqa: E402
    Inventory,
    NearExpiryAlert,
    NearExpiryConfig,
    Product,
    ProductBatch,
    Store,
)
from app.services import near_expiry as near_expiry_service  # noqa: E402

DEV_DATABASE = "RTS_DB"
DEMO_DATABASE = "RTS_DB_DEMO"
STORE_ID = "TEST-PB43"
SKU_PREFIX = "TEST-PB43-S"
BATCH_PREFIX = "TEST-PB43-B"
CATEGORY_PREFIX = "TEST-PB43-"
# Configured thresholds: every band around a small, a medium and a wide window,
# plus one category that has no config row and uses the default window.
THRESHOLDS = {"TEST-PB43-T3": 3, "TEST-PB43-T7": 7, "TEST-PB43-T14": 14}
SHOWN = 10
NONE = "NONE"


@dataclass(frozen=True)
class BatchCase:
    """One dataset batch: its known expiry offset and the result it must get."""

    batch_id: str
    sku: str
    category: str
    threshold: int
    days_left: int
    expected: str


@dataclass(frozen=True)
class Accuracy:
    """The EXP43-2 and EXP43-3 counts for one run."""

    correct: int = 0
    missed: int = 0
    false: int = 0
    problems: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.correct + self.missed + self.false

    @property
    def share(self) -> float:
        """Correctly flagged batches as a share of the dataset, in percent."""
        return round(100.0 * self.correct / self.total, 2) if self.total else 100.0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Measure how accurately the near-expiry job flags batches (PB-43).")
    parser.add_argument("--db", default="RTS_DB_TEST",
                        help="database to load the dataset into (default RTS_DB_TEST)")
    parser.add_argument("--cleanup", action="store_true",
                        help="delete the dataset store again after the measurement")
    args = parser.parse_args(argv)
    if not re.fullmatch(r"[A-Za-z0-9_]{1,64}", args.db):
        parser.error(f"'{args.db}' is not a plain database name")
    if not allowed_database(args.db):
        parser.error(
            f"refusing {args.db}: the measurement writes rows, so it only runs on "
            f"{DEMO_DATABASE} or a database whose name ends in _TEST")
    return args


def allowed_database(name: str) -> bool:
    """True for the two databases DS-09 allows the measurement to write.

    The demo database is the one the project resets before a demo, and any
    name ending in ``_TEST`` is a test database a reviewer may create. Every
    other database, the development one included, is refused.
    """
    return name.upper() == DEMO_DATABASE or name.upper().endswith("_TEST")


def expected_alert(days_left: int, threshold: int) -> str:
    """The result the daily check must produce, from DS-09 section 6.

    ``days_left < 0`` is EXPIRED whatever the threshold is, ``0 <= days_left
    <= threshold`` is NEAR_EXPIRY, and a batch with more days left gets none.
    """
    if days_left < 0:
        return "EXPIRED"
    if days_left <= threshold:
        return "NEAR_EXPIRY"
    return NONE


def build_dataset(thresholds: dict[str, int]) -> list[BatchCase]:
    """One batch in every band around every threshold, each with its expectation.

    The bands are ``threshold + 2``, ``threshold + 1``, ``threshold``,
    ``threshold - 1``, ``1``, ``0``, ``-1`` and ``-3`` days left, deduplicated
    for small thresholds, so every threshold is probed just above it, at it,
    just below it, on the last sellable day and after expiry.
    """
    cases: list[BatchCase] = []
    for category, threshold in sorted(thresholds.items(), key=lambda item: (item[1], item[0])):
        offsets = list(dict.fromkeys(
            [threshold + 2, threshold + 1, threshold, threshold - 1, 1, 0, -1, -3]))
        for offset in offsets:
            index = len(cases)
            cases.append(BatchCase(
                batch_id=f"{BATCH_PREFIX}{index:02d}",
                sku=f"{SKU_PREFIX}{index:02d}",
                category=category,
                threshold=threshold,
                days_left=offset,
                expected=expected_alert(offset, threshold),
            ))
    return cases


def count_results(cases: list[BatchCase],
                  actual: dict[str, str | None]) -> Accuracy:
    """Compare every batch's expectation with the alert the job left behind.

    ``actual`` maps a batch id to the type of its OPEN alert, or to None when
    the batch has no OPEN alert. A wrong alert type counts as missed, and the
    problem line says what the job produced instead.
    """
    correct = missed = false = 0
    problems: list[str] = []
    for case in cases:
        found = actual.get(case.batch_id)
        if case.expected == NONE:
            if found is None:
                correct += 1
            else:
                false += 1
                problems.append(
                    f"{case.batch_id} ({case.category}, {case.days_left} day(s) left): "
                    f"expected no alert, got {found}")
        elif found == case.expected:
            correct += 1
        else:
            missed += 1
            problems.append(
                f"{case.batch_id} ({case.category}, {case.days_left} day(s) left): "
                f"expected {case.expected}, got {found or 'no alert'}")
    return Accuracy(correct=correct, missed=missed, false=false, problems=problems)


def reset_dataset(session: Session) -> None:
    """Delete the rows of a previous run, children before parents.

    A recommendation of a previous run may still reference the store's alerts
    and batches (migration 003), so its results, decisions and rows go first.
    """
    if session.execute(text("SELECT OBJECT_ID('dbo.recommendation')")).scalar_one():
        for table in ("guardrail_result", "staff_decision"):
            session.execute(text(
                f"DELETE FROM dbo.{table} WHERE rec_id IN "
                "(SELECT rec_id FROM dbo.recommendation WHERE store_id = :store)"),
                {"store": STORE_ID})
        session.execute(text(
            "DELETE FROM dbo.recommendation WHERE store_id = :store"), {"store": STORE_ID})
    session.query(NearExpiryAlert).filter(NearExpiryAlert.store_id == STORE_ID) \
        .delete(synchronize_session=False)
    session.query(ProductBatch).filter(ProductBatch.store_id == STORE_ID) \
        .delete(synchronize_session=False)
    session.query(Inventory).filter(Inventory.store_id == STORE_ID) \
        .delete(synchronize_session=False)
    session.query(Product).filter(Product.sku.like(SKU_PREFIX + "%")) \
        .delete(synchronize_session=False)
    session.query(NearExpiryConfig) \
        .filter(NearExpiryConfig.category.like(CATEGORY_PREFIX + "%")) \
        .delete(synchronize_session=False)
    session.query(Store).filter(Store.store_id == STORE_ID) \
        .delete(synchronize_session=False)
    session.flush()


def load_dataset(session: Session, today: date) -> list[BatchCase]:
    """Create the store, the batches and the thresholds, and return the cases.

    Every batch keeps a quantity above zero, so the job sees it; a batch whose
    quantity reached zero is left out by design (PB-21). The thresholds of the
    script's own categories are written so the bands sit around known windows.

    Only ``THRESHOLDS`` is written as ``near_expiry_config`` rows. The DEFAULT
    category deliberately gets none, so its batches exercise the fallback to
    ``NEAR_EXPIRY_DEFAULT_DAYS`` -- the branch audit #11b found untested. The
    dataset still contains the DEFAULT category, because ``build_dataset`` takes
    it from the merged dictionary ``covered`` below.
    """
    covered = dict(THRESHOLDS)
    covered[f"{CATEGORY_PREFIX}DEFAULT"] = settings.near_expiry_default_days
    cases = build_dataset(covered)
    session.add(Store(store_id=STORE_ID, name="Near-expiry accuracy store",
                      latitude=Decimal("16.067800"), longitude=Decimal("108.220800"),
                      region_id="TEST"))
    # The models declare no relationships, so a flush cannot order products
    # before the rows that reference them: insert one level at a time.
    for case in cases:
        session.add(Product(sku=case.sku, barcode=f"BC-{case.sku}",
                            name=f"Accuracy batch {case.days_left:+d}d",
                            category=case.category, unit_price=Decimal("10.00")))
    session.flush()
    for case in cases:
        session.add(ProductBatch(batch_id=case.batch_id, sku=case.sku,
                                 store_id=STORE_ID,
                                 expiry_date=today + timedelta(days=case.days_left),
                                 quantity=5))
        session.add(Inventory(store_id=STORE_ID, sku=case.sku, quantity=5))
    for category, threshold in THRESHOLDS.items():
        session.add(NearExpiryConfig(category=category, threshold_days=threshold))
    session.flush()
    return cases


def run_job(engine, today: date) -> dict:
    """Run the daily check for the dataset's store and commit it, as the job does.

    ``run_near_expiry_check`` checks every store of the database; the
    measurement runs only the per-store unit of that job -- read the
    thresholds, ``check_store``, commit -- for ``TEST-PB43``, so the run
    leaves no alerts on any other store of the database.
    """
    factory = sessionmaker(class_=Session, bind=engine)
    with factory() as session:
        thresholds = {config.category: config.threshold_days
                      for config in session.query(NearExpiryConfig)}
        result = near_expiry_service.check_store(
            session, STORE_ID, today, thresholds, settings.near_expiry_default_days)
        session.commit()
        return result.__dict__


def read_actual(session: Session, cases: list[BatchCase]) -> dict[str, str | None]:
    """Batch id to the type of its OPEN alert, None where there is none."""
    actual: dict[str, str | None] = {case.batch_id: None for case in cases}
    alerts = session.query(NearExpiryAlert) \
        .filter(NearExpiryAlert.store_id == STORE_ID).all()
    for alert in alerts:
        if alert.status == "OPEN":
            actual[alert.batch_id] = alert.alert_type
    return actual


def print_report(cases: list[BatchCase], actual: dict[str, str | None],
                 accuracy: Accuracy) -> None:
    by_category: dict[str, Accuracy] = defaultdict(Accuracy)
    for case in cases:
        bucket = count_results([case], {case.batch_id: actual.get(case.batch_id)})
        previous = by_category[case.category]
        by_category[case.category] = Accuracy(
            correct=previous.correct + bucket.correct,
            missed=previous.missed + bucket.missed,
            false=previous.false + bucket.false,
        )
    for category in sorted(by_category):
        result = by_category[category]
        threshold = next(case.threshold for case in cases if case.category == category)
        print(f"  {category} (threshold {threshold}): {result.correct} correct, "
              f"{result.missed} missed, {result.false} false of {result.total}")
    print(f"TOTAL: {accuracy.correct} correct, {accuracy.missed} missed, "
          f"{accuracy.false} false of {accuracy.total} batches "
          f"({accuracy.share}% correct)")
    for problem in accuracy.problems[:SHOWN]:
        print(f"    {problem}")
    if len(accuracy.problems) > SHOWN:
        print(f"    ... {len(accuracy.problems) - SHOWN} more")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    today = clock.today_local()
    print(f"Near-expiry accuracy on {args.db}, business date {today.isoformat()}")
    engine = create_engine(database_url(args.db), hide_parameters=True)
    with Session(engine) as session:
        reset_dataset(session)
        cases = load_dataset(session, today)
        session.commit()
    run_job(engine, today)
    with Session(engine) as session:
        actual = read_actual(session, cases)
    accuracy = count_results(cases, actual)
    print_report(cases, actual, accuracy)
    if args.cleanup:
        with Session(engine) as session:
            reset_dataset(session)
            session.commit()
        print(f"Cleaned up store {STORE_ID}")
    print("NEAR-EXPIRY ACCURACY PASS" if not accuracy.problems
          else "NEAR-EXPIRY ACCURACY FAIL")
    return 0 if not accuracy.problems else 1


if __name__ == "__main__":
    sys.exit(main())
