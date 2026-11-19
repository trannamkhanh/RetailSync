"""scripts/metrics/near_expiry_accuracy.py (PB-43, EXP43-1 to EXP43-3).

The measurement itself runs live against RTS_DB_TEST or RTS_DB_DEMO; these
tests check the dataset and the counting on known inputs, so a wrong count
cannot hide behind a database.
"""

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "metrics" / "near_expiry_accuracy.py"


@pytest.fixture(scope="module")
def metrics():
    if not SCRIPT.exists():
        pytest.skip("scripts/ is not mounted; run from the repository root mount.")
    spec = importlib.util.spec_from_file_location("near_expiry_accuracy", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# EXP43-1


def test_exp43_1_every_batch_in_the_dataset_has_a_known_expected_result(metrics):
    cases = metrics.build_dataset({"TEST-PB43-T3": 3, "TEST-PB43-T7": 7, "TEST-PB43-T14": 14})

    assert cases
    for case in cases:
        assert case.expected in {"NEAR_EXPIRY", "EXPIRED", metrics.NONE}
        assert case.expected == metrics.expected_alert(case.days_left, case.threshold)


def test_exp43_1_the_dataset_probes_every_band_around_every_threshold(metrics):
    cases = metrics.build_dataset({"TEST-PB43-T3": 3, "TEST-PB43-T7": 7, "TEST-PB43-T14": 14})

    for threshold in (3, 7, 14):
        offsets = {case.days_left for case in cases if case.threshold == threshold}
        # just above the threshold, at it, just below it, the last sellable
        # day, and two days after expiry
        assert {threshold + 1, threshold, threshold - 1, 0, -1} <= offsets
        assert all(case.expected == metrics.NONE for case in cases
                   if case.days_left == threshold + 1)
        assert all(case.expected == "NEAR_EXPIRY" for case in cases
                   if case.days_left in {threshold, 0})
        assert all(case.expected == "EXPIRED" for case in cases if case.days_left < 0)


def test_exp43_1_a_threshold_of_zero_still_produces_distinct_bands(metrics):
    cases = metrics.build_dataset({"TEST-PB43-T0": 0})

    offsets = [case.days_left for case in cases]
    assert len(offsets) == len(set(offsets))
    assert set(offsets) == {2, 1, 0, -1, -3}


# EXP43-2


def test_exp43_2_correct_flags_are_counted_as_a_share(metrics):
    cases = metrics.build_dataset({"TEST-PB43-T3": 3})
    actual = {case.batch_id: (None if case.expected == metrics.NONE else case.expected)
              for case in cases}

    result = metrics.count_results(cases, actual)

    assert result.correct == len(cases)
    assert result.missed == 0 and result.false == 0
    assert result.share == 100.0

    first_alert = next(case for case in cases if case.expected != metrics.NONE)
    actual[first_alert.batch_id] = None

    result = metrics.count_results(cases, actual)

    assert result.correct == len(cases) - 1
    assert result.share == round(100.0 * (len(cases) - 1) / len(cases), 2)


# EXP43-3


def test_exp43_3_missed_alerts_are_counted(metrics):
    cases = metrics.build_dataset({"TEST-PB43-T3": 3})
    expected_alerts = [case for case in cases if case.expected != metrics.NONE]
    quiet = [case for case in cases if case.expected == metrics.NONE]

    result = metrics.count_results(cases, {case.batch_id: None for case in cases})

    assert result.missed == len(expected_alerts)
    assert result.correct == len(quiet)
    assert result.false == 0


def test_exp43_3_false_alerts_are_counted(metrics):
    cases = metrics.build_dataset({"TEST-PB43-T3": 3})
    quiet = next(case for case in cases if case.expected == metrics.NONE)

    actual = {case.batch_id: None for case in cases}
    actual[quiet.batch_id] = "NEAR_EXPIRY"

    result = metrics.count_results(cases, actual)

    assert result.false == 1
    assert any(quiet.batch_id in problem for problem in result.problems)


def test_exp43_3_a_wrong_alert_type_counts_as_missed(metrics):
    cases = metrics.build_dataset({"TEST-PB43-T3": 3})
    near = next(case for case in cases if case.expected == "NEAR_EXPIRY")

    actual = {case.batch_id: (None if case.expected == metrics.NONE else case.expected)
              for case in cases}
    actual[near.batch_id] = "EXPIRED"

    result = metrics.count_results(cases, actual)

    assert result.missed == 1
    assert result.false == 0
    assert any(near.batch_id in problem and "EXPIRED" in problem
               for problem in result.problems)


# PB-43 cases without a sheet id


def test_pb43_the_script_refuses_the_development_database(metrics, capsys):
    with pytest.raises(SystemExit) as stopped:
        metrics.parse_args(["--db", "RTS_DB"])

    assert stopped.value.code == 2
    assert "refusing RTS_DB" in capsys.readouterr().err


@pytest.mark.parametrize("name", ["RTS_HQ", "master", "msdb", "RTS_DB_TEST2", "tempdb"])
def test_pb43_the_script_refuses_any_database_outside_the_allowlist(metrics, name, capsys):
    """Only RTS_DB_DEMO and names ending in _TEST may be written."""
    with pytest.raises(SystemExit) as stopped:
        metrics.parse_args(["--db", name])

    assert stopped.value.code == 2
    assert f"refusing {name}" in capsys.readouterr().err


@pytest.mark.parametrize("name", ["RTS_DB_DEMO", "rts_db_demo", "RTS_DB_TEST",
                                  "RTS_DB_TEST", "PB43_TEST", "reviewer_test_tmp_TEST"])
def test_pb43_the_allowlist_takes_the_demo_and_any_test_database(metrics, name):
    assert metrics.parse_args(["--db", name]).db == name
    assert metrics.allowed_database(name)


def test_pb43_the_allowlist_refuses_the_development_database(metrics):
    assert not metrics.allowed_database("RTS_DB")
    assert not metrics.allowed_database("RTS_HQ")


def test_pb43_cleanup_removes_the_dataset_store_again(metrics, capsys):
    args = metrics.parse_args(["--db", "RTS_DB_TEST", "--cleanup"])

    assert args.cleanup is True
    assert metrics.parse_args(["--db", "RTS_DB_TEST"]).cleanup is False


def test_pb43_the_script_defaults_to_the_test_database(metrics):
    assert metrics.parse_args([]).db == "RTS_DB_TEST"
