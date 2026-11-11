"""Own-store barcode result with batch expiry detail."""

from decimal import Decimal

from pydantic import BaseModel, Field, field_serializer

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
