"""Demand forecast accuracy metrics."""

from collections.abc import Sequence


def _absolute_error(actual: Sequence[float], predicted: Sequence[float]) -> float:
    if not actual or len(actual) != len(predicted):
        raise ValueError("Expected equally sized, nonempty actual and predicted series.")
    return sum(abs(a - p) for a, p in zip(actual, predicted, strict=True))


def mae(actual: Sequence[float], predicted: Sequence[float]) -> float:
    return _absolute_error(actual, predicted) / len(actual)


def wape(actual: Sequence[float], predicted: Sequence[float]) -> float | None:
    error = _absolute_error(actual, predicted)
    total = sum(actual)
    return error / total if total else None
