"""Offline operation and recovery (PB-17, SYNC17-1 to 17-4 and 17-6).

SYNC17-1 and 17-2 run the POS and Staff paths while every call to HQ fails:
the HQ client is replaced by one that records the call and raises, so a test
fails if any of these requests calls HQ or waits for it. The cross-store
lookup (PB-35) is not on main yet and the alerts endpoint is PB-34 in Sprint 4,
so SYNC17-2 covers the stock query and the barcode lookup.

SYNC17-3, 17-4 and 17-6 drive the send cycle with committed batches in
RTS_DB_TEST and the fake HQ of ``test_sync_sender``.
"""

from collections.abc import Generator
from datetime import timedelta

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import create_token
from app.domain.models import PosTransaction, StaffUser
from app.integration import hq_client
from app.jobs import sync_send
from app.jobs.sync_send import run_send_cycle
from tests.pos_test_support import post, return_payload, sale_payload, seed_sale, stock, uid
from tests.test_sync_sender import HQ_SECRET, NOW, Clock, FakeHq, World


SECRET = "test-only-secret-with-enough-length-for-hs256"


class HqDown:
    """Every call to HQ is recorded and fails at once."""

    def __init__(self) -> None:
        self.calls = 0

    def send_batch(self, message: dict) -> hq_client.HqResult:
        self.calls += 1
        raise AssertionError("the POS and Staff paths must not call HQ")

    def transport(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        raise httpx.ConnectError("HQ is unreachable")


@pytest.fixture
def hq_down(monkeypatch) -> HqDown:
    down = HqDown()
    monkeypatch.setattr(settings, "jwt_secret", SecretStr(SECRET))
    monkeypatch.setattr(settings, "hq_url", "https://hq.unreachable.test/api/v1")
    monkeypatch.setattr(hq_client, "send_batch", down.send_batch)
    monkeypatch.setattr(hq_client, "transport", httpx.MockTransport(down.transport))
    return down


def test_sync17_1_sale_return_and_cancellation_are_processed_while_hq_is_down(client, db_session, hq_down):
    world = seed_sale(db_session)
    first, second = world.skus

    sale = sale_payload(world, [(first, 2, "10.00"), (second, 1, "10.00")])
    returned = return_payload(world, [(first, 1, "10.00")])
    cancellation = {"event_type": "CANCELLATION", "transaction_id": f"TEST-CAN-{uid(12)}",
                    "original_transaction_id": sale["transaction_id"], "store_id": world.store_id,
                    "pos_id": world.pos_id, "timestamp": "2026-11-14T03:20:00Z"}

    for event in (sale, returned, cancellation):
        response = post(client, event, world.token)
        assert response.status_code == 200, response.text
        assert response.json()["outcome"] == "OK"

    db_session.expire_all()
    assert db_session.get(PosTransaction, sale["transaction_id"]).status == "CANCELLED"
    # Opening 10 after the seeded sale; the new sale was cancelled; one unit returned.
    assert (stock(db_session, world, first), stock(db_session, world, second)) == (11, 10)
    assert hq_down.calls == 0


def test_sync17_2_staff_stock_query_and_barcode_lookup_answer_while_hq_is_down(client, db_session, hq_down):
    world = seed_sale(db_session)
    username = f"TEST-STAFF-{uid(8)}"
    db_session.add(StaffUser(username=username, full_name="Offline staff", role="STORE_STAFF",
                             store_id=world.store_id))
    db_session.flush()
    db_session.commit()
    headers = {"Authorization": f"Bearer {create_token(username, 'Staff', store_id=world.store_id)}"}

    inventory = client.get(f"/api/v1/stores/{world.store_id}/inventory", headers=headers)
    lookup = client.get(f"/api/v1/products/barcode/BC-{world.skus[0]}", headers=headers)

    assert inventory.status_code == 200, inventory.text
    assert {item["sku"]: item["quantity"] for item in inventory.json()["items"]} == {
        sku: 10 for sku in world.skus}
    assert lookup.status_code == 200, lookup.text
    assert lookup.json()["sku"] == world.skus[0]
    assert hq_down.calls == 0


# Batches during an outage and after it


@pytest.fixture
def hq(monkeypatch, test_engine: Engine) -> FakeHq:
    fake = FakeHq(test_engine)
    monkeypatch.setattr(settings, "hq_url", "https://hq.test/api/v1")
    monkeypatch.setattr(settings, "hq_jwt_secret", SecretStr(HQ_SECRET))
    monkeypatch.setattr(settings, "hq_ca_file", None)
    monkeypatch.setattr(settings, "sync_retry_base_seconds", 60)
    monkeypatch.setattr(hq_client, "transport", httpx.MockTransport(fake))
    monkeypatch.setattr(sync_send, "session_factory", lambda: Session(test_engine))
    monkeypatch.setattr(sync_send, "clock", Clock(NOW))
    return fake


@pytest.fixture
def world(test_engine: Engine) -> Generator[World, None, None]:
    created = World(test_engine)
    try:
        yield created
    finally:
        created.cleanup()


def three_batches(world: World) -> list[str]:
    """Three PENDING batches of two stores, oldest first."""
    store, other = world.store(), world.store()
    return [world.batch(store, timedelta(hours=3)), world.batch(other, timedelta(hours=2)),
            world.batch(store, timedelta(hours=1))]


def run_at(moment) -> sync_send.SendResult:
    sync_send.clock.now = moment
    return run_send_cycle()


def test_sync17_3_batches_stay_pending_with_attempts_and_last_error_across_cycles(world, hq):
    batches = three_batches(world)
    for batch_id in batches:
        hq.answer_next(batch_id, *["OFFLINE"] * 5)

    run_at(NOW)
    run_at(NOW + timedelta(seconds=30))  # the retry is not due: nothing is sent
    run_at(NOW + timedelta(seconds=60))
    run_at(NOW + timedelta(seconds=180))

    rows = [world.row(batch_id) for batch_id in batches]
    assert [row.status for row in rows] == ["PENDING"] * 3
    oldest = rows[0]
    assert oldest.attempts == 3
    assert oldest.last_error.startswith("503 HQ_OFFLINE")
    assert oldest.next_retry_at == NOW + timedelta(seconds=180 + 240)
    # Decided 12 Nov 2026: newer batches wait behind the oldest, untouched.
    assert [(row.attempts, row.last_error) for row in rows[1:]] == [(0, None), (0, None)]
    assert hq.ids(set(batches)) == [batches[0]] * 3


def test_sync17_4_when_hq_returns_the_next_due_retry_sends_all_oldest_first(world, hq):
    batches = three_batches(world)
    hq.answer_next(batches[0], "OFFLINE", "OFFLINE")
    run_at(NOW)
    run_at(NOW + timedelta(seconds=60))
    retry_at = world.row(batches[0]).next_retry_at
    assert retry_at == NOW + timedelta(seconds=60 + 120)

    # HQ is back (no more planned failures), but the retry is not due yet.
    assert run_at(retry_at - timedelta(seconds=1)).acked == []
    result = run_at(retry_at)

    assert [batch_id for batch_id in result.acked if batch_id in batches] == batches
    assert hq.ids(set(batches)) == [batches[0], batches[0], *batches]
    assert [world.row(batch_id).status for batch_id in batches] == ["ACKED"] * 3
    assert [[audit.action for audit in world.audits(batch_id)] for batch_id in batches] == [["SYNC_ACKED"]] * 3


def test_sync17_6_a_failed_batch_does_not_block_later_ones(world, hq):
    store = world.store()
    failed_before = world.batch(store, timedelta(hours=4), status="FAILED")
    batches = three_batches(world)
    hq.answer_next(batches[0], "HTTP_422")

    result = run_at(NOW)

    assert hq.ids({failed_before, *batches}) == batches
    assert [world.row(batch_id).status for batch_id in batches] == ["FAILED", "ACKED", "ACKED"]
    assert world.row(failed_before).status == "FAILED"
    assert batches[0] in result.rejected and result.failed is None
