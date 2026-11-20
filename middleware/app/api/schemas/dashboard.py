"""Dashboard response bodies (plan B4).

Two serializers carry the contract:

* Money is a JSON **number** with two decimals. Pydantic v2 emits a ``Decimal`` as
  a string, which DS-04 forbids, so every money field converts to ``float`` at
  this boundary. The database and the service still work with the exact
  ``Decimal``; only the wire form changes.
* Every timestamp is ISO 8601 UTC with a ``Z``, as the rest of the contract does.
  The stored values are naive UTC, so the offset is appended, not converted.

The models are read-only views of the service's results: they never decide
anything, so a scope or a total cannot be changed here. ``from``/``to`` are
Python keywords, so the bucket fields are named ``from_time``/``to_time`` and
carry a serialization alias; FastAPI serializes response models by alias.
"""

from datetime import datetime, timezone
from decimal import Decimal

from pydantic import BaseModel, Field, field_serializer


def _as_utc(value: datetime | None) -> str | None:
    """``...Z`` for a stored UTC value, normalising an aware one to UTC first."""
    if value is None:
        return None
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return f"{value.isoformat()}Z"


def _as_number(value: Decimal) -> float:
    """Two-decimal money as a JSON number, never a string."""
    return float(round(value, 2))


class DashboardScope(BaseModel):
    """Which scope answered, so the caller can tell the two apart."""

    store_id: str | None
    is_system_wide: bool


class DashboardTimePolicy(BaseModel):
    """The thresholds the server applied; the console shows them, never recomputes."""

    max_future_skew_seconds: int
    max_backfill_days: int


class DashboardTimeQuality(BaseModel):
    """The five labels of the selected interval; they always add up."""

    on_time: int
    backfill: int
    suspect_future: int
    suspect_old: int
    unknown: int


class DashboardBucket(BaseModel):
    """One point of the line chart, over the half-open bucket ``[from, to)``."""

    from_time: datetime = Field(serialization_alias="from")
    to_time: datetime = Field(serialization_alias="to")
    revenue: Decimal
    transactions: int

    @field_serializer("from_time", "to_time")
    def _times(self, value: datetime) -> str:
        return _as_utc(value)

    @field_serializer("revenue")
    def _money(self, value: Decimal) -> float:
        return _as_number(value)


class DashboardRevenue(BaseModel):
    """The line chart, the KPI and the quality badge of the interval."""

    scope: DashboardScope
    time_policy: DashboardTimePolicy
    data_from: datetime | None
    data_to: datetime | None
    has_data: bool
    total_revenue: Decimal
    transactions: int
    quality: DashboardTimeQuality
    buckets: list[DashboardBucket]

    @field_serializer("data_from", "data_to")
    def _span(self, value: datetime | None) -> str | None:
        return _as_utc(value)

    @field_serializer("total_revenue")
    def _money(self, value: Decimal) -> float:
        return _as_number(value)


class DashboardCategory(BaseModel):
    """One slice of the pie chart; a negative slice is returned as it is."""

    category: str
    revenue: Decimal
    share: Decimal

    @field_serializer("revenue")
    def _money(self, value: Decimal) -> float:
        return _as_number(value)

    @field_serializer("share")
    def _fraction(self, value: Decimal) -> float:
        return float(value)


class DashboardCategoryRevenue(BaseModel):
    """The pie chart plus its KPI and quality."""

    scope: DashboardScope
    time_policy: DashboardTimePolicy
    total_revenue: Decimal
    transactions: int
    quality: DashboardTimeQuality
    categories: list[DashboardCategory]

    @field_serializer("total_revenue")
    def _money(self, value: Decimal) -> float:
        return _as_number(value)


class DashboardStoreRevenue(BaseModel):
    """One column of the comparison chart."""

    store_id: str
    name: str
    region_id: str
    revenue: Decimal
    share: Decimal

    @field_serializer("revenue")
    def _money(self, value: Decimal) -> float:
        return _as_number(value)

    @field_serializer("share")
    def _fraction(self, value: Decimal) -> float:
        return float(value)


class DashboardStoreRevenueResponse(BaseModel):
    """The bar chart plus its KPI and quality."""

    scope: DashboardScope
    time_policy: DashboardTimePolicy
    data_from: datetime | None
    data_to: datetime | None
    has_data: bool
    total_revenue: Decimal
    transactions: int
    quality: DashboardTimeQuality
    stores: list[DashboardStoreRevenue]

    @field_serializer("data_from", "data_to")
    def _span(self, value: datetime | None) -> str | None:
        return _as_utc(value)

    @field_serializer("total_revenue")
    def _money(self, value: Decimal) -> float:
        return _as_number(value)


class DashboardStore(BaseModel):
    """One entry of ``GET /dashboard/stores``."""

    store_id: str
    name: str
    region_id: str
    is_active: bool


class DashboardStoreList(BaseModel):
    """The store list of the caller's scope."""

    stores: list[DashboardStore]