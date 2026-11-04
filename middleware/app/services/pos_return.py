"""RETURN processing (PB-06): validate the original sale, refund stock safely."""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.core.security import Principal
from app.repositories.pos_events import add_transaction_items, find_existing_skus
from app.services.event_validation import validate_event_source
from app.services.idempotency import claim_transaction, content_hash, stock_of_transaction
from app.services.inventory import apply_stock_change
from app.services.original_sale import lock_original_sale, require_original_sale

if TYPE_CHECKING:
    from app.api.schemas.pos import PosEvent


APPLIED_MESSAGE = "Event applied"
DUPLICATE_MESSAGE = "Transaction already recorded"


def _duplicate_result(session: Session, store_id: str, txn_id: str) -> dict:
    return {
        "outcome": "DUPLICATE",
        "code": "DUPLICATE_IGNORED",
        "message": DUPLICATE_MESSAGE,
        "current_stock": stock_of_transaction(session, store_id, txn_id),
    }


def _missing_sku(sku: str) -> ApiError:
    return ApiError(422, "INVALID_EVENT", f"Invalid field 'items': SKU '{sku}' does not exist.")


def process_return(session: Session, event: PosEvent, principal: Principal) -> dict:
    """Apply one RETURN in the caller's transaction and return the result body."""
    validate_event_source(session, principal, event.store_id, event.pos_id)

    existing = find_existing_skus(session, (item.sku for item in event.items))
    missing = [item.sku for item in event.items if item.sku not in existing]
    if missing:
        raise _missing_sku(missing[0])

    original_id = event.original_transaction_id
    if original_id is None:
        raise ApiError(422, "INVALID_EVENT",
                       "Invalid field 'original_transaction_id': is required for RETURN")
    require_original_sale(session, event.store_id, original_id)

    # The RETURN row inserted by claim_transaction has a foreign key to the
    # sale. SQL Server takes a shared lock for that check; two claims that both
    # insert before taking the sale's update lock would deadlock. Take the
    # update lock first, then claim; lock_original_sale below re-reads the
    # locked row and returns the quantities used for the business rules.
    lock_original_sale(session, event.store_id, original_id)

    payload_hash = content_hash(
        event.event_type,
        event.store_id,
        event.pos_id,
        original_id,
        [(item.sku, item.quantity, item.unit_price) for item in event.items],
    )
    claimed = claim_transaction(
        session,
        event.transaction_id,
        event.store_id,
        event.pos_id,
        event.event_type,
        original_id,
        payload_hash,
    )
    if not claimed:
        return _duplicate_result(session, event.store_id, event.transaction_id)

    sale = lock_original_sale(session, event.store_id, original_id)
    if sale.status == "CANCELLED":
        raise ApiError(409, "SALE_ALREADY_CANCELLED",
                       f"Sale '{original_id}' has already been cancelled.")

    merged: Counter[str] = Counter()
    for item in event.items:
        merged[item.sku] += item.quantity
    for sku in sorted(merged):
        remaining = sale.sold.get(sku, 0) - sale.returned.get(sku, 0)
        if merged[sku] > remaining:
            raise ApiError(
                409,
                "RETURN_QTY_EXCEEDED",
                f"Return quantity for SKU '{sku}' exceeds the sold quantity.",
            )

    add_transaction_items(
        session,
        event.transaction_id,
        [(item.sku, item.quantity, item.unit_price) for item in event.items],
    )
    current_stock: dict[str, int] = {}
    for sku in sorted(merged):
        current_stock[sku] = apply_stock_change(
            session,
            event.store_id,
            sku,
            merged[sku],
            "RETURN",
            txn_id=event.transaction_id,
        )
    return {
        "outcome": "OK",
        "code": "OK",
        "message": APPLIED_MESSAGE,
        "current_stock": current_stock,
    }
