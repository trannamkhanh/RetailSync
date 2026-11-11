"""Warm start of the HQ demo service (PB-18).

The first request after ``hq-demo`` starts must not pay for the first database
connection, because the Middleware's send timeout is 3 seconds. These tests run
against RTS_HQ_TEST.
"""

import time

from fastapi.testclient import TestClient

from app import modes
from app.main import _warm_up, app


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
