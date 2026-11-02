"""Audit query endpoint (PB-04-4). Read-only: it never commits."""

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.schemas.audit import AuditEntry, AuditLogList
from app.api.schemas.registry import ID_PATTERN
from app.core.db import get_db
from app.core.security import Principal, require_role
from app.services import audit


router = APIRouter(tags=["Audit"])


@router.get("/audit-logs", response_model=AuditLogList)
def list_audit_logs(user_id: int | None = Query(default=None, ge=1, le=2147483647),
                    action: str | None = Query(default=None, min_length=1, max_length=50, pattern=ID_PATTERN),
                    from_time: datetime | None = Query(default=None, alias="from"),
                    to: datetime | None = Query(default=None),
                    limit: int = Query(default=100, ge=1, le=500),
                    session: Session = Depends(get_db),
                    _: Principal = Depends(require_role("Auditor"))) -> AuditLogList:
    entries = audit.list_audit_logs(session, user_id, action, from_time, to, limit)
    return AuditLogList(items=[AuditEntry.model_validate(entry) for entry in entries])
