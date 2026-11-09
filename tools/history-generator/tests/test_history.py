from collections import defaultdict
from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app.domain.models import Inventory, InventoryMovement, PosTerminal, PosTransaction, Product, ProductBatch
from app.domain.models import Store, SyncBatch, TransactionItem
from history_generator.loader import allowed_database, load_history
from tests.pos_test_support import add_stock, uid


def test_pb22_1_refuses_other_databases():
    with pytest.raises(ValueError, match="RTS_DB_DEMO or RTS_DB_TEST"):
        allowed_database("RTS_DB")


def test_pb22_1_history_is_repeatable_without_touching_stock(db_session):
    suffix = uid(5)
    store, sku, pos = f"TEST-{suffix}", f"TEST-SKU-{suffix}", f"TEST-POS-{suffix}"
    db_session.add_all([
        Store(store_id=store, name="History", latitude=0, longitude=0, region_id="TEST"),
        Product(sku=sku, barcode=sku, name="History product", category="TEST", unit_price=10),
    ])
    db_session.flush()
    db_session.add(PosTerminal(pos_id=pos, store_id=store, status="ACTIVE"))
    batch = add_stock(db_session, store, sku, 7)
    as_of = date(2026, 11, 14)

    def rows():
        return db_session.execute(
            select(PosTransaction.txn_id, PosTransaction.txn_type, PosTransaction.ref_txn_id,
                   PosTransaction.created_at, PosTransaction.payload_hash, TransactionItem.sku,
                   TransactionItem.qty, TransactionItem.unit_price)
            .join(TransactionItem, TransactionItem.txn_id == PosTransaction.txn_id)
            .where(PosTransaction.store_id == store)
            .order_by(PosTransaction.txn_id)
        ).all()

    count = load_history(db_session, 90, 42, as_of, store_ids={store})
    original = rows()
    assert count == len(original) > 0
    assert load_history(db_session, 90, 42, as_of, store_ids={store}) == count
    assert rows() == original

    sync = db_session.get(SyncBatch, f"SB-HIST-{store}")
    assert sync.status == "ACKED" and sync.txn_count == count
    assert {value for value in db_session.scalars(
        select(PosTransaction.sync_batch_id).where(PosTransaction.store_id == store)
    )} == {sync.sync_batch_id}
    spans = defaultdict(set)
    for txn, kind, _, created_at, _, item_sku, _, _ in original:
        assert txn.startswith("HIST-")
        assert as_of - timedelta(days=90) <= created_at.date() < as_of
        if kind == "SALE":
            spans[item_sku].add(created_at.date())
    assert any(0 < len(dates) < 28 for dates in spans.values())
    assert db_session.scalar(select(InventoryMovement).where(InventoryMovement.store_id == store)) is None
    db_session.expire_all()
    assert db_session.get(Inventory, (store, sku)).quantity == 7
    assert db_session.get(ProductBatch, batch).quantity == 7
