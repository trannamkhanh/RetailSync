"""DS-04 GuardrailRule bodies for the admin endpoints."""

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class GuardrailRuleRead(BaseModel):
    """The threshold is a decimal column; DS-04 wants a JSON number."""

    model_config = ConfigDict(from_attributes=True)

    rule_id: int
    rule_type: str
    threshold: float
    category: str | None
    is_active: bool


class GuardrailRuleUpdate(BaseModel):
    """Only threshold and is_active change; another field is a 422."""

    model_config = ConfigDict(extra="forbid")

    threshold: Decimal = Field(ge=Decimal("0"))
    is_active: bool


class GuardrailRuleList(BaseModel):
    items: list[GuardrailRuleRead]
