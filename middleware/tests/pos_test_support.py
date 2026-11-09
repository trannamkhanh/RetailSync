"""Shared builders for POS RETURN and audit tests. Not collected by pytest."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import clock
from app.core.security import create_token
from app.domain.models import (
    AuditLog,
    Inventory,
    InventoryMovement,
    PosTerminal,
    PosTransaction,
    Product,
    ProductBatch,
    StaffUser,
    Store,
    TransactionItem,
)
from app.services.inventory import deduct_items


URL = "/api/v1/pos/events"

# A batch created by the helpers is sellable unless a test asks for another date.
DEFAULT_BATCH_DAYS = 30


@dataclass(frozen=True)
class World:
    store_id: str
    pos_id: str
    skus: list[str]
    username: str
    token: str
    sale_txn: str
    user_id: int


def uid(length: int = 8) -> str:
    return uuid4().hex[:length].upper()


def add_batch(session: Session, store_id: str, sku: str, quantity: int,
              expiry_date: date | None = None, batch_id: str | None = None) -> str:
    """Add one batch of a SKU and return its id.

    The default expiry is ``today_local() + 30 days``, so the batch is sellable
    unless a test asks for another date. Tests that need an expired batch pass
    one in the past.
    """
    if quantity < 0:
        raise ValueError("quantity must be >= 0")
    batch_id = batch_id or f"TEST-B-{uid(8)}"
    if expiry_date is None:
        expiry_date = clock.today_local() + timedelta(days=DEFAULT_BATCH_DAYS)
    session.add(
        ProductBatch(
            batch_id=batch_id,
            sku=sku,
            store_id=store_id,
            expiry_date=expiry_date,
            quantity=quantity,
        )
    )
    session.flush()
    return batch_id


def add_stock(session: Session, store_id: str, sku: str, quantity: int,
              expiry_date: date | None = None) -> str:
    """Create an inventory row and one batch of the same quantity.

    ``inventory.quantity`` must equal the sum of the batches of the store and SKU,
    so new tests create stock only through this helper (PB-20). A row that is
    already there takes the extra quantity; the batch is created either way.
    """
    row = session.get(Inventory, (store_id, sku))
    if row is None:
        session.add(Inventory(store_id=store_id, sku=sku, quantity=quantity))
    else:
        row.quantity += quantity
    session.flush()
    return add_batch(session, store_id, sku, quantity, expiry_date=expiry_date)



def seed_sale(session: Session, *, sold: dict[str, int] | None = None, stock: int = 10,
              status: str = "OK") -> World:
    """Create a store, products, one SALE transaction and its items."""
    if sold is None:
        sold = {f"TEST-SKU-{uid(8)}": 2, f"TEST-SKU-{uid(8)}": 1}
    store_id = f"TEST-{uid(5)}"
    pos_id = f"TEST-POS-{uid(8)}"
    username = f"TEST-USER-{uid(8)}"
    skus = list(sold)

    session.add(
        Store(
            store_id=store_id,
            name="Return test store",
            latitude=Decimal("10.500000"),
            longitude=Decimal("106.500000"),
            region_id="TEST",
        )
    )
    session.flush()
    for sku in skus:
        session.add(
            Product(
                sku=sku,
                barcode=f"BC-{sku}",
                name="Return test product",
                category="TEST",
                unit_price=Decimal("10.00"),
            )
        )
    session.flush()
    session.add(PosTerminal(pos_id=pos_id, store_id=store_id, status="ACTIVE"))
    user = StaffUser(
        username=username,
        full_name="Return test user",
        role="POS_SYSTEM",
        store_id=None,
    )
    session.add(user)
    session.flush()
    for sku in skus:
        # The sale below already happened, so the opening stock is the stock the
        # test expects plus what the sale took. The batch and the sale's own
        # movements are recorded here, exactly as a real SALE records them.
        add_stock(session, store_id, sku, stock + sold.get(sku, 0))
    sale_txn = f"TEST-SALE-{uid(8)}"
    session.add(
        PosTransaction(
            txn_id=sale_txn,
            store_id=store_id,
            pos_id=pos_id,
            txn_type="SALE",
            status=status,
            payload_hash="0" * 64,
        )
    )
    for sku, quantity in sold.items():
        session.add(
            TransactionItem(
                txn_id=sale_txn,
                sku=sku,
                qty=quantity,
                unit_price=Decimal("10.00"),
            )
        )
    session.flush()
    deduct_items(session, store_id, list(sold.items()), sale_txn)
    token = create_token(username, "POS", store_id=store_id, pos_id=pos_id)
    user_id = user.user_id
    session.commit()
    return World(store_id, pos_id, skus, username, token, sale_txn, user_id)


def add_sale(session: Session, store_id: str, pos_id: str, *, skus: list[str],
             status: str = "OK") -> str:
    """Create one more SALE row for a store; its items are optional for 404 tests."""
    txn_id = f"TEST-SALE-{uid(8)}"
    session.add(
        PosTransaction(
            txn_id=txn_id,
            store_id=store_id,
            pos_id=pos_id,
            txn_type="SALE",
            status=status,
            payload_hash="0" * 64,
        )
    )
    for sku in skus:
        session.add(
            TransactionItem(txn_id=txn_id, sku=sku, qty=1, unit_price=Decimal("10.00"))
        )
    session.commit()
    return txn_id


def return_payload(world: World, items: list[tuple[str, int, object]], *,
                   txn_id: str | None = None, **overrides) -> dict:
    payload = {
        "event_type": "RETURN",
        "transaction_id": txn_id if txn_id is not None else f"TEST-RET-{uid(10)}",
        "original_transaction_id": world.sale_txn,
        "store_id": world.store_id,
        "pos_id": world.pos_id,
        "timestamp": "2026-11-14T03:15:00Z",
        "items": [
            {"sku": sku, "quantity": quantity, "unit_price": price}
            for sku, quantity, price in items
        ],
    }
    payload.update(overrides)
    return payload


def sale_payload(world: World, items: list[tuple[str, int, object]], *,
                 txn_id: str | None = None, **overrides) -> dict:
    payload = {
        "event_type": "SALE",
        "transaction_id": txn_id if txn_id is not None else f"TEST-TXN-{uid(10)}",
        "store_id": world.store_id,
        "pos_id": world.pos_id,
        "timestamp": "2026-11-14T03:15:00Z",
        "items": [
            {"sku": sku, "quantity": quantity, "unit_price": price}
            for sku, quantity, price in items
        ],
    }
    payload.update(overrides)
    return payload


def post(client, payload: dict, token: str | None):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return client.post(URL, json=payload, headers=headers)


def assert_error(response, status: int, code: str) -> None:
    assert response.status_code == status, response.text
    body = response.json()
    assert body["outcome"] == ("ERROR" if status == 503 else "REJECTED")
    assert body["code"] == code
    assert body["message"]


def count(session: Session, model, **filters) -> int:
    statement = select(func.count()).select_from(model)
    for name, value in filters.items():
        statement = statement.where(getattr(model, name) == value)
    return session.scalar(statement)


def stock(session: Session, world: World, sku: str) -> int:
    session.expire_all()
    return session.get(Inventory, (world.store_id, sku)).quantity


def transaction_items(session: Session, txn_id: str) -> list[TransactionItem]:
    return list(
        session.scalars(
            select(TransactionItem)
            .where(TransactionItem.txn_id == txn_id)
            .order_by(TransactionItem.item_id)
        )
    )


def movements(session: Session, txn_id: str) -> list[InventoryMovement]:
    return list(
        session.scalars(
            select(InventoryMovement)
            .where(InventoryMovement.txn_id == txn_id)
            .order_by(InventoryMovement.movement_id)
        )
    )


def stock_changes(session: Session, txn_id: str) -> list[AuditLog]:
    return list(
        session.scalars(
            select(AuditLog)
            .where(AuditLog.action == "STOCK_CHANGE", AuditLog.entity_key == txn_id)
            .order_by(AuditLog.audit_id)
        )
    )


def assert_ledger_balanced(session: Session, store_id: str, skus: list[str],
                           opening: dict[str, int]) -> None:
    """Check on-hand stock against its movement ledger for an isolated store.

    A transaction may move several SKUs and, since PB-20, several batches of one
    SKU, so the once-only check is per transaction, SKU and batch: a movement row
    exists at most once for each of them. ``inventory.quantity`` must also equal
    the sum of the store's batches for the SKU, expired ones included.
    """
    assert set(skus) == set(opening)
    session.expire_all()
    for sku in skus:
        inventory = session.get(Inventory, (store_id, sku))
        assert inventory is not None, f"missing inventory row for {store_id}/{sku}"
        assert inventory.quantity >= 0, f"negative stock for {store_id}/{sku}"
        movement_total = session.scalar(
            select(func.coalesce(func.sum(InventoryMovement.quantity), 0)).where(
                InventoryMovement.store_id == store_id,
                InventoryMovement.sku == sku,
            )
        )
        assert inventory.quantity == opening[sku] + int(movement_total)
        batch_total = session.scalar(
            select(func.coalesce(func.sum(ProductBatch.quantity), 0)).where(
                ProductBatch.store_id == store_id,
                ProductBatch.sku == sku,
            )
        )
        assert inventory.quantity == int(batch_total), (
            f"stock and batches disagree for {store_id}/{sku}: "
            f"{inventory.quantity} on hand, {int(batch_total)} in batches"
        )

    repeated_movements = session.execute(
        select(InventoryMovement.txn_id, InventoryMovement.sku, InventoryMovement.batch_id)
        .where(
            InventoryMovement.store_id == store_id,
            InventoryMovement.txn_id.is_not(None),
            InventoryMovement.sku.in_(skus),
        )
        .group_by(InventoryMovement.txn_id, InventoryMovement.sku, InventoryMovement.batch_id)
        .having(func.count() > 1)
    ).all()
    assert not repeated_movements, f"multiple stock movements for one transaction/SKU/batch: {repeated_movements}"
