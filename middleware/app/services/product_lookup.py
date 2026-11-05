"""Find a product before reading its caller-scoped inventory."""

from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.repositories import product_lookup as repository


def lookup_product(session: Session, barcode: str, store_id: str) -> dict:
    product = repository.find_product(session, barcode)
    if product is None:
        raise ApiError(404, "NOT_FOUND", "Product barcode was not found.")
    return {
        "sku": product.sku, "barcode": product.barcode, "name": product.name,
        "category": product.category, "unit_price": product.unit_price,
        "quantity": repository.quantity(session, store_id, product.sku),
    }
