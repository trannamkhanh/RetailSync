"""Audit #4: the FEFO batch lock names its index.

``lock_batches`` reads the batches of one store and SKU under ``UPDLOCK`` before
it deducts or restores. Without an index hint the optimiser may pick the
clustered index and scan, taking update locks on rows of other stores and SKUs
on a small table; the FEFO lock order then depends on the plan instead of
``(expiry_date, batch_id)``. ``repositories/original_sale.py`` already names its
index for the same reason.

The plan a given SQL Server chooses is not stable enough to assert, so the test
pins the statement text, which is what the audit found missing, and then the
concurrency test shows that two stores selling at the same moment still do not
deadlock or time out.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from decimal import Decimal
from threading import Barrier, Lock
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

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
from app.repositories.inventory import lock_batches
from app.services.inventory import deduct_items
from tests.pos_test_support import add_stock, uid

TODAY = date(2026, 11, 14)
INDEX_NAME = "ix_product_batch_fefo"


class Recorder:
    """A stand-in session that records the statement and its parameters."""

    def __init__(self) -> None:
        self.statement = ""
        self.parameters: dict[str, Any] = {}

    def execute(self, statement, parameters=None):
        self.statement = str(statement)
        self.parameters = dict(parameters or {})
        return self

    def all(self):
        return []


def statement_of(*, sellable_only: bool) -> str:
    recorder = Recorder()
    lock_batches(recorder, "TEST-STORE", "TEST-SKU", sellable_only=sellable_only,
                 today=TODAY if sellable_only else None)
    return recorder.statement


@pytest.mark.parametrize("sellable_only", [True, False], ids=["sale", "restore"])
def test_audit04_the_batch_lock_names_the_fefo_index(sellable_only):
    statement = statement_of(sellable_only=sellable_only)

    assert "WITH (UPDLOCK, ROWLOCK, INDEX(ix_product_batch_fefo))" in statement


def test_audit04_the_index_exists_in_the_migration():
    """The hint is only safe while the migration creates exactly this index."""
    from pathlib import Path

    migration = (Path(__file__).resolve().parents[2] / "database" / "migrations"
                 / "002_batches_alerts_forecast.sql").read_text(encoding="utf-8")

    assert (f"CREATE INDEX {INDEX_NAME} ON dbo.product_batch"
            "(store_id, sku, expiry_date);") in migration


def test_audit04_the_lock_still_reads_the_sellable_range_only():
    recorder = Recorder()
    lock_batches(recorder, "TEST-STORE", "TEST-SKU", sellable_only=True, today=TODAY)

    assert "AND expiry_date >= CAST(:today AS date)" in recorder.statement
    assert recorder.parameters == {"store_id": "TEST-STORE", "sku": "TEST-SKU",
                                  "today": TODAY}


# Two stores, one SKU each, selling at the same instant.


class Shop:
    def __init__(self, store_id: str, pos_id: str, sku: str, username: str) -> None:
        self.store_id = store_id
        self.pos_id = pos_id
        self.sku = sku
        self.username = username


def _make_shop(session: Session, label: str) -> Shop:
    # store_id is varchar(10), so the id is "TEST-" plus the label and 4 hex digits.
    suffix = uid(4)
    shop = Shop(f"TEST-{label}{suffix}", f"TEST-POS-{label}{suffix}",
                f"TEST-SKU-{label}{suffix}", f"TEST-user-{label}{suffix}")
    session.add(Store(store_id=shop.store_id, name=f"Audit concurrency {label}",
                      latitude=Decimal("16.000000"), longitude=Decimal("108.000000"),
                      region_id="TEST"))
    session.add(Product(sku=shop.sku, barcode=f"BC-{shop.sku}", name="Audit FEFO product",
                        category="TEST", unit_price=Decimal("10.00")))
    session.flush()
    session.add(PosTerminal(pos_id=shop.pos_id, store_id=shop.store_id, status="ACTIVE"))
    session.add(StaffUser(username=shop.username, full_name="Audit FEFO POS",
                          role="POS_SYSTEM", store_id=None))
    for days in (2, 5, 9):
        add_stock(session, shop.store_id, shop.sku, 10,
                  expiry_date=TODAY + timedelta(days=days))
    session.commit()
    return shop


def _add_sale(session: Session, shop: Shop, txn_id: str) -> None:
    """A SALE row the deduction's movement can point at (fk_inventory_movement_txn)."""
    session.add(PosTransaction(txn_id=txn_id, store_id=shop.store_id, pos_id=shop.pos_id,
                               txn_type="SALE", status="OK", payload_hash="0" * 64))
    session.flush()


def _cleanup(engine, shops: list[Shop]) -> None:
    with Session(engine) as session:
        stores = [shop.store_id for shop in shops]
        txns = select(PosTransaction.txn_id).where(PosTransaction.store_id.in_(stores))
        session.execute(delete(InventoryMovement).where(
            InventoryMovement.store_id.in_(stores)))
        session.execute(delete(TransactionItem).where(TransactionItem.txn_id.in_(txns)))
        session.execute(delete(PosTransaction).where(PosTransaction.store_id.in_(stores)))
        session.execute(delete(Inventory).where(Inventory.store_id.in_(stores)))
        session.execute(delete(ProductBatch).where(ProductBatch.store_id.in_(stores)))
        session.execute(delete(PosTerminal).where(
            PosTerminal.pos_id.in_([shop.pos_id for shop in shops])))
        session.execute(delete(StaffUser).where(
            StaffUser.username.in_([shop.username for shop in shops])))
        session.execute(delete(Product).where(
            Product.sku.in_([shop.sku for shop in shops])))
        session.execute(delete(Store).where(Store.store_id.in_(stores)))
        session.commit()


def _sell(engine, shop: Shop, txn_id: str, barrier: Barrier,
          order: list[str], guard: Lock) -> str:
    """Deduct two units from one store's SKU once both threads are ready.

    The two threads call ``lock_batches`` with ``store_id`` predicates that touch
    disjoint rows; a scan would make them wait on each other's locks instead.
    """
    with Session(engine) as session:
        with guard:
            order.append(shop.store_id)
        barrier.wait(timeout=15)
        try:
            _add_sale(session, shop, txn_id)
            deduct_items(session, shop.store_id, [(shop.sku, 2)], txn_id)
            session.commit()
            return "SOLD"
        except Exception as failure:  # noqa: BLE001 - the point is to name it
            session.rollback()
            return f"FAILED: {type(failure).__name__}: {failure}"


def test_audit04_two_stores_selling_at_once_neither_deadlock_nor_time_out(test_engine):
    with Session(test_engine) as session:
        shops = [_make_shop(session, "A"), _make_shop(session, "B")]
    barrier = Barrier(2)
    order: list[str] = []
    guard = Lock()
    try:
        for run in range(5):
            order.clear()
            transactions = {shop.store_id: f"TEST-AUDIT4-{uid(8)}-{run}" for shop in shops}
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(_sell, test_engine, shop,
                                       transactions[shop.store_id], barrier, order, guard)
                           for shop in shops]
                results = [future.result(timeout=30) for future in futures]
            assert results == ["SOLD", "SOLD"], results
        with Session(test_engine) as session:
            for shop in shops:
                remaining = session.scalar(
                    select(Inventory.quantity).where(Inventory.store_id == shop.store_id,
                                                     Inventory.sku == shop.sku))
                # 30 opened, five runs of two units each: the store's own rows only.
                assert remaining == 30 - 5 * 2, f"{shop.store_id} sold from the wrong rows"
                in_batches = session.scalar(
                    select(func.coalesce(func.sum(ProductBatch.quantity), 0))
                    .where(ProductBatch.store_id == shop.store_id,
                           ProductBatch.sku == shop.sku))
                assert int(in_batches) == remaining
    finally:
        _cleanup(test_engine, shops)
