"""Audit minor (POS/API group): scripts/metrics/cross_test_totals.py reports Re-test Status too.

The workbook has two count rows per sheet: ``Status`` (what the first pass did)
and ``Re-test Status`` (what the second pass did). The script read both but only
printed and summed ``Status``, so a case that failed once and passed on the
re-test still counted as a failure in the report, and the re-test row was
invisible.

These tests build a tiny workbook with openpyxl instead of reading the real one,
so the numbers are known and the file never has to be present.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = (Path(__file__).resolve().parents[2] / "scripts" / "metrics"
          / "cross_test_totals.py")


@pytest.fixture(scope="module")
def metrics():
    pytest.importorskip("openpyxl")
    if not SCRIPT.exists():
        pytest.skip("scripts/ is not mounted; run from the repository root mount.")
    spec = importlib.util.spec_from_file_location("cross_test_totals", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_workbook(openpyxl, path: Path, sheets: dict[str, tuple[tuple, tuple | None]]) -> Path:
    """A cases workbook in the same shape as GROUP_08_Test case.xlsx.

    Per sheet: a few header rows, then a ``Status`` label row, then its numbers
    one row below starting in column C, then the same for ``Re-test Status``.
    That two-row shape is what ``_status_row`` reads, so the fixture must use it.
    The counts are (total, pass, fail, not implemented, skipped).
    """
    header = ("TOTAL", "PASS", "FAIL", "Not Implemented", "SKIPPED")
    workbook = openpyxl.Workbook()
    workbook.remove(workbook.active)
    for title, (status, retest) in sheets.items():
        sheet = workbook.create_sheet(title)
        sheet.append(["Module", None, "Platform & Security"])
        sheet.append(["Code", None, "PS00"])
        sheet.append(["Tester", None, "Cross tester"])
        sheet.append(["Status", None, *header])
        sheet.append([None, None, *status])
        if retest is not None:
            sheet.append(["Re-test Status", None, *header])
            sheet.append([None, None, *retest])
    workbook.save(path)
    return path


@pytest.fixture
def cases(tmp_path, metrics):
    openpyxl = pytest.importorskip("openpyxl")
    # PB-10 failed once and passed on the re-test; PB-20 still fails.
    return make_workbook(openpyxl, tmp_path / "cases.xlsx", {
        "PB-10 auth": ((10, 8, 2, 0, 0), (10, 10, 0, 0, 0)),
        "PB-20 stock": ((6, 4, 2, 0, 0), None),
    })


def sprint_backlog(tmp_path, openpyxl) -> Path:
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Sprint 3 Backlog"
    sheet.append(["ID", "Item"])
    sheet.append(["PB-10", "Auth"])
    workbook.save(tmp_path / "backlog.xlsx")
    return tmp_path / "backlog.xlsx"


def test_audit_minor_the_retest_row_is_printed(metrics, cases, tmp_path, capsys):
    openpyxl = pytest.importorskip("openpyxl")
    backlog = sprint_backlog(tmp_path, openpyxl)
    assert metrics.main(["--cases", str(cases), "--backlog", str(backlog)]) == 0

    printed = capsys.readouterr().out
    assert "PB-10 (Sprint 3, tester Cross tester): 8 pass, 2 fail, 0 not implemented, 0 skipped of 10" in printed
    assert "    Re-test Status: 10 pass, 0 fail, 0 not implemented, 0 skipped of 10" in printed
    assert "PB-20 (unknown, tester Cross tester): 4 pass, 2 fail" in printed


def test_audit_minor_the_retest_row_is_counted_in_the_summary(metrics, cases, tmp_path, capsys):
    openpyxl = pytest.importorskip("openpyxl")
    backlog = sprint_backlog(tmp_path, openpyxl)
    metrics.main(["--cases", str(cases), "--backlog", str(backlog)])

    printed = capsys.readouterr().out
    assert "  Re-test Status: 10 pass, 0 fail, 0 not implemented, 0 skipped of 10" in printed
    assert "Re-test Status across 1 sheet(s): 10 pass, 0 fail, 0 not implemented, 0 skipped of 10" in printed


def test_audit_minor_a_sheet_without_a_retest_row_is_still_fine(metrics, tmp_path, capsys):
    openpyxl = pytest.importorskip("openpyxl")
    path = make_workbook(openpyxl, tmp_path / "cases.xlsx", {
        "PB-30 alerts": ((5, 5, 0, 0, 0), None),
    })
    backlog = sprint_backlog(tmp_path, openpyxl)

    assert metrics.main(["--cases", str(path), "--backlog", str(backlog)]) == 0
    printed = capsys.readouterr().out
    assert "PB-30 (unknown, tester Cross tester): 5 pass, 0 fail" in printed
    # One sheet has a Re-test row (PB-10 is not in this workbook), so no total.
    assert "No sheet has a Re-test Status row yet." in printed


def test_audit_minor_a_failed_retest_still_counts_as_a_failed_sheet(metrics, tmp_path, capsys):
    openpyxl = pytest.importorskip("openpyxl")
    path = make_workbook(openpyxl, tmp_path / "cases.xlsx", {
        "PB-40 sync": ((4, 4, 0, 0, 0), (4, 2, 2, 0, 0)),
    })
    backlog = sprint_backlog(tmp_path, openpyxl)

    metrics.main(["--cases", str(path), "--backlog", str(backlog)])
    printed = capsys.readouterr().out
    assert "Sheets with failed cases (a GitHub issue each):" in printed
    assert "  PB-40 sync" in printed


def test_audit_minor_a_sheet_that_passed_its_retest_is_not_listed_as_failed(
        metrics, cases, tmp_path, capsys):
    """The reviewer's finding: PB-10 failed once and passed the re-test.

    ``Re-test Status`` is the later run, so it decides. Counting a sheet as
    outstanding because its *first* pass had failures asks for a GitHub issue
    that nobody should open (review of PR #78).
    """
    openpyxl = pytest.importorskip("openpyxl")
    backlog = sprint_backlog(tmp_path, openpyxl)

    metrics.main(["--cases", str(cases), "--backlog", str(backlog)])
    printed = capsys.readouterr().out

    assert "PB-10 (Sprint 3, tester Cross tester): 8 pass, 2 fail" in printed
    assert "    Re-test Status: 10 pass, 0 fail" in printed
    # PB-20 has no re-test row and still fails, so it is the only outstanding one.
    assert "Sheets with failed cases (a GitHub issue each):" in printed
    assert "  PB-20 stock" in printed
    assert "  PB-10 auth" not in printed


def test_audit_minor_the_failed_list_comes_from_the_latest_count_row(metrics, tmp_path, capsys):
    """``failed_sheets`` picks the re-test row when there is one."""
    openpyxl = pytest.importorskip("openpyxl")
    path = make_workbook(openpyxl, tmp_path / "cases.xlsx", {
        "PB-50 fixed": ((3, 1, 2, 0, 0), (3, 3, 0, 0, 0)),
        "PB-51 broken": ((3, 3, 0, 0, 0), (3, 1, 2, 0, 0)),
        "PB-52 no retest": ((3, 2, 1, 0, 0), None),
        "PB-53 clean": ((3, 3, 0, 0, 0), (3, 3, 0, 0, 0)),
    })
    backlog = sprint_backlog(tmp_path, openpyxl)

    metrics.main(["--cases", str(path), "--backlog", str(backlog)])
    printed = capsys.readouterr().out

    listed = [line.strip() for line in printed.splitlines() if line.startswith("  PB-")]
    assert listed == ["PB-51 broken", "PB-52 no retest"]
