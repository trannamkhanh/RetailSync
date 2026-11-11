"""Run a daily job now (PB-15-6). Admin only; the audit commits in the router.

The run takes the scheduler's per-job lock (``Job.running`` of
``registered_jobs()``), so a scheduled run and a requested run never overlap.
It works whether or not the scheduler is enabled. Sync keeps its own
``POST /sync/run``.
"""

import logging
from typing import Literal

from fastapi import APIRouter, Depends, Path
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.errors import ApiError
from app.core.security import Principal, require_role
from app.jobs import registry  # noqa: F401  registers the jobs, also when the scheduler is off
from app.jobs.scheduler import Job, registered_jobs
from app.repositories.registry import find_user_id
from app.services.audit import record_audit


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["Admin"])

JOB_NAME = Path(min_length=1, max_length=50, pattern=r"^[A-Za-z0-9_-]+$")


class JobRunResult(BaseModel):
    job: str
    status: Literal["COMPLETED"]


def _daily_job(name: str) -> Job:
    for job in registered_jobs():
        if job.name == name and job.daily_at is not None:
            return job
    raise ApiError(404, "NOT_FOUND", f"No daily job named '{name}'.")


def _audit_request(session: Session, name: str, principal: Principal) -> None:
    """Committed before the run, so the request is recorded even if the job fails."""
    record_audit(session, "JOB_RUN_REQUESTED", "job", name, find_user_id(session, principal.sub),
                 f"Run of daily job {name} requested.")
    session.commit()


@router.post("/jobs/{name}/run", response_model=JobRunResult)
def run_job(name: str = JOB_NAME,
            session: Session = Depends(get_db),
            principal: Principal = Depends(require_role("Admin"))) -> JobRunResult:
    job = _daily_job(name)
    if not job.running.acquire(blocking=False):
        raise ApiError(409, "JOB_RUNNING", f"Job '{name}' is already running.")
    try:
        _audit_request(session, name, principal)
        try:
            job.run()
        except Exception:
            logger.exception("Requested run of job %s failed", name)
            raise ApiError(503, "SERVICE_UNAVAILABLE", f"Job '{name}' failed. Try again later.",
                           outcome="ERROR") from None
    finally:
        job.running.release()
    return JobRunResult(job=name, status="COMPLETED")
