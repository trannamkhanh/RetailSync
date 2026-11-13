"""Own-store barcode result with batch detail, and cross-store stock (PB-31, PB-35)."""

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.api.schemas.inventory import BatchInfo


class ProductLookup(BaseModel):
    sku: str
    barcode: str
    name: str
    category: str
    unit_price: Decimal
    quantity: int = Field(ge=0)
    batches: list[BatchInfo] = Field(default_factory=list)

    @field_serializer("unit_price", when_used="json")
    def serialize_price(self, value: Decimal) -> float:
        return float(value)


class CrossStoreLine(BaseModel):
    """One store of the answer; ``distance_km`` is haversine, rounded to 2 decimals."""

    store_id: str
    name: str
    qty: int = Field(ge=0)
    distance_km: float = Field(ge=0)


class CrossStoreStock(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    sku: str
    stores: list[CrossStoreLine]
