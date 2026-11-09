"""Stock service: apply signed changes, deduct a basket by FEFO, restore it.

All functions take a session and never commit. The caller (a router) owns the
transaction, so a later failure rolls the stock change, its batches and its
movement back together.

PB-20 changes what a stock change means: ``inventory.quantity`` is the sum of
``product_batch.quantity`` for the same store and SKU, expired batches included.
A sale takes stock from the batches that are still sellable, earliest expiry
first (FEFO); RETURN and CANCELLATION put the stock back into the batches the
sale took it from, newest expiry first. Both sides change the batch rows and the
inventory row in the same transaction, in that order, so two writers of one
store and SKU cannot deadlock.
"""

from collections import Counter
from datetime import timedelta
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core import clock
from app.core.errors import ApiError
from app.repositories import inventory as inventory_repository
from app.repositories.inventory import (
    add_movement,
    insert_stock_row,
    update_stock_with_guard,
)

# inventory_movement.movement_type values from 001_core.sql.
MOVEMENT_TYPES = frozenset(
    {
        "SALE",
        "RETURN",
        "CANCELLATION",
        "ADJUSTMENT",
        "STOCK_RECEIVED",
        "TRANSFER_IN",
        "TRANSFER_OUT",
    }
)

# A sale recorded before PB-20 has no batch_id on its movements, so a reversal
# has no batch to go back to. Sprint 3 decision 5 sends that stock to the newest
# batch of the store and SKU; when the store and SKU never had a batch, one is
# created with this prefix and a far future expiry, so the stock stays sellable.
LEGACY_BATCH_PREFIX = "LEGACY-"
LEGACY_BATCH_DAYS = 365


def get_stock(session: Session, store_id: str, sku: str) -> int:
    """Current quantity of one SKU in one store; 0 when no row exists."""
    return inventory_repository.get_stock(session, store_id, sku)


def sellable_stock(session: Session, store_id: str, sku: str) -> int:
    """Units of one SKU in one store that may still be sold (not expired).

    This is the sum of the batches whose ``expiry_date >= today_local()``, which
    is what the forecast and the cross-store lookup compare; ``inventory.quantity``
    also counts expired stock.
    """
    return inventory_repository.sum_sellable(session, store_id, sku, clock.today_local())


def apply_stock_change(
    session: Session,
    store_id: str,
    sku: str,
    delta: int,
    movement_type: str,
    txn_id: str | None = None,
    created_by: int | None = None,
    reason: str | None = None,
) -> int:
    """Apply one signed stock change and record its movement.

    This is the single-SKU primitive for changes that are not a sale, such as a
    delivery (``STOCK_RECEIVED``) or an adjustment. It does not touch
    ``product_batch``; the batch-aware paths are ``deduct_items`` and
    ``restore_items``, which a SALE, RETURN and CANCELLATION use.

    Args:
        session: SQLAlchemy session; the caller commits or rolls back.
        store_id: Store identifier.
        sku: Product identifier.
        delta: Signed change; positive adds stock, negative removes it.
        movement_type: One of the values accepted by 001_core.sql.
        txn_id: ``pos_transaction`` row this change belongs to, if any.
        created_by: ``staff_user.user_id`` responsible for the change.
        reason: Free-text reason stored on the movement.

    Returns:
        The new quantity after the change.

    Raises:
        ValueError: if ``delta`` is 0 or ``movement_type`` is unknown.
        ApiError(409, "INSUFFICIENT_STOCK"): if ``delta`` is negative and the
            stock row is missing or does not have enough quantity.
    """
    if delta == 0:
        raise ValueError("delta must not be zero")
    if movement_type not in MOVEMENT_TYPES:
        raise ValueError(f"unknown movement_type: {movement_type}")

    new_quantity = update_stock_with_guard(session, store_id, sku, delta)
    if new_quantity is None:
        if delta < 0:
            raise _insufficient_stock(store_id, sku)
        # A positive change for a SKU that has no inventory row yet.
        new_quantity = insert_stock_row(session, store_id, sku, delta)

    add_movement(
        session,
        store_id=store_id,
        sku=sku,
        movement_type=movement_type,
        quantity=delta,
        txn_id=txn_id,
        created_by=created_by,
        reason=reason,
    )
    return new_quantity


def deduct_items(
    session: Session,
    store_id: str,
    items: list[tuple[str, int]],
    txn_id: str,
) -> dict[str, int]:
    """Deduct one or more SKUs for a sale, earliest-expiring batch first.

    Repeated SKUs are merged first, then processed in sorted SKU order, so
    concurrent sales lock rows in the same order and deadlocks are avoided.

    For each SKU the sellable batches are locked in FEFO order and checked to
    cover the quantity before anything changes; a short SKU raises without
    touching a batch. Each batch that gives stock gets its own movement row with
    that ``batch_id``, and ``inventory`` is then updated by the existing guarded
    statement, so ``inventory.quantity`` stays the sum of the batches.

    Args:
        session: SQLAlchemy session; the caller commits or rolls back.
        store_id: Store identifier.
        items: ``(sku, quantity)`` pairs; every quantity must be above zero.
        txn_id: ``pos_transaction`` row the sale belongs to.

    Returns:
        New quantity per SKU, after all deductions.

    Raises:
        ValueError: if ``items`` is empty or a quantity is not above zero.
        ApiError(409, "INSUFFICIENT_STOCK"): if a SKU's sellable batches or its
            inventory row cannot cover the quantity. The caller rolls back, so
            earlier deductions are discarded and nothing changes.
    """
    merged = _merge_items(items)
    today = clock.today_local()
    return {
        sku: _deduct_sku(session, store_id, sku, merged[sku], txn_id, today)
        for sku in sorted(merged)
    }


def restore_items(
    session: Session,
    store_id: str,
    items: list[tuple[str, int]],
    *,
    original_txn_id: str,
    txn_id: str,
    movement_type: str,
) -> dict[str, int]:
    """Put stock back into the batches the original sale took it from.

    A RETURN restores what it returns, a CANCELLATION everything the sale took.
    Per batch the limit is what the sale took minus what earlier returns already
    put back, newest ``expiry_date`` first (DS-06 section 2). A batch that has
    expired since still gets its stock back; it is simply not sellable.

    A movement without ``batch_id`` (a sale from before PB-20) has no batch to
    go back to, so its stock joins the newest batch of the store and SKU.

    Args:
        session: SQLAlchemy session; the caller commits or rolls back.
        store_id: Store identifier.
        items: ``(sku, quantity)`` pairs to restore; quantities above zero.
        original_txn_id: SALE the reversal refers to.
        txn_id: ``pos_transaction`` row of the RETURN or CANCELLATION.
        movement_type: ``RETURN`` or ``CANCELLATION``.

    Returns:
        New quantity per SKU.

    Raises:
        ValueError: if ``movement_type`` is not a reversal, ``items`` is empty
            or a quantity is not above zero.
    """
    if movement_type not in ("RETURN", "CANCELLATION"):
        raise ValueError(f"{movement_type} is not a reversal")
    merged = _merge_items(items)
    taken = inventory_repository.sale_batch_quantities(session, store_id, original_txn_id)
    restored = inventory_repository.restored_batch_quantities(session, store_id, original_txn_id)
    return {
        sku: _restore_sku(session, store_id, sku, merged[sku], taken, restored,
                          txn_id=txn_id, movement_type=movement_type)
        for sku in sorted(merged)
    }


def _merge_items(items: list[tuple[str, int]]) -> Counter[str]:
    """Merge repeated SKUs and reject an empty basket or a non-positive quantity."""
    merged: Counter[str] = Counter()
    for sku, quantity in items:
        if quantity <= 0:
            raise ValueError(f"quantity must be above zero for SKU {sku}")
        merged[sku] += quantity
    if not merged:
        raise ValueError("items must not be empty")
    return merged


def _insufficient_stock(store_id: str, sku: str) -> ApiError:
    return ApiError(
        409,
        "INSUFFICIENT_STOCK",
        f"Not enough stock for SKU {sku} at store {store_id}",
    )


def _deduct_sku(session: Session, store_id: str, sku: str, quantity: int,
                txn_id: str, today) -> int:
    """Take ``quantity`` of one SKU from the sellable batches, FEFO."""
    batches = inventory_repository.lock_batches(
        session, store_id, sku, sellable_only=True, today=today,
    )
    if sum(int(batch.quantity) for batch in batches) < quantity:
        raise _insufficient_stock(store_id, sku)

    remaining = quantity
    for batch in batches:
        if remaining == 0:
            break
        take = min(int(batch.quantity), remaining)
        if take == 0:
            continue
        inventory_repository.deduct_batch(session, batch.batch_id, take)
        add_movement(
            session,
            store_id=store_id,
            sku=sku,
            movement_type="SALE",
            quantity=-take,
            txn_id=txn_id,
            batch_id=batch.batch_id,
        )
        remaining -= take

    new_quantity = update_stock_with_guard(session, store_id, sku, -quantity)
    if new_quantity is None:
        # The batches cover the sale but the inventory row does not: the data is
        # inconsistent, and the caller's rollback leaves everything unchanged.
        raise _insufficient_stock(store_id, sku)
    return new_quantity


def _restore_sku(session: Session, store_id: str, sku: str, quantity: int,
                 taken: dict[tuple[str, str | None], int],
                 restored: dict[tuple[str, str | None], int],
                 *, txn_id: str, movement_type: str) -> int:
    """Put ``quantity`` of one SKU back, newest expiry first."""
    batches = inventory_repository.lock_batches(session, store_id, sku, sellable_only=False)
    # Locked earliest first; the contract restores newest first.
    newest_first = list(reversed(batches))

    plan: dict[str, int] = {}
    if not newest_first:
        # The store and SKU never had a batch: create the batch the stock of a
        # legacy sale goes back to.
        batch_id = f"{LEGACY_BATCH_PREFIX}{uuid4().hex[:16].upper()}"
        inventory_repository.insert_batch(
            session, store_id, sku, batch_id, 0,
            clock.today_local() + timedelta(days=LEGACY_BATCH_DAYS),
        )
        plan[batch_id] = quantity
    else:
        remaining = quantity
        for batch in newest_first:
            if remaining == 0:
                break
            key = (sku, str(batch.batch_id))
            limit = max(0, taken.get(key, 0) - restored.get(key, 0))
            take = min(limit, remaining)
            if take:
                plan[str(batch.batch_id)] = take
                remaining -= take
        legacy_key = (sku, None)
        legacy_taken = max(0, taken.get(legacy_key, 0) - restored.get(legacy_key, 0))
        if remaining and legacy_taken:
            take = min(legacy_taken, remaining)
            newest = str(newest_first[0].batch_id)
            plan[newest] = plan.get(newest, 0) + take
            remaining -= take
        if remaining:
            # The sale's movements do not add up to what is being returned. The
            # stock still has to come back, so it joins the newest batch; the
            # caller's own quantity check (RETURN_QTY_EXCEEDED) makes this rare.
            newest = str(newest_first[0].batch_id)
            plan[newest] = plan.get(newest, 0) + remaining

    for batch_id, put_back in plan.items():
        inventory_repository.add_batch_quantity(session, batch_id, put_back)
        add_movement(
            session,
            store_id=store_id,
            sku=sku,
            movement_type=movement_type,
            quantity=put_back,
            txn_id=txn_id,
            batch_id=batch_id,
        )

    new_quantity = update_stock_with_guard(session, store_id, sku, quantity)
    if new_quantity is None:
        new_quantity = insert_stock_row(session, store_id, sku, quantity)
    return new_quantity
