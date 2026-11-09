"""SYNC14-1 to SYNC14-7, SYNC15-2 and the PB-14 scenarios.

The tests that call ``run_aggregation`` use the module's ``session_factory``
pointed at RTS_DB_TEST (the autouse fixture), so the job never writes to the
database the middleware serves. Every row they create has a TEST- id and is
deleted afterwards; the savepoint tests leave nothing behind either.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from app.domain.models import (
    PosTerminal,
    PosTransaction,
    Product,
    SalesSummaryLine,
    Store,
    SyncBatch,
    TransactionItem,
)
from app.jobs import aggregation as job
from app.repositories import aggregation as repository
from app.services.aggregation import aggregate_store


def _uid(length: int = 6) -> str:
    return uuid4().hex[:length].upper()


@pytest.fixture(autouse=True)
def test_database(monkeypatch, test_engine):
    """Point the job at RTS_DB_TEST, never at DB_NAME."""

    def factory() -> Session:
        return Session(bind=test_engine)

    monkeypatch.setattr(job, "session_factory", factory)


def _create_store(session: Session, skus: list[str]) -> tuple[str, str]:
    store_id = f"TEST-{_uid(5)}"
    pos_id = f"TEST-POS-{_uid(6)}"
    session.add(Store(store_id=store_id, name="Aggregation test store",
                      latitude=Decimal("10.500000"), longitude=Decimal("106.500000"),
                      region_id="TEST"))
    session.flush()
    for sku in skus:
        session.add(Product(sku=sku, barcode=f"BC-{sku}", name="Aggregation product",
                            category="TEST", unit_price=Decimal("10.00")))
    session.add(PosTerminal(pos_id=pos_id, store_id=store_id, status="ACTIVE"))
    session.flush()
    return store_id, pos_id


def _add_transaction(session: Session, store_id: str, pos_id: str, txn_type: str,
                     items: list[tuple[str, int, Decimal]], *, txn_id: str | None = None,
                     created_at: datetime | None = None, ref_txn_id: str | None = None,
                     sync_batch_id: str | None = None) -> str:
    txn_id = txn_id or f"TEST-{_uid(10)}"
    values = {
        "txn_id": txn_id, "store_id": store_id, "pos_id": pos_id,
        "txn_type": txn_type, "ref_txn_id": ref_txn_id, "status": "OK",
        "sync_batch_id": sync_batch_id, "payload_hash": "0" * 64,
    }
    if created_at is not None:
        values["created_at"] = created_at
    session.add(PosTransaction(**values))
    session.flush()
    for sku, quantity, price in items:
        session.add(TransactionItem(txn_id=txn_id, sku=sku, qty=quantity,
                                    unit_price=price))
    session.flush()
    return txn_id


def _cleanup(store_id: str, skus: list[str]) -> None:
    with job.session_factory() as session:
        batch_ids = list(session.scalars(
            select(SyncBatch.sync_batch_id).where(SyncBatch.store_id == store_id)))
        if batch_ids:
            session.execute(delete(SalesSummaryLine).where(
                SalesSummaryLine.sync_batch_id.in_(batch_ids)))
        txn_ids = select(PosTransaction.txn_id).where(PosTransaction.store_id == store_id)
        session.execute(delete(TransactionItem).where(TransactionItem.txn_id.in_(txn_ids)))
        session.execute(delete(PosTransaction).where(
            PosTransaction.store_id == store_id,
            PosTransaction.ref_txn_id.is_not(None)))
        session.execute(delete(PosTransaction).where(PosTransaction.store_id == store_id))
        if batch_ids:
            session.execute(delete(SyncBatch).where(
                SyncBatch.sync_batch_id.in_(batch_ids)))
        session.execute(delete(PosTerminal).where(PosTerminal.store_id == store_id))
        session.execute(delete(Product).where(Product.sku.in_(skus)))
        session.execute(delete(Store).where(Store.store_id == store_id))
        session.commit()


def _committed_world(skus: list[str], sales: list[list[tuple[str, int, Decimal]]]):
    with job.session_factory() as session:
        store_id, pos_id = _create_store(session, skus)
        for items in sales:
            _add_transaction(session, store_id, pos_id, "SALE", items)
        session.commit()
    return store_id, pos_id


def test_sync14_1_run_aggregation_makes_one_batch_per_store():
    skus_a = [f"TEST-SKU-{_uid(5)}"]
    skus_b = [f"TEST-SKU-{_uid(5)}"]
    stores = []
    try:
        stores.append(_committed_world(skus_a, [[(skus_a[0], 1, Decimal("10.00"))]]))
        stores.append(_committed_world(skus_b, [[(skus_b[0], 2, Decimal("10.00"))]]))

        created = job.run_aggregation()

        for (store_id, _), skus in zip(stores, [skus_a, skus_b]):
            with job.session_factory() as session:
                batches = list(session.scalars(
                    select(SyncBatch).where(SyncBatch.store_id == store_id)))
                assert len(batches) == 1
                batch = batches[0]
                assert batch.sync_batch_id in created
                transactions = list(session.scalars(select(PosTransaction).where(
                    PosTransaction.store_id == store_id)))
                assert {txn.sync_batch_id for txn in transactions} == {
                    batch.sync_batch_id}
    finally:
        for (store_id, _), skus in zip(stores, [skus_a, skus_b]):
            _cleanup(store_id, skus)


def test_sync14_2_batch_lines_match_the_source_transactions():
    skus = [f"TEST-SKU-{_uid(5)}", f"TEST-SKU-{_uid(5)}"]
    store_id = pos_id = None
    try:
        with job.session_factory() as session:
            store_id, pos_id = _create_store(session, skus)
            sale = _add_transaction(session, store_id, pos_id, "SALE", [
                (skus[0], 3, Decimal("10.00")), (skus[1], 2, Decimal("20.00"))])
            _add_transaction(session, store_id, pos_id, "RETURN",
                             [(skus[0], 1, Decimal("10.00"))], ref_txn_id=sale)
            _add_transaction(session, store_id, pos_id, "CANCELLATION",
                             [(skus[1], 2, Decimal("20.00"))], ref_txn_id=sale)
            session.commit()

        job.run_aggregation()

        with job.session_factory() as session:
            batch_ids = list(session.scalars(
                select(SyncBatch.sync_batch_id).where(SyncBatch.store_id == store_id)))
            lines = session.execute(
                select(SalesSummaryLine.sku, SalesSummaryLine.sold_qty,
                       SalesSummaryLine.returned_qty, SalesSummaryLine.net_revenue)
                .where(SalesSummaryLine.sync_batch_id.in_(batch_ids))
            ).all()
            summarized = {row.sku: (row.sold_qty, row.returned_qty, row.net_revenue)
                          for row in lines}

            for index, sku in enumerate(skus):
                sold = session.scalar(
                    select(TransactionItem.qty)
                    .join(PosTransaction, PosTransaction.txn_id == TransactionItem.txn_id)
                    .where(PosTransaction.store_id == store_id,
                           TransactionItem.sku == sku,
                           PosTransaction.txn_type == "SALE"))
                returned = session.scalar(
                    select(TransactionItem.qty)
                    .join(PosTransaction, PosTransaction.txn_id == TransactionItem.txn_id)
                    .where(PosTransaction.store_id == store_id,
                           TransactionItem.sku == sku,
                           PosTransaction.txn_type.in_(("RETURN", "CANCELLATION"))))
                sold_amount = session.scalar(
                    select(TransactionItem.qty * TransactionItem.unit_price)
                    .join(PosTransaction, PosTransaction.txn_id == TransactionItem.txn_id)
                    .where(PosTransaction.store_id == store_id,
                           TransactionItem.sku == sku,
                           PosTransaction.txn_type == "SALE"))
                returned_amount = session.scalar(
                    select(TransactionItem.qty * TransactionItem.unit_price)
                    .join(PosTransaction, PosTransaction.txn_id == TransactionItem.txn_id)
                    .where(PosTransaction.store_id == store_id,
                           TransactionItem.sku == sku,
                           PosTransaction.txn_type.in_(("RETURN", "CANCELLATION"))))
                assert summarized[sku] == (
                    int(sold or 0), int(returned or 0),
                    Decimal(sold_amount or 0) - Decimal(returned_amount or 0))
    finally:
        if store_id is not None:
            _cleanup(store_id, skus)


def test_sync14_3_a_cancellation_is_counted_in_returned_qty(db_session):
    skus = [f"TEST-SKU-{_uid(5)}"]
    store_id, pos_id = _create_store(db_session, skus)
    sale = _add_transaction(db_session, store_id, pos_id, "SALE",
                            [(skus[0], 2, Decimal("10.00"))])
    _add_transaction(db_session, store_id, pos_id, "CANCELLATION",
                     [(skus[0], 2, Decimal("10.00"))], ref_txn_id=sale)

    batch_id = aggregate_store(db_session, store_id, datetime.now(timezone.utc))

    line = db_session.scalar(select(SalesSummaryLine).where(
        SalesSummaryLine.sync_batch_id == batch_id))
    assert line.sold_qty == 2
    assert line.returned_qty == 2
    assert line.net_revenue == Decimal("0.00")


def test_sync14_4_a_store_without_new_transactions_gets_no_batch(db_session):
    skus = [f"TEST-SKU-{_uid(5)}"]
    store_id, _ = _create_store(db_session, skus)

    batch_id = aggregate_store(db_session, store_id, datetime.now(timezone.utc))

    assert batch_id is None
    assert db_session.scalar(
        select(SyncBatch).where(SyncBatch.store_id == store_id)) is None


def test_sync14_5_each_transaction_appears_in_one_batch(db_session):
    skus = [f"TEST-SKU-{_uid(5)}"]
    store_id, pos_id = _create_store(db_session, skus)
    first = _add_transaction(db_session, store_id, pos_id, "SALE",
                             [(skus[0], 1, Decimal("10.00"))])
    second = _add_transaction(db_session, store_id, pos_id, "SALE",
                              [(skus[0], 2, Decimal("10.00"))])

    batch_id = aggregate_store(db_session, store_id,
                               datetime(2026, 11, 14, 3, 0, 0, tzinfo=timezone.utc))
    again = aggregate_store(db_session, store_id,
                            datetime(2026, 11, 14, 4, 0, 0, tzinfo=timezone.utc))

    assert again is None
    batches = list(db_session.scalars(
        select(SyncBatch).where(SyncBatch.store_id == store_id)))
    assert [batch.sync_batch_id for batch in batches] == [batch_id]
    linked = db_session.execute(select(PosTransaction.txn_id, PosTransaction.sync_batch_id)
                                .where(PosTransaction.txn_id.in_((first, second)))).all()
    assert {row.sync_batch_id for row in linked} == {batch_id}


def test_sync14_6_period_covers_the_batch(db_session):
    skus = [f"TEST-SKU-{_uid(5)}"]
    store_id, pos_id = _create_store(db_session, skus)
    first = datetime(2026, 11, 14, 3, 0, 0)
    second = first + timedelta(minutes=5)
    _add_transaction(db_session, store_id, pos_id, "SALE",
                     [(skus[0], 1, Decimal("10.00"))], created_at=first)
    _add_transaction(db_session, store_id, pos_id, "SALE",
                     [(skus[0], 2, Decimal("10.00"))], created_at=second)

    batch_id = aggregate_store(db_session, store_id,
                               datetime(2026, 11, 14, 4, 0, 0, tzinfo=timezone.utc))

    batch = db_session.get(SyncBatch, batch_id)
    assert batch.status == "PENDING"
    assert batch.attempts == 0
    assert batch.txn_count == 2
    assert batch.period_start == first
    assert batch.period_end == second
    assert batch.payload_bytes is None
    assert batch.raw_bytes is None


def test_sync14_7_a_failure_rolls_back_and_the_next_run_includes_it(monkeypatch):
    skus = [f"TEST-SKU-{_uid(5)}"]
    store_id = pos_id = None
    try:
        store_id, pos_id = _committed_world(skus, [[(skus[0], 3, Decimal("10.00"))]])
        original = job.aggregate_store
        calls = {"count": 0}

        def flaky(session, store, now):
            if store == store_id and calls["count"] == 0:
                calls["count"] += 1
                raise RuntimeError("simulated database failure")
            return original(session, store, now)

        with monkeypatch.context() as patch:
            patch.setattr(job, "aggregate_store", flaky)
            first = job.run_aggregation()

        assert not any(batch.startswith(f"SB-{store_id}-") for batch in first)
        with job.session_factory() as session:
            assert session.scalar(
                select(SyncBatch).where(SyncBatch.store_id == store_id)) is None
            txn = session.scalar(select(PosTransaction).where(
                PosTransaction.store_id == store_id))
            assert txn.sync_batch_id is None

        second = job.run_aggregation()

        assert any(batch.startswith(f"SB-{store_id}-") for batch in second)
        with job.session_factory() as session:
            txn = session.scalar(select(PosTransaction).where(
                PosTransaction.store_id == store_id))
            assert txn.sync_batch_id is not None
    finally:
        if store_id is not None:
            _cleanup(store_id, skus)


def test_sync15_2_batch_id_format(db_session):
    skus = [f"TEST-SKU-{_uid(5)}"]
    store_id, pos_id = _create_store(db_session, skus)
    _add_transaction(db_session, store_id, pos_id, "SALE",
                     [(skus[0], 1, Decimal("10.00"))])

    batch_id = aggregate_store(db_session, store_id,
                               datetime(2026, 11, 14, 3, 4, 5, tzinfo=timezone.utc))

    assert batch_id == f"SB-{store_id}-20261114030405"
    assert len(batch_id) <= 28


def test_pb14_history_transactions_are_never_aggregated(db_session):
    skus = [f"TEST-SKU-{_uid(5)}"]
    store_id, pos_id = _create_store(db_session, skus)
    history_batch = SyncBatch(
        sync_batch_id=f"SB-HIST-{store_id}", store_id=store_id,
        period_start=datetime(2026, 1, 1), period_end=datetime(2026, 1, 2),
        txn_count=1, status="ACKED")
    db_session.add(history_batch)
    db_session.flush()
    _add_transaction(db_session, store_id, pos_id, "SALE",
                     [(skus[0], 5, Decimal("10.00"))],
                     txn_id=f"HIST-{_uid(8)}", sync_batch_id=history_batch.sync_batch_id)

    batch_id = aggregate_store(db_session, store_id, datetime.now(timezone.utc))

    assert batch_id is None
    batches = list(db_session.scalars(
        select(SyncBatch).where(SyncBatch.store_id == store_id)))
    assert [batch.sync_batch_id for batch in batches] == [history_batch.sync_batch_id]


def test_pb14_a_sale_during_aggregation_goes_to_the_next_batch(monkeypatch):
    skus = [f"TEST-SKU-{_uid(5)}"]
    store_id = pos_id = None
    try:
        store_id, pos_id = _committed_world(skus, [[(skus[0], 1, Decimal("10.00"))]])
        base = datetime.now(timezone.utc)
        original = repository.link_transactions
        late_txn = {}

        def link_then_commit_late(session, store, batch):
            rows = original(session, store, batch)
            with job.session_factory() as other:
                late_txn["id"] = _add_transaction(
                    other, store, pos_id, "SALE", [(skus[0], 2, Decimal("10.00"))])
                other.commit()
            return rows

        with monkeypatch.context() as patch:
            patch.setattr(repository, "link_transactions", link_then_commit_late)
            first = job.run_aggregation(now=base)

        with job.session_factory() as session:
            late = session.get(PosTransaction, late_txn["id"])
            assert late.sync_batch_id is None
            batch = session.scalar(select(SyncBatch).where(
                SyncBatch.store_id == store_id))
            assert batch.sync_batch_id in first
            assert batch.txn_count == 1

        second = job.run_aggregation(now=base + timedelta(seconds=1))

        with job.session_factory() as session:
            late = session.get(PosTransaction, late_txn["id"])
            assert late.sync_batch_id is not None
            assert late.sync_batch_id in second
    finally:
        if store_id is not None:
            _cleanup(store_id, skus)


def test_pb14_a_cancellation_in_a_later_batch_keeps_the_net_correct(db_session):
    skus = [f"TEST-SKU-{_uid(5)}"]
    store_id, pos_id = _create_store(db_session, skus)
    sale = _add_transaction(db_session, store_id, pos_id, "SALE",
                            [(skus[0], 2, Decimal("10.00"))])
    first = aggregate_store(db_session, store_id,
                            datetime(2026, 11, 14, 3, 0, 0, tzinfo=timezone.utc))
    _add_transaction(db_session, store_id, pos_id, "CANCELLATION",
                     [(skus[0], 2, Decimal("10.00"))], ref_txn_id=sale)
    second = aggregate_store(db_session, store_id,
                             datetime(2026, 11, 14, 4, 0, 0, tzinfo=timezone.utc))

    first_line = db_session.scalar(select(SalesSummaryLine).where(
        SalesSummaryLine.sync_batch_id == first))
    second_line = db_session.scalar(select(SalesSummaryLine).where(
        SalesSummaryLine.sync_batch_id == second))
    assert (first_line.sold_qty, first_line.returned_qty) == (2, 0)
    assert first_line.net_revenue == Decimal("20.00")
    assert (second_line.sold_qty, second_line.returned_qty) == (0, 2)
    assert second_line.net_revenue == Decimal("-20.00")
    assert first_line.net_revenue + second_line.net_revenue == Decimal("0.00")


def test_pb14_lock_timeout_is_restored_after_aggregation(db_session):
    skus = [f"TEST-SKU-{_uid(5)}"]
    store_id, pos_id = _create_store(db_session, skus)
    _add_transaction(db_session, store_id, pos_id, "SALE",
                     [(skus[0], 1, Decimal("10.00"))])

    aggregate_store(db_session, store_id, datetime.now(timezone.utc))

    assert db_session.execute(text("SELECT @@LOCK_TIMEOUT")).scalar() == -1
