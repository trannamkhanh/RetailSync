"""Shared job scheduler (PB-15-1).

Timing tests drive ``Scheduler.tick`` with a fake clock and a lock that is
always held, so no thread and no database are needed. The application lock
tests use real SQL Server sessions in RTS_DB_TEST.
"""

from datetime import datetime, time, timedelta, timezone
import logging
import threading
import time as wall

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import Engine, text

from app.core.config import Settings, settings
from app.core.db import database_url
from app.jobs import scheduler
from app.jobs.scheduler import Job, JobLock, Scheduler, register_job
from app.main import app


class FakeClock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


class HeldLock:
    """Stands in for the application lock: always granted."""

    def __init__(self) -> None:
        self.released = False

    def acquire(self) -> bool:
        return True

    def holds(self) -> bool:
        return True

    def release(self) -> None:
        self.released = True


class Counter:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self) -> None:
        self.calls += 1


START = datetime(2026, 11, 14, 18, 30, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def empty_registry(monkeypatch):
    monkeypatch.setattr(scheduler, "_jobs", {})


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(START)


def make(jobs: list[Job], clock: FakeClock, lock=None, **options) -> Scheduler:
    return Scheduler(jobs, lock=lock or HeldLock(), clock=clock, **options)


def lock_for_tests() -> JobLock:
    return JobLock(database_url(settings.test_db_name))


# Timing


def test_pb15_1_interval_job_runs_once_each_interval(clock):
    count = Counter()
    sched = make([Job("every-minute", count, every_seconds=60)], clock)

    assert sched.tick() == []
    clock.advance(59)
    assert sched.tick() == []
    clock.advance(1)
    assert sched.tick() == ["every-minute"]
    assert sched.tick() == []
    clock.advance(60)
    assert sched.tick() == ["every-minute"]
    assert count.calls == 2


def test_pb15_1_missed_intervals_run_once_not_in_a_burst(clock):
    count = Counter()
    sched = make([Job("every-minute", count, every_seconds=60)], clock)

    clock.advance(300)
    assert sched.tick() == ["every-minute"]
    assert sched.tick() == []
    assert sched.next_run("every-minute") == clock.now + timedelta(seconds=60)
    assert count.calls == 1


def test_pb15_1_daily_job_runs_at_business_local_time(clock, monkeypatch):
    monkeypatch.setattr(settings, "business_utc_offset_hours", 7)
    count = Counter()
    # 18:30 UTC on 14 Nov is 01:30 on 15 Nov in UTC+7, so 02:00 local is 19:00 UTC.
    sched = make([Job("nightly", count, daily_at=time(2, 0))], clock)

    assert sched.next_run("nightly") == datetime(2026, 11, 14, 19, 0, tzinfo=timezone.utc)
    clock.advance(29 * 60)
    assert sched.tick() == []
    clock.advance(60)
    assert sched.tick() == ["nightly"]
    assert sched.next_run("nightly") == datetime(2026, 11, 15, 19, 0, tzinfo=timezone.utc)


def test_pb15_1_daily_time_already_passed_today_runs_tomorrow(clock, monkeypatch):
    monkeypatch.setattr(settings, "business_utc_offset_hours", 7)
    # 01:30 local is after 01:00 local, so the next run is 01:00 local on 16 Nov.
    sched = make([Job("nightly", Counter(), daily_at=time(1, 0))], clock)

    assert sched.next_run("nightly") == datetime(2026, 11, 15, 18, 0, tzinfo=timezone.utc)


def test_pb15_1_daily_time_follows_the_configured_offset(clock, monkeypatch):
    monkeypatch.setattr(settings, "business_utc_offset_hours", 0)

    sched = make([Job("nightly", Counter(), daily_at=time(2, 0))], clock)

    assert sched.next_run("nightly") == datetime(2026, 11, 15, 2, 0, tzinfo=timezone.utc)


# Catch-up of daily jobs at start (PB-15-6). START is 01:30 local in UTC+7.


def test_pb15_6_start_before_the_daily_time_catches_up_nothing(clock, monkeypatch):
    monkeypatch.setattr(settings, "business_utc_offset_hours", 7)
    count = Counter()
    sched = make([Job("nightly", count, daily_at=time(2, 0))], clock)

    assert sched.catch_up_pending() == []
    assert sched.tick() == []
    clock.advance(60)
    assert sched.tick() == []
    assert count.calls == 0


def test_pb15_6_start_after_the_daily_time_runs_the_job_once(clock, monkeypatch):
    monkeypatch.setattr(settings, "business_utc_offset_hours", 7)
    count = Counter()
    sched = make([Job("nightly", count, daily_at=time(1, 0))], clock)

    assert sched.catch_up_pending() == ["nightly"]
    assert sched.tick() == ["nightly"]
    clock.advance(60)
    assert sched.tick() == []
    assert count.calls == 1
    assert sched.catch_up_pending() == []
    # The next run stays at 01:00 local tomorrow (18:00 UTC on 15 Nov).
    assert sched.next_run("nightly") == datetime(2026, 11, 15, 18, 0, tzinfo=timezone.utc)


def test_pb15_6_two_daily_jobs_catch_up_in_registry_order(clock, monkeypatch):
    monkeypatch.setattr(settings, "business_utc_offset_hours", 7)
    order: list[str] = []
    register_job("near-expiry", lambda: order.append("near-expiry"), daily_at=time(0, 30))
    register_job("hourly", lambda: order.append("hourly"), every_seconds=3600)
    register_job("forecast", lambda: order.append("forecast"), daily_at=time(1, 0))
    register_job("late", lambda: order.append("late"), daily_at=time(2, 0))
    sched = make(scheduler.registered_jobs(), clock)

    assert sched.tick() == ["near-expiry", "forecast"]
    assert order == ["near-expiry", "forecast"]


def test_pb15_6_catch_up_runs_before_jobs_due_at_the_same_tick(clock, monkeypatch):
    monkeypatch.setattr(settings, "business_utc_offset_hours", 7)
    order: list[str] = []
    sched = make([Job("every-minute", lambda: order.append("every-minute"), every_seconds=60),
                  Job("nightly", lambda: order.append("nightly"), daily_at=time(1, 0))], clock)

    clock.advance(60)
    assert sched.tick() == ["nightly", "every-minute"]
    assert order == ["nightly", "every-minute"]


def test_pb15_6_catch_up_waits_for_the_application_lock(clock, monkeypatch):
    monkeypatch.setattr(settings, "business_utc_offset_hours", 7)

    class LockHeldElsewhere(HeldLock):
        free = False

        def acquire(self) -> bool:
            return self.free

        def holds(self) -> bool:
            return self.free

    lock = LockHeldElsewhere()
    count = Counter()
    sched = make([Job("nightly", count, daily_at=time(1, 0))], clock, lock=lock, lock_retry_seconds=0)

    assert sched.tick() == []
    lock.free = True
    assert sched.tick() == ["nightly"]
    assert sched.tick() == []
    assert count.calls == 1


def test_pb15_6_a_failing_catch_up_job_is_logged_and_not_retried(clock, monkeypatch, caplog):
    monkeypatch.setattr(settings, "business_utc_offset_hours", 7)
    attempts = Counter()

    def broken() -> None:
        attempts()
        raise RuntimeError("job failed")

    sched = make([Job("nightly", broken, daily_at=time(1, 0))], clock)

    with caplog.at_level(logging.ERROR, logger=scheduler.__name__):
        assert sched.tick() == ["nightly"]
    clock.advance(60)
    assert sched.tick() == []
    assert attempts.calls == 1
    assert any("nightly" in record.getMessage() for record in caplog.records)


# Failures and overlap


def test_pb15_1_failing_job_is_logged_and_runs_again(clock, caplog):
    attempts = Counter()
    healthy = Counter()

    def broken() -> None:
        attempts()
        raise RuntimeError("job failed")

    sched = make([Job("broken", broken, every_seconds=60), Job("healthy", healthy, every_seconds=60)], clock)
    clock.advance(60)

    with caplog.at_level(logging.ERROR, logger=scheduler.__name__):
        assert sched.tick() == ["broken", "healthy"]
    clock.advance(60)
    sched.tick()

    assert (attempts.calls, healthy.calls) == (2, 2)
    assert any("broken" in record.getMessage() and record.exc_info for record in caplog.records)


def test_pb15_1_runs_of_the_same_job_never_overlap(clock):
    started, finish = threading.Event(), threading.Event()
    slow_runs, quick = Counter(), Counter()

    def slow() -> None:
        slow_runs()
        started.set()
        finish.wait(timeout=10)

    sched = make([Job("slow", slow, every_seconds=60), Job("quick", quick, every_seconds=60)], clock)
    clock.advance(60)
    first = threading.Thread(target=sched.tick)
    first.start()
    assert started.wait(timeout=5)

    clock.advance(60)
    second = sched.tick()
    finish.set()
    first.join(timeout=10)

    assert "slow" not in second
    assert slow_runs.calls == 1
    assert quick.calls >= 1


def test_pb15_1_a_job_that_is_still_running_is_not_started_by_run_job(clock):
    started, finish = threading.Event(), threading.Event()

    def slow() -> None:
        started.set()
        finish.wait(timeout=10)

    sched = make([Job("slow", slow, every_seconds=60)], clock)
    runner = threading.Thread(target=sched.run_job, args=("slow",))
    runner.start()
    assert started.wait(timeout=5)

    assert sched.run_job("slow") is False
    finish.set()
    runner.join(timeout=10)
    assert sched.run_job("slow") is True


# The application lock


def test_pb15_1_second_scheduler_cannot_get_the_lock_and_runs_nothing(clock):
    first_count, second_count = Counter(), Counter()
    first = make([Job("job", first_count, every_seconds=60)], clock, lock=lock_for_tests())
    second = make([Job("job", second_count, every_seconds=60)], clock, lock=lock_for_tests(),
                  lock_retry_seconds=0)
    try:
        clock.advance(60)
        assert first.tick() == ["job"]
        assert second.tick() == []

        first.stop()
        assert second.tick() == ["job"]
    finally:
        first.stop()
        second.stop()

    assert (first_count.calls, second_count.calls) == (1, 1)


def test_pb15_1_lock_is_taken_at_the_first_tick_before_any_job_is_due(clock):
    lock = lock_for_tests()
    sched = make([Job("hourly", Counter(), every_seconds=3600)], clock, lock=lock)
    try:
        assert sched.tick() == []
        assert lock.holds() is True
    finally:
        sched.stop()


def test_pb15_1_lock_is_released_on_stop(clock):
    sched = make([Job("job", Counter(), every_seconds=60)], clock, lock=lock_for_tests())
    sched.tick()
    sched.stop()

    other = lock_for_tests()
    try:
        assert other.acquire() is True
    finally:
        other.release()


def test_pb15_1_lost_lock_stops_the_jobs_until_it_is_held_again(clock, test_engine: Engine):
    count = Counter()
    holder = lock_for_tests()
    sched = make([Job("job", count, every_seconds=60)], clock, lock=holder, lock_retry_seconds=0)
    other = lock_for_tests()
    try:
        clock.advance(60)
        assert sched.tick() == ["job"]
        # As if the database dropped the holder's session.
        with test_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as admin:
            admin.execute(text(f"KILL {int(holder.session_id())}"))
        assert other.acquire() is True

        clock.advance(60)
        assert sched.tick() == []
        assert count.calls == 1
    finally:
        other.release()
        sched.stop()


def test_pb15_1_lock_is_held_by_one_session_at_a_time():
    first, second = lock_for_tests(), lock_for_tests()
    try:
        assert first.acquire() is True
        assert first.holds() is True
        assert second.acquire() is False
        assert second.holds() is False
    finally:
        first.release()
        second.release()


# The background thread and the app


def test_pb15_1_thread_runs_jobs_and_stops():
    count = Counter()
    lock = HeldLock()
    sched = Scheduler([Job("fast", count, every_seconds=1)], lock=lock, tick_seconds=0.05)

    sched.start()
    deadline = wall.monotonic() + 5
    while count.calls == 0 and wall.monotonic() < deadline:
        wall.sleep(0.05)
    sched.stop()

    assert count.calls >= 1
    assert not sched.is_running()
    assert lock.released


def test_pb15_1_stop_keeps_the_lock_while_a_job_is_still_running(caplog):
    started, finish = threading.Event(), threading.Event()

    def slow() -> None:
        started.set()
        finish.wait(timeout=10)

    lock = lock_for_tests()
    other = lock_for_tests()
    sched = Scheduler([Job("slow", slow, every_seconds=1)], lock=lock, tick_seconds=0.05)
    try:
        sched.start()
        assert started.wait(timeout=5)

        with caplog.at_level(logging.WARNING, logger=scheduler.__name__):
            sched.stop(timeout=0.2)

        assert sched.is_running()
        assert any("still running" in record.getMessage() for record in caplog.records)
        assert other.acquire() is False

        finish.set()
        deadline = wall.monotonic() + 5
        while sched.is_running() and wall.monotonic() < deadline:
            wall.sleep(0.05)
        assert not sched.is_running()
        assert other.acquire() is True
    finally:
        finish.set()
        sched.stop()
        other.release()


class FakeScheduler:
    def __init__(self) -> None:
        self.stopped = False

    def stop(self) -> None:
        self.stopped = True


def test_pb15_1_app_starts_and_stops_the_scheduler_when_enabled(monkeypatch):
    started: list[FakeScheduler] = []

    def fake_start() -> FakeScheduler:
        started.append(FakeScheduler())
        return started[-1]

    monkeypatch.setattr(scheduler, "start_scheduler", fake_start)
    monkeypatch.setattr(settings, "scheduler_enabled", True)

    with TestClient(app) as client:
        assert client.get("/api/v1/health").status_code == 200
        assert len(started) == 1 and not started[0].stopped

    assert started[0].stopped


def test_pb15_1_app_does_not_start_the_scheduler_when_disabled(monkeypatch):
    monkeypatch.setattr(scheduler, "start_scheduler", lambda: pytest.fail("scheduler started"))
    monkeypatch.setattr(settings, "scheduler_enabled", False)

    with TestClient(app) as client:
        assert client.get("/api/v1/health").status_code == 200


# Registering jobs and settings


def test_pb15_1_register_job_adds_one_job():
    count = Counter()

    register_job("sync-send", count, every_seconds=3600)

    jobs = scheduler.registered_jobs()
    assert [(job.name, job.every_seconds, job.daily_at) for job in jobs] == [("sync-send", 3600, None)]


@pytest.mark.parametrize(("name", "options"), [
    ("job", {}),
    ("job", {"every_seconds": 60, "daily_at": time(2, 0)}),
    ("job", {"every_seconds": 0}),
    ("job", {"every_seconds": -5}),
    ("job", {"every_seconds": 1.5}),
    ("job", {"every_seconds": True}),
    ("job", {"daily_at": time(2, 0, tzinfo=timezone.utc)}),
    ("job", {"daily_at": "02:00"}),
    ("", {"every_seconds": 60}),
    ("   ", {"every_seconds": 60}),
], ids=["no-schedule", "both", "zero", "negative", "float", "bool", "aware-time", "text-time",
        "empty-name", "blank-name"])
def test_pb15_1_register_job_rejects_a_bad_schedule(name, options):
    with pytest.raises(ValueError):
        register_job(name, Counter(), **options)


def test_pb15_1_register_job_rejects_a_duplicate_name():
    register_job("nightly", Counter(), daily_at=time(2, 0))

    with pytest.raises(ValueError, match="nightly"):
        register_job("nightly", Counter(), every_seconds=60)


def test_pb15_1_register_job_needs_a_callable():
    with pytest.raises(ValueError):
        register_job("job", "not callable", every_seconds=60)


def test_pb15_1_settings_defaults(monkeypatch):
    # _env_file=None skips .env files only; compose sets these for the middleware service.
    monkeypatch.delenv("SCHEDULER_ENABLED", raising=False)
    monkeypatch.delenv("BUSINESS_UTC_OFFSET_HOURS", raising=False)

    defaults = Settings(_env_file=None)

    assert defaults.scheduler_enabled is False
    assert defaults.business_utc_offset_hours == 7


@pytest.mark.parametrize("offset", [-13, 15])
def test_pb15_1_business_offset_is_bounded(offset):
    with pytest.raises(ValidationError, match="business_utc_offset_hours"):
        Settings(_env_file=None, business_utc_offset_hours=offset)
