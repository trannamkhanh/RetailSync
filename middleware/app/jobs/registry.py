"""Jobs run by the shared scheduler (PB-15-1). Register each job with one line:

    register_job("sync-send", run_send_cycle, every_seconds=settings.sync_interval)
    register_job("near-expiry", run_near_expiry_check, daily_at=time(2, 0))

``every_seconds`` is an interval; ``daily_at`` is business local time. Each
job opens its own sessions with ``SessionLocal()`` and commits them itself.
Jobs due at the same tick run in the order below, so register aggregation
(PB-14) before ``sync-send``: a new batch is then sent in the same tick.
"""

from app.core.config import settings
from app.jobs.aggregation import run_aggregation
from app.jobs.scheduler import register_job
from app.jobs.sync_send import run_send_cycle


register_job("aggregation", run_aggregation, every_seconds=settings.sync_interval)
register_job("sync-send", run_send_cycle, every_seconds=settings.sync_interval)
