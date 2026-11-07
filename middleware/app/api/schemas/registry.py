"""DS-04 Store and PosTerminal bodies for the registration endpoints."""

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


# Ids are varchar in SQL Server, so non-ASCII characters would be stored as "?".
ID_PATTERN = r"^[A-Za-z0-9_-]+$"
# name is nvarchar(100): SQL Server counts UTF-16 code units, so one emoji uses two.
NAME_UTF16_LIMIT = 100


def utf16_units(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


class StoreCreate(BaseModel):
    store_id: str = Field(min_length=1, max_length=10, pattern=ID_PATTERN)
    name: str = Field(min_length=1, max_length=100)
    latitude: Decimal = Field(ge=Decimal("-90"), le=Decimal("90"), decimal_places=6)
    longitude: Decimal = Field(ge=Decimal("-180"), le=Decimal("180"), decimal_places=6)
    region_id: str = Field(min_length=1, max_length=10, pattern=ID_PATTERN)
    is_active: bool = True

    @field_validator("name")
    @classmethod
    def _fits_the_nvarchar_column(cls, value: str) -> str:
        """max_length counts code points; nvarchar(100) counts UTF-16 units."""
        if utf16_units(value) > NAME_UTF16_LIMIT:
            raise ValueError(
                "must fit 100 UTF-16 code units, because nvarchar(100) counts an "
                "emoji as two characters.")
        return value


class StoreRead(BaseModel):
    """Coordinates stay JSON numbers, which decimal columns cannot be."""

    model_config = ConfigDict(from_attributes=True)

    store_id: str
    name: str
    latitude: float
    longitude: float
    region_id: str
    is_active: bool


class PosTerminalCreate(BaseModel):
    pos_id: str = Field(min_length=1, max_length=20, pattern=ID_PATTERN)
    store_id: str = Field(min_length=1, max_length=10, pattern=ID_PATTERN)
    cert_fingerprint: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    status: Literal["ACTIVE", "INACTIVE"] = "ACTIVE"


class PosTerminalRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    pos_id: str
    store_id: str
    cert_fingerprint: str | None
    status: str
