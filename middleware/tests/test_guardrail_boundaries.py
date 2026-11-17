"""Every boundary row of DS-07 as a test case (PB-28-1, PB-28-2, REC28-1 to REC28-4).

PB-28-1: the boundary table of `docs/design/DS-07_Guardrail_Rules.md`, with the
test that covers each row and the case id of that test:

| # | Rule threshold | Input | Expected | Test | Case |
|---|---|---|---|---|---|
| 1 | MIN_SHELF_LIFE 1 | 1 day left | PASSED | `test_rec28_1` | REC28-1 |
| 2 | MIN_SHELF_LIFE 1 | 0 days left | BLOCKED | `test_rec28_1` | REC28-1 |
| 3 | MAX_DISCOUNT 50 | 49.99% | PASSED | `test_rec28_2` | REC28-2 |
| 4 | MAX_DISCOUNT 50 | 50.00% | PASSED | `test_rec28_2` | REC28-2 |
| 5 | MAX_DISCOUNT 50 | 50.01% | ADJUSTED to 50% | `test_rec28_2` | REC28-2 |
| 6 | MIN_PRICE 1,000; price 2,000 | 50% (result 1,000) | PASSED | `test_rec28_3` | REC28-3 |
| 7 | MIN_PRICE 1,000; price 2,000 | 51% | ADJUSTED to 50% | `test_rec28_3` | REC28-3 |
| 8 | MIN_PRICE 1,000; price 900 | Any discount | BLOCKED | `test_rec28_4` | REC28-4 |
| 9 | Category MAX_DISCOUNT 30, all-category 50 | 40% in that category | ADJUSTED to 30% | `test_pb28_category_rule_boundary` | PB-28 |
| 10 | MIN_PRICE 1,000; price 1,000.01 | 50% | BLOCKED (MIN_PRICE) | `test_pb28_zero_discount_boundary` | PB-28 |
| 11 | MAX_DISCOUNT 0 | 10% | BLOCKED (MAX_DISCOUNT) | `test_pb28_zero_discount_boundary` | PB-28 |

Every row asserts three things: the outcome, the value the rule stored as
``adjusted_value`` and the ``guardrail_result`` row itself. The test builds its
own store, product, batch and rules with TEST- prefixed ids, so it never depends
on seed data.
"""

from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select, update
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
from app.services import guardrails

STORE_ID = "TEST-GBS1"
SKU = "TEST-GB-SKU-1"
BATCH_ID = "TEST-GB-B1"
CATEGORY = "TEST-GB-CAT"
PRICE = Decimal("2000.00")

# The defaults of DS-07; a row overrides only what it needs.
MIN_SHELF_LIFE = Decimal(1)
MAX_DISCOUNT = Decimal(50)
MIN_PRICE = Decimal(1000)

BOUNDARIES: dict[int, dict] = {
    1: {"rule": "MIN_SHELF_LIFE", "discount": Decimal("10.00"), "expiry_days": 1,
        "price": PRICE, "outcome": "PASSED", "adjusted": None, "status": "PENDING"},
    2: {"rule": "MIN_SHELF_LIFE", "discount": Decimal("10.00"), "expiry_days": 0,
        "price": PRICE, "outcome": "BLOCKED", "adjusted": None, "status": "BLOCKED"},
    3: {"rule": "MAX_DISCOUNT", "discount": Decimal("49.99"), "expiry_days": 30,
        "price": PRICE, "outcome": "PASSED", "adjusted": None, "status": "PENDING"},
    4: {"rule": "MAX_DISCOUNT", "discount": Decimal("50.00"), "expiry_days": 30,
        "price": PRICE, "outcome": "PASSED", "adjusted": None, "status": "PENDING"},
    5: {"rule": "MAX_DISCOUNT", "discount": Decimal("50.01"), "expiry_days": 30,
        "price": PRICE, "outcome": "ADJUSTED", "adjusted": Decimal("50.00"),
        "status": "PENDING"},
    6: {"rule": "MIN_PRICE", "discount": Decimal("50.00"), "expiry_days": 30,
        "price": PRICE, "outcome": "PASSED", "adjusted": None, "status": "PENDING",
        "max_discount": Decimal(100)},
    7: {"rule": "MIN_PRICE", "discount": Decimal("51.00"), "expiry_days": 30,
        "price": PRICE, "outcome": "ADJUSTED", "adjusted": Decimal("50.00"),
        "status": "PENDING", "max_discount": Decimal(100)},
    8: {"rule": "MIN_PRICE", "discount": Decimal("10.00"), "expiry_days": 30,
        "price": Decimal("900.00"), "outcome": "BLOCKED", "adjusted": None,
        "status": "BLOCKED"},
    9: {"rule": "MAX_DISCOUNT", "discount": Decimal("40.00"), "expiry_days": 30,
        "price": PRICE, "outcome": "ADJUSTED", "adjusted": Decimal("30.00"),
        "status": "PENDING", "category_max_discount": Decimal(30)},
    10: {"rule": "MIN_PRICE", "discount": Decimal("50.00"), "expiry_days": 30,
         "price": Decimal("1000.01"), "outcome": "BLOCKED", "adjusted": Decimal("0.00"),
         "status": "BLOCKED"},
    11: {"rule": "MAX_DISCOUNT", "discount": Decimal("10.00"), "expiry_days": 30,
         "price": PRICE, "outcome": "BLOCKED", "adjusted": Decimal("0.00"),
         "status": "BLOCKED", "max_discount": Decimal(0)},
}

SHELF_LIFE_ROWS = (1, 2)
DISCOUNT_ROWS = (3, 4, 5)
PRICE_ROWS = (6, 7)
LIST_PRICE_ROWS = (8,)
CATEGORY_ROWS = (9,)
ZERO_DISCOUNT_ROWS = (10, 11)


@pytest.fixture(autouse=True)
def no_active_rules(db_session: Session) -> None:
    """Start from no active rule, so a row sees only the rules it creates."""
    db_session.execute(update(GuardrailRule).values(is_active=False))
    db_session.flush()


def add_rule(session: Session, rule_type: str, threshold, category: str | None = None
             ) -> GuardrailRule:
    rule = GuardrailRule(rule_type=rule_type, threshold=Decimal(str(threshold)),
                         category=category, is_active=True)
    session.add(rule)
    session.flush()
    return rule


def add_rules(session: Session, row: dict) -> dict[str, GuardrailRule]:
    """The rules a boundary row needs.

    Row 9 adds a stricter category MAX_DISCOUNT rule; rows 6 and 7 raise MAX_DISCOUNT
    above their discount, so the rows test MIN_PRICE and nothing else adjusts first.
    """
    rules = {
        "MIN_SHELF_LIFE": add_rule(session, "MIN_SHELF_LIFE", MIN_SHELF_LIFE),
        "MAX_DISCOUNT": add_rule(session, "MAX_DISCOUNT", row.get("max_discount", MAX_DISCOUNT)),
        "MIN_PRICE": add_rule(session, "MIN_PRICE", MIN_PRICE),
    }
    if "category_max_discount" in row:
        rules["MAX_DISCOUNT"] = add_rule(session, "MAX_DISCOUNT", row["category_max_discount"],
                                         category=CATEGORY)
    return rules


def build(session: Session, row: dict) -> Recommendation:
    session.add(Store(store_id=STORE_ID, name="Boundary test store",
                      latitude=Decimal("10.500000"), longitude=Decimal("106.500000"),
                      region_id="TEST"))
    session.flush()
    session.add(Product(sku=SKU, barcode="TEST-GB-BC-1", name="Boundary test product",
                        category=CATEGORY, unit_price=row["price"]))
    session.flush()
    session.add(ProductBatch(batch_id=BATCH_ID, sku=SKU, store_id=STORE_ID,
                             expiry_date=clock.today_local()
                             + timedelta(days=row["expiry_days"]), quantity=10))
    session.flush()
    recommendation = Recommendation(store_id=STORE_ID, sku=SKU, batch_id=BATCH_ID,
                                    action_type="DISCOUNT", discount_pct=row["discount"],
                                    reason="TEST reason", status="GENERATED")
    session.add(recommendation)
    session.flush()
    return recommendation


def stored_result(session: Session, rec_id: int, rule_id: int) -> GuardrailResult:
    session.expire_all()
    result = session.scalar(select(GuardrailResult)
                            .where(GuardrailResult.rec_id == rec_id,
                                   GuardrailResult.rule_id == rule_id))
    assert result is not None, f"no guardrail_result for rule {rule_id}"
    return result


def fresh(session: Session, recommendation: Recommendation) -> Recommendation:
    session.expire_all()
    row = session.get(Recommendation, recommendation.rec_id)
    assert row is not None
    return row


def assert_boundary(session: Session, row_number: int) -> None:
    """Run one boundary row and assert outcome, adjusted value and stored result."""
    row = BOUNDARIES[row_number]
    rules = add_rules(session, row)
    recommendation = build(session, row)
    rule = rules[row["rule"]]
    before = recommendation.discount_pct

    assert guardrails.apply_guardrails(session, recommendation) == row["status"]

    stored = stored_result(session, recommendation.rec_id, rule.rule_id)
    assert stored.outcome == row["outcome"], f"row {row_number}"
    assert stored.adjusted_value == row["adjusted"], f"row {row_number}"
    expected_discount = row["adjusted"] if row["outcome"] == "ADJUSTED" else before
    assert fresh(session, recommendation).status == row["status"]
    if row["rule"] == "MIN_SHELF_LIFE":
        assert before == expected_discount
    else:
        assert fresh(session, recommendation).discount_pct == expected_discount
        assert stored.original_value == before, f"row {row_number}"


# REC28-1


@pytest.mark.parametrize("row_number", SHELF_LIFE_ROWS, ids=[f"row-{n}" for n in SHELF_LIFE_ROWS])
def test_rec28_1_the_shelf_life_boundary(db_session, row_number):
    assert_boundary(db_session, row_number)


# REC28-2


@pytest.mark.parametrize("row_number", DISCOUNT_ROWS, ids=[f"row-{n}" for n in DISCOUNT_ROWS])
def test_rec28_2_the_discount_boundary(db_session, row_number):
    assert_boundary(db_session, row_number)


# REC28-3


@pytest.mark.parametrize("row_number", PRICE_ROWS, ids=[f"row-{n}" for n in PRICE_ROWS])
def test_rec28_3_the_price_boundary(db_session, row_number):
    assert_boundary(db_session, row_number)


# REC28-4


@pytest.mark.parametrize("row_number", LIST_PRICE_ROWS,
                         ids=[f"row-{n}" for n in LIST_PRICE_ROWS])
def test_rec28_4_a_list_price_below_the_minimum_blocks(db_session, row_number):
    assert_boundary(db_session, row_number)


def test_pb28_category_rule_boundary(db_session):
    assert_boundary(db_session, CATEGORY_ROWS[0])


@pytest.mark.parametrize("row_number", ZERO_DISCOUNT_ROWS,
                         ids=[f"row-{n}" for n in ZERO_DISCOUNT_ROWS])
def test_pb28_zero_discount_boundary(db_session, row_number):
    assert_boundary(db_session, row_number)
    checked = list(db_session.scalars(select(GuardrailResult)
                                     .join(Recommendation,
                                           Recommendation.rec_id == GuardrailResult.rec_id)
                                     .where(Recommendation.sku == SKU)
                                     .order_by(GuardrailResult.result_id)))
    assert len(checked) == (3 if row_number == 10 else 2)
    assert checked[-1].outcome == "BLOCKED"
    assert "0%" in checked[-1].message


# PB-28-1: the table above is only a boundary suite if every row is covered.


def test_pb28_every_ds07_row_is_a_test():
    covered = (set(SHELF_LIFE_ROWS) | set(DISCOUNT_ROWS) | set(PRICE_ROWS)
               | set(LIST_PRICE_ROWS) | set(CATEGORY_ROWS) | set(ZERO_DISCOUNT_ROWS))
    assert covered == set(BOUNDARIES)
    assert covered == set(range(1, 12))


def test_pb28_a_shelf_life_block_stops_the_discount_checks(db_session):
    """Row 2 blocks on the shelf life, so neither discount rule is checked."""
    rules = add_rules(db_session, BOUNDARIES[2])
    recommendation = build(db_session, BOUNDARIES[2])

    assert guardrails.apply_guardrails(db_session, recommendation) == "BLOCKED"

    db_session.expire_all()
    checked = list(db_session.scalars(select(GuardrailResult)
                                     .where(GuardrailResult.rec_id == recommendation.rec_id)))
    assert [result.rule_id for result in checked] == [rules["MIN_SHELF_LIFE"].rule_id]
    assert checked[0].outcome == "BLOCKED"
