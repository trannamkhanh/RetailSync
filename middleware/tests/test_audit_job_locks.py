"""Cross-process job exclusion, using independent local locks and SQL sessions."""

from concurrent.futures import ThreadPoolExecutor, TimeoutError
from datetime import time
from importlib.util import find_spec
from threading import Barrier, Event
from uuid import uuid4

import pytest

from app.api import jobs
from app.core.errors import ApiError
from app.core.security import Principal
from app.jobs.scheduler import Job


def setup_jobs(monkeypatch, test_engine, callback):
    if find_spec("app.jobs.locks") is not None:
        from app.jobs import locks
        monkeypatch.setattr(locks, "database_url", lambda: test_engine.url)
    # Each lookup represents a different worker process with its own local lock.
    monkeypatch.setattr(jobs, "_daily_job", lambda name: Job(name, callback, daily_at=time(1)))
    monkeypatch.setattr(jobs, "_audit_request", lambda *args: None)


def request(name):
    try:
        jobs.run_job(name, None, Principal("TEST-ADMIN", "Admin", None, None))
        return 200
    except ApiError as error:
        assert error.code == "JOB_RUNNING"
        return error.status


def test_audit14_same_job_in_independent_workers_returns_conflict(monkeypatch, test_engine):
    entered, release = Event(), Event()

    def run():
        entered.set()
        assert release.wait(10)

    setup_jobs(monkeypatch, test_engine, run)
    name = "audit-" + uuid4().hex
    with ThreadPoolExecutor(2) as workers:
        first = workers.submit(request, name)
        try:
            assert entered.wait(5)
            second = workers.submit(request, name)
            try:
                second_status = second.result(timeout=2)
            except TimeoutError:
                second_status = None
        finally:
            release.set()
        assert first.result(timeout=5) == 200
        actual_second = second.result(timeout=5)
    assert second_status == actual_second == 409


def test_audit14_different_jobs_run_in_parallel(monkeypatch, test_engine):
    barrier = Barrier(2)
    setup_jobs(monkeypatch, test_engine, lambda: barrier.wait(timeout=5))
    with ThreadPoolExecutor(2) as workers:
        futures = [workers.submit(request, "audit-" + uuid4().hex) for _ in range(2)]
        assert [future.result(timeout=10) for future in futures] == [200, 200]


def test_audit14_sql_lock_released_after_job_exception(monkeypatch, test_engine):
    from app.jobs import locks
    monkeypatch.setattr(locks, "database_url", lambda: test_engine.url)
    name = "audit-" + uuid4().hex
    with pytest.raises(ValueError, match="job failed"):
        with locks.job_lock(name) as acquired:
            assert acquired
            with locks.job_lock(name) as other:
                assert not other
            raise ValueError("job failed")
    with locks.job_lock(name) as acquired:
        assert acquired


@pytest.mark.parametrize("failure", ["connect", "options", "acquire", "release", "close"])
def test_audit14_connections_and_engine_cleaned_on_errors(monkeypatch, failure):
    from app.jobs import locks
    from unittest.mock import Mock
    engine, connection = Mock(), Mock()
    engine.connect.return_value = connection
    connection.execution_options.return_value = connection
    connection.exec_driver_sql.return_value.scalar.return_value = 0
    if failure == "connect":
        engine.connect.side_effect = RuntimeError("connect")
    elif failure == "options":
        connection.execution_options.side_effect = RuntimeError("options")
    elif failure in ("acquire", "release"):
        def execute(sql, params):
            if ("sp_getapplock" in sql) == (failure == "acquire"):
                raise RuntimeError(failure)
            result = Mock()
            result.scalar.return_value = 0
            return result
        connection.exec_driver_sql.side_effect = execute
    else:
        connection.close.side_effect = RuntimeError("close")
    monkeypatch.setattr(locks, "database_url", lambda: "unused")
    monkeypatch.setattr(locks, "create_engine", lambda *args, **kwargs: engine)
    if failure == "release":
        with locks.job_lock("test") as acquired:
            assert acquired
    else:
        with pytest.raises(RuntimeError, match=failure):
            with locks.job_lock("test"):
                pass
    if failure != "connect":
        connection.close.assert_called_once()
    engine.dispose.assert_called_once()
