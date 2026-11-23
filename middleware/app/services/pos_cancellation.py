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
from app.services.inventory import restore_items
from app.services.original_sale import lock_original_sale

if TYPE_CHECKING:
    from app.api.schemas.pos import PosEvent


def process_cancellation(session: Session, event: PosEvent, principal: Principal) -> dict:
    validate_event_source(session, principal, event.store_id, event.pos_id)
    original_id = event.original_transaction_id
    if original_id is None:
        raise ApiError(422, "INVALID_EVENT", "original_transaction_id is required for CANCELLATION.")
    # One locked read answers both questions the old code asked separately
    # (audit minor, POS/API group): an unknown sale is 404
    # ORIGINAL_SALE_NOT_FOUND before the FK-bearing claim row is inserted, which is
    # where DS-04 puts that check, and the row comes back with its sold and
    # returned quantities. The update lock is held until this transaction ends, so
    # the second lock_original_sale the old code took after the claim was
    # re-reading a row it already held.
    sale = lock_original_sale(session, event.store_id, original_id)
    payload_hash = content_hash("CANCELLATION", event.store_id, event.pos_id, original_id, [])
    if not claim_transaction(session, event.transaction_id, event.store_id, event.pos_id,
                             "CANCELLATION", original_id, payload_hash, event.timestamp):
        return {
            "outcome": "DUPLICATE", "code": "DUPLICATE_IGNORED",
            "message": "Transaction already recorded",
            "current_stock": stock_of_transaction(session, event.store_id, event.transaction_id),
        }
    if sale.status == "CANCELLED":
        raise ApiError(409, "SALE_ALREADY_CANCELLED", f"Sale '{original_id}' has already been cancelled.")
    if any(quantity > 0 for quantity in sale.returned.values()):
        raise ApiError(409, "SALE_HAS_RETURNS", f"Sale '{original_id}' already has returns.")
    add_transaction_items(session, event.transaction_id, repository.sale_items(session, sale.txn_id))
    current_stock = restore_items(
        session,
        event.store_id,
        [(sku, sale.sold[sku]) for sku in sorted(sale.sold)],
        original_txn_id=original_id,
        txn_id=event.transaction_id,
        movement_type="CANCELLATION",
    )
    repository.mark_cancelled(session, sale.txn_id)
    return {"outcome": "OK", "code": "OK", "message": "Event applied", "current_stock": current_stock}
