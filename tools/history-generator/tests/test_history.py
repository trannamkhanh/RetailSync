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


def test_generated_history_carries_occurred_at(db_session):
    """A generated line is a sale that happened, not a backfill (plan M7)."""
    suffix = uid(5)
    store, sku, pos = f"TEST-{suffix}", f"TEST-SKU-{suffix}", f"TEST-POS-{suffix}"
    db_session.add_all([
        Store(store_id=store, name="History", latitude=0, longitude=0, region_id="TEST"),
        Product(sku=sku, barcode=sku, name="History product", category="TEST", unit_price=10),
    ])
    db_session.flush()
    db_session.add(PosTerminal(pos_id=pos, store_id=store, status="ACTIVE"))
    add_stock(db_session, store, sku, 7)
    as_of = date(2026, 11, 14)

    load_history(db_session, 90, 42, as_of, store_ids={store})

    rows = db_session.execute(
        select(PosTransaction.occurred_at, PosTransaction.created_at)
        .where(PosTransaction.store_id == store)
    ).all()
    assert rows and all(occurred is not None for occurred, _ in rows)
    # A generated row is received at once, so it is ON_TIME and not BACKFILL, and
    # created_at is unchanged, so the demo data keeps its shape.
    assert all(occurred == created for occurred, created in rows)
    # The declared moment is never in the future.
    assert all(occurred.date() < as_of for occurred, _ in rows)


def test_pb52_demo_profile_covers_all_90_days_without_truncation(db_session):
    """PB-52 demo profile generates full 90-day history without 14-day short-pair truncation."""
    as_of = date(2026, 11, 28)
    count = load_history(
        db_session,
        90,
        42,
        as_of,
        store_ids={"STORE-DN1", "STORE-DN2", "STORE-DN3"},
        demo_profile=True,
    )
    assert count > 0
    rows = db_session.execute(
        select(PosTransaction.store_id, TransactionItem.sku, PosTransaction.created_at)
        .join(TransactionItem, TransactionItem.txn_id == PosTransaction.txn_id)
        .where(
            PosTransaction.store_id.in_(("STORE-DN1", "STORE-DN2", "STORE-DN3")),
            PosTransaction.txn_id.startswith("HIST-"),
            PosTransaction.txn_type == "SALE",
        )
    ).all()
    by_pair = defaultdict(set)
    for store_id, sku, created_at in rows:
        by_pair[(store_id, sku)].add(created_at.date())
    assert len(by_pair) >= 27
    assert all(len(days) >= 60 for days in by_pair.values())
