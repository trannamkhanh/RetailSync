from datetime import date

import pytest

from app.repositories.forecast import Demand
from app.services.forecast import evaluate
from app.services.forecast_metrics import mae, wape


def test_exp24_1_holdout_demand_never_changes_predictions():
    training = tuple(range(42))
    original = Demand("TEST-STORE", "TEST-SKU", "TEST", 10, date(2026, 8, 1), training + (1,) * 14)
    changed = Demand("TEST-STORE", "TEST-SKU", "TEST", 10, original.start, training + (99,) * 14)
    predictions, fitted = evaluate([original])
    assert fitted
    assert predictions == evaluate([changed])[0]
    assert all(len(rows[0]) == 14 for rows in predictions.values())


def test_exp24_2_metrics_match_hand_calculation():
    assert mae([2, 0, 6], [3, 2, 5]) == pytest.approx(4 / 3)
    assert wape([2, 0, 6], [3, 2, 5]) == 0.5
    assert wape([0, 0], [1, 2]) is None
