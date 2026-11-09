"""Batch message and HQ sender (PB-15-2 to 15-5, PB-16-1, PB-16-2).

The send cycle opens its own sessions, so the batches here are committed for
real in RTS_DB_TEST and deleted afterwards. HQ is faked with an
httpx.MockTransport that behaves like the HQ demo: it stores a batch id once and
answers a repeat with ``duplicate: true``. The sender picks batches of every
store, so assertions filter on this test's own batch ids.
"""

from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import importlib
import json
import sys
import threading
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import Engine, bindparam, delete, select, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.domain.models import AuditLog, Product, Store, SyncBatch
from app.integration import hq_client
from app.jobs import scheduler, sync_send
from app.jobs.scheduler import Job, Scheduler
from app.jobs.sync_send import run_send_cycle
from app.services.sync_message import batch_hash, build_message


HQ_SECRET = "test-only-hq-secret-with-enough-length-for-hs256"
NOW = datetime(2026, 11, 14, 10, 0, 0)


def _uid(length: int = 5) -> str:
    return uuid4().hex[:length].upper()


class Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


class FakeHq:
    """Like the HQ demo: idempotent by batch id; each call can be told how to answer."""

    def __init__(self, test_engine: Engine) -> None:
        self.engine = test_engine
        self.stored: dict[str, str] = {}
        self.received: list[dict] = []
        self.bodies: list[bytes] = []
        self.status_during_call: dict[str, str] = {}
        self.plan: dict[str, list[str]] = {}
        self.hold: threading.Event | None = None
        self.entered = threading.Event()

    def answer_next(self, batch_id: str, *answers: str) -> None:
        self.plan.setdefault(batch_id, []).extend(answers)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        message = json.loads(request.content, parse_float=Decimal)
        batch_id = message["batch_id"]
        self.received.append(message)
        self.bodies.append(request.content)
        with Session(self.engine) as session:
            self.status_during_call[batch_id] = session.get(SyncBatch, batch_id).status
        self.entered.set()
        if self.hold is not None:
            self.hold.wait(timeout=10)
        planned = self.plan.get(batch_id)
        answer = planned.pop(0) if planned else "ONLINE"
        if answer == "OFFLINE":
            return httpx.Response(503, json={"status": "NACK", "batch_id": batch_id, "code": "HQ_OFFLINE",
                                             "message": "HQ is offline for this demo."})
        if answer == "TIMEOUT_AFTER_STORE":
            self.stored.setdefault(batch_id, batch_id)
            raise httpx.ReadTimeout("HQ stored the batch but the answer was lost")
        duplicate = batch_id in self.stored
        self.stored.setdefault(batch_id, batch_id)
        if answer == "DROP_ACK":
            return httpx.Response(500, json={"status": "NACK", "batch_id": batch_id, "code": "ACK_DROPPED",
                                             "message": "Batch stored, ACK dropped."})
        return httpx.Response(200, json={"status": "ACK", "batch_id": batch_id, "duplicate": duplicate})

    def ids(self, own: set[str]) -> list[str]:
        return [message["batch_id"] for message in self.received if message["batch_id"] in own]


@pytest.fixture(autouse=True)
def hq(monkeypatch, test_engine: Engine) -> FakeHq:
    fake = FakeHq(test_engine)
    monkeypatch.setattr(settings, "hq_url", "https://hq.test/api/v1")
    monkeypatch.setattr(settings, "hq_jwt_secret", SecretStr(HQ_SECRET))
    monkeypatch.setattr(settings, "hq_ca_file", None)
    monkeypatch.setattr(hq_client, "transport", httpx.MockTransport(fake))
    monkeypatch.setattr(sync_send, "session_factory", lambda: Session(test_engine))
    monkeypatch.setattr(sync_send, "clock", Clock(NOW))
    return fake


class World:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.stores: list[str] = []
        self.batches: list[str] = []
        self.skus = [f"TEST-SKU-{_uid(6)}", f"TEST-SKU-{_uid(6)}"]
        with Session(engine) as session:
            for sku in self.skus:
                session.add(Product(sku=sku, barcode=f"BC-{sku}", name="Sync test product",
                                    category="TEST", unit_price=Decimal("10.00")))
            session.commit()

    def store(self) -> str:
        store_id = f"TEST-{_uid()}"
        with Session(self.engine) as session:
            session.add(Store(store_id=store_id, name="Sync test store", latitude=Decimal("16.000000"),
                              longitude=Decimal("108.000000"), region_id="TEST"))
            session.commit()
        self.stores.append(store_id)
        return store_id

    def batch(self, store_id: str, age: timedelta, status: str = "PENDING",
              next_retry_at: datetime | None = None,
              lines: list[tuple[int, int, str]] | None = None) -> str:
        created = NOW - age
        batch_id = f"SB-{store_id}-{created:%Y%m%d%H%M%S}"
        lines = lines or [(2, 0, "20.10"), (1, 1, "0.00")]
        with Session(self.engine) as session:
            session.add(SyncBatch(sync_batch_id=batch_id, store_id=store_id, period_start=created,
                                  period_end=created, txn_count=3, status=status, attempts=0,
                                  next_retry_at=next_retry_at, created_at=created))
            session.flush()
            for sku, (sold, returned, revenue) in zip(reversed(self.skus), reversed(lines)):
                session.execute(text(
                    "INSERT dbo.sales_summary_line (sync_batch_id, sku, sold_qty, returned_qty, net_revenue) "
                    "VALUES (:batch, :sku, :sold, :returned, :revenue)"),
                    {"batch": batch_id, "sku": sku, "sold": sold, "returned": returned, "revenue": Decimal(revenue)})
            session.commit()
        self.batches.append(batch_id)
        return batch_id

    def row(self, batch_id: str) -> SyncBatch:
        with Session(self.engine) as session:
            return session.get(SyncBatch, batch_id)

    def audits(self, batch_id: str) -> list[AuditLog]:
        with Session(self.engine) as session:
            return list(session.scalars(select(AuditLog).where(
                AuditLog.entity_name == "sync_batch", AuditLog.entity_key == batch_id)))

    def cleanup(self) -> None:
        with Session(self.engine) as session:
            if self.batches:
                session.execute(delete(AuditLog).where(AuditLog.entity_name == "sync_batch",
                                                       AuditLog.entity_key.in_(self.batches)))
                session.execute(text("DELETE dbo.sales_summary_line WHERE sync_batch_id IN :ids")
                                .bindparams(bindparam("ids", expanding=True)), {"ids": self.batches})
                session.execute(delete(SyncBatch).where(SyncBatch.sync_batch_id.in_(self.batches)))
            session.execute(delete(Product).where(Product.sku.in_(self.skus)))
            if self.stores:
                session.execute(delete(Store).where(Store.store_id.in_(self.stores)))
            session.commit()


@pytest.fixture
def world(test_engine: Engine) -> Generator[World, None, None]:
    created = World(test_engine)
    try:
        yield created
    finally:
        created.cleanup()


# The message (PB-15-2)


def test_pb15_message_matches_sync_batch_message(world, test_engine):
    batch_id = world.batch(world.store(), timedelta(hours=1), lines=[(2, 0, "5.5"), (1, 1, "0")])

    with Session(test_engine) as session:
        message = build_message(session, batch_id)

    assert set(message) == {"batch_id", "store_id", "created_at", "txn_count", "lines"}
    assert message["batch_id"] == batch_id
    assert message["store_id"] == world.stores[0]
    assert message["created_at"] == "2026-11-14T09:00:00Z"
    assert message["txn_count"] == 3
    assert [line["sku"] for line in message["lines"]] == sorted(world.skus)
    for line in message["lines"]:
        assert set(line) == {"sku", "sold_qty", "returned_qty", "net_revenue"}
        assert isinstance(line["sold_qty"], int) and isinstance(line["returned_qty"], int)
        assert isinstance(line["net_revenue"], Decimal)
        assert line["net_revenue"].as_tuple().exponent == -2
    assert sorted(str(line["net_revenue"]) for line in message["lines"]) == ["0.00", "5.50"]


def test_pb15_message_of_an_unknown_batch_is_an_error(test_engine):
    with Session(test_engine) as session, pytest.raises(LookupError, match="SB-TEST-NONE"):
        build_message(session, "SB-TEST-NONE")


def test_pb15_hash_follows_ds05():
    message = {
        "batch_id": "SB-TEST-HASH-20261114010203", "store_id": "TEST-HASH",
        "created_at": "2026-11-14T01:02:03Z", "txn_count": 3,
        "lines": [
            {"sku": "TEST-SKU-B", "sold_qty": 1, "returned_qty": 1, "net_revenue": Decimal("0")},
            {"sku": "TEST-SKU-A", "sold_qty": 2, "returned_qty": 0, "net_revenue": Decimal("20.1")},
        ],
    }

    # SHA-256 of {"batch_id":...,"lines":[{"net_revenue":"20.10",...},...],"store_id":...,"txn_count":3}
    assert batch_hash(message) == "ab1cd0a4607bb279d77bdc1622bc5013d7724b904762e989d2140b5f897e1662"
    assert batch_hash({**message, "created_at": "2030-01-01T00:00:00Z"}) == batch_hash(message)


def test_pb15_hash_is_the_same_on_resend(world, test_engine, hq):
    batch_id = world.batch(world.store(), timedelta(hours=1))
    hq.answer_next(batch_id, "OFFLINE")
    with Session(test_engine) as session:
        before = build_message(session, batch_id)

    run_send_cycle()
    run_send_cycle()

    with Session(test_engine) as session:
        after = build_message(session, batch_id)
    assert after == before and batch_hash(after) == batch_hash(before)
    first, second = (json.loads(body, parse_float=Decimal) for body in hq.bodies if batch_id.encode() in body)
    assert first == second


# Sending (PB-15-3, 15-4) and the ACK (PB-16-1, 16-2)


def test_sync15_3_batches_are_sent_oldest_first(world, hq):
    first_store, second_store = world.store(), world.store()
    newest = world.batch(first_store, timedelta(hours=1))
    oldest = world.batch(second_store, timedelta(hours=3))
    middle = world.batch(first_store, timedelta(hours=2))

    result = run_send_cycle()

    own = {newest, oldest, middle}
    assert hq.ids(own) == [oldest, middle, newest]
    assert {world.row(batch_id).status for batch_id in own} == {"ACKED"}
    assert [batch_id for batch_id in result.acked if batch_id in own] == [oldest, middle, newest]


def test_sync15_4_status_is_sent_while_the_call_is_in_progress(world, hq):
    batch_id = world.batch(world.store(), timedelta(hours=1))

    run_send_cycle()

    assert hq.status_during_call[batch_id] == "SENT"
    assert world.row(batch_id).status == "ACKED"


def test_sync16_1_ack_sets_acked_acked_at_and_writes_the_audit(world, hq):
    batch_id = world.batch(world.store(), timedelta(hours=1))

    run_send_cycle()

    row = world.row(batch_id)
    body = next(body for body in hq.bodies if batch_id.encode() in body)
    assert (row.status, row.acked_at, row.attempts, row.last_error) == ("ACKED", NOW, 0, None)
    assert row.next_retry_at is None
    assert row.payload_bytes == len(body)
    audits = world.audits(batch_id)
    assert [(audit.action, audit.entity_name, audit.entity_key) for audit in audits] == [
        ("SYNC_ACKED", "sync_batch", batch_id)]


@pytest.mark.parametrize("lost", ["DROP_ACK", "TIMEOUT_AFTER_STORE"])
def test_sync16_2_lost_ack_is_resent_with_the_same_id_and_acked_once(world, hq, lost):
    batch_id = world.batch(world.store(), timedelta(hours=1))
    hq.answer_next(batch_id, lost)

    first = run_send_cycle()
    row = world.row(batch_id)
    assert (row.status, row.attempts) == ("PENDING", 1)
    assert row.last_error
    assert first.failed == batch_id

    second = run_send_cycle()

    assert hq.ids({batch_id}) == [batch_id, batch_id]
    assert batch_id in second.acked
    assert world.row(batch_id).status == "ACKED"
    audits = world.audits(batch_id)
    assert [audit.action for audit in audits] == ["SYNC_ACKED"]
    assert "duplicate" in audits[0].details
    assert len(hq.stored) == len(set(hq.stored))


def test_sync16_8_stale_sent_returns_to_pending_and_is_resent(world, hq):
    store_id = world.store()
    stale = world.batch(store_id, timedelta(hours=2), status="SENT", next_retry_at=NOW - timedelta(seconds=1))
    fresh = world.batch(world.store(), timedelta(hours=1), status="SENT", next_retry_at=NOW + timedelta(seconds=30))

    result = run_send_cycle()

    assert result.released >= 1
    assert world.row(stale).status == "ACKED"
    assert hq.ids({stale, fresh}) == [stale]
    assert world.row(fresh).status == "SENT"


def test_pb15_batch_of_another_store_does_not_block(world, hq):
    busy_store, other_store = world.store(), world.store()
    in_flight = world.batch(busy_store, timedelta(hours=2), status="SENT", next_retry_at=NOW + timedelta(seconds=30))
    waiting = world.batch(other_store, timedelta(hours=1))

    run_send_cycle()

    assert hq.ids({in_flight, waiting}) == [waiting]
    assert world.row(waiting).status == "ACKED"


def test_pb15_failed_batch_is_never_picked(world, hq):
    store_id = world.store()
    failed = world.batch(store_id, timedelta(hours=3), status="FAILED")
    pending = world.batch(store_id, timedelta(hours=1))

    run_send_cycle()

    assert hq.ids({failed, pending}) == [pending]
    assert world.row(failed).status == "FAILED"


def test_pb15_batch_whose_retry_is_not_due_is_not_picked(world, hq):
    later = world.batch(world.store(), timedelta(hours=2), next_retry_at=NOW + timedelta(minutes=5))
    due = world.batch(world.store(), timedelta(hours=1), next_retry_at=NOW - timedelta(minutes=5))

    run_send_cycle()

    assert hq.ids({later, due}) == [due]
    assert world.row(later).status == "PENDING"


def test_pb15_any_other_answer_returns_the_batch_and_stops_the_cycle(world, hq):
    first = world.batch(world.store(), timedelta(hours=2))
    second = world.batch(world.store(), timedelta(hours=1))
    hq.answer_next(first, "OFFLINE")

    result = run_send_cycle()

    row = world.row(first)
    assert (row.status, row.attempts) == ("PENDING", 1)
    assert row.last_error.startswith("503 HQ_OFFLINE")
    assert row.payload_bytes > 0
    assert hq.ids({first, second}) == [first]
    assert world.row(second).status == "PENDING"
    assert result.failed == first
    assert world.audits(first) == []


def test_pb15_only_one_cycle_runs_at_a_time(world, hq):
    batch_id = world.batch(world.store(), timedelta(hours=1))
    hq.hold = threading.Event()
    results: list = []
    runner = threading.Thread(target=lambda: results.append(run_send_cycle()))
    runner.start()
    assert hq.entered.wait(timeout=10)

    second = run_send_cycle()
    hq.hold.set()
    runner.join(timeout=10)

    assert second.skipped is True
    assert hq.ids({batch_id}) == [batch_id]
    assert results[0].acked == [batch_id] or batch_id in results[0].acked


def test_pb15_without_a_service_secret_no_batch_is_touched(world, hq, monkeypatch):
    batch_id = world.batch(world.store(), timedelta(hours=1))
    monkeypatch.setattr(settings, "hq_jwt_secret", None)

    result = run_send_cycle()

    assert "HQ_JWT_SECRET" in result.error
    assert hq.received == []
    assert world.row(batch_id).status == "PENDING"


def test_pb15_missing_ca_file_touches_no_batch(world, hq, monkeypatch):
    batch_id = world.batch(world.store(), timedelta(hours=1))
    monkeypatch.setattr(settings, "hq_ca_file", "/no/such/ca.crt")

    result = run_send_cycle()

    assert "HQ_CA_FILE" in result.error
    assert world.row(batch_id).status == "PENDING"


# The scheduled job (SYNC15-1)


def test_sync15_1_the_job_runs_each_interval(world, hq):
    first = world.batch(world.store(), timedelta(hours=2))
    clock_now = [datetime(2026, 11, 14, 3, 0, tzinfo=timezone.utc)]

    class HeldLock:
        def acquire(self) -> bool:
            return True

        def holds(self) -> bool:
            return True

        def release(self) -> None:
            pass

    sched = Scheduler([Job("sync-send", run_send_cycle, every_seconds=60)], lock=HeldLock(),
                      clock=lambda: clock_now[0])

    assert sched.tick() == []
    clock_now[0] += timedelta(seconds=60)
    assert sched.tick() == ["sync-send"]
    assert world.row(first).status == "ACKED"

    second = world.batch(world.store(), timedelta(hours=1))
    clock_now[0] += timedelta(seconds=60)
    assert sched.tick() == ["sync-send"]
    assert world.row(second).status == "ACKED"


def test_sync15_1_sync_send_is_registered_every_sync_interval(monkeypatch):
    monkeypatch.setattr(scheduler, "_jobs", {})
    monkeypatch.setattr(settings, "sync_interval", 60)
    monkeypatch.delitem(sys.modules, "app.jobs.registry", raising=False)

    importlib.import_module("app.jobs.registry")

    jobs = {job.name: job for job in scheduler.registered_jobs()}
    assert jobs["sync-send"].run is run_send_cycle
    assert (jobs["sync-send"].every_seconds, jobs["sync-send"].daily_at) == (60, None)
