"""Pydantic response models for the store web API.

``unit_price`` stays a string with two decimals: money is never a float in
JSON. ``nearest_expiry`` is a date or null.
"""

from datetime import date

from pydantic import BaseModel, Field


class Health(BaseModel):
    status: str
    database: str


class ErrorBody(BaseModel):
    outcome: str
    code: str
    message: str


class StoreCard(BaseModel):
    store_id: str
    name: str
    region_id: str
    address_text: str | None = None
    product_count: int
    sellable_units: int


class StoreDetail(StoreCard):
    expired_units: int


class StoreList(BaseModel):
    stores: list[StoreCard]


class BatchItem(BaseModel):
    batch_id: str
    expiry_date: date
    quantity: int
    sellable: bool


class StoreSuggestion(BaseModel):
    """A store that can sell a product, with how far away it is."""

    store_id: str
    name: str
    region_id: str
    address_text: str | None = None
    sellable_quantity: int
    distance_km: float
    distance_kind: str


class ProductItem(BaseModel):
    sku: str
    barcode: str
    name: str
    category: str
    unit_price: str
    image_url: str | None = None
    quantity: int
    sellable_quantity: int
    expired_quantity: int
    nearest_expiry: date | None = None
    batches: list[BatchItem] = Field(default_factory=list)
    # Where else the product can be bought, nearest first. The store being viewed
    # comes first when it has stock, so it reads as "buy it here".
    nearest_store: StoreSuggestion | None = None


class ProductPage(BaseModel):
    store_id: str
    total: int
    limit: int
    offset: int
    items: list[ProductItem]


class ProductDetail(BaseModel):
    store_id: str
    item: ProductItem


class Categories(BaseModel):
    categories: list[str]


# --- Customer shop ---------------------------------------------------------


class CustomerProfile(BaseModel):
    customer_id: int
    email: str
    full_name: str


class RegisterRequest(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    full_name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=8, max_length=200)


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    password: str = Field(min_length=1, max_length=200)


class AuthSession(BaseModel):
    customer: CustomerProfile


class AddressItem(BaseModel):
    address_id: str
    label: str
    address_text: str
    latitude: float
    longitude: float


class AddressList(BaseModel):
    addresses: list[AddressItem]


class NewAddress(BaseModel):
    label: str = Field(min_length=1, max_length=60)
    address_text: str = Field(min_length=1, max_length=300)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class ShopProduct(BaseModel):
    sku: str
    barcode: str
    name: str
    category: str
    unit_price: str
    image_url: str | None = None
    stores: list[StoreSuggestion]
    nearest: StoreSuggestion | None = None


class ShopSearch(BaseModel):
    q: str
    latitude: float
    longitude: float
    total: int
    items: list[ShopProduct]

