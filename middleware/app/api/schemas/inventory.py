"""DS-04 StockLine and the store inventory response."""

from pydantic import BaseModel


class StockLine(BaseModel):
    sku: str
    quantity: int


class StoreInventory(BaseModel):
    store_id: str
    items: list[StockLine]
