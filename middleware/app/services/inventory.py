"""Stock service: apply signed changes and deduct a basket of SKUs.

All functions take a session and never commit. The caller (a router) owns the
transaction, so a later failure rolls the stock change and its movement back
together.
"""

from collections import Counter

from sqlalchemy.orm import Session

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


def get_stock(session: Session, store_id: str, sku: str) -> int:
    """Current quantity of one SKU in one store; 0 when no row exists."""
    return inventory_repository.get_stock(session, store_id, sku)


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
            raise ApiError(
                409,
                "INSUFFICIENT_STOCK",
                f"Not enough stock for SKU {sku} at store {store_id}",
            )
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
    """Deduct one or more SKUs for a sale in the caller's transaction.

    Repeated SKUs are merged first, then processed in sorted SKU order, so
    concurrent sales lock rows in the same order and deadlocks are avoided.

    Args:
        session: SQLAlchemy session; the caller commits or rolls back.
        store_id: Store identifier.
        items: ``(sku, quantity)`` pairs; every quantity must be above zero.
        txn_id: ``pos_transaction`` row the sale belongs to.

    Returns:
        New quantity per SKU, after all deductions.

    Raises:
        ValueError: if ``items`` is empty or a quantity is not above zero.
        ApiError(409, "INSUFFICIENT_STOCK"): if any SKU is short; the caller
            rolls back, so earlier deductions are discarded.
    """
    merged: Counter[str] = Counter()
    for sku, quantity in items:
        if quantity <= 0:
            raise ValueError(f"quantity must be above zero for SKU {sku}")
        merged[sku] += quantity
    if not merged:
        raise ValueError("items must not be empty")

    result: dict[str, int] = {}
    for sku in sorted(merged):
        result[sku] = apply_stock_change(
            session,
            store_id=store_id,
            sku=sku,
            delta=-merged[sku],
            movement_type="SALE",
            txn_id=txn_id,
        )
    return result
