"""PB-53 own-store forecast response. Decimal quantities are JSON numbers."""
from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from pydantic import BaseModel, field_serializer


class StaffForecast(BaseModel):
    sku: str
    name: str
    category: str
    horizon_days: int
    predicted_demand: Decimal
    sellable_stock: int
    surplus_shortage: Decimal
    balance_status: Literal["SHORTAGE", "SURPLUS", "BALANCED"]
    model_version: str
    created_at: datetime
    sold_last_7_days: int

    @field_serializer("predicted_demand", "surplus_shortage", when_used="json")
    def serialize_quantity(self, value: Decimal) -> float:
        return float(value)


class StaffForecastList(BaseModel):
    business_date: date
    items: list[StaffForecast]
