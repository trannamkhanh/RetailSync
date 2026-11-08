"""SYNC18-1 to SYNC18-7 and the auth/concurrency cases of PB-18.

These run against RTS_HQ_TEST, never RTS_HQ. Every test creates its own store
and batch id with a TEST- prefix.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from threading import Thread
import time
from uuid import uuid4

import jwt
import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.hashing import batch_hash
from app.models import HqSalesTotal, HqSyncBatch
from app.schemas import SyncBatchMessage
from app.service import apply_batch


def _store() -> str:
    # store_id is varchar(10): TEST- plus five hex characters.
    return "TEST-" + uuid4().hex[:5].upper()


def _batch(store_id: str, **overrides) -> dict:
    message = {
        "batch_id": f"SB-{store_id}-20261113090000",
        "store_id": store_id,
        "created_at": "2026-11-13T09:00:00Z",
        "txn_count": 2,
        "lines": [
            {"sku": "TEST-A", "sold_qty": 3, "returned_qty": 1, "net_revenue": 100.50},
            {"sku": "TEST-B", "sold_qty": 1, "returned_qty": 0, "net_revenue": 20.00},
        ],
    }
    message.update(overrides)
    return message


def _post(client, auth, message):
    return client.post("/api/v1/sync", json=message, headers=auth)


def _totals(session: Session, store_id: str) -> dict[str, HqSalesTotal]:
    session.expire_all()
    rows = session.scalars(
        select(HqSalesTotal).where(HqSalesTotal.store_id == store_id)
    ).all()
    return {row.sku: row for row in rows}


def test_sync18_1_health_is_public(client):
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_sync18_2_new_batch_is_acked_and_totals_are_added(client, auth, db_session):
    store = _store()
    message = _batch(store)

    response = _post(client, auth, message)

    assert response.status_code == 200, response.text
    assert response.json() == {"status": "ACK", "batch_id": message["batch_id"],
                               "duplicate": False}
    db_session.expire_all()
    batch = db_session.get(HqSyncBatch, message["batch_id"])
    assert batch is not None
    assert batch.txn_count == 2
    assert len(batch.payload_hash) == 64
    totals = _totals(db_session, store)
    assert totals["TEST-A"].sold_qty == 3
    assert totals["TEST-A"].returned_qty == 1
    assert totals["TEST-A"].net_revenue == Decimal("100.50")
    assert totals["TEST-B"].sold_qty == 1


def test_sync18_3_same_batch_is_a_duplicate(client, auth, db_session):
    store = _store()
    message = _batch(store)
    assert _post(client, auth, message).status_code == 200
    before = _totals(db_session, store)

    response = _post(client, auth, message)

    assert response.status_code == 200, response.text
    assert response.json()["duplicate"] is True
    db_session.expire_all()
    batch = db_session.get(HqSyncBatch, message["batch_id"])
    assert batch.duplicate_count == 1
    after = _totals(db_session, store)
    assert after["TEST-A"].sold_qty == before["TEST-A"].sold_qty
    assert after["TEST-A"].net_revenue == before["TEST-A"].net_revenue


def test_sync18_4_same_id_with_other_content_is_a_conflict(client, auth, db_session):
    store = _store()
    message = _batch(store)
    assert _post(client, auth, message).status_code == 200
    before = _totals(db_session, store)

    changed = _batch(store, lines=[
        {"sku": "TEST-A", "sold_qty": 99, "returned_qty": 0, "net_revenue": 1.00},
    ])
    response = _post(client, auth, changed)

    assert response.status_code == 409
    body = response.json()
    assert (body["status"], body["code"]) == ("NACK", "CONFLICT")
    after = _totals(db_session, store)
    assert after["TEST-A"].sold_qty == before["TEST-A"].sold_qty
    assert after["TEST-A"].net_revenue == before["TEST-A"].net_revenue
    assert db_session.get(HqSyncBatch, message["batch_id"]).duplicate_count == 0


@pytest.mark.parametrize("overrides", [
    {"lines": []},
    {"txn_count": 0},
    {"lines": [{"sku": "TEST-A", "sold_qty": -1, "returned_qty": 0,
                "net_revenue": 10.0}]},
    {"lines": [{"sku": "TEST-A", "sold_qty": 1, "returned_qty": 0,
                "net_revenue": 10.0},
               {"sku": "TEST-A", "sold_qty": 2, "returned_qty": 0,
                "net_revenue": 20.0}]},
    {"batch_id": "X" * 41},
    {"batch_id": "bad id"},
], ids=["no-lines", "txn-count-zero", "negative-quantity", "repeated-sku",
        "batch-id-too-long", "batch-id-pattern"])
def test_sync18_5_invalid_batch_is_nacked(client, auth, db_session, overrides):
    store = _store()
    message = _batch(store, **overrides)

    response = _post(client, auth, message)

    assert response.status_code == 422, response.text
    body = response.json()
    assert (body["status"], body["code"]) == ("NACK", "INVALID_BATCH")
    assert db_session.get(HqSyncBatch, message["batch_id"]) is None


def test_sync18_6_demo_batches_lists_the_received_batch(client, auth):
    store = _store()
    message = _batch(store)
    assert _post(client, auth, message).status_code == 200

    response = client.get("/api/v1/demo/batches")

    assert response.status_code == 200
    body = response.json()
    batch = next(item for item in body["batches"]
                 if item["batch_id"] == message["batch_id"])
    assert batch["store_id"] == store
    assert batch["txn_count"] == 2
    assert batch["duplicate_count"] == 0
    line = next(item for item in body["totals"]
                if item["store_id"] == store and item["sku"] == "TEST-A")
    assert line["sold_qty"] == 3
    assert line["returned_qty"] == 1
    assert line["net_revenue"] == 100.5


def test_sync18_7_demo_modes(client, auth, db_session):
    # OFFLINE: 503, nothing stored.
    store_off = _store()
    offline = _batch(store_off)
    assert client.put("/api/v1/demo/mode", json={"mode": "OFFLINE"}).status_code == 200
    response = _post(client, auth, offline)
    assert (response.status_code, response.json()["code"]) == (503, "HQ_OFFLINE")
    assert db_session.get(HqSyncBatch, offline["batch_id"]) is None

    # ERROR: 500, nothing stored.
    store_error = _store()
    error = _batch(store_error)
    assert client.put("/api/v1/demo/mode", json={"mode": "ERROR"}).status_code == 200
    response = _post(client, auth, error)
    assert (response.status_code, response.json()["code"]) == (500, "HQ_ERROR")
    assert db_session.get(HqSyncBatch, error["batch_id"]) is None

    # SLOW: answers after 4 seconds and handles the batch normally.
    store_slow = _store()
    slow = _batch(store_slow)
    assert client.put("/api/v1/demo/mode", json={"mode": "SLOW"}).status_code == 200
    started = time.monotonic()
    response = _post(client, auth, slow)
    elapsed = time.monotonic() - started
    assert response.status_code == 200, response.text
    assert elapsed >= 4
    assert db_session.get(HqSyncBatch, slow["batch_id"]) is not None

    # DROP_ACK: stored, then 500.
    store_drop = _store()
    drop = _batch(store_drop)
    assert client.put("/api/v1/demo/mode", json={"mode": "DROP_ACK"}).status_code == 200
    response = _post(client, auth, drop)
    assert (response.status_code, response.json()["code"]) == (500, "ACK_DROPPED")
    db_session.expire_all()
    assert db_session.get(HqSyncBatch, drop["batch_id"]) is not None
    assert _totals(db_session, store_drop)["TEST-A"].sold_qty == 3


def test_pb18_sync_without_a_token_is_401(client):
    response = client.post("/api/v1/sync", json=_batch(_store()))

    assert response.status_code == 401
    body = response.json()
    assert (body["outcome"], body["code"]) == ("REJECTED", "UNAUTHORIZED")


def test_pb18_sync_with_another_role_is_401(client, hq_secret):
    token = jwt.encode(
        {"sub": "staff_dn1", "role": "Staff",
         "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
        hq_secret, algorithm="HS256",
    )

    response = client.post("/api/v1/sync", json=_batch(_store()),
                           headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401


def test_pb18_two_identical_batches_at_once_acknowledge_once(test_engine):
    store = _store()
    message = _batch(store, batch_id=f"SB-{store}-20261113090001")
    parsed = SyncBatchMessage.model_validate(message)
    payload_hash = batch_hash(parsed)
    results: list[bool] = []

    def worker() -> None:
        session = Session(bind=test_engine)
        try:
            results.append(apply_batch(session, parsed, payload_hash))
            session.commit()
        finally:
            session.close()

    try:
        threads = [Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)

        assert sorted(results) == [False, True]
        with Session(bind=test_engine) as session:
            batch = session.get(HqSyncBatch, message["batch_id"])
            assert batch is not None
            assert batch.duplicate_count == 1
            totals = session.scalars(
                select(HqSalesTotal).where(HqSalesTotal.store_id == store)
            ).all()
            assert {row.sku: row.sold_qty for row in totals} == {"TEST-A": 3, "TEST-B": 1}
    finally:
        with Session(bind=test_engine) as session:
            session.execute(delete(HqSalesTotal).where(HqSalesTotal.store_id == store))
            session.execute(delete(HqSyncBatch).where(HqSyncBatch.store_id == store))
            session.commit()
