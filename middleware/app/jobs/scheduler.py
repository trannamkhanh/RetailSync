"""Shared job scheduler (PB-15-1).

One background thread runs the registered jobs, each at a fixed interval or
once a day at a business local time (UTC + ``BUSINESS_UTC_OFFSET_HOURS``).

- Only one process runs jobs: the scheduler takes the SQL Server application
  lock ``retailsync-jobs`` (exclusive, session owner) on a connection of its
  own and keeps it until it stops. A process that cannot get the lock runs
  nothing and tries again later, so it takes over if the holder goes away.
- A job that raises is logged and runs again at its next time.
- Two runs of the same job never overlap, in this process or across workers:
  a run takes ``Job.running`` and the per-job SQL lock of ``app/jobs/locks.py``,
  like ``POST /admin/jobs/{name}/run`` and ``POST /sync/run``. A job whose lock
  is held elsewhere is not run and stays due.
- Schedules are computed when the application lock is first taken, not when the
  scheduler is created, so a standby that takes over late plans from that moment.
- Catch-up (PB-15-6, decided 11 Nov 2026): every ``daily_at`` job whose time
  has already passed today when the scheduler first takes the application lock
  runs once, in registry order, before any other job. No run history is stored,
  so daily jobs must be safe to run twice on one business date.
- Between two jobs of one tick the scheduler checks again that it holds the
  application lock and has not been stopped.

A job takes no arguments, opens its own sessions with ``SessionLocal()`` and
commits them itself. Jobs are registered in ``app/jobs/registry.py``.
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, timezone
import importlib
import logging
import threading

from sqlalchemy import URL, Connection, create_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.core.db import database_url
from app.jobs.locks import job_lock


logger = logging.getLogger(__name__)

LOCK_NAME = "retailsync-jobs"


@dataclass
class Job:
    name: str
    run: Callable[[], object]
    every_seconds: int | None = None
    daily_at: time | None = None
    running: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    def next_after(self, now: datetime) -> datetime:
        """The first run time after ``now`` (UTC), when no run is pending."""
        if self.every_seconds is not None:
            return now + timedelta(seconds=self.every_seconds)
        offset = timedelta(hours=settings.business_utc_offset_hours)
        local_now = (now + offset).replace(tzinfo=None)
        local_run = datetime.combine(local_now.date(), self.daily_at)
        if local_run <= local_now:
            local_run += timedelta(days=1)
        return (local_run - offset).replace(tzinfo=timezone.utc)

    def passed_today(self, now: datetime) -> bool:
        """True for a daily job whose business local time today is not after ``now`` (UTC)."""
        if self.daily_at is None:
            return False
        local_now = (now + timedelta(hours=settings.business_utc_offset_hours)).replace(tzinfo=None)
        return datetime.combine(local_now.date(), self.daily_at) <= local_now


_jobs: dict[str, Job] = {}


def _check_schedule(name: str, run: object, every_seconds: object, daily_at: object) -> None:
    if not isinstance(name, str) or not name.strip():
        raise ValueError("A job needs a name.")
    if name in _jobs:
        raise ValueError(f"A job named '{name}' is already registered.")
    if not callable(run):
        raise ValueError(f"Job '{name}' needs a callable.")
    if (every_seconds is None) == (daily_at is None):
        raise ValueError(f"Job '{name}' needs exactly one of every_seconds and daily_at.")
    if every_seconds is not None and (type(every_seconds) is not int or every_seconds <= 0):
        raise ValueError(f"Job '{name}': every_seconds must be a positive integer.")
    if daily_at is not None and (not isinstance(daily_at, time) or daily_at.tzinfo is not None):
        raise ValueError(f"Job '{name}': daily_at must be a business local time without a time zone.")


def register_job(name: str, run: Callable[[], object], *,
                 every_seconds: int | None = None, daily_at: time | None = None) -> None:
    _check_schedule(name, run, every_seconds, daily_at)
    _jobs[name] = Job(name, run, every_seconds, daily_at)


def registered_jobs() -> list[Job]:
    return list(_jobs.values())


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class JobLock:
    """The application lock ``retailsync-jobs`` on a dedicated connection.

    The engine has no pool, so closing the connection ends the SQL Server
    session and frees the lock even when the release itself fails.
    """

    def __init__(self, url: URL | None = None) -> None:
        self._url = url
        self._connection: Connection | None = None

    def acquire(self) -> bool:
        self.release()
        engine = create_engine(self._url or database_url(), poolclass=NullPool,
                               connect_args={"timeout": 5}, hide_parameters=True)
        connection = engine.connect().execution_options(isolation_level="AUTOCOMMIT")
        try:
            result = connection.exec_driver_sql(
                "SET NOCOUNT ON; DECLARE @result int; "
                "EXEC @result = sp_getapplock @Resource = ?, @LockMode = 'Exclusive', "
                "@LockOwner = 'Session', @LockTimeout = 0; SELECT @result",
                (LOCK_NAME,),
            ).scalar()
        except Exception:
            connection.close()
            raise
        if result is not None and result >= 0:
            self._connection = connection
            return True
        connection.close()
        return False

    def holds(self) -> bool:
        if self._connection is None:
            return False
        try:
            mode = self._connection.exec_driver_sql(
                "SELECT APPLOCK_MODE('public', ?, 'Session')", (LOCK_NAME,)).scalar()
        except Exception:
            logger.warning("Lost the connection that held the job lock", exc_info=True)
            self.release()
            return False
        return mode == "Exclusive"

    def session_id(self) -> int | None:
        if self._connection is None:
            return None
        return self._connection.exec_driver_sql("SELECT @@SPID").scalar()

    def release(self) -> None:
        connection, self._connection = self._connection, None
        if connection is None:
            return
        try:
            connection.exec_driver_sql(
                "EXEC sp_releaseapplock @Resource = ?, @LockOwner = 'Session'", (LOCK_NAME,))
        except Exception:
            logger.debug("Releasing the job lock failed; closing its session instead", exc_info=True)
        finally:
            connection.close()


class Scheduler:
    def __init__(self, jobs: Iterable[Job] | None = None, *, lock: JobLock | None = None,
                 clock: Callable[[], datetime] = _utc_now, tick_seconds: float = 1.0,
                 lock_retry_seconds: float = 30.0,
                 on_lock_acquired: Callable[[], object] | None = None) -> None:
        self._jobs = {job.name: job for job in (registered_jobs() if jobs is None else jobs)}
        self._lock = lock or JobLock()
        self._on_lock_acquired = on_lock_acquired
        self._clock = clock
        self._tick_seconds = tick_seconds
        self._lock_retry_seconds = lock_retry_seconds
        self._has_lock = False
        self._next_lock_try: datetime | None = None
        # Planned when the application lock is first taken (audit #15), see _plan().
        self._planned = False
        self._next_run: dict[str, datetime] = {}
        self._catch_up: list[str] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def next_run(self, name: str) -> datetime:
        return self._next_run[name]

    def _try_lock(self, now: datetime) -> bool:
        """Take the lock if it is free; at most once per ``lock_retry_seconds``."""
        if self._next_lock_try is not None and now < self._next_lock_try:
            return False
        self._next_lock_try = now + timedelta(seconds=self._lock_retry_seconds)
        self._has_lock = self._lock.acquire()
        if self._has_lock:
            logger.info("Scheduler holds the job lock; running %d jobs", len(self._jobs))
            if not self._planned:
                self._plan(now)
            if self._on_lock_acquired is not None:
                try:
                    self._on_lock_acquired()
                except Exception:
                    logger.exception("Startup step after taking the job lock failed")
        else:
            logger.info("Another process holds the job lock; this process runs no jobs")
        return self._has_lock

    def _plan(self, now: datetime) -> None:
        """First run times and catch-up, from the moment this process first holds the lock."""
        self._next_run = {job.name: job.next_after(now) for job in self._jobs.values()}
        self._catch_up = [job.name for job in self._jobs.values() if job.passed_today(now)]
        self._planned = True

    def _may_go_on(self) -> bool:
        """Checked before each job of a tick: not stopped, and the lock is still held."""
        if self._stop.is_set():
            return False
        if self._lock.holds():
            return True
        logger.warning("The scheduler lost the job lock during a tick; the remaining jobs wait")
        self._has_lock = False
        self._next_lock_try = None
        return False

    def _still_holds_lock(self, now: datetime) -> bool:
        """Checked before jobs run, so a dropped session cannot leave two runners."""
        if self._has_lock and self._lock.holds():
            return True
        if self._has_lock:
            logger.warning("The scheduler no longer holds the job lock")
            self._has_lock = False
            self._next_lock_try = None
        return self._try_lock(now)

    def run_job(self, name: str) -> bool:
        """Run one job now. A failure of the job is logged.

        Returns False, without running it, while a run of it is in progress in
        this process or holds its per-job SQL lock elsewhere (a manual run or
        another worker), or when that lock cannot be taken; the caller then
        keeps the job due.
        """
        job = self._jobs[name]
        if not job.running.acquire(blocking=False):
            return False
        try:
            with job_lock(name) as acquired:
                if not acquired:
                    logger.info("Job %s is running elsewhere; it stays due", name)
                    return False
                try:
                    job.run()
                except Exception:
                    logger.exception("Job %s failed; it runs again at its next time", name)
        except Exception:
            logger.exception("Could not take the job lock of %s; it stays due", name)
            return False
        finally:
            job.running.release()
        return True

    def catch_up_pending(self) -> list[str]:
        """Daily jobs still to catch up, in registry order."""
        return list(self._catch_up)

    def _run_catch_up(self) -> list[str]:
        """Run each missed daily job once; its next run stays at its next daily time."""
        names, self._catch_up = self._catch_up, []
        ran = []
        for index, name in enumerate(names):
            if not self._may_go_on():
                self._catch_up = names[index:]  # kept for the next tick that holds the lock
                break
            if self.run_job(name):
                ran.append(name)
                self._next_run[name] = self._jobs[name].next_after(self._clock())
        return ran

    def tick(self) -> list[str]:
        """Run every job that is due. Returns the names of the jobs that ran."""
        now = self._clock()
        if not self._has_lock:
            self._try_lock(now)
        if not self._planned:
            return []
        any_due = any(at <= now for at in self._next_run.values())
        if not (any_due or self._catch_up) or not self._still_holds_lock(now):
            return []
        ran = self._run_catch_up()
        # After the catch-up, which has moved its jobs to their next daily time.
        due = [name for name, at in self._next_run.items() if at <= now]
        for name in due:
            if not self._may_go_on():
                break
            if self.run_job(name):
                ran.append(name)
                after = self._clock()
                planned = self._next_run[name]
                job = self._jobs[name]
                self._next_run[name] = (planned + timedelta(seconds=job.every_seconds)
                                        if job.every_seconds is not None else job.next_after(after))
                if self._next_run[name] <= after:
                    self._next_run[name] = job.next_after(after)
        return ran

    def _release_lock(self) -> None:
        self._has_lock = False
        self._lock.release()

    def _loop(self) -> None:
        try:
            while not self._stop.is_set():
                try:
                    self.tick()
                except Exception:
                    logger.exception("Scheduler tick failed")
                self._stop.wait(self._tick_seconds)
        finally:
            self._release_lock()

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="retailsync-scheduler", daemon=True)
        self._thread.start()

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def stop(self, timeout: float = 30.0) -> None:
        """Stop the thread. The lock is released only once no job is running.

        If a job is still running after ``timeout`` seconds, the thread keeps the
        lock and releases it when the job ends; if the process exits first, its
        connection closes and SQL Server frees the lock.
        """
        self._stop.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout)
            if self._thread.is_alive():
                logger.warning("A job is still running %s s after stop; the job lock is kept until it ends",
                               timeout)
                return
        self._release_lock()


def start_scheduler() -> Scheduler:
    """Start the scheduler with every job of ``app/jobs/registry.py``."""
    importlib.import_module("app.jobs.registry")  # registers the jobs
    from app.jobs.sync_send import release_stale_batches

    # DS-05 section 5: stale SENT batches return to PENDING as soon as this process runs jobs.
    running = Scheduler(on_lock_acquired=release_stale_batches)
    running.start()
    return running
