"""Manual sync: POST /api/v1/sync/run (SYNC15-5).

The request runs the real aggregation and send jobs. Both open their own
sessions, so their ``session_factory`` points at RTS_DB_TEST, never at DB_NAME,
and the store, its transactions and its batches are committed for real and
deleted afterwards. HQ is an httpx.MockTransport.
"""

from collections.abc import Generator
from decimal import Decimal
import json
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import Engine, delete, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import create_token
from app.domain.models import (
    AuditLog,
    PosTerminal,
    PosTransaction,
    Product,
    SalesSummaryLine,
    StaffUser,
    Store,
    SyncBatch,
    TransactionItem,
)
from app.integration import hq_client
from app.jobs import aggregation, scheduler, sync_send


SECRET = "test-only-secret-with-enough-length-for-hs256"
HQ_SECRET = "test-only-hq-secret-with-enough-length-for-hs256"
URL = "/api/v1/sync/run"
ADMIN = "TEST-sync-admin"


def _uid(length: int = 6) -> str:
    return uuid4().hex[:length].upper()


class FakeHq:
    def __init__(self) -> None:
        self.online = True
        self.received: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        batch_id = json.loads(request.content)["batch_id"]
        self.received.append(batch_id)
        if not self.online:
            return httpx.Response(503, json={"status": "NACK", "batch_id": batch_id, "code": "HQ_OFFLINE",
                                             "message": "HQ is offline."})
        return httpx.Response(200, json={"status": "ACK", "batch_id": batch_id, "duplicate": False})


@pytest.fixture(autouse=True)
def hq(monkeypatch, test_engine: Engine) -> FakeHq:
    fake = FakeHq()
    monkeypatch.setattr(settings, "jwt_secret", SecretStr(SECRET))
    monkeypatch.setattr(settings, "hq_url", "https://hq.test/api/v1")
    monkeypatch.setattr(settings, "hq_jwt_secret", SecretStr(HQ_SECRET))
    monkeypatch.setattr(settings, "hq_ca_file", None)
    monkeypatch.setattr(hq_client, "transport", httpx.MockTransport(fake))
    monkeypatch.setattr(aggregation, "session_factory", lambda: Session(test_engine))
    monkeypatch.setattr(sync_send, "session_factory", lambda: Session(test_engine))
    return fake


@pytest.fixture
def headers(db_session: Session) -> dict[str, str]:
    db_session.add(StaffUser(username=ADMIN, full_name="Sync admin", role="ADMIN"))
    db_session.flush()
    db_session.commit()
    return {"Authorization": f"Bearer {create_token(ADMIN, 'Admin')}"}


class World:
    """One store with two committed sales that no batch holds yet."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.store_id = f"TEST-{_uid(5)}"
        self.sku = f"TEST-SKU-{_uid(5)}"
        with Session(engine) as session:
            session.add(Store(store_id=self.store_id, name="Sync run store", latitude=Decimal("16.000000"),
                              longitude=Decimal("108.000000"), region_id="TEST"))
            session.add(Product(sku=self.sku, barcode=f"BC-{self.sku}", name="Sync run product",
                                category="TEST", unit_price=Decimal("10.00")))
            session.flush()
            pos_id = f"TEST-POS-{_uid(6)}"
            session.add(PosTerminal(pos_id=pos_id, store_id=self.store_id, status="ACTIVE"))
            session.flush()
            for quantity in (1, 2):
                txn_id = f"TEST-{_uid(10)}"
                session.add(PosTransaction(txn_id=txn_id, store_id=self.store_id, pos_id=pos_id, txn_type="SALE",
                                           status="OK", payload_hash="0" * 64))
                session.flush()
                session.add(TransactionItem(txn_id=txn_id, sku=self.sku, qty=quantity, unit_price=Decimal("10.00")))
            session.commit()

    def batches(self) -> list[SyncBatch]:
        with Session(self.engine) as session:
            return list(session.scalars(select(SyncBatch).where(SyncBatch.store_id == self.store_id)))

    def cleanup(self) -> None:
        with Session(self.engine) as session:
            batch_ids = list(session.scalars(select(SyncBatch.sync_batch_id)
                                             .where(SyncBatch.store_id == self.store_id)))
            txn_ids = select(PosTransaction.txn_id).where(PosTransaction.store_id == self.store_id)
            if batch_ids:
                session.execute(delete(AuditLog).where(AuditLog.entity_name == "sync_batch",
                                                       AuditLog.entity_key.in_(batch_ids)))
                session.execute(delete(SalesSummaryLine).where(SalesSummaryLine.sync_batch_id.in_(batch_ids)))
            session.execute(delete(TransactionItem).where(TransactionItem.txn_id.in_(txn_ids)))
            session.execute(delete(PosTransaction).where(PosTransaction.store_id == self.store_id))
            if batch_ids:
                session.execute(delete(SyncBatch).where(SyncBatch.sync_batch_id.in_(batch_ids)))
            session.execute(delete(PosTerminal).where(PosTerminal.store_id == self.store_id))
            session.execute(delete(Product).where(Product.sku == self.sku))
            session.execute(delete(Store).where(Store.store_id == self.store_id))
            session.commit()


# Tests list ``world`` before ``client``: it is then deleted after the request's
# savepoint transaction ends. Deleting the store earlier would wait for ever on
# that transaction's uncommitted staff_user row (foreign key check).
@pytest.fixture
def world(test_engine: Engine) -> Generator[World, None, None]:
    created = World(test_engine)
    try:
        yield created
    finally:
        created.cleanup()


def job(name: str) -> scheduler.Job:
    return next(job for job in scheduler.registered_jobs() if job.name == name)


def test_sync15_5_manual_trigger_answers_202_with_created_sent_and_pending(world, client, headers, hq):
    response = client.post(URL, headers=headers)

    assert response.status_code == 202, response.text
    assert response.json() == {"batches_created": 1, "batches_sent": 1, "batches_pending": 0}
    [batch] = world.batches()
    assert (batch.status, batch.txn_count) == ("ACKED", 2)
    assert hq.received == [batch.sync_batch_id]


def test_pb15_5_sync_run_while_hq_is_down_leaves_the_batch_pending(world, client, headers, hq):
    hq.online = False

    response = client.post(URL, headers=headers)

    assert response.status_code == 202, response.text
    assert response.json() == {"batches_created": 1, "batches_sent": 0, "batches_pending": 1}
    [batch] = world.batches()
    assert (batch.status, batch.attempts) == ("PENDING", 1)


def test_pb15_5_sync_run_joins_no_send_cycle_that_is_running(world, client, headers, hq):
    lock = job("sync-send").running
    assert lock.acquire(blocking=False)
    try:
        response = client.post(URL, headers=headers)
    finally:
        lock.release()

    assert response.status_code == 202, response.text
    assert response.json() == {"batches_created": 1, "batches_sent": 0, "batches_pending": 1}
    assert hq.received == []


def test_pb15_5_sync_run_joins_no_aggregation_that_is_running(world, client, headers, hq):
    lock = job("aggregation").running
    assert lock.acquire(blocking=False)
    try:
        response = client.post(URL, headers=headers)
    finally:
        lock.release()

    assert response.status_code == 202, response.text
    assert response.json() == {"batches_created": 0, "batches_sent": 0, "batches_pending": 0}
    assert world.batches() == []
