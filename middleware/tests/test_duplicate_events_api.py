"""PB-09-5: POS09-1 through POS09-8 over the real POS API and SQL Server.

POS09-1 identical resend; 2 new timestamp; 3 changed quantity; 4 parallel
requests; 5 unavailable duplicate check; 6 resend after that failure;
7 retry after a committed response is lost; 8 current stock after later sales.
All rows are test-owned. Parallel requests use independent database sessions.
"""

from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import dataclass
from decimal import Decimal
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, delete, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import create_token
from app.domain.models import (
    Inventory, InventoryMovement, PosTerminal, PosTransaction, Product,
    StaffUser, Store, TransactionItem,
)
from app.main import app
from app.repositories import idempotency as repository


URL = "/api/v1/pos/events"


@dataclass(frozen=True)
class World:
    store: str
    pos: str
    sku: str
    username: str
    token: str


def seed(session: Session) -> World:
    suffix = uuid4().hex[:5].upper()
    store, pos, sku, username = (
        f"TEST-{suffix}", f"TEST-POS-{suffix}",
        f"TEST-SKU-{suffix}", f"TEST-USER-{suffix}",
    )
    session.add(Store(store_id=store, name="Duplicate API test", latitude=0, longitude=0, region_id="TEST"))
    session.add(Product(sku=sku, barcode=sku, name="Test product", category="TEST", unit_price=Decimal("10.00")))
    session.flush()
    session.add(PosTerminal(pos_id=pos, store_id=store, status="ACTIVE"))
    session.add(StaffUser(username=username, full_name="Test POS", role="POS_SYSTEM", store_id=None))
    session.add(Inventory(store_id=store, sku=sku, quantity=10))
    session.flush()
    session.commit()
    return World(store, pos, sku, username, create_token(username, "POS", store_id=store, pos_id=pos))


@pytest.fixture
def world(db_session: Session) -> World:
    # db_session's outer transaction contains even the router's commits.
    return seed(db_session)


def payload(world: World) -> dict:
    return {
        "event_type": "SALE", "transaction_id": f"TEST-TXN-{uuid4().hex[:20]}",
        "store_id": world.store, "pos_id": world.pos,
        "timestamp": "2026-11-03T00:00:00Z",
        "items": [{"sku": world.sku, "quantity": 2, "unit_price": "10.00"}],
    }


def post(client: TestClient, world: World, event: dict):
    return client.post(URL, json=event, headers={"Authorization": f"Bearer {world.token}"})


def snapshot(session: Session, world: World) -> dict:
    """Compare persisted content, not cached objects or response quantities."""
    session.expire_all()
    return {
        "stock": session.get(Inventory, (world.store, world.sku)).quantity,
        "transactions": session.execute(select(
            PosTransaction.txn_id, PosTransaction.payload_hash, PosTransaction.status,
        ).where(PosTransaction.store_id == world.store).order_by(PosTransaction.txn_id)).all(),
        "items": session.execute(select(
            TransactionItem.txn_id, TransactionItem.sku, TransactionItem.qty, TransactionItem.unit_price,
        ).join(PosTransaction, TransactionItem.txn_id == PosTransaction.txn_id)
          .where(PosTransaction.store_id == world.store).order_by(TransactionItem.item_id)).all(),
        "movements": session.execute(select(
            InventoryMovement.txn_id, InventoryMovement.movement_type, InventoryMovement.quantity,
        ).where(InventoryMovement.store_id == world.store).order_by(InventoryMovement.movement_id)).all(),
    }


def assert_applied(response, world: World, quantity: int = 8) -> None:
    assert response.status_code == 200, response.text
    assert response.json() == {
        "outcome": "OK", "code": "OK", "message": "Event applied",
        "current_stock": {world.sku: quantity},
    }


def assert_duplicate(response, world: World, quantity: int = 8) -> None:
    assert response.status_code == 200, response.text
    assert response.json() == {
        "outcome": "DUPLICATE", "code": "DUPLICATE_IGNORED",
        "message": "Transaction already recorded", "current_stock": {world.sku: quantity},
    }


def assert_one_sale(state: dict) -> None:
    assert state["stock"] == 8
    assert len(state["transactions"]) == len(state["items"]) == len(state["movements"]) == 1
    assert state["items"][0].qty == 2
    assert state["movements"][0].movement_type == "SALE"
    assert state["movements"][0].quantity == -2


def test_pos09_1_identical_sale_is_applied_once(client, db_session, world) -> None:
    event = payload(world)
    assert_applied(post(client, world, event), world)
    before = snapshot(db_session, world)
    assert_one_sale(before)
    assert_duplicate(post(client, world, event), world)
    assert snapshot(db_session, world) == before


def test_pos09_2_new_timestamp_is_still_duplicate(client, db_session, world) -> None:
    event = payload(world)
    assert_applied(post(client, world, event), world)
    before = snapshot(db_session, world)
    assert_duplicate(post(client, world, {**event, "timestamp": "2026-11-04T12:30:00Z"}), world)
    assert snapshot(db_session, world) == before


def test_pos09_3_changed_quantity_conflicts_without_changes(client, db_session, world) -> None:
    event = payload(world)
    assert_applied(post(client, world, event), world)
    before = snapshot(db_session, world)
    changed = deepcopy(event)
    changed["items"][0]["quantity"] = 3
    response = post(client, world, changed)
    assert response.status_code == 409, response.text
    assert response.json()["outcome"] == "REJECTED"
    assert response.json()["code"] == "CONFLICT"
    assert response.json()["message"]
    assert snapshot(db_session, world) == before


def cleanup(engine: Engine, world: World) -> None:
    with Session(engine) as session:
        txns = select(PosTransaction.txn_id).where(PosTransaction.store_id == world.store)
        session.execute(delete(InventoryMovement).where(InventoryMovement.store_id == world.store))
        session.execute(delete(TransactionItem).where(TransactionItem.txn_id.in_(txns)))
        session.execute(delete(PosTransaction).where(PosTransaction.store_id == world.store))
        session.execute(delete(Inventory).where(Inventory.store_id == world.store))
        session.execute(delete(PosTerminal).where(PosTerminal.store_id == world.store))
        session.execute(delete(StaffUser).where(StaffUser.username == world.username))
        session.execute(delete(Product).where(Product.sku == world.sku))
        session.execute(delete(Store).where(Store.store_id == world.store))
        session.commit()


def test_pos09_4_parallel_requests_change_stock_once(test_engine, monkeypatch) -> None:
    with Session(test_engine) as setup:
        world = seed(setup)
    event = payload(world)
    barrier = Barrier(2)
    original_read = repository.find_payload_hash
    def synchronized_read(session: Session, txn_id: str) -> str | None:
        result = original_read(session, txn_id)
        if not session.info.get("initial_duplicate_check"):
            session.info["initial_duplicate_check"] = True
            assert result is None
            barrier.wait(timeout=10)
        return result
    monkeypatch.setattr(repository, "find_payload_hash", synchronized_read)

    def independent_db() -> Generator[Session, None, None]:
        with Session(test_engine) as session:
            try:
                yield session
            except BaseException:
                session.rollback()
                raise

    previous = app.dependency_overrides.copy()
    app.dependency_overrides[get_db] = independent_db
    try:
        with TestClient(app) as request_client:
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(post, request_client, world, event) for _ in range(2)]
                responses = [future.result(timeout=20) for future in futures]
        assert [response.status_code for response in responses] == [200, 200]
        by_outcome = {response.json()["outcome"]: response for response in responses}
        assert set(by_outcome) == {"OK", "DUPLICATE"}
        assert_applied(by_outcome["OK"], world)
        assert_duplicate(by_outcome["DUPLICATE"], world)
        with Session(test_engine) as verification:
            assert_one_sale(snapshot(verification, world))
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)
        cleanup(test_engine, world)


def failed_check(client, world, event, monkeypatch):
    def unavailable(*args, **kwargs):
        raise OperationalError("simulated duplicate lookup failure", {}, RuntimeError("offline"))
    with monkeypatch.context() as patch:
        patch.setattr(repository, "find_payload_hash", unavailable)
        # Preserve the fixture's get_db override but let the global handler return 503.
        with TestClient(app, raise_server_exceptions=False) as failing_client:
            response = post(failing_client, world, event)
    assert response.status_code == 503, response.text
    assert response.json() == {
        "outcome": "ERROR", "code": "SERVICE_UNAVAILABLE",
        "message": "Service unavailable. Try again later.",
    }


def test_pos09_5_duplicate_check_failure_changes_nothing(client, db_session, world, monkeypatch) -> None:
    before = snapshot(db_session, world)
    failed_check(client, world, payload(world), monkeypatch)
    assert snapshot(db_session, world) == before


def test_pos09_6_resend_after_check_failure_is_new(client, db_session, world, monkeypatch) -> None:
    event = payload(world)
    before = snapshot(db_session, world)
    failed_check(client, world, event, monkeypatch)
    assert snapshot(db_session, world) == before
    assert_applied(post(client, world, event), world)
    assert_one_sale(snapshot(db_session, world))
    assert_duplicate(post(client, world, event), world)
    assert_one_sale(snapshot(db_session, world))


def test_pos09_7_retry_after_lost_committed_response(client, db_session, world) -> None:
    event = payload(world)
    # The POS discards a completed response, then retries the same transaction ID.
    post(client, world, event)
    before = snapshot(db_session, world)
    assert_one_sale(before)
    assert_duplicate(post(client, world, event), world)
    assert snapshot(db_session, world) == before


def test_pos09_8_duplicate_returns_stock_after_later_sale(client, db_session, world) -> None:
    event = payload(world)
    assert_applied(post(client, world, event), world)
    later = payload(world)
    later["items"][0]["quantity"] = 1
    assert_applied(post(client, world, later), world, quantity=7)
    before = snapshot(db_session, world)
    assert len(before["transactions"]) == len(before["items"]) == len(before["movements"]) == 2
    assert_duplicate(post(client, world, event), world, quantity=7)
    assert snapshot(db_session, world) == before
