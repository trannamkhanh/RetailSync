"""Audit #12: restoring stock still works when the inventory row is missing.

``_restore_sku`` wrote to ``inventory_movement`` (FK to ``dbo.inventory``) for
every batch it filled *before* it upserted a missing ``inventory`` row, so the
``insert_stock_row`` branch could never succeed: the first movement raised FK
547 and the whole reversal rolled back. The order is now: update
``product_batch``, upsert ``inventory``, then insert the movements.

The state is the legacy one PB-20 has to keep working for: a sale recorded
before the movement ledger existed (``pos_transaction`` and
``transaction_item`` only), so the stock it took has no ``inventory_movement``
rows, the batch is sold out, and the store and SKU have no ``inventory`` row.

Every test owns its store, product, batch and transaction with ``TEST-`` ids
inside the ``db_session`` savepoint, which the fixture rolls back.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import clock
from app.domain.models import (
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
from app.services.inventory import restore_items
from tests.pos_test_support import assert_ledger_balanced, uid

TODAY = date(2026, 11, 17)


@pytest.fixture(autouse=True)
def business_date(monkeypatch) -> None:
    monkeypatch.setattr(clock, "today_local", lambda: TODAY)


class Shop:
    def __init__(self, store_id: str, pos_id: str, sku: str, sale_txn: str,
                 batch_id: str) -> None:
        self.store_id = store_id
        self.pos_id = pos_id
        self.sku = sku
        self.sale_txn = sale_txn
        self.batch_id = batch_id


def make_legacy_shop(db_session: Session, *, quantity: int = 0) -> Shop:
    """A legacy sale: rows only, no movement ledger and no inventory row.

    ``quantity`` is what the sold-out batch holds; zero keeps the movement ledger
    self-consistent after the restore, which is what the balance check needs.
    """
    suffix = uid(4)
    store_id = f"TEST-R{suffix}"
    pos_id = f"TEST-POS-{suffix}"
    sku = f"TEST-SKU-{suffix}"
    batch_id = f"TEST-B-{suffix}"
    db_session.add(Store(store_id=store_id, name="Audit restore store",
                         latitude=Decimal("10.500000"), longitude=Decimal("106.500000"),
                         region_id="TEST"))
    db_session.flush()
    db_session.add(Product(sku=sku, barcode=f"BC-{sku}", name="Audit restore product",
                           category="TEST", unit_price=Decimal("10.00")))
    db_session.flush()
    db_session.add(PosTerminal(pos_id=pos_id, store_id=store_id, status="ACTIVE"))
    db_session.add(StaffUser(username=f"TEST-user-{suffix}", full_name="Audit restore POS",
                             role="POS_SYSTEM", store_id=None))
    db_session.flush()
    # The batch is created directly: add_stock() would create the inventory row
    # this test needs to be missing.
    db_session.add(ProductBatch(batch_id=batch_id, sku=sku, store_id=store_id,
                                expiry_date=TODAY + timedelta(days=10), quantity=quantity))
    sale_txn = f"TEST-SALE-{suffix}"
    db_session.add(PosTransaction(txn_id=sale_txn, store_id=store_id, pos_id=pos_id,
                                  txn_type="SALE", status="OK", payload_hash="0" * 64))
    db_session.add(TransactionItem(txn_id=sale_txn, sku=sku, qty=2,
                                   unit_price=Decimal("10.00")))
    db_session.flush()
    db_session.commit()
    return Shop(store_id, pos_id, sku, sale_txn, batch_id)


def add_reversal_row(db_session: Session, shop: Shop, txn_id: str, kind: str) -> None:
    db_session.add(PosTransaction(txn_id=txn_id, store_id=shop.store_id,
                                  pos_id=shop.pos_id, txn_type=kind, status="OK",
                                  ref_txn_id=shop.sale_txn, payload_hash="1" * 64))
    db_session.flush()


def movements_for(session: Session, shop: Shop, txn_id: str) -> list[InventoryMovement]:
    session.expire_all()
    return list(session.scalars(
        select(InventoryMovement)
        .where(InventoryMovement.store_id == shop.store_id,
               InventoryMovement.sku == shop.sku,
               InventoryMovement.txn_id == txn_id)
        .order_by(InventoryMovement.movement_id)))


def test_audit12_no_inventory_row_exists_before_the_restore(db_session):
    """The fixture really is the audited state; without this the rest proves nothing."""
    shop = make_legacy_shop(db_session)

    assert db_session.get(Inventory, (shop.store_id, shop.sku)) is None
    assert movements_for(db_session, shop, shop.sale_txn) == []


def test_audit12_a_return_without_an_inventory_row_restores_stock(db_session):
    shop = make_legacy_shop(db_session)
    return_txn = f"TEST-RET-{uid(8)}"
    add_reversal_row(db_session, shop, return_txn, "RETURN")

    restored = restore_items(db_session, shop.store_id, [(shop.sku, 2)],
                             original_txn_id=shop.sale_txn, txn_id=return_txn,
                             movement_type="RETURN")
    db_session.flush()

    assert restored == {shop.sku: 2}
    inventory = db_session.get(Inventory, (shop.store_id, shop.sku))
    assert inventory is not None and inventory.quantity == 2
    assert [(movement.movement_type, movement.quantity)
            for movement in movements_for(db_session, shop, return_txn)] == [("RETURN", 2)]


def test_audit12_a_cancellation_without_an_inventory_row_restores_stock(db_session):
    shop = make_legacy_shop(db_session)
    cancellation_txn = f"TEST-CAN-{uid(8)}"
    add_reversal_row(db_session, shop, cancellation_txn, "CANCELLATION")

    restore_items(db_session, shop.store_id, [(shop.sku, 2)],
                  original_txn_id=shop.sale_txn, txn_id=cancellation_txn,
                  movement_type="CANCELLATION")
    db_session.flush()

    inventory = db_session.get(Inventory, (shop.store_id, shop.sku))
    assert inventory is not None and inventory.quantity == 2
    assert movements_for(db_session, shop, cancellation_txn)[0].movement_type == "CANCELLATION"


def test_audit12_the_batch_gets_its_units_back_and_the_row_is_created_once(db_session):
    shop = make_legacy_shop(db_session)
    return_txn = f"TEST-RET-{uid(8)}"
    add_reversal_row(db_session, shop, return_txn, "RETURN")
    before = db_session.scalar(select(ProductBatch.quantity).where(
        ProductBatch.batch_id == shop.batch_id))

    restore_items(db_session, shop.store_id, [(shop.sku, 2)],
                  original_txn_id=shop.sale_txn, txn_id=return_txn,
                  movement_type="RETURN")
    db_session.flush()

    after = db_session.scalar(select(ProductBatch.quantity).where(
        ProductBatch.batch_id == shop.batch_id))
    assert int(after) == int(before) + 2
    rows = db_session.scalars(select(Inventory).where(
        Inventory.store_id == shop.store_id, Inventory.sku == shop.sku)).all()
    assert len(rows) == 1 and rows[0].quantity == 2


def test_audit12_the_ledger_stays_balanced_after_that_restore(db_session):
    shop = make_legacy_shop(db_session)
    return_txn = f"TEST-RET-{uid(8)}"
    add_reversal_row(db_session, shop, return_txn, "RETURN")

    restore_items(db_session, shop.store_id, [(shop.sku, 2)],
                  original_txn_id=shop.sale_txn, txn_id=return_txn,
                  movement_type="RETURN")
    db_session.flush()

    # Nothing was on hand before the restore: the sale is legacy and left no
    # movement, so the only movement is the RETURN's own +2.
    assert_ledger_balanced(db_session, shop.store_id, [shop.sku], {shop.sku: 0})


def test_audit12_the_inventory_row_keeps_its_quantity_when_it_exists(db_session):
    """The ordinary branch, with the inventory row present, is unchanged."""
    shop = make_legacy_shop(db_session)
    db_session.add(Inventory(store_id=shop.store_id, sku=shop.sku, quantity=5))
    db_session.commit()
    return_txn = f"TEST-RET-{uid(8)}"
    add_reversal_row(db_session, shop, return_txn, "RETURN")

    restore_items(db_session, shop.store_id, [(shop.sku, 2)],
                  original_txn_id=shop.sale_txn, txn_id=return_txn,
                  movement_type="RETURN")
    db_session.flush()

    assert db_session.get(Inventory, (shop.store_id, shop.sku)).quantity == 7
    assert [movement.quantity for movement in movements_for(db_session, shop, return_txn)] == [2]
