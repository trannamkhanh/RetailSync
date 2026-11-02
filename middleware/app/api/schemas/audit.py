"""DS-04 AuditEntry and the audit query response."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_serializer


class AuditEntry(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    audit_id: int
    user_id: int | None
    action: str
    entity_name: str
    entity_key: str | None
    details: str | None
    created_at: datetime

    @field_serializer("created_at")
    def _as_utc(self, value: datetime) -> str:
        """audit_log stores UTC without an offset."""
        return f"{value.isoformat()}Z"


class AuditLogList(BaseModel):
    items: list[AuditEntry]
