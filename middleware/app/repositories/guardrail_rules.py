"""Queries for guardrail rules (PB-26). Read-only, never commits."""

from sqlalchemy import case, select
from sqlalchemy.orm import Session

from app.domain.models import GuardrailRule


def list_rules(session: Session) -> list[GuardrailRule]:
    """Every rule: rule_type, all-category rules first, category, then rule_id."""
    return list(session.scalars(
        select(GuardrailRule).order_by(
            GuardrailRule.rule_type,
            case((GuardrailRule.category.is_(None), 0), else_=1),
            GuardrailRule.category,
            GuardrailRule.rule_id,
        )
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
