"""POS event processing (PB-05): SALE validation, idempotency and stock.

The router owns the commit. This module never commits, so a failure after the
stock change rolls the transaction, its items and its movements back together.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.core.security import Principal
from app.repositories import pos_events as repository
from app.services.event_validation import validate_event_source
from app.services.idempotency import claim_transaction, content_hash, stock_of_transaction
from app.services.inventory import deduct_items

if TYPE_CHECKING:
    from app.api.schemas.pos import PosEvent


DUPLICATE_MESSAGE = "Transaction already recorded"
APPLIED_MESSAGE = "Event applied"


def _unsupported(event_type: str) -> ApiError:
    return ApiError(422, "INVALID_EVENT", f"Event type {event_type} is not available yet.")


def _missing_sku(sku: str) -> ApiError:
    return ApiError(422, "INVALID_EVENT", f"Invalid field 'items': SKU '{sku}' does not exist.")


def _duplicate_result(session: Session, store_id: str, txn_id: str) -> dict:
    return {
        "outcome": "DUPLICATE",
        "code": "DUPLICATE_IGNORED",
        "message": DUPLICATE_MESSAGE,
        "current_stock": stock_of_transaction(session, store_id, txn_id),
    }


def _process_sale(session: Session, event: PosEvent, principal: Principal) -> dict:
    validate_event_source(session, principal, event.store_id, event.pos_id)

    existing = repository.find_existing_skus(session, (item.sku for item in event.items))
    missing = [item.sku for item in event.items if item.sku not in existing]
    if missing:
        raise _missing_sku(missing[0])

    payload_hash = content_hash(
        event.event_type,
        event.store_id,
        event.pos_id,
        event.original_transaction_id,
        [(item.sku, item.quantity, item.unit_price) for item in event.items],
    )
    claimed = claim_transaction(
        session,
        event.transaction_id,
        event.store_id,
        event.pos_id,
        event.event_type,
        event.original_transaction_id,
        payload_hash,
    )
    if not claimed:
        return _duplicate_result(session, event.store_id, event.transaction_id)

    repository.add_transaction_items(
        session,
        event.transaction_id,
        [(item.sku, item.quantity, item.unit_price) for item in event.items],
    )
    current_stock = deduct_items(
        session,
        event.store_id,
        [(item.sku, item.quantity) for item in event.items],
        event.transaction_id,
    )
    return {
        "outcome": "OK",
        "code": "OK",
        "message": APPLIED_MESSAGE,
        "current_stock": current_stock,
    }


def process_event(session: Session, event: PosEvent, principal: Principal) -> dict:
    """Apply one POS event in the caller's transaction and return the result body.

    SALE is implemented now. RETURN and CANCELLATION keep their own branches so
    PB-06 and PB-07 can plug in without rewriting the SALE flow.
    """
    if event.event_type == "SALE":
        return _process_sale(session, event, principal)
    raise _unsupported(event.event_type)
