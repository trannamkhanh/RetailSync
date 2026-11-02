"""PB-09 service behavior against real SQL Server, including insert races."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from decimal import Decimal
from hashlib import sha256
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.domain.models import (
    Inventory, InventoryMovement, PosTerminal, PosTransaction, Product, Store,
    TransactionItem,
)
from app.repositories import idempotency as repository
from app.services.idempotency import claim_transaction, content_hash, stock_of_transaction
from app.services.inventory import deduct_items


@dataclass
class World:
    store: str
    pos: str
    sku: str
    txn: str


def seed(session: Session) -> World:
    suffix = uuid4().hex[:5].upper()
    world = World(f"TEST-{suffix}", f"TEST-POS-{suffix}", f"TEST-SKU-{suffix}", f"TEST-TXN-{suffix}")
    session.add(Store(store_id=world.store, name="Idempotency test", latitude=0, longitude=0, region_id="TEST"))
    session.add(Product(sku=world.sku, barcode=world.sku, name="Test product", category="TEST", unit_price=Decimal("10.00")))
    session.flush()
    session.add(PosTerminal(pos_id=world.pos, store_id=world.store, status="ACTIVE"))
    session.add(Inventory(store_id=world.store, sku=world.sku, quantity=10))
    session.flush()
    return world


@pytest.fixture
def world(db_session: Session) -> World:
    return seed(db_session)


def claim(session: Session, world: World, payload: str = "a" * 64) -> bool:
    return claim_transaction(session, world.txn, world.store, world.pos, "SALE", None, payload)


def test_hash_reproduces_vector_in_reverse_item_order() -> None:
    result = content_hash("SALE", "STORE-DN1", "POS-DN1-01", None, [
        ("SKU-0002", 1, Decimal("7000")), ("SKU-0001", 2, Decimal("15000")),
    ])
    assert result == "e013b09b2bfaeea60e37919452faf8489b59c0904c301003abbedfd4b6b9a5df"


def test_hash_sorts_all_item_tiebreakers() -> None:
    items = [("TEST-SKU", 2, Decimal("10")), ("TEST-SKU", 1, Decimal("10")), ("TEST-SKU", 1, Decimal("2"))]
    canonical = ('{"event_type":"SALE","items":[{"quantity":1,"sku":"TEST-SKU","unit_price":"2.00"},'
                 '{"quantity":1,"sku":"TEST-SKU","unit_price":"10.00"},'
                 '{"quantity":2,"sku":"TEST-SKU","unit_price":"10.00"}],'
                 '"original_transaction_id":null,"pos_id":"TEST-POS","store_id":"TEST-STORE"}')
    assert content_hash("SALE", "TEST-STORE", "TEST-POS", None, items) == sha256(canonical.encode()).hexdigest()
    assert content_hash("SALE", "TEST-STORE", "TEST-POS", None, items) == content_hash("SALE", "TEST-STORE", "TEST-POS", None, list(reversed(items)))


def test_timestamp_is_not_a_hash_input() -> None:
    event = dict(event_type="SALE", store_id="TEST-STORE", pos_id="TEST-POS", original_transaction_id=None, items=[])
    def digest(timestamp: str) -> str:
        request = {**event, "timestamp": timestamp}
        return content_hash(**{key: value for key, value in request.items() if key != "timestamp"})
    assert digest("2026-11-01T00:00:00Z") == digest("2026-11-02T00:00:00Z")


def test_cancellation_ignores_items() -> None:
    assert content_hash("CANCELLATION", "TEST-STORE", "TEST-POS", "TEST-ORIG", []) == content_hash(
        "CANCELLATION", "TEST-STORE", "TEST-POS", "TEST-ORIG", [("TEST-SKU", 1, Decimal("10"))],
    )


@pytest.mark.parametrize("field,value", [
    ("event_type", "RETURN"), ("store_id", "TEST-OTHER"), ("pos_id", "TEST-OTHER"),
    ("original_transaction_id", "TEST-ORIG"), ("items", [("TEST-SKU", 2, Decimal("10"))]),
    ("items", [("TEST-OTHER", 1, Decimal("10"))]), ("items", [("TEST-SKU", 1, Decimal("11"))]),
])
def test_changed_field_changes_hash(field, value) -> None:
    event = dict(event_type="SALE", store_id="TEST-STORE", pos_id="TEST-POS", original_transaction_id=None, items=[("TEST-SKU", 1, Decimal("10"))])
    assert content_hash(**event) != content_hash(**{**event, field: value})


def test_new_and_duplicate_claim(db_session, world) -> None:
    assert claim(db_session, world) is True
    assert claim(db_session, world) is False
    row = db_session.get(PosTransaction, world.txn)
    assert (row.store_id, row.pos_id, row.status, row.payload_hash) == (world.store, world.pos, "OK", "a" * 64)
    assert db_session.scalar(select(func.count()).select_from(PosTransaction).where(PosTransaction.txn_id == world.txn)) == 1


def test_conflicting_claim_changes_nothing(db_session, world) -> None:
    claim(db_session, world)
    with pytest.raises(ApiError) as failure:
        claim(db_session, world, "b" * 64)
    assert (failure.value.status, failure.value.code) == (409, "CONFLICT")
    assert db_session.get(PosTransaction, world.txn).payload_hash == "a" * 64
    assert db_session.get(Inventory, (world.store, world.sku)).quantity == 10


def test_foreign_key_failure_is_reraised_and_session_survives(db_session, world) -> None:
    with pytest.raises(IntegrityError):
        claim_transaction(db_session, world.txn, world.store, "TEST-NO-POS", "SALE", None, "a" * 64)
    assert db_session.get(PosTransaction, world.txn) is None
    assert claim(db_session, world) is True


def test_rejected_sale_rolls_back_claim_and_resend_is_new(db_session, world) -> None:
    with pytest.raises(ApiError) as failure:
        with db_session.begin_nested():
            assert claim(db_session, world) is True
            deduct_items(db_session, world.store, [(world.sku, 11)], world.txn)
    assert failure.value.code == "INSUFFICIENT_STOCK"
    assert db_session.get(PosTransaction, world.txn) is None
    assert db_session.get(Inventory, (world.store, world.sku)).quantity == 10
    assert claim(db_session, world) is True


def test_stock_uses_stored_items_and_current_values(db_session, world) -> None:
    claim(db_session, world)
    db_session.add_all([
        TransactionItem(txn_id=world.txn, sku=world.sku, qty=1, unit_price=10),
        TransactionItem(txn_id=world.txn, sku=world.sku, qty=2, unit_price=10),
    ])
    db_session.flush()
    assert stock_of_transaction(db_session, world.store, world.txn) == {world.sku: 10}
    db_session.get(Inventory, (world.store, world.sku)).quantity = 7
    db_session.flush()
    assert stock_of_transaction(db_session, world.store, world.txn) == {world.sku: 7}
    assert stock_of_transaction(db_session, "TEST-OTHER", world.txn) == {}
    assert stock_of_transaction(db_session, world.store, "TEST-MISSING") == {}


@pytest.mark.parametrize("operation", ["find_payload_hash", "insert_transaction"])
def test_database_errors_propagate(db_session, world, monkeypatch, operation) -> None:
    failure = OperationalError("test database unavailable", {}, RuntimeError("offline"))
    def fail(*args, **kwargs):
        raise failure
    monkeypatch.setattr(repository, operation, fail)
    with pytest.raises(OperationalError) as raised:
        claim(db_session, world)
    assert raised.value is failure


def cleanup(engine, world: World) -> None:
    with Session(engine) as session:
        session.execute(delete(InventoryMovement).where(InventoryMovement.txn_id == world.txn))
        session.execute(delete(TransactionItem).where(TransactionItem.txn_id == world.txn))
        session.execute(delete(PosTransaction).where(PosTransaction.txn_id == world.txn))
        session.execute(delete(Inventory).where(Inventory.store_id == world.store))
        session.execute(delete(PosTerminal).where(PosTerminal.pos_id == world.pos))
        session.execute(delete(Product).where(Product.sku == world.sku))
        session.execute(delete(Store).where(Store.store_id == world.store))
        session.commit()


@pytest.mark.parametrize("conflicting", [False, True])
def test_concurrent_claims_commit_once(test_engine, monkeypatch, conflicting) -> None:
    with Session(test_engine) as setup:
        world = seed(setup)
        setup.commit()
    barrier = Barrier(2)
    original_read = repository.find_payload_hash
    def synchronized_read(session, txn_id):
        result = original_read(session, txn_id)
        if not session.info.get("checked"):
            session.info["checked"] = True
            assert result is None
            barrier.wait(timeout=10)
        return result
    monkeypatch.setattr(repository, "find_payload_hash", synchronized_read)
    def run(payload):
        with Session(test_engine) as session:
            try:
                inserted = claim(session, world, payload)
                if inserted:
                    session.add(TransactionItem(txn_id=world.txn, sku=world.sku, qty=2, unit_price=10))
                    session.flush()
                    deduct_items(session, world.store, [(world.sku, 2)], world.txn)
                session.commit()
                return "NEW" if inserted else "DUPLICATE"
            except ApiError as failure:
                session.rollback()
                assert (failure.status, failure.code) == (409, "CONFLICT")
                return "CONFLICT"
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(run, "a" * 64), pool.submit(run, ("b" if conflicting else "a") * 64)]
            results = [future.result(timeout=20) for future in futures]
        assert sorted(results) == sorted(["NEW", "CONFLICT" if conflicting else "DUPLICATE"])
        with Session(test_engine) as verification:
            assert verification.scalar(select(func.count()).select_from(PosTransaction).where(PosTransaction.txn_id == world.txn)) == 1
            assert verification.scalar(select(func.count()).select_from(TransactionItem).where(TransactionItem.txn_id == world.txn)) == 1
            assert verification.scalar(select(func.count()).select_from(InventoryMovement).where(InventoryMovement.txn_id == world.txn)) == 1
            assert verification.get(Inventory, (world.store, world.sku)).quantity == 8
    finally:
        cleanup(test_engine, world)
