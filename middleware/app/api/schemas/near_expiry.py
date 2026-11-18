"""DS-04 NearExpiryThreshold bodies for the admin endpoints (PB-21) and the
DS-04 NearExpiryAlert body for the staff list (PB-34)."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# product.category is varchar(50). DS-04 allows letters, digits, space, _ and -,
# so a category may contain single spaces between words, but no leading, trailing
# or repeated space: "Dry goods" is valid, " Dry goods", "Dry goods " and "   " are not.
CATEGORY_PATTERN = r"^[A-Za-z0-9_-]+(?: [A-Za-z0-9_-]+)*$"
CATEGORY_MAX_LENGTH = 50
MAX_THRESHOLD_DAYS = 3650


class NearExpiryThresholdRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    category: str
    threshold_days: int = Field(ge=0, le=MAX_THRESHOLD_DAYS)


class NearExpiryThresholdUpdate(BaseModel):
    """Only threshold_days is accepted, and it must be a JSON integer.

    ``strict=True`` rejects a decimal, a string and a boolean, so a bad value is
    a 422 and never reaches the service.
    """

    model_config = ConfigDict(extra="forbid")

    threshold_days: int = Field(strict=True, ge=0, le=MAX_THRESHOLD_DAYS)


class NearExpiryThresholdList(BaseModel):
    items: list[NearExpiryThresholdRead]


class NearExpiryAlertRead(BaseModel):
    """DS-04 NearExpiryAlert; ``days_to_expiry`` is computed at read time (PB-34).

    ``alert_type`` is EXPIRED whenever the recomputed count is negative, so a
    batch that expired after the last daily check is still shown as EXPIRED.
    """

    alert_id: int
    batch_id: str
    sku: str
    expiry_date: date
    remaining_qty: int = Field(ge=0)
    days_to_expiry: int
    alert_type: Literal["NEAR_EXPIRY", "EXPIRED"]


class NearExpiryAlertList(BaseModel):
    items: list[NearExpiryAlertRead]
