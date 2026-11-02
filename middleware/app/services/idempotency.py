"""Canonical POS hashes and idempotent claims in the caller's transaction."""

import hashlib
import json
from decimal import Decimal

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.repositories import idempotency as repository
from app.services.inventory import get_stock


def content_hash(
    event_type: str, store_id: str, pos_id: str,
    original_transaction_id: str | None,
    items: list[tuple[str, int, Decimal]],
) -> str:
    lines = [] if event_type == "CANCELLATION" else [
        {"sku": sku, "quantity": quantity, "unit_price": format(price, ".2f")}
        for sku, quantity, price in sorted(items, key=lambda item: (item[0], item[1], item[2]))
    ]
    payload = {
        "event_type": event_type, "store_id": store_id, "pos_id": pos_id,
        "original_transaction_id": original_transaction_id, "items": lines,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _duplicate(existing_hash: str, payload_hash: str) -> bool:
    if existing_hash != payload_hash:
        raise ApiError(409, "CONFLICT", "Transaction ID already recorded with different content.")
    return False


def claim_transaction(
    session: Session, txn_id: str, store_id: str, pos_id: str, txn_type: str,
    ref_txn_id: str | None, payload_hash: str,
) -> bool:
    existing = repository.find_payload_hash(session, txn_id)
    if existing is not None:
        return _duplicate(existing, payload_hash)
    try:
        with session.begin_nested():
            repository.insert_transaction(
                session, txn_id, store_id, pos_id, txn_type, ref_txn_id, payload_hash,
            )
    except IntegrityError:
        existing = repository.find_payload_hash(session, txn_id)
        if existing is None:
            raise
        return _duplicate(existing, payload_hash)
    return True


def stock_of_transaction(session: Session, store_id: str, txn_id: str) -> dict[str, int]:
    return {
        sku: get_stock(session, store_id, sku)
        for sku in repository.transaction_skus(session, store_id, txn_id)
    }
