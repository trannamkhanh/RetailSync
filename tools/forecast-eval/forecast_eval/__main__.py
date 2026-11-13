"""Write the PB-24 comparison from a read-only demo history query."""

import argparse
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core import clock
from app.core.db import database_url
from app.repositories.forecast import Demand, load_demand
from app.services.forecast import HGB, HOLDOUT, NAIVE, SEED, eligible_demand, evaluate
from app.services.forecast_metrics import mae, wape


def render_report(series: list[Demand], end: date) -> str:
    series = eligible_demand(series)
    if not series:
        raise ValueError("Load at least 28 days of simulated demo history before evaluation.")
    predictions, fitted = evaluate(series)
    if not fitted:
        raise ValueError("Insufficient training observations after the holdout.")
    groups = defaultdict(list)
    for index, demand in enumerate(series):
        groups[demand.category].append(index)

    cutoff = end - timedelta(days=HOLDOUT)
    lines = [
        "# Forecast accuracy", "",
        f"Model seed `{SEED}`. Source is simulated `HIST-` transactions in `RTS_DB_DEMO`.",
        f"Data range {min(demand.start for demand in series)} through {end - timedelta(days=1)}.",
        f"Training ends before {cutoff}. The 14-day holdout starts on {cutoff}.",
        "Both models predict the holdout recursively using only training demand and earlier predictions.",
        "WAPE is unavailable where total actual demand is zero.", "",
        "| Category | Model | Observations | MAE (units) | WAPE |",
        "| --- | --- | ---: | ---: | ---: |",
    ]
    for category, indices in sorted(groups.items()):
        actual = [value for index in indices for value in series[index].values[-HOLDOUT:]]
        label = category.replace("|", r"\|").replace("\n", " ").replace("\r", "")
        for model in (HGB, NAIVE):
            predicted = [value for index in indices for value in predictions[model][index]]
            weighted_error = wape(actual, predicted)
            percentage = "N/A" if weighted_error is None else f"{weighted_error:.2%}"
            lines.append(f"| {label} | {model} | {len(actual)} | {mae(actual, predicted):.2f} | {percentage} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of", type=date.fromisoformat, help="Exclusive business date")
    parser.add_argument("--output", type=Path, default=Path("docs/reports/Forecast_Accuracy.md"))
    args = parser.parse_args()
    end = args.as_of or clock.today_local()
    engine = create_engine(database_url("RTS_DB_DEMO"), hide_parameters=True)
    try:
        with Session(engine) as session:
            report = render_report(load_demand(session, end, history_only=True), end)
    finally:
        engine.dispose()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report, encoding="utf-8")
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
