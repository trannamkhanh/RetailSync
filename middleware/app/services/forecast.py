"""Global HGB and seasonal-naive demand forecasts with recursive prediction."""

from collections.abc import Sequence
from datetime import date, timedelta
import logging
from statistics import mean

from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.feature_extraction import DictVectorizer
from threadpoolctl import threadpool_limits

from app.repositories.forecast import Demand
from app.services.forecast_metrics import wape


HORIZON = 7
HOLDOUT = 14
MIN_HISTORY = 28
SEED = 42
HGB = "hgb-v1"
NAIVE = "seasonal-naive-v1"
logger = logging.getLogger(__name__)


def eligible_demand(series: list[Demand]) -> list[Demand]:
    eligible = []
    for demand in series:
        if len(demand.values) < MIN_HISTORY:
            logger.info("Skipping forecast for %s/%s with %s days of history",
                        demand.store, demand.sku, len(demand.values))
        else:
            eligible.append(demand)
    return eligible


def _features(demand: Demand, day: date, history: Sequence[float]) -> dict[str, float | str]:
    return {
        "weekday": day.weekday(), "weekend": int(day.weekday() >= 5), "month_day": day.day,
        "lag_1": history[-1], "lag_7": history[-7], "lag_14": history[-14],
        "mean_7": mean(history[-7:]), "mean_28": sum(history[-28:]) / 28,
        "store": demand.store, "sku": demand.sku, "category": demand.category,
        "price": demand.unit_price,
    }


class Models:
    def __init__(self, series: list[Demand], holdout: int = 0) -> None:
        features, targets = [], []
        for demand in series:
            stop = len(demand.values) - holdout
            for index in range(14, stop):
                features.append(_features(demand, demand.start + timedelta(days=index),
                                          demand.values[max(0, index - 28):index]))
                targets.append(demand.values[index])
        self.encoder = DictVectorizer(sparse=False)
        self.hgb = None
        if targets:
            self.hgb = HistGradientBoostingRegressor(random_state=SEED)
            with threadpool_limits(limits=1):
                self.hgb.fit(self.encoder.fit_transform(features), targets)

    def predict(self, series: list[Demand], steps: int, *, holdout: int = 0,
                model: str = NAIVE) -> list[list[float]]:
        histories = [list(demand.values[:len(demand.values) - holdout]) for demand in series]
        if not histories:
            return []
        forecasts = [[] for _ in histories]
        with threadpool_limits(limits=1):
            for _ in range(steps):
                if model == HGB and self.hgb is not None:
                    rows = [_features(demand, demand.start + timedelta(days=len(history)), history)
                            for demand, history in zip(series, histories, strict=True)]
                    predictions = self.hgb.predict(self.encoder.transform(rows))
                else:
                    predictions = [history[-7] for history in histories]
                for history, forecast, prediction in zip(histories, forecasts, predictions, strict=True):
                    value = max(0.0, float(prediction))
                    history.append(value)
                    forecast.append(value)
        return forecasts


def evaluate(series: list[Demand]) -> tuple[dict[str, list[list[float]]], bool]:
    models = Models(series, holdout=HOLDOUT)
    return {
        name: models.predict(series, HOLDOUT, holdout=HOLDOUT, model=name)
        for name in (NAIVE, HGB)
    }, models.hgb is not None


def predict_demand(series: list[Demand]) -> tuple[str, list[int]]:
    if not series:
        return NAIVE, []
    predictions, fitted = evaluate(series)
    actual = [value for demand in series for value in demand.values[-HOLDOUT:]]
    scores = {name: wape(actual, [value for row in rows for value in row])
              for name, rows in predictions.items()}
    hgb, naive = scores[HGB], scores[NAIVE]
    chosen = HGB if fitted and hgb is not None and naive is not None and hgb < naive else NAIVE
    models = Models(series if chosen == HGB else [])
    return chosen, [round(sum(values)) for values in models.predict(series, HORIZON, model=chosen)]
