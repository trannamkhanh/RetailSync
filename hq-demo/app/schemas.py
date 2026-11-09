"""DS-04 SyncBatchMessage, SalesLine and the mode body."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modes import Mode


# Ids are varchar in SQL Server: ASCII only, like the middleware ids.
ID_PATTERN = r"^[A-Za-z0-9_-]+$"
# The matching SQL Server columns are int (32-bit); a larger value must be 422.
INT_MAX = 2_147_483_647


class SalesLine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sku: str = Field(min_length=1, max_length=20, pattern=ID_PATTERN)
    sold_qty: int = Field(ge=0, le=INT_MAX)
    returned_qty: int = Field(ge=0, le=INT_MAX)
    net_revenue: Decimal = Field(max_digits=14, decimal_places=2)

    @field_validator("net_revenue", mode="before")
    @classmethod
    def _is_a_json_number(cls, value: object) -> object:
        if isinstance(value, (str, bool)):
            raise ValueError("must be a JSON number.")
        return value


class SyncBatchMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    batch_id: str = Field(min_length=1, max_length=40, pattern=ID_PATTERN)
    store_id: str = Field(min_length=1, max_length=10, pattern=ID_PATTERN)
    created_at: datetime
    txn_count: int = Field(ge=1, le=INT_MAX)
    lines: list[SalesLine] = Field(min_length=1)

    @field_validator("lines")
    @classmethod
    def _one_line_per_sku(cls, lines: list[SalesLine]) -> list[SalesLine]:
        skus = [line.sku for line in lines]
        if len(skus) != len(set(skus)):
            raise ValueError("must not repeat a sku.")
        return lines


class ModeUpdate(BaseModel):
    mode: Mode
