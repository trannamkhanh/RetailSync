"""Cross-test totals from the test case workbook (Phase 7, item 4).

Reads every ``PB-*`` sheet of ``GROUP_08_Test case.xlsx``, takes the Status and
Re-test Status counts (TOTAL, PASS, FAIL, Not Implemented, SKIPPED) that the
four cross-testers fill in, maps each sheet to its sprint through the sprint
backlog of ``C1SE_24_RetailSync_Sprint_Backlog_v1.4.xlsx``, and prints the
totals per sprint and per backlog item for the report. Since audit #5 the
Re-test Status row is printed and counted too: a case that failed and was then
fixed shows a FAIL under Status and a PASS under Re-test Status, and a report
that only counted Status would still call it a failure.

Sheets with a FAIL count in Status or in Re-test Status are listed, because
every failed case needs a GitHub issue.

Run it with any Python that has openpyxl (``pip install openpyxl``), from the
repository root:

    python scripts/metrics/cross_test_totals.py
"""

import argparse
import re
from pathlib import Path
import sys

from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CASES = ROOT / "docs" / "document" / "GROUP_08_Test case.xlsx"
DEFAULT_BACKLOG = ROOT / "docs" / "document" / "C1SE_24_RetailSync_Sprint_Backlog_v1.4.xlsx"
COLUMNS = ("total", "pass", "fail", "not_implemented", "skipped")
SHEET_ID = re.compile(r"^(PB-\d+)")
BACKLOG_ID = re.compile(r"^(PB-\d+)")
COUNT_ROW_OFFSET = 1
STATUS = "Status"
RETEST = "Re-test Status"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Totals per sprint and per backlog item from the test case workbook.")
    parser.add_argument("--cases", default=str(DEFAULT_CASES),
                        help="path of GROUP_08_Test case.xlsx")
    parser.add_argument("--backlog", default=str(DEFAULT_BACKLOG),
                        help="path of the sprint backlog workbook")
    return parser.parse_args(argv)


def _status_row(sheet, label: str) -> dict[str, int] | None:
    """The numbers under a ``Status`` or ``Re-test Status`` row, as a dict."""
    rows = list(sheet.iter_rows(values_only=True))
    for index, row in enumerate(rows):
        if row and str(row[0] or "").strip() == label:
            if index + COUNT_ROW_OFFSET < len(rows):
                numbers = rows[index + COUNT_ROW_OFFSET][2:7]
                return {name: int(number or 0)
                        for name, number in zip(COLUMNS, numbers, strict=True)}
    return None


def _tester(sheet) -> str:
    for row in sheet.iter_rows(values_only=True, max_row=6):
        if row and str(row[0] or "").strip() == "Tester":
            return str(row[2] or "").strip()
    return ""


def sprint_map(backlog_path: Path) -> dict[str, str]:
    """Backlog id prefix (``PB-34``) to the sprint whose backlog lists it."""
    workbook = load_workbook(backlog_path, read_only=True, data_only=True)
    mapping: dict[str, str] = {}
    try:
        for sheet in workbook.worksheets:
            match = re.fullmatch(r"Sprint (\d+) Backlog", sheet.title)
            if not match:
                continue
            for row in sheet.iter_rows(values_only=True):
                for cell in row:
                    hit = BACKLOG_ID.match(str(cell or "").strip())
                    if hit:
                        mapping.setdefault(hit.group(1), f"Sprint {match.group(1)}")
    finally:
        workbook.close()
    return mapping


def collect(cases_path: Path, sprints: dict[str, str]) -> list[dict]:
    workbook = load_workbook(cases_path, read_only=True, data_only=True)
    sheets: list[dict] = []
    try:
        for sheet in workbook.worksheets:
            hit = SHEET_ID.match(sheet.title)
            if not hit:
                continue
            status = _status_row(sheet, STATUS)
            if status is None:
                continue
            sheets.append({
                "sheet": sheet.title,
                "backlog": hit.group(1),
                "sprint": sprints.get(hit.group(1), "unknown"),
                "tester": _tester(sheet),
                "status": status,
                "retest": _status_row(sheet, RETEST),
            })
    finally:
        workbook.close()
    return sheets


def _sum(rows: list[dict | None]) -> dict[str, int]:
    total = dict.fromkeys(COLUMNS, 0)
    for row in rows:
        for name in COLUMNS:
            total[name] += (row or {}).get(name, 0)
    return total


def _line(label: str, counts: dict[str, int]) -> str:
    line = (f"{counts['pass']} pass, {counts['fail']} fail, "
            f"{counts['not_implemented']} not implemented, {counts['skipped']} skipped "
            f"of {counts['total']}")
    return f"{label}: {line}" if label else line


def _retest_line(label: str, counts: dict[str, int]) -> str:
    return f"{label}Re-test Status: {_line('', counts)}"


def print_report(sheets: list[dict]) -> None:
    per_sprint: dict[str, dict[str, int]] = {}
    per_sprint_retest: dict[str, dict[str, int]] = {}
    for item in sorted(sheets, key=lambda entry: (entry["sprint"], entry["backlog"])):
        label = f"{item['backlog']} ({item['sprint']}, tester {item['tester'] or '?'})"
        print(_line(label, item["status"]))
        if item["retest"] is not None:
            print(_retest_line("    ", item["retest"]))
        bucket = per_sprint.setdefault(item["sprint"], dict.fromkeys(COLUMNS, 0))
        for name in COLUMNS:
            bucket[name] += item["status"][name]
        if item["retest"] is not None:
            retest_bucket = per_sprint_retest.setdefault(
                item["sprint"], dict.fromkeys(COLUMNS, 0))
            for name in COLUMNS:
                retest_bucket[name] += item["retest"][name]
    print()
    for sprint in sorted(per_sprint):
        print(_line(sprint, per_sprint[sprint]))
        if sprint in per_sprint_retest:
            print(_retest_line("  ", per_sprint_retest[sprint]))

    with_retest = [item for item in sheets if item["retest"] is not None]
    print()
    if with_retest:
        print(_line(f"Re-test Status across {len(with_retest)} sheet(s)",
                    _sum([item["retest"] for item in with_retest])))
    else:
        print("No sheet has a Re-test Status row yet.")

    failed = [item["sheet"] for item in sheets
              if item["status"]["fail"] or (item["retest"] or {}).get("fail", 0)]
    print()
    if failed:
        print("Sheets with failed cases (a GitHub issue each):")
        for title in failed:
            print(f"  {title}")
    else:
        print("No failed cases.")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    sprints = sprint_map(Path(args.backlog))
    sheets = collect(Path(args.cases), sprints)
    if not sheets:
        print(f"No PB-* sheets with a Status row found in {args.cases}", file=sys.stderr)
        return 1
    print(f"Cross-test totals from {Path(args.cases).name}\n")
    print_report(sheets)
    return 0


if __name__ == "__main__":
    sys.exit(main())
