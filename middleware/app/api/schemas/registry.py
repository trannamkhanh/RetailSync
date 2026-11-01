"""DS-04 Store and PosTerminal bodies for the registration endpoints."""

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StoreCreate(BaseModel):
    store_id: str = Field(max_length=10)
    name: str = Field(max_length=100)
    latitude: Decimal = Field(ge=Decimal("-90"), le=Decimal("90"))
    longitude: Decimal = Field(ge=Decimal("-180"), le=Decimal("180"))
    region_id: str = Field(max_length=10)
    is_active: bool = True


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
    pos_id: str = Field(max_length=20)
    store_id: str = Field(max_length=10)
    cert_fingerprint: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    status: Literal["ACTIVE", "INACTIVE"] = "ACTIVE"


class PosTerminalRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    pos_id: str
    store_id: str
    cert_fingerprint: str | None
    status: str
