"""Warm start of the HQ demo service (PB-18).

The first request after ``hq-demo`` starts must not pay for the first database
connection, because the Middleware's send timeout is 3 seconds. These tests run
against RTS_HQ_TEST.
"""

import time

from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app import modes
from app.db import get_engine
from app.main import _warm_up, app
from app.models import HqSalesTotal, HqSyncBatch


def test_health_answers_quickly_right_after_start(client):
    started = time.monotonic()

    response = client.get("/api/v1/health")

    elapsed = time.monotonic() - started
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert elapsed < 1.0, f"/health took {elapsed:.2f}s right after start"


def test_startup_opens_the_database_connection(monkeypatch):
    calls = []
    monkeypatch.setattr("app.main.get_engine", lambda: _Recorder(calls))

    _warm_up()

    assert calls == ["SELECT 1"]


class _Connection:
    def __init__(self, calls: list[str]) -> None:
        self._calls = calls

    def __enter__(self) -> "_Connection":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def execute(self, statement) -> None:
        self._calls.append(str(statement))


class _Recorder:
    def __init__(self, calls: list[str]) -> None:
        self._calls = calls

    def connect(self) -> _Connection:
        return _Connection(self._calls)


def test_an_unreachable_database_does_not_stop_startup(monkeypatch, caplog):
    def fail():
        raise RuntimeError("database is down")

    monkeypatch.setattr("app.main.get_engine", fail)

    _warm_up()

    assert "could not reach the database" in caplog.text


def test_the_app_starts_with_the_warm_start(monkeypatch):
    """A TestClient runs the lifespan, so this fails if the warm start raises."""
    modes.reset()
    with TestClient(app) as started:
        assert started.get("/api/v1/health").status_code == 200
    modes.reset()


def test_first_sync_after_a_cold_start_does_not_pay_for_the_connection(auth, test_engine):
    """Drop the pooled engine, let the lifespan warm it up, then time /sync.

    /health never touches the database, so this is the check that the warm
    start really removed the cold-connection cost from the first send.
    """
    get_engine().dispose()
    get_engine.cache_clear()
    store = "TEST-WARM"
    batch = {
        "batch_id": f"SB-{store}-{int(time.time() * 1000)}",
        "store_id": store,
        "created_at": "2026-11-13T09:00:00Z",
        "txn_count": 1,
        "lines": [{"sku": "TEST-SKU", "sold_qty": 1, "returned_qty": 0,
                   "net_revenue": 10.0}],
    }
    try:
        with TestClient(app) as client:
            started = time.monotonic()
            response = client.post("/api/v1/sync", json=batch, headers=auth)
            elapsed = time.monotonic() - started

        assert response.status_code == 200, response.text
        assert response.json()["duplicate"] is False
        assert elapsed < 2.0, f"first /sync took {elapsed:.2f}s after a cold start"
    finally:
        with Session(bind=test_engine) as session:
            session.execute(delete(HqSalesTotal).where(HqSalesTotal.store_id == store))
            session.execute(delete(HqSyncBatch).where(HqSyncBatch.store_id == store))
            session.commit()
