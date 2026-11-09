"""DS-04 StockLine, its barcode batch detail and the store inventory response."""

from datetime import date

from pydantic import BaseModel, Field


class BatchInfo(BaseModel):
    batch_id: str
    expiry_date: date
    quantity: int = Field(ge=0)


class StockLine(BaseModel):
    sku: str
    quantity: int
    batches: list[BatchInfo] = Field(default_factory=list)


class StoreInventory(BaseModel):
    store_id: str
    items: list[StockLine]
