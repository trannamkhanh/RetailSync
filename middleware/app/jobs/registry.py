"""Jobs run by the shared scheduler (PB-15-1). Register each job with one line:

    register_job("sync-send", run_send_cycle, every_seconds=settings.sync_interval)
    register_job("near-expiry", run_near_expiry_check, daily_at=time(2, 0))

``every_seconds`` is an interval; ``daily_at`` is business local time. Each
job opens its own sessions with ``SessionLocal()`` and commits them itself.
Jobs due at the same tick run in the order below, so register aggregation
(PB-14) before ``sync-send``: a new batch is then sent in the same tick.

Daily jobs (PB-15-6): when the scheduler starts, each ``daily_at`` job whose
time has already passed today runs once, in the order below (catch-up), and
``POST /admin/jobs/{name}/run`` runs one on demand. No run history is kept, so
every daily job must be safe to run twice on one business date: a second run
creates no duplicate rows and changes nothing the first run settled.
"""

from datetime import time

from app.core.config import settings
from app.jobs.aggregation import run_aggregation
from app.jobs.near_expiry import run_near_expiry_check
from app.jobs.scheduler import register_job
from app.jobs.sync_send import run_send_cycle


register_job("aggregation", run_aggregation, every_seconds=settings.sync_interval)
register_job("near-expiry", run_near_expiry_check, daily_at=time(0, 30))
register_job("sync-send", run_send_cycle, every_seconds=settings.sync_interval)
