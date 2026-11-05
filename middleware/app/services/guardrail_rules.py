"""Guardrail rule configuration (PB-26). The router owns the commit."""

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.core.security import Principal
from app.domain.models import GuardrailRule
from app.repositories import guardrail_rules as repository
from app.repositories.registry import find_user_id
from app.services.audit import record_audit


# threshold is decimal(12,2): 10 integer digits plus 2 decimals, so the largest
# value it stores is 9999999999.99. Counting digits is not enough, because a value
# like 99999999999 has 11 digits and still overflows the column.
MAX_THRESHOLD = Decimal("10000000000")


def list_rules(session: Session) -> list[GuardrailRule]:
    return repository.list_rules(session)


def active_rules(session: Session) -> list[GuardrailRule]:
    """Active rules, read fresh on every call, so a change applies at once.

    PB-27 validates recommendations with these; there is no cache.
    """
    return repository.list_active_rules(session)


def _invalid_threshold(reason: str) -> ApiError:
    return ApiError(422, "VALIDATION_ERROR", f"Invalid field 'threshold': {reason}")


def _tightening_reason(rule_type: str) -> str:
    direction = "above" if rule_type == "MAX_DISCOUNT" else "below"
    return f"a category {rule_type} rule may not be {direction} the all-category rule."


def _validate_threshold(rule_type: str, threshold: Decimal) -> None:
    if not threshold.is_finite():
        raise _invalid_threshold("must be a finite number.")
    if threshold < 0:
        raise _invalid_threshold("must not be negative.")
    if threshold.as_tuple().exponent < -2:
        raise _invalid_threshold("must have at most two decimal places.")
    if threshold >= MAX_THRESHOLD:
        raise _invalid_threshold("must be below 10000000000, the largest value decimal(12,2) "
                                 "can store.")
    if rule_type == "MAX_DISCOUNT" and threshold > 100:
        raise _invalid_threshold("MAX_DISCOUNT must be between 0 and 100.")
    if rule_type == "MIN_SHELF_LIFE" and threshold != threshold.to_integral_value():
        raise _invalid_threshold("MIN_SHELF_LIFE must be a whole number of days.")


def _tightens(rule_type: str, category_threshold: Decimal, all_threshold: Decimal) -> bool:
    if rule_type == "MAX_DISCOUNT":
        return category_threshold <= all_threshold
    return category_threshold >= all_threshold


def _check_tightening(rules: list[GuardrailRule], rule: GuardrailRule,
                      threshold: Decimal, is_active: bool) -> None:
    """DS-07: an active category rule may only tighten the all-category rule.

    Checked in both directions, so neither side can be moved past the other.
    """
    if not is_active:
        return
    others = [other for other in rules
              if other.rule_type == rule.rule_type and other.rule_id != rule.rule_id
              and other.is_active]
    if rule.category is None:
        for other in others:
            if other.category is not None and not _tightens(rule.rule_type, other.threshold,
                                                            threshold):
                raise _invalid_threshold(_tightening_reason(rule.rule_type))
    else:
        for other in others:
            if other.category is None and not _tightens(rule.rule_type, threshold,
                                                        other.threshold):
                raise _invalid_threshold(_tightening_reason(rule.rule_type))


def update_rule(session: Session, rule_id: int, threshold: Decimal, is_active: bool,
                principal: Principal) -> GuardrailRule:
    """Apply one change in the caller's transaction and write its audit row.

    Raises:
        ApiError(404, "NOT_FOUND"): no rule with that id.
        ApiError(422, "VALIDATION_ERROR"): the threshold does not fit the rule type,
            or it would break the tightening rule.
    """
    rule = repository.get_rule(session, rule_id)
    if rule is None:
        raise ApiError(404, "NOT_FOUND", f"Guardrail rule {rule_id} does not exist.")
    _validate_threshold(rule.rule_type, threshold)
    _check_tightening(repository.list_rules(session), rule, threshold, is_active)

    old_threshold, old_active = rule.threshold, rule.is_active
    rule.threshold = threshold
    rule.is_active = is_active
    rule.updated_by = find_user_id(session, principal.sub)
    rule.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    record_audit(session, "GUARDRAIL_RULE_UPDATED", "guardrail_rule", str(rule_id),
                 user_id=rule.updated_by,
                 details=f"threshold {old_threshold} -> {threshold}, "
                         f"is_active {old_active} -> {is_active}")
    session.flush()
    return rule
