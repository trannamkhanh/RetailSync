"""Jobs run by the shared scheduler (PB-15-1). Register each job with one line:

    register_job("sync-send", run_send_cycle, every_seconds=settings.sync_interval)
    register_job("near-expiry", run_near_expiry_check, daily_at=time(2, 0))

``every_seconds`` is an interval; ``daily_at`` is business local time. Each
job opens its own sessions with ``SessionLocal()`` and commits them itself.
"""

from app.jobs.scheduler import register_job


__all__ = ["register_job"]
