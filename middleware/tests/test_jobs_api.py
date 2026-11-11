"""Run a daily job now: POST /api/v1/admin/jobs/{name}/run (PB-15-6).

Until PB-21 and PB-22 register ``near-expiry`` and ``forecast``, each test
registers test-only jobs in an empty registry. The jobs only record their
calls, so they touch no database. The request and its audit row use the
``db_session`` savepoint in RTS_DB_TEST and are rolled back after the test.
The scheduler stays off (conftest), so these runs also prove the endpoint
works without it.
"""

from datetime import time
import threading

import pytest
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import create_token
from app.domain.models import AuditLog, StaffUser
from app.jobs import scheduler
from app.jobs.scheduler import Scheduler, register_job


SECRET = "test-only-secret-with-enough-length-for-hs256"
URL = "/api/v1/admin/jobs/{name}/run"
ADMIN = "TEST-jobs-admin"
DAILY = "TEST-daily"
INTERVAL = "TEST-interval"


class Recorder:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self) -> None:
        self.calls += 1


class HeldLock:
    """Stands in for the scheduler's application lock: always granted."""

    def acquire(self) -> bool:
        return True

    def holds(self) -> bool:
        return True

    def release(self) -> None:
        pass


@pytest.fixture(autouse=True)
def jwt_secret(monkeypatch):
    monkeypatch.setattr(settings, "jwt_secret", SecretStr(SECRET))


@pytest.fixture(autouse=True)
def empty_registry(monkeypatch):
    monkeypatch.setattr(scheduler, "_jobs", {})


@pytest.fixture
def daily() -> Recorder:
    job = Recorder()
    register_job(DAILY, job, daily_at=time(0, 30))
    register_job(INTERVAL, Recorder(), every_seconds=3600)
    return job


@pytest.fixture
def admin(db_session: Session) -> StaffUser:
    user = StaffUser(username=ADMIN, full_name="Jobs admin", role="ADMIN")
    db_session.add(user)
    db_session.flush()
    # Commit the savepoint so a rejected request cannot roll the account away.
    db_session.commit()
    return user


@pytest.fixture
def headers(admin: StaffUser) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_token(ADMIN, 'Admin')}"}


def job(name: str) -> scheduler.Job:
    return next(job for job in scheduler.registered_jobs() if job.name == name)


def audit_rows(session: Session, name: str) -> list[AuditLog]:
    session.expire_all()
    return list(session.scalars(select(AuditLog).where(AuditLog.action == "JOB_RUN_REQUESTED",
                                                       AuditLog.entity_key == name)))


def assert_error(response, status: int, outcome: str, code: str) -> None:
    assert response.status_code == status, response.text
    body = response.json()
    assert set(body) == {"outcome", "code", "message"}
    assert (body["outcome"], body["code"]) == (outcome, code)


def test_pb15_6_run_job_runs_the_daily_job_and_answers_completed(client, db_session, daily, headers, admin):
    response = client.post(URL.format(name=DAILY), headers=headers)

    assert response.status_code == 200, response.text
    assert response.json() == {"job": DAILY, "status": "COMPLETED"}
    assert daily.calls == 1
    [row] = audit_rows(db_session, DAILY)
    assert (row.entity_name, row.entity_key, row.user_id) == ("job", DAILY, admin.user_id)
    assert job(DAILY).running.acquire(blocking=False)
    job(DAILY).running.release()


def test_pb15_6_run_job_can_run_twice(client, daily, headers):
    for _ in range(2):
        assert client.post(URL.format(name=DAILY), headers=headers).status_code == 200

    assert daily.calls == 2


@pytest.mark.parametrize("name", ["TEST-unknown", INTERVAL], ids=["unknown", "interval-job"])
def test_pb15_6_run_job_unknown_or_non_daily_name_is_404(client, db_session, daily, headers, name):
    response = client.post(URL.format(name=name), headers=headers)

    assert_error(response, 404, "REJECTED", "NOT_FOUND")
    assert audit_rows(db_session, name) == []
    assert daily.calls == 0


def test_pb15_6_run_job_bad_name_is_422(client, daily, headers):
    response = client.post(URL.format(name="bad.name"), headers=headers)

    assert_error(response, 422, "REJECTED", "VALIDATION_ERROR")


def test_pb15_6_run_job_while_a_run_holds_the_lock_is_409(client, db_session, daily, headers):
    lock = job(DAILY).running
    assert lock.acquire(blocking=False)
    try:
        response = client.post(URL.format(name=DAILY), headers=headers)
    finally:
        lock.release()

    assert_error(response, 409, "REJECTED", "JOB_RUNNING")
    assert daily.calls == 0
    assert audit_rows(db_session, DAILY) == []


def test_pb15_6_run_job_while_the_scheduler_runs_it_is_409(client, headers, admin):
    started, finish = threading.Event(), threading.Event()

    def slow() -> None:
        started.set()
        finish.wait(timeout=10)

    register_job(DAILY, slow, daily_at=time(0, 30))
    sched = Scheduler(scheduler.registered_jobs(), lock=HeldLock())
    runner = threading.Thread(target=sched.run_job, args=(DAILY,))
    runner.start()
    try:
        assert started.wait(timeout=5)
        response = client.post(URL.format(name=DAILY), headers=headers)
    finally:
        finish.set()
        runner.join(timeout=10)

    assert_error(response, 409, "REJECTED", "JOB_RUNNING")


def test_pb15_6_run_job_that_raises_is_503_and_stays_audited(client, db_session, headers):
    def broken() -> None:
        raise RuntimeError("job failed")

    register_job(DAILY, broken, daily_at=time(0, 30))

    response = client.post(URL.format(name=DAILY), headers=headers)

    assert_error(response, 503, "ERROR", "SERVICE_UNAVAILABLE")
    assert len(audit_rows(db_session, DAILY)) == 1
    assert job(DAILY).running.acquire(blocking=False)
    job(DAILY).running.release()
