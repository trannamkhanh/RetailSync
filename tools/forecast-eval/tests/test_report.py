from datetime import date, timedelta

from app.repositories.forecast import Demand
from forecast_eval.__main__ import render_report


def test_exp24_3_report_lists_both_models_for_each_category():
    start = date(2026, 8, 1)
    series = [
        Demand("TEST-STORE", f"TEST-{category}", category, 10, start, (1, 2, 3, 4, 5, 6, 7) * 8)
        for category in ("Dairy", "Bakery")
    ]
    report = render_report(series, start + timedelta(days=56))
    for category in ("Dairy", "Bakery"):
        assert f"| {category} | hgb-v1 | 14 |" in report
        assert f"| {category} | seasonal-naive-v1 | 14 | 0.00 | 0.00% |" in report
    assert "2026-09-12" in report
