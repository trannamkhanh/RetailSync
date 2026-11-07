"""Bounded lock waits on the POS path (PB-04-5).

A second connection holds a lock while a SALE is sent. The SALE runs on its own
one-connection pool, as in production, so afterwards the test can read that
connection's LOCK_TIMEOUT from sys.dm_exec_sessions. The world is committed for
real, so the holder never waits on the test's own transaction, and it is deleted
afterwards with everything the events wrote.
"""

from collections.abc import Generator
from contextlib import contextmanager
import threading
from time import perf_counter

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine, create_engine, delete, select, text
from sqlalchemy.orm import Session

from app.core.config import Settings, settings
from app.core.db import database_url, get_db
from app.domain.models import (
    AuditLog, Inventory, InventoryMovement, PosTerminal, PosTransaction,
    Product, StaffUser, Store, TransactionItem,
)
from app.main import app
from tests.pos_test_support import World, assert_error, post, sale_payload, seed_sale, uid


SECRET = "test-only-secret-with-enough-length-for-hs256"
AUDIT_TABLE_LOCK = "SELECT TOP 1 * FROM dbo.audit_log WITH (TABLOCKX, HOLDLOCK)"
INVENTORY_ROW_LOCK = ("SELECT quantity FROM dbo.inventory WITH (UPDLOCK, ROWLOCK) "
                      "WHERE store_id = :store_id AND sku = :sku")


@pytest.fixture(autouse=True)
def jwt_secret(monkeypatch):
    monkeypatch.setattr(settings, "jwt_secret", SecretStr(SECRET))


@pytest.fixture
def world(test_engine: Engine) -> Generator[World, None, None]:
    with Session(test_engine) as session:
        world = seed_sale(session, sold={f"TEST-SKU-{uid(8)}": 2}, stock=10)
    try:
        yield world
    finally:
        with Session(test_engine) as session:
            txn_ids = select(PosTransaction.txn_id).where(PosTransaction.store_id == world.store_id)
            session.execute(delete(AuditLog).where(AuditLog.user_id == world.user_id))
            session.execute(delete(InventoryMovement).where(InventoryMovement.store_id == world.store_id))
            session.execute(delete(TransactionItem).where(TransactionItem.txn_id.in_(txn_ids)))
            session.execute(delete(PosTransaction).where(PosTransaction.store_id == world.store_id))
            session.execute(delete(Inventory).where(Inventory.store_id == world.store_id))
            session.execute(delete(PosTerminal).where(PosTerminal.pos_id == world.pos_id))
            session.execute(delete(StaffUser).where(StaffUser.user_id == world.user_id))
            session.execute(delete(Product).where(Product.sku.in_(world.skus)))
            session.execute(delete(Store).where(Store.store_id == world.store_id))
            session.commit()


@pytest.fixture
def pos_engine() -> Generator[Engine, None, None]:
    """One pooled connection, so the request's connection is the one inspected later."""
    engine = create_engine(database_url(settings.test_db_name), pool_size=1, max_overflow=0,
                           connect_args={"timeout": 5}, hide_parameters=True)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def pos_client(pos_engine: Engine) -> Generator[TestClient, None, None]:
    def pooled_db() -> Generator[Session, None, None]:
        with Session(pos_engine) as session:
            try:
                yield session
            except BaseException:
                session.rollback()
                raise

    previous = app.dependency_overrides.copy()
    app.dependency_overrides[get_db] = pooled_db
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)


@contextmanager
def held_lock(test_engine: Engine, sql: str, params: dict):
    with test_engine.connect() as holder:
        transaction = holder.begin()
        holder.execute(text(sql), params)
        try:
            yield
        finally:
            transaction.rollback()


def send_while_locked(test_engine: Engine, client: TestClient, payload: dict, token: str,
                      sql: str, params: dict) -> tuple:
    """Send while the lock is held; give up waiting after the timeout plus three seconds."""
    result: dict = {}

    def send() -> None:
        started = perf_counter()
        result["response"] = post(client, payload, token)
        result["waited"] = perf_counter() - started

    sender = threading.Thread(target=send)
    with held_lock(test_engine, sql, params):
        sender.start()
        sender.join(timeout=settings.pos_lock_timeout_ms / 1000 + 3)
    sender.join(timeout=30)
    return result.get("response"), result.get("waited")


def assert_nothing_stored(test_engine: Engine, world: World, txn_id: str, sku: str) -> None:
    with Session(test_engine) as session:
        assert session.get(PosTransaction, txn_id) is None
        assert session.scalars(select(TransactionItem).where(TransactionItem.txn_id == txn_id)).all() == []
        assert session.scalars(select(InventoryMovement).where(InventoryMovement.txn_id == txn_id)).all() == []
        assert session.get(Inventory, (world.store_id, sku)).quantity == 10
        assert session.scalars(select(AuditLog.action).where(AuditLog.entity_key == txn_id)).all() == []


def connection_lock_timeout(pos_engine: Engine) -> int:
    with pos_engine.connect() as connection:
        return connection.exec_driver_sql(
            "SELECT lock_timeout FROM sys.dm_exec_sessions WHERE session_id = @@SPID").scalar()


@pytest.mark.parametrize("lock", ["audit_log", "inventory"])
def test_pb04_5_lock_held_lock_gives_503_then_the_resend_applies(test_engine, world, pos_engine,
                                                                 pos_client, lock):
    sku = world.skus[0]
    payload = sale_payload(world, [(sku, 1, "10.00")])
    sql, params = ((AUDIT_TABLE_LOCK, {}) if lock == "audit_log"
                   else (INVENTORY_ROW_LOCK, {"store_id": world.store_id, "sku": sku}))
    timeout = settings.pos_lock_timeout_ms / 1000

    response, waited = send_while_locked(test_engine, pos_client, payload, world.token, sql, params)

    assert waited is not None and waited < timeout + 1, f"waited {waited}s while the lock was held"
    assert waited >= timeout - 0.2
    assert_error(response, 503, "SERVICE_UNAVAILABLE")
    assert_nothing_stored(test_engine, world, payload["transaction_id"], sku)
    assert connection_lock_timeout(pos_engine) == -1

    resent = post(pos_client, payload, world.token)

    assert resent.status_code == 200, resent.text
    assert resent.json()["outcome"] == "OK"
    assert resent.json()["current_stock"] == {sku: 9}
    assert connection_lock_timeout(pos_engine) == -1


def test_pb04_5_lock_connection_returns_with_default_timeout(test_engine, world, pos_engine, pos_client):
    sku = world.skus[0]
    payload = sale_payload(world, [(sku, 1, "10.00")])

    assert post(pos_client, payload, world.token).json()["outcome"] == "OK"
    assert connection_lock_timeout(pos_engine) == -1
    assert post(pos_client, payload, world.token).json()["outcome"] == "DUPLICATE"
    assert connection_lock_timeout(pos_engine) == -1
    rejected = post(pos_client, sale_payload(world, [("TEST-SKU-MISSING", 1, "10.00")]), world.token)
    assert rejected.status_code == 422
    assert connection_lock_timeout(pos_engine) == -1


def test_pb04_5_lock_timeout_is_configurable(test_engine, world, pos_engine, pos_client, monkeypatch):
    monkeypatch.setattr(settings, "pos_lock_timeout_ms", 500)
    sku = world.skus[0]
    payload = sale_payload(world, [(sku, 1, "10.00")])

    response, waited = send_while_locked(test_engine, pos_client, payload, world.token,
                                         INVENTORY_ROW_LOCK, {"store_id": world.store_id, "sku": sku})

    assert waited is not None and 0.3 <= waited < 1.5
    assert_error(response, 503, "SERVICE_UNAVAILABLE")


def test_pb04_5_lock_timeout_defaults_to_2000_ms():
    assert Settings(_env_file=None).pos_lock_timeout_ms == 2000
