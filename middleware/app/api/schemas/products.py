"""Sprint 2 barcode result; batch details arrive with PB-31-2."""

from decimal import Decimal

from pydantic import BaseModel, Field, field_serializer


class ProductLookup(BaseModel):
    sku: str
    barcode: str
    name: str
    category: str
    unit_price: Decimal
    quantity: int = Field(ge=0)

    @field_serializer("unit_price", when_used="json")
    def serialize_price(self, value: Decimal) -> float:
        return float(value)
