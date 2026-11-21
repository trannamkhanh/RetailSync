"""Canonical POS hashes and idempotent claims in the caller's transaction."""

import hashlib
import json
from datetime import datetime, timezone
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


def _to_utc_naive(value: datetime | None) -> datetime | None:
    """A naive timestamp is already UTC; an offset is converted before storing.

    ``pos_transaction`` keeps ``datetime2`` without an offset, as every other
    table does, and the convention (DS-04) is that a value without one is UTC.

    A timestamp within one offset of ``datetime.min`` or ``datetime.max`` cannot be
    converted: ``0001-01-01T00:00:00+07:00`` is a legal instant that the UTC
    conversion pushes out of range, and ``astimezone`` raises ``OverflowError``.
    Raising there would answer 503 for an accepted event, so the value is clamped
    to the nearest representable instant instead. The stored moment is then a
    boundary value, which the classifier reports as ``SUSPECT_FUTURE`` or
    ``SUSPECT_OLD`` rather than silently trusting it (Dashboard_Review 4.4).
    """
    if value is None or value.tzinfo is None:
        return value
    try:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    except (OverflowError, ValueError):
        # The conversion left the representable range. An early year underflowed below
        # datetime.min; anything else overflowed above datetime.max. Both are pinned to
        # the representable edge, which the classifier then reports as suspect.
        return datetime.min if value.year < 2 else datetime.max.replace(microsecond=0)


def claim_transaction(
    session: Session, txn_id: str, store_id: str, pos_id: str, txn_type: str,
    ref_txn_id: str | None, payload_hash: str, occurred_at: datetime | None = None,
) -> bool:
    """Claim ``txn_id`` and store ``occurred_at`` on the first one only.

    ``occurred_at`` is the moment the POS declares, never the moment of arrival,
    and it is never overwritten: a duplicate returns before anything is written,
    so a resend with a different timestamp keeps the first value.
    """
    existing = repository.find_payload_hash(session, txn_id)
    if existing is not None:
        return _duplicate(existing, payload_hash)
    occurred = _to_utc_naive(occurred_at)
    try:
        with session.begin_nested():
            repository.insert_transaction(
                session, txn_id, store_id, pos_id, txn_type, ref_txn_id, payload_hash,
                occurred,
            )
    except IntegrityError:
        existing = repository.find_payload_hash(session, txn_id)
        if existing is None:
            raise
        return _duplicate(existing, payload_hash)
    return True


def stored_occurred_at(session: Session, txn_id: str) -> datetime | None:
    """The ``occurred_at`` of the stored transaction, or ``None`` when it has none."""
    return repository.find_occurred_at(session, txn_id)


def stock_of_transaction(session: Session, store_id: str, txn_id: str) -> dict[str, int]:
    return {
        sku: get_stock(session, store_id, sku)
        for sku in repository.transaction_skus(session, store_id, txn_id)
    }
