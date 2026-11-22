"""Audit #11b: the accuracy script exercises the DEFAULT-category fallback.

``scripts/metrics/near_expiry_accuracy.py`` builds its dataset from
``THRESHOLDS`` plus one category without a config row, so the run covers both a
configured window and ``NEAR_EXPIRY_DEFAULT_DAYS``. ``load_dataset`` then wrote a
``near_expiry_config`` row for every entry of that merged dictionary, DEFAULT
included, so the fallback branch was never taken and the run silently measured
the default window as if it were configured.

These tests drive ``load_dataset`` and ``run_job`` against the real test database
with the script's own ``TEST-PB43`` ids, then delete the rows again, so the
suite leaves the database as it found it. They need no live accuracy run.
"""

from __future__ import annotations

import importlib.util
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings

SCRIPT = (Path(__file__).resolve().parents[2] / "scripts" / "metrics"
          / "near_expiry_accuracy.py")
TODAY = date(2026, 11, 14)
FALLBACK_CATEGORY = "TEST-PB43-DEFAULT"


@pytest.fixture(scope="module")
def metrics():
    if not SCRIPT.exists():
        pytest.skip("scripts/ is not mounted; run from the repository root mount.")
    spec = importlib.util.spec_from_file_location("near_expiry_accuracy", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def dataset(metrics, test_engine):
    """The script's store loaded and committed, then removed again."""
    with Session(test_engine) as session:
        metrics.reset_dataset(session)
        cases = metrics.load_dataset(session, TODAY)
        session.commit()
    try:
        yield cases
    finally:
        with Session(test_engine) as session:
            metrics.reset_dataset(session)
            session.commit()


def config_categories(engine) -> set[str]:
    with Session(engine) as session:
        return {row[0] for row in session.execute(
            text("SELECT category FROM dbo.near_expiry_config"))}


def test_audit11b_no_config_row_is_written_for_the_fallback_category(
        metrics, test_engine, dataset):
    categories = config_categories(test_engine)

    assert FALLBACK_CATEGORY not in categories
    # The categories the script does configure are all there.
    assert set(metrics.THRESHOLDS) <= categories


def test_audit11b_the_dataset_still_covers_the_fallback_category(metrics, dataset):
    fallback_cases = [case for case in dataset if case.category == FALLBACK_CATEGORY]

    assert fallback_cases, "the dataset must keep a category without a config row"
    assert {case.threshold for case in fallback_cases} == {settings.near_expiry_default_days}


def test_audit11b_the_fallback_band_is_judged_with_the_default_window(
        metrics, test_engine, dataset):
    """The job, run on the loaded dataset, still makes the DEFAULT bands right."""
    metrics.run_job(test_engine, TODAY)
    with Session(test_engine) as session:
        actual = metrics.read_actual(session, dataset)
    accuracy = metrics.count_results(dataset, actual)

    assert accuracy.problems == [], accuracy.problems[:5]


def test_audit11b_a_configured_category_keeps_using_its_own_threshold(
        metrics, test_engine, dataset):
    """The fallback fix must not move the configured categories to the default."""
    fallback_days = settings.near_expiry_default_days
    # T3 may equal the default window; a wider configured category cannot.
    widest = max(metrics.THRESHOLDS.values())
    configured = next(case for case in dataset
                      if case.category in metrics.THRESHOLDS and case.threshold == widest)
    assert configured.threshold != fallback_days

    metrics.run_job(test_engine, TODAY)
    with Session(test_engine) as session:
        actual = metrics.read_actual(session, dataset)

    accuracy = metrics.count_results(dataset, actual)
    assert all(configured.category not in problem for problem in accuracy.problems)
