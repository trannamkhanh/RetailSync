"""DS-04 POS event bodies for ``POST /api/v1/pos/events``."""

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, StrictInt, ValidationInfo, field_validator


# Ids are varchar in SQL Server, so non-ASCII characters would be stored as "?".
ID_PATTERN = r"^[A-Za-z0-9_-]+$"
MAX_ITEMS = 100
MAX_QUANTITY = 1_000_000


class PosEventItem(BaseModel):
    sku: str = Field(min_length=1, max_length=20, pattern=ID_PATTERN)
    quantity: StrictInt = Field(gt=0, le=MAX_QUANTITY)
    unit_price: Decimal = Field(
        ge=0, le=Decimal("9999999999.99"), max_digits=12, decimal_places=2
    )


class PosEvent(BaseModel):
    event_type: Literal["SALE", "RETURN", "CANCELLATION"]
    transaction_id: str = Field(min_length=1, max_length=40, pattern=ID_PATTERN)
    original_transaction_id: str | None = Field(
        default=None, min_length=1, max_length=40, pattern=ID_PATTERN,
        validate_default=True,
    )
    store_id: str = Field(min_length=1, max_length=10, pattern=ID_PATTERN)
    pos_id: str = Field(min_length=1, max_length=20, pattern=ID_PATTERN)
    timestamp: datetime
    items: list[PosEventItem] = Field(
        default_factory=list, max_length=MAX_ITEMS, validate_default=True
    )

    @field_validator("original_transaction_id")
    @classmethod
    def original_transaction_matches_event_type(
        cls, value: str | None, info: ValidationInfo
    ) -> str | None:
        event_type = info.data.get("event_type")
        if event_type in ("RETURN", "CANCELLATION") and value is None:
            raise ValueError(f"is required for {event_type}")
        if event_type == "SALE" and value is not None:
            raise ValueError("must be absent for SALE")
        return value

    @field_validator("items")
    @classmethod
    def items_match_event_type(cls, value: list[PosEventItem],
                               info: ValidationInfo) -> list[PosEventItem]:
        event_type = info.data.get("event_type")
        if event_type in ("SALE", "RETURN") and not value:
            raise ValueError(f"at least one item is required for {event_type}")
        return value


class PosEventResult(BaseModel):
    outcome: Literal["OK", "DUPLICATE"]
    code: Literal["OK", "DUPLICATE_IGNORED"]
    message: str
    current_stock: dict[str, int]
