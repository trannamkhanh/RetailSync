"""PB-44 metrics against fixed rows in the real, rollback-only test DB."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

from app.domain.models import GuardrailResult, GuardrailRule, Product, Recommendation, StaffDecision, StaffUser, Store
from tests.pos_test_support import uid


spec = spec_from_file_location("guardrail_metrics", Path(__file__).resolve().parents[2] /
                               "scripts/metrics/guardrail_metrics.py")
metrics = module_from_spec(spec)
spec.loader.exec_module(metrics)


@pytest.fixture
def fixed_rows(db_session):
    suffix = uid(5)
    store, sku = f"TEST-{suffix}", f"TEST-M-{suffix}"
    db_session.add(Store(store_id=store, name="Metrics", latitude=0, longitude=0, region_id="TEST"))
    db_session.add(Product(sku=sku, barcode=sku, name="Metrics", category="TEST", unit_price=1000))
    db_session.flush()
    user = StaffUser(username=sku, full_name="Metrics", role="STORE_STAFF", store_id=store)
    rules = [GuardrailRule(rule_type=kind, threshold=0, category="TEST", is_active=True)
             for kind in metrics.RULES]
    db_session.add_all([user, *rules])
    db_session.flush()

    def add(status, outcomes=(), decision=None, action="DISCOUNT", discount=0):
        row = Recommendation(store_id=store, sku=sku, action_type=action, status=status,
                             discount_pct=discount, reason="Fixed PB-44 row")
        db_session.add(row)
        db_session.flush()
        for rule_index, outcome in outcomes:
            db_session.add(GuardrailResult(rec_id=row.rec_id, rule_id=rules[rule_index].rule_id,
                                           outcome=outcome))
        if decision:
            db_session.add(StaffDecision(rec_id=row.rec_id, user_id=user.user_id, decision=decision))
        db_session.flush()
        return row

    return store, add


def test_pb44_each_outcome_and_generated_exclusion(db_session, fixed_rows):
    store, add = fixed_rows
    add("PENDING", [(0, "PASSED")])
    add("PENDING", [(0, "ADJUSTED"), (0, "PASSED")], discount=15)
    add("BLOCKED", [(0, "ADJUSTED"), (1, "BLOCKED")])
    add("GENERATED", [(0, "ADJUSTED")])
    _, outcomes, rules, _, _ = metrics.collect(db_session.connection())
    assert outcomes[store] == {"PASSED": 1, "ADJUSTED": 1, "BLOCKED": 1}
    assert rules[store, "MAX_DISCOUNT"] == {"PASSED": 1, "ADJUSTED": 2}
    assert rules[store, "MIN_PRICE"] == {"BLOCKED": 1}


def test_pb44_zero_percent_discount_is_still_blocked(db_session, fixed_rows):
    store, add = fixed_rows
    add("BLOCKED", [(0, "ADJUSTED"), (1, "BLOCKED")], discount=0)
    _, outcomes, _, _, _ = metrics.collect(db_session.connection())
    assert outcomes[store]["BLOCKED"] == 1
    assert outcomes[store]["ADJUSTED"] == 0


def test_pb44_acceptance_uses_decisions_not_pending_or_expired(db_session, fixed_rows):
    store, add = fixed_rows
    add("ACCEPTED", decision="ACCEPT")
    add("REJECTED", decision="REJECT", action="CLEARANCE")
    add("PENDING")
    add("EXPIRED")
    data = metrics.collect(db_session.connection())
    assert data[3][store] == {"ACCEPT": 1, "REJECT": 1, "PENDING": 1, "EXPIRED": 1}
    assert "50.00% (1/2)" in metrics.decision_row(store, data[3][store])
    assert data[4][store, "DISCOUNT"]["ACCEPT"] == 1
    assert data[4][store, "CLEARANCE"]["REJECT"] == 1


def test_pb44_no_decisions_is_na_and_small_sample(db_session, fixed_rows):
    store, add = fixed_rows
    add("PENDING")
    add("EXPIRED")
    data = metrics.collect(db_session.connection())
    assert "n/a (0/0) — small sample" in metrics.decision_row(store, data[3][store])
    assert metrics.rate(1, 10) == "10.00% (1/10)"
    assert "small sample" in metrics.rate(1, 9)


@pytest.mark.parametrize("database", ["RTS_DB", "rts_db", "bad-name;DROP", ""])
def test_pb44_refuses_development_and_invalid_database(database):
    with pytest.raises(SystemExit):
        metrics.parse_args(["--db", database])


def test_pb44_two_store_totals_and_report_tables():
    rows = [
        {"rec_id": 1, "store_id": "STORE-A", "action_type": "DISCOUNT", "status": "PENDING"},
        {"rec_id": 2, "store_id": "STORE-A", "action_type": "DISCOUNT", "status": "ACCEPTED"},
        {"rec_id": 3, "store_id": "STORE-B", "action_type": "CLEARANCE", "status": "BLOCKED"},
        {"rec_id": 4, "store_id": "STORE-B", "action_type": "DISCOUNT", "status": "REJECTED"},
        {"rec_id": 5, "store_id": "STORE-B", "action_type": "DISCOUNT", "status": "GENERATED"},
        {"rec_id": 6, "store_id": "STORE-B", "action_type": "REDISTRIBUTION", "status": "EXPIRED"},
    ]
    results = [
        (1, "MAX_DISCOUNT", "PASSED"),
        (2, "MAX_DISCOUNT", "PASSED"), (2, "MAX_DISCOUNT", "ADJUSTED"),
        (3, "MAX_DISCOUNT", "ADJUSTED"), (3, "MIN_SHELF_LIFE", "BLOCKED"),
        (4, "MAX_DISCOUNT", "PASSED"),
        (5, "MAX_DISCOUNT", "ADJUSTED"),
        (6, "MAX_DISCOUNT", "PASSED"),
    ]
    data = metrics.summarize(rows, results, {2: "ACCEPT", 4: "REJECT"}, ["STORE-A", "STORE-B"])
    assert data[1]["STORE-A"] == {"PASSED": 1, "ADJUSTED": 1}
    assert data[1]["STORE-B"] == {"PASSED": 2, "BLOCKED": 1}
    assert data[1]["TOTAL"] == {"PASSED": 3, "ADJUSTED": 1, "BLOCKED": 1}
    assert data[2]["TOTAL", "MAX_DISCOUNT"] == {"PASSED": 3, "ADJUSTED": 2}
    assert data[3]["TOTAL"] == {"ACCEPT": 1, "REJECT": 1, "PENDING": 1, "EXPIRED": 1}
    output = metrics.report(data)
    staff = output.split("## Staff acceptance\n", 1)[1].split("## Acceptance per action type", 1)[0]
    actions = output.split("## Acceptance per action type\n", 1)[1]
    assert "| Store | ACCEPT | REJECT |" in staff
    assert "| Store / action | ACCEPT | REJECT |" in actions
    assert ("| TOTAL | 5 | 60.00% (3/5) — small sample | 20.00% (1/5) — small sample "
            "| 20.00% (1/5) — small sample |") in output
    assert "| TOTAL | 1 | 1 | 50.00% (1/2) — small sample | 1 | 1 |" in staff
    assert "| TOTAL / DISCOUNT | 1 | 1 | 50.00% (1/2) — small sample | 1 | 0 |" in actions
