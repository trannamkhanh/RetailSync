"""Admin guardrail rule endpoints (PB-26). The update commits in the router."""

from fastapi import APIRouter, Depends, Path
from sqlalchemy.orm import Session

from app.api.schemas.guardrails import GuardrailRuleList, GuardrailRuleRead, GuardrailRuleUpdate
from app.core.db import get_db
from app.core.security import Principal, require_role
from app.services import guardrail_rules


router = APIRouter(prefix="/admin", tags=["Admin"])

RULE_ID = Path(ge=1, le=2_147_483_647)


@router.get("/guardrail-rules", response_model=GuardrailRuleList)
def list_guardrail_rules(session: Session = Depends(get_db),
                         _: Principal = Depends(require_role("Admin"))) -> GuardrailRuleList:
    rules = guardrail_rules.list_rules(session)
    return GuardrailRuleList(items=[GuardrailRuleRead.model_validate(rule) for rule in rules])


@router.put("/guardrail-rules/{rule_id}", response_model=GuardrailRuleRead)
def update_guardrail_rule(payload: GuardrailRuleUpdate,
                          rule_id: int = RULE_ID,
                          session: Session = Depends(get_db),
                          principal: Principal = Depends(require_role("Admin"))) -> GuardrailRuleRead:
    rule = guardrail_rules.update_rule(session, rule_id, payload.threshold, payload.is_active,
                                       principal)
    updated = GuardrailRuleRead.model_validate(rule)
    session.commit()
    return updated
