"""Guardrail validation of a recommendation (PB-27, DS-07).

The caller owns the transaction: nothing here commits, so the recommendation and
its results are stored or lost together (REC27-6).
"""

from dataclasses import dataclass
from decimal import Decimal
from decimal import ROUND_FLOOR

from sqlalchemy.orm import Session

from app.core import clock
from app.domain.models import GuardrailResult, GuardrailRule, Recommendation
from app.repositories import guardrails as repository
from app.services import guardrail_rules

# DS-07 order: the shelf-life rule runs first, so a blocked recommendation is
# never adjusted.
RULE_ORDER = ("MIN_SHELF_LIFE", "MAX_DISCOUNT", "MIN_PRICE")
DISCOUNT_RULES = ("MAX_DISCOUNT", "MIN_PRICE")

PASSED = "PASSED"
ADJUSTED = "ADJUSTED"
BLOCKED = "BLOCKED"
PENDING = "PENDING"

PERCENT = Decimal(100)
CENT = Decimal("0.01")


class GuardrailRulesUnavailable(Exception):
    """The rules could not be read, so nothing is released (REC27-5).

    The recommendation keeps its status, GENERATED, until the next run.
    """


@dataclass(frozen=True)
class _Target:
    """The values the rules compare: category, list price and shelf life."""

    category: str
    unit_price: Decimal
    days_left: int | None


def load_rules(session: Session) -> list[GuardrailRule]:
    """Read the active rules, turning any failure into GuardrailRulesUnavailable."""
    try:
        return guardrail_rules.active_rules(session)
    except Exception as error:  # noqa: BLE001 - any failure must write nothing
        raise GuardrailRulesUnavailable(
            "Không thể tải các quy tắc kiểm soát.") from error


def apply_guardrails(session: Session, recommendation: Recommendation,
                     rules: list[GuardrailRule] | None = None) -> str:
    """Check one recommendation against DS-07 and store one result per rule.

    Returns the new status, PENDING or BLOCKED, and never commits. A rule that
    blocks stops the remaining checks. A recommendation with no rule to check,
    such as a REDISTRIBUTION without a batch, becomes PENDING with no result.
    Pass preloaded ``rules`` from ``load_rules(session)`` to validate without
    re-reading the database.
    """
    active = load_rules(session) if rules is None else rules
    target = _target(session, recommendation)
    if recommendation.rec_id is None:
        session.flush()
    status = PENDING
    for rule in _rules_to_check(recommendation, active, target):
        outcome, original, adjusted, message = _check(rule, recommendation, target)
        _store(session, recommendation, rule, outcome, original, adjusted, message)
        if outcome == BLOCKED:
            status = BLOCKED
            break
    recommendation.status = status
    session.flush()
    return status


def _target(session: Session, recommendation: Recommendation) -> _Target:
    product = repository.get_product(session, recommendation.sku)
    if product is None:
        raise ValueError(f"Product {recommendation.sku} does not exist.")
    days_left = None
    if recommendation.batch_id is not None:
        batch = repository.get_batch(session, recommendation.batch_id)
        if batch is None:
            raise ValueError(f"Batch {recommendation.batch_id} does not exist.")
        days_left = (batch.expiry_date - clock.today_local()).days
    return _Target(category=product.category, unit_price=Decimal(product.unit_price),
                   days_left=days_left)


def _rules_to_check(recommendation: Recommendation, rules: list[GuardrailRule],
                    target: _Target) -> list[GuardrailRule]:
    """The strictest matching active rule of each type, in DS-07 order."""
    checked = []
    for rule_type in RULE_ORDER:
        if rule_type == "MIN_SHELF_LIFE" and target.days_left is None:
            continue
        if rule_type in DISCOUNT_RULES and recommendation.action_type != "DISCOUNT":
            continue
        rule = _strictest(rules, rule_type, target.category)
        if rule is not None:
            checked.append(rule)
    return checked


def _matches_category(rule_category: str | None, category: str) -> bool:
    if guardrail_rules.is_general_category(rule_category):
        return True
    assert rule_category is not None
    return rule_category.casefold() == category.casefold()


def _strictest(rules: list[GuardrailRule], rule_type: str,
               category: str) -> GuardrailRule | None:
    """The lowest MAX_DISCOUNT, the highest MIN_PRICE or MIN_SHELF_LIFE (DS-07)."""
    matching = [rule for rule in rules
                if rule.rule_type == rule_type
                and _matches_category(rule.category, category)]
    if not matching:
        return None

    def rank(rule: GuardrailRule) -> tuple:
        # The category rule wins a tie, because it is the more specific one.
        specific = 1 if guardrail_rules.is_general_category(rule.category) else 0
        if rule_type == "MAX_DISCOUNT":
            return rule.threshold, specific, rule.rule_id
        return -rule.threshold, specific, rule.rule_id

    return min(matching, key=rank)


def _check(rule: GuardrailRule, recommendation: Recommendation,
           target: _Target) -> tuple[str, Decimal | None, Decimal | None, str | None]:
    if rule.rule_type == "MIN_SHELF_LIFE":
        return _check_shelf_life(rule, target)
    if rule.rule_type == "MAX_DISCOUNT":
        return _check_max_discount(rule, recommendation)
    return _check_min_price(rule, recommendation, target)


def _check_shelf_life(rule: GuardrailRule,
                      target: _Target) -> tuple[str, Decimal | None, Decimal | None, str | None]:
    days = target.days_left
    threshold = int(rule.threshold)
    if days < threshold:
        return (BLOCKED, Decimal(days), None,
                f"Còn {days} ngày hạn dùng; tối thiểu là {threshold} ngày.")
    return (PASSED, Decimal(days), None, None)


def _check_max_discount(rule: GuardrailRule, recommendation: Recommendation
                        ) -> tuple[str, Decimal | None, Decimal | None, str | None]:
    discount = _discount(recommendation)
    if discount > rule.threshold:
        if rule.threshold == 0:
            return (BLOCKED, discount, Decimal("0.00"),
                    "Giới hạn giảm giá đưa mức giảm về 0%; không còn giảm giá để áp dụng.")
        recommendation.discount_pct = rule.threshold
        return (ADJUSTED, discount, rule.threshold,
                f"Giảm {discount}% vượt mức tối đa {rule.threshold}%.")
    return (PASSED, discount, None, None)


def _check_min_price(rule: GuardrailRule, recommendation: Recommendation, target: _Target
                     ) -> tuple[str, Decimal | None, Decimal | None, str | None]:
    discount = _discount(recommendation)
    price, minimum = target.unit_price, rule.threshold
    if price < minimum:
        return (BLOCKED, discount, None,
                f"Giá niêm yết {price} thấp hơn giá tối thiểu {minimum}.")
    if _price_after(price, discount) >= minimum:
        return (PASSED, discount, None, None)
    adjusted = _largest_discount(price, minimum)
    if adjusted == 0:
        return (BLOCKED, discount, adjusted,
                "Giá tối thiểu đưa mức giảm về 0% sau khi làm tròn xuống; "
                "không còn giảm giá để áp dụng.")
    recommendation.discount_pct = adjusted
    return (ADJUSTED, discount, adjusted,
            f"Giảm {discount}% làm giá bán thấp hơn giá tối thiểu {minimum}.")


def _discount(recommendation: Recommendation) -> Decimal:
    value = recommendation.discount_pct
    return Decimal("0") if value is None else Decimal(value)


def _price_after(price: Decimal, discount: Decimal) -> Decimal:
    """The price the customer pays: price x (1 - discount / 100), in Decimal."""
    return price * (PERCENT - discount) / PERCENT


def _largest_discount(price: Decimal, minimum: Decimal) -> Decimal:
    """The largest discount that keeps the price at or above the minimum.

    Rounded down to two decimals, because the recommendation stores
    discount_pct in a decimal(5,2) column and rounding up could go below.
    """
    return ((price - minimum) * PERCENT / price).quantize(CENT, rounding=ROUND_FLOOR)


def _store(session: Session, recommendation: Recommendation, rule: GuardrailRule, outcome: str,
           original: Decimal | None, adjusted: Decimal | None, message: str | None) -> None:
    session.add(GuardrailResult(
        rec_id=recommendation.rec_id,
        rule_id=rule.rule_id,
        outcome=outcome,
        original_value=_money(original),
        adjusted_value=_money(adjusted),
        message=message,
    ))


def _money(value: Decimal | None) -> Decimal | None:
    return None if value is None else value.quantize(CENT)
