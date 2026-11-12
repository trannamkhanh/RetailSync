"""Manual sync: POST /api/v1/sync/run (SYNC15-5, DS-05 section 6). Admin only.

Runs aggregation and then one send cycle in the request, each under the
scheduler's per-job lock (``Job.running`` of ``registered_jobs()``), so a
scheduled run and a requested run never overlap. A job that is already running
is joined by nothing: its count is 0, and the answer gives what can be read.
"""

from collections.abc import Callable
from typing import TypeVar

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import Principal, require_role
from app.jobs import registry  # noqa: F401  registers the jobs, also when the scheduler is off
from app.jobs.scheduler import registered_jobs
from app.jobs.sync_send import SendResult
from app.repositories import sync_batches


router = APIRouter(prefix="/sync", tags=["Sync"])

AGGREGATION = "aggregation"
SYNC_SEND = "sync-send"

T = TypeVar("T")


class SyncRunResult(BaseModel):
    batches_created: int
    batches_sent: int
    batches_pending: int


def _run_unless_running(name: str, empty: Callable[[], T]) -> T:
    """Run the registered job now, or return ``empty()`` if a run of it is in progress."""
    job = next(job for job in registered_jobs() if job.name == name)
    if not job.running.acquire(blocking=False):
        return empty()
    try:
        return job.run()
    finally:
        job.running.release()


@router.post("/run", response_model=SyncRunResult, status_code=202)
def run_sync(session: Session = Depends(get_db),
             _: Principal = Depends(require_role("Admin"))) -> SyncRunResult:
    # End the authorization read, so the request holds no connection while the jobs run.
    session.commit()
    created = _run_unless_running(AGGREGATION, list)
    sent = _run_unless_running(SYNC_SEND, lambda: SendResult(skipped=True))
    return SyncRunResult(batches_created=len(created), batches_sent=len(sent.acked),
                         batches_pending=sync_batches.count_pending(session))
