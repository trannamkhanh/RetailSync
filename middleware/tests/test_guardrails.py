"""Guardrail validation on real SQL Server (PB-27-1 to PB-27-4, REC27-1 to REC27-7).

The test builds its own store, product, batch and recommendation, so it never
depends on seed data (TEST- prefixed ids). Only the rules a test creates are
active: an autouse fixture deactivates every rule inside the savepoint, which
the rollback at the end of the test restores.
"""

from datetime import timedelta
from decimal import Decimal
from unittest.mock import Mock

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import clock
from app.domain.models import (
    GuardrailResult,
    GuardrailRule,
    Product,
    ProductBatch,
    Recommendation,
    Store,
)
from app.repositories import guardrails as repository
from app.services import guardrail_rules, guardrails

STORE_ID = "TEST-GRS1"
SKU = "TEST-GR-SKU-1"
BATCH_ID = "TEST-GR-B1"
CATEGORY = "TEST-GR-CAT"
OTHER_CATEGORY = "TEST-GR-OTHER"
PRICE = Decimal("2000.00")


@pytest.fixture(autouse=True)
def no_active_rules(db_session: Session) -> None:
    """Start from no active rule, so a test sees only the rules it creates."""
    db_session.execute(update(GuardrailRule).values(is_active=False))
    db_session.flush()


def add_rule(session: Session, rule_type: str, threshold, category: str | None = None,
             is_active: bool = True) -> GuardrailRule:
    rule = GuardrailRule(rule_type=rule_type, threshold=Decimal(str(threshold)),
                         category=category, is_active=is_active)
    session.add(rule)
    session.flush()
    return rule


def add_default_rules(session: Session) -> dict[str, GuardrailRule]:
    """The DS-07 defaults: 1 day, 50% and 1,000 VND, for every category."""
    return {
        "MIN_SHELF_LIFE": add_rule(session, "MIN_SHELF_LIFE", 1),
        "MAX_DISCOUNT": add_rule(session, "MAX_DISCOUNT", 50),
        "MIN_PRICE": add_rule(session, "MIN_PRICE", 1000),
    }


def build(session: Session, *, action_type: str = "DISCOUNT", discount=Decimal("10.00"),
          expiry_days: int | None = 30, price=PRICE, category: str = CATEGORY
          ) -> Recommendation:
    """Create the rows a recommendation needs, then the recommendation itself."""
    session.add(Store(store_id=STORE_ID, name="Guardrail test store",
                      latitude=Decimal("10.500000"), longitude=Decimal("106.500000"),
                      region_id="TEST"))
    session.flush()
    session.add(Product(sku=SKU, barcode="TEST-GR-BC-1", name="Guardrail test product",
                        category=category, unit_price=price))
    session.flush()
    batch_id = None
    if expiry_days is not None:
        batch_id = BATCH_ID
        session.add(ProductBatch(batch_id=BATCH_ID, sku=SKU, store_id=STORE_ID,
                                 expiry_date=clock.today_local() + timedelta(days=expiry_days),
                                 quantity=10))
        session.flush()
    recommendation = Recommendation(
        store_id=STORE_ID, sku=SKU, batch_id=batch_id, action_type=action_type,
        discount_pct=None if discount is None else Decimal(discount),
        reason="TEST reason", status="GENERATED",
    )
    session.add(recommendation)
    session.flush()
    return recommendation


def fresh(session: Session, recommendation: Recommendation) -> Recommendation:
    """The stored recommendation, read again after the service changed it."""
    session.expire_all()
    row = session.get(Recommendation, recommendation.rec_id)
    assert row is not None
    return row


def stored_results(session: Session, recommendation: Recommendation
                   ) -> list[tuple[str, int, str, Decimal | None, Decimal | None]]:
    """(rule_type, rule_id, outcome, original_value, adjusted_value) per result."""
    session.expire_all()
    rows = session.execute(
        select(GuardrailRule.rule_type, GuardrailResult.rule_id, GuardrailResult.outcome,
               GuardrailResult.original_value, GuardrailResult.adjusted_value)
        .join(GuardrailRule, GuardrailRule.rule_id == GuardrailResult.rule_id)
        .where(GuardrailResult.rec_id == recommendation.rec_id)
        .order_by(GuardrailResult.result_id)
    ).all()
    return [(row[0], row[1], row[2], row[3], row[4]) for row in rows]


def result_count(session: Session, rec_id: int) -> int:
    return session.scalar(select(func.count()).select_from(GuardrailResult)
                          .where(GuardrailResult.rec_id == rec_id))


# REC27-1


def test_rec27_1_a_recommendation_that_meets_every_rule_becomes_pending(db_session):
    add_default_rules(db_session)
    recommendation = build(db_session, discount=Decimal("10.00"))

    status = guardrails.apply_guardrails(db_session, recommendation)

    assert status == "PENDING"
    assert fresh(db_session, recommendation).status == "PENDING"
    assert [(rule_type, outcome) for rule_type, _, outcome, _, _ in
            stored_results(db_session, recommendation)] == [
        ("MIN_SHELF_LIFE", "PASSED"), ("MAX_DISCOUNT", "PASSED"), ("MIN_PRICE", "PASSED")]


# REC27-2


def test_rec27_2_a_discount_above_the_limit_is_adjusted(db_session):
    add_default_rules(db_session)
    recommendation = build(db_session, discount=Decimal("60.00"))

    assert guardrails.apply_guardrails(db_session, recommendation) == "PENDING"

    row = fresh(db_session, recommendation)
    assert row.status == "PENDING"
    assert row.discount_pct == Decimal("50.00")
    (rule_type, _, outcome, original, adjusted), = [
        result for result in stored_results(db_session, recommendation)
        if result[0] == "MAX_DISCOUNT"]
    assert (rule_type, outcome, original, adjusted) == ("MAX_DISCOUNT", "ADJUSTED",
                                                        Decimal("60.00"), Decimal("50.00"))


# REC27-3


def test_rec27_3_shelf_life_below_the_minimum_blocks(db_session):
    add_default_rules(db_session)
    recommendation = build(db_session, discount=Decimal("60.00"), expiry_days=0)

    assert guardrails.apply_guardrails(db_session, recommendation) == "BLOCKED"

    row = fresh(db_session, recommendation)
    assert row.status == "BLOCKED"
    # A blocked recommendation keeps the discount it was generated with, and the
    # later rules are not checked.
    assert row.discount_pct == Decimal("60.00")
    assert [(rule_type, outcome, original, adjusted) for rule_type, _, outcome, original, adjusted
            in stored_results(db_session, recommendation)] == [
        ("MIN_SHELF_LIFE", "BLOCKED", Decimal("0.00"), None)]


# REC27-4


def test_rec27_4_one_result_per_rule_checked(db_session):
    rules = add_default_rules(db_session)
    recommendation = build(db_session)

    guardrails.apply_guardrails(db_session, recommendation)

    results = stored_results(db_session, recommendation)
    assert [rule_id for _, rule_id, _, _, _ in results] == [
        rules["MIN_SHELF_LIFE"].rule_id, rules["MAX_DISCOUNT"].rule_id,
        rules["MIN_PRICE"].rule_id]
    assert len(results) == result_count(db_session, recommendation.rec_id) == 3


# REC27-5


def test_rec27_5_rules_that_cannot_be_loaded_release_nothing(db_session, monkeypatch):
    add_default_rules(db_session)
    recommendation = build(db_session, discount=Decimal("60.00"))

    def unavailable(session):
        raise RuntimeError("guardrail_rule is not reachable")

    monkeypatch.setattr(guardrail_rules, "active_rules", unavailable)

    with pytest.raises(guardrails.GuardrailRulesUnavailable):
        guardrails.apply_guardrails(db_session, recommendation)

    row = fresh(db_session, recommendation)
    assert row.status == "GENERATED"
    assert row.discount_pct == Decimal("60.00")
    assert result_count(db_session, recommendation.rec_id) == 0


# REC27-6


def test_rec27_6_a_failed_save_keeps_neither_the_change_nor_a_result(db_session, monkeypatch):
    add_default_rules(db_session)
    recommendation = build(db_session, discount=Decimal("60.00"))
    rec_id = recommendation.rec_id

    def broken_store(session, recommendation, rule, outcome, original, adjusted, message):
        # outcome is a CHECK-constrained column, so the flush fails like a full
        # guardrail_result table would.
        session.add(GuardrailResult(rec_id=recommendation.rec_id, rule_id=rule.rule_id,
                                    outcome="INVALID"))

    monkeypatch.setattr(guardrails, "_store", broken_store)

    with pytest.raises(IntegrityError):
        guardrails.apply_guardrails(db_session, recommendation)

    db_session.rollback()

    assert db_session.get(Recommendation, rec_id) is None
    assert result_count(db_session, rec_id) == 0


# REC27-7


def test_rec27_7_the_stricter_category_rule_applies(db_session):
    category_rule = add_rule(db_session, "MAX_DISCOUNT", 30, category=CATEGORY)
    add_rule(db_session, "MAX_DISCOUNT", 50)
    recommendation = build(db_session, discount=Decimal("40.00"))

    assert guardrails.apply_guardrails(db_session, recommendation) == "PENDING"

    assert fresh(db_session, recommendation).discount_pct == Decimal("30.00")
    assert [(rule_id, outcome, adjusted) for _, rule_id, outcome, _, adjusted
            in stored_results(db_session, recommendation)] == [
        (category_rule.rule_id, "ADJUSTED", Decimal("30.00"))]


# Cases outside the REC27 sheet.


def test_pb27_inactive_rules_are_ignored(db_session):
    add_rule(db_session, "MAX_DISCOUNT", 10, is_active=False)
    add_rule(db_session, "MAX_DISCOUNT", 50)
    recommendation = build(db_session, discount=Decimal("60.00"))

    guardrails.apply_guardrails(db_session, recommendation)

    assert fresh(db_session, recommendation).discount_pct == Decimal("50.00")
    assert [rule_type for rule_type, _, _, _, _ in stored_results(db_session, recommendation)] == [
        "MAX_DISCOUNT"]


def test_pb27_redistribution_without_a_batch_is_pending_with_no_result(db_session):
    add_default_rules(db_session)
    recommendation = build(db_session, action_type="REDISTRIBUTION", discount=None,
                           expiry_days=None)

    assert guardrails.apply_guardrails(db_session, recommendation) == "PENDING"

    assert fresh(db_session, recommendation).status == "PENDING"
    assert result_count(db_session, recommendation.rec_id) == 0


def test_pb27_both_discount_rules_can_adjust_and_store_both_results(db_session):
    add_rule(db_session, "MAX_DISCOUNT", 60)
    add_rule(db_session, "MIN_PRICE", 1000)
    recommendation = build(db_session, discount=Decimal("70.00"))

    assert guardrails.apply_guardrails(db_session, recommendation) == "PENDING"

    assert fresh(db_session, recommendation).discount_pct == Decimal("50.00")
    assert [(rule_type, outcome, original, adjusted) for rule_type, _, outcome, original, adjusted
            in stored_results(db_session, recommendation)] == [
        ("MAX_DISCOUNT", "ADJUSTED", Decimal("70.00"), Decimal("60.00")),
        ("MIN_PRICE", "ADJUSTED", Decimal("60.00"), Decimal("50.00"))]


def test_pb27_min_price_rounds_the_discount_down(db_session):
    add_rule(db_session, "MAX_DISCOUNT", 100)
    add_rule(db_session, "MIN_PRICE", 1000)
    recommendation = build(db_session, discount=Decimal("100.00"), price=Decimal("3000.00"))

    guardrails.apply_guardrails(db_session, recommendation)

    # 2000 / 3000 is 66.66% and a rounding up would take the price below 1,000.
    row = fresh(db_session, recommendation)
    assert row.discount_pct == Decimal("66.66")
    assert row.discount_pct < Decimal("66.67")


def test_pb27_a_clearance_with_a_batch_only_checks_the_shelf_life(db_session):
    add_default_rules(db_session)
    recommendation = build(db_session, action_type="CLEARANCE", discount=Decimal("80.00"))

    assert guardrails.apply_guardrails(db_session, recommendation) == "PENDING"

    assert fresh(db_session, recommendation).discount_pct == Decimal("80.00")
    assert [rule_type for rule_type, _, _, _, _ in stored_results(db_session, recommendation)] == [
        "MIN_SHELF_LIFE"]


def test_pb27_a_category_rule_does_not_apply_to_another_category(db_session):
    add_rule(db_session, "MAX_DISCOUNT", 10, category=CATEGORY)
    add_rule(db_session, "MAX_DISCOUNT", 50)
    recommendation = build(db_session, discount=Decimal("60.00"), category=OTHER_CATEGORY)

    guardrails.apply_guardrails(db_session, recommendation)

    assert fresh(db_session, recommendation).discount_pct == Decimal("50.00")


def test_pb27_no_active_rule_leaves_the_recommendation_pending(db_session):
    recommendation = build(db_session, discount=Decimal("90.00"))

    assert guardrails.apply_guardrails(db_session, recommendation) == "PENDING"

    assert fresh(db_session, recommendation).discount_pct == Decimal("90.00")
    assert result_count(db_session, recommendation.rec_id) == 0


def test_pb27_validation_never_commits(db_session, monkeypatch):
    add_default_rules(db_session)
    recommendation = build(db_session, discount=Decimal("60.00"))
    commit = Mock()
    monkeypatch.setattr(db_session, "commit", commit)

    guardrails.apply_guardrails(db_session, recommendation)

    commit.assert_not_called()
    assert len(repository.list_results(db_session, recommendation.rec_id)) == 3


def test_pb27_results_are_read_in_the_order_the_rules_were_checked(db_session):
    add_default_rules(db_session)
    recommendation = build(db_session, discount=Decimal("60.00"))

    guardrails.apply_guardrails(db_session, recommendation)

    results = repository.list_results(db_session, recommendation.rec_id)
    ids = [row.result_id for row in results]
    assert len(results) == 3
    assert ids == sorted(ids)
