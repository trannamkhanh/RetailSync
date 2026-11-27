"""Read-only PB-44 guardrail and staff-decision rates on a demo/test database.

Run inside the middleware image: python scripts/metrics/guardrail_metrics.py
--db RTS_DB_DEMO. GENERATED rows have not completed guardrails and are excluded.
Rule rates count each recommendation once per rule type, taking its worst
recorded outcome when several rules of that type applied.
"""

import argparse
from collections import Counter, defaultdict
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "middleware"))

from sqlalchemy import create_engine, text  # noqa: E402

from app.core import clock  # noqa: E402
from app.core.db import database_url  # noqa: E402


RULES = ("MAX_DISCOUNT", "MIN_PRICE", "MIN_SHELF_LIFE")
ACTIONS = ("DISCOUNT", "CLEARANCE", "REDISTRIBUTION")
OUTCOMES = ("PASSED", "ADJUSTED", "BLOCKED")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="RTS_DB_DEMO")
    args = parser.parse_args(argv)
    if not re.fullmatch(r"[A-Za-z0-9_]{1,64}", args.db):
        parser.error("--db must be a plain database name")
    if args.db.upper() == "RTS_DB":
        parser.error("refusing RTS_DB; use RTS_DB_DEMO or a test database")
    return args


def collect(connection):
    recommendations = connection.execute(text(
        "SELECT rec_id, store_id, action_type, status FROM dbo.recommendation"
    )).mappings().all()
    results = connection.execute(text(
        "SELECT g.rec_id, r.rule_type, g.outcome FROM dbo.guardrail_result g "
        "JOIN dbo.guardrail_rule r ON r.rule_id = g.rule_id"
    )).all()
    decisions = dict(connection.execute(text(
        "SELECT rec_id, decision FROM dbo.staff_decision"
    )).all())
    stores = list(connection.execute(text("SELECT store_id FROM dbo.store ORDER BY store_id")).scalars())
    return summarize(recommendations, results, decisions, stores)


def summarize(recommendations, results, decisions, stores):
    guardrails = defaultdict(Counter)
    rules = defaultdict(Counter)
    acceptance = defaultdict(Counter)
    actions = defaultdict(Counter)
    per_rec = defaultdict(list)
    per_rule = {}
    for rec_id, rule_type, outcome in results:
        per_rec[rec_id].append(outcome)
        key = (rec_id, rule_type)
        if key not in per_rule or OUTCOMES.index(outcome) > OUTCOMES.index(per_rule[key]):
            per_rule[key] = outcome
    for row in recommendations:
        rec_id, store = row["rec_id"], row["store_id"]
        groups = (store, "TOTAL")
        if row["status"] != "GENERATED":
            outcome = ("BLOCKED" if row["status"] == "BLOCKED" else
                       "ADJUSTED" if "ADJUSTED" in per_rec[rec_id] else "PASSED")
            for group in groups:
                guardrails[group][outcome] += 1
            for rule in RULES:
                outcome_for_rule = per_rule.get((rec_id, rule))
                if outcome_for_rule:
                    for group in groups:
                        rules[group, rule][outcome_for_rule] += 1
        decision = decisions.get(rec_id)
        state = decision if decision else row["status"] if row["status"] in ("PENDING", "EXPIRED") else None
        if state:
            for group in groups:
                acceptance[group][state] += 1
                actions[group, row["action_type"]][state] += 1
    return stores, guardrails, rules, acceptance, actions


def rate(numerator, denominator):
    value = "n/a" if denominator == 0 else f"{100 * numerator / denominator:.2f}%"
    return f"{value} ({numerator}/{denominator})" + (" — small sample" if denominator < 10 else "")


def outcome_row(name, counts):
    total = sum(counts.values())
    return f"| {name} | {total} | " + " | ".join(rate(counts[outcome], total) for outcome in OUTCOMES) + " |"


def decision_row(name, counts):
    accepted, rejected = counts["ACCEPT"], counts["REJECT"]
    return (f"| {name} | {accepted} | {rejected} | {rate(accepted, accepted + rejected)} "
            f"| {counts['PENDING']} | {counts['EXPIRED']} |")


def report(data):
    stores, guardrails, rules, acceptance, actions = data
    groups = stores + ["TOTAL"]
    lines = ["## Guardrail outcomes", "", "| Store | Evaluated recommendations | PASSED | ADJUSTED | BLOCKED |",
             "|---|---:|---:|---:|---:|"]
    lines.extend(outcome_row(store, guardrails[store]) for store in groups)
    lines += ["", "## Outcomes per rule type", "",
              "| Store / rule type | Recommendations checked | PASSED | ADJUSTED | BLOCKED |",
              "|---|---:|---:|---:|---:|"]
    lines.extend(outcome_row(f"{store} / {rule}", rules[store, rule]) for store in groups for rule in RULES)
    header = ["| Store | ACCEPT | REJECT | Acceptance rate | PENDING without decision | EXPIRED without decision |",
              "|---|---:|---:|---:|---:|---:|"]
    lines += ["", "## Staff acceptance", "", *header]
    lines.extend(decision_row(store, acceptance[store]) for store in groups)
    lines += ["", "## Acceptance per action type", "",
              header[0].replace("| Store |", "| Store / action |"), header[1]]
    lines.extend(decision_row(f"{store} / {action}", actions[store, action])
                 for store in groups for action in ACTIONS)
    return "\n".join(lines)


def main(argv=None):
    args = parse_args(argv)
    engine = create_engine(database_url(args.db), hide_parameters=True)
    try:
        with engine.connect() as connection:
            data = collect(connection)
    finally:
        engine.dispose()
    print(f"Guardrail metrics for {args.db}; business date {clock.today_local()} (UTC+7)\n")
    print("GENERATED excluded. Recommendation precedence: BLOCKED, then ADJUSTED, else PASSED.")
    print("Rule-type rates use the worst result per recommendation/type; denominators may differ.")
    print("Acceptance uses staff_decision only; undecided PENDING/EXPIRED rows are separate.\n")
    print(report(data))
    return 0


if __name__ == "__main__":
    sys.exit(main())
