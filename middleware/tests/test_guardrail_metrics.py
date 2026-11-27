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
