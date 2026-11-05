"""Reverse a sale once, serialized with RETURN using the original-sale lock."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.core.security import Principal
from app.repositories import pos_cancellation as repository
from app.repositories.pos_events import add_transaction_items
from app.services.event_validation import validate_event_source
from app.services.idempotency import claim_transaction, content_hash, stock_of_transaction
from app.services.inventory import apply_stock_change
from app.services.original_sale import lock_original_sale, require_original_sale

if TYPE_CHECKING:
    from app.api.schemas.pos import PosEvent


def process_cancellation(session: Session, event: PosEvent, principal: Principal) -> dict:
    validate_event_source(session, principal, event.store_id, event.pos_id)
    original_id = event.original_transaction_id
    if original_id is None:
        raise ApiError(422, "INVALID_EVENT", "original_transaction_id is required for CANCELLATION.")
    require_original_sale(session, event.store_id, original_id)
    # Match process_return: take UPDLOCK before inserting the FK-bearing claim.
    # Otherwise concurrent events can deadlock while upgrading FK shared locks.
    lock_original_sale(session, event.store_id, original_id)
    payload_hash = content_hash("CANCELLATION", event.store_id, event.pos_id, original_id, [])
    if not claim_transaction(session, event.transaction_id, event.store_id, event.pos_id,
                             "CANCELLATION", original_id, payload_hash):
        return {
            "outcome": "DUPLICATE", "code": "DUPLICATE_IGNORED",
            "message": "Transaction already recorded",
            "current_stock": stock_of_transaction(session, event.store_id, event.transaction_id),
        }
    sale = lock_original_sale(session, event.store_id, original_id)
    if sale.status == "CANCELLED":
        raise ApiError(409, "SALE_ALREADY_CANCELLED", f"Sale '{original_id}' has already been cancelled.")
    if any(quantity > 0 for quantity in sale.returned.values()):
        raise ApiError(409, "SALE_HAS_RETURNS", f"Sale '{original_id}' already has returns.")
    add_transaction_items(session, event.transaction_id, repository.sale_items(session, sale.txn_id))
    current_stock = {
        sku: apply_stock_change(session, event.store_id, sku, sale.sold[sku],
                                "CANCELLATION", txn_id=event.transaction_id)
        for sku in sorted(sale.sold)
    }
    repository.mark_cancelled(session, sale.txn_id)
    return {"outcome": "OK", "code": "OK", "message": "Event applied", "current_stock": current_stock}
