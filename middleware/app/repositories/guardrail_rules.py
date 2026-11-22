"""Queries for guardrail rules (PB-26). Read-only, never commits."""

from sqlalchemy import case, or_, select
from sqlalchemy.orm import Session

from app.domain.models import GuardrailRule


def list_rules(session: Session) -> list[GuardrailRule]:
    """Every rule: rule_type, all-category rules first, category, then rule_id."""
    return list(session.scalars(
        select(GuardrailRule).order_by(
            GuardrailRule.rule_type,
            case((or_(GuardrailRule.category.is_(None), GuardrailRule.category == ""), 0), else_=1),
            GuardrailRule.category,
            GuardrailRule.rule_id,
        )
    ))


def list_rules_for_update(session: Session) -> list[GuardrailRule]:
    """Lock all guardrail rules in primary-key order until the transaction ends.

    Uses ``UPDLOCK, HOLDLOCK`` so parallel rule updates serialize without
    deadlocking and preserve DS-07's category tightening invariant.
    """
    return list(session.scalars(
        select(GuardrailRule)
        .with_hint(GuardrailRule.__table__, "WITH (UPDLOCK, HOLDLOCK)")
        .order_by(GuardrailRule.rule_id)
        .execution_options(populate_existing=True)
    ))


def get_rule(session: Session, rule_id: int) -> GuardrailRule | None:
    return session.get(GuardrailRule, rule_id)


def list_active_rules(session: Session) -> list[GuardrailRule]:
    """Active rules, read from the database on every call."""
    return list(session.scalars(
        select(GuardrailRule)
        .where(GuardrailRule.is_active)
        .order_by(GuardrailRule.rule_type, GuardrailRule.rule_id)
    ))
