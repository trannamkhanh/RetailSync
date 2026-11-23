"""Active discounts for staff and POS (PB-50).

Money and percentages are JSON numbers, as in ``products.py`` (audit #7).
"""

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, field_serializer


class StaffDiscount(BaseModel):
    store_id: str
    store_name: str
    distance_km: float | None
    sku: str
    name: str
    batch_id: str | None
    expiry_date: date | None
    discount_pct: Decimal
    list_price: Decimal
    discounted_price: Decimal
    decided_at: datetime
    sold_at_discount: bool

    @field_serializer("discount_pct", "list_price", "discounted_price", when_used="json")
    def serialize_money(self, value: Decimal) -> float:
        return float(value)


class StaffDiscountList(BaseModel):
    items: list[StaffDiscount]


class PosDiscount(BaseModel):
    sku: str
    discount_pct: Decimal
    discounted_price: Decimal

    @field_serializer("discount_pct", "discounted_price", when_used="json")
    def serialize_money(self, value: Decimal) -> float:
        return float(value)


class PosDiscountList(BaseModel):
    business_date: date
    items: list[PosDiscount]
