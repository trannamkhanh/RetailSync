"""FastAPI application entry point."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.admin import router as admin_router
from app.api.audit import router as audit_router
from app.api.guardrails import router as guardrails_router
from app.api.health import router as health_router
from app.api.hq_snapshot import router as hq_snapshot_router
from app.api.inventory import router as inventory_router
from app.api.jobs import router as jobs_router
from app.api.near_expiry import router as near_expiry_router
from app.api.pos import router as pos_router
from app.api.products import router as products_router
from app.core.config import API_PREFIX, settings
from app.core.errors import register_error_handlers
from app.jobs import scheduler


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Run the shared scheduler with the app when SCHEDULER_ENABLED is true (PB-15-1)."""
    running = scheduler.start_scheduler() if settings.scheduler_enabled else None
    try:
        yield
    finally:
        if running is not None:
            running.stop()


app = FastAPI(title="RetailSync Middleware", version="0.1.0", lifespan=lifespan)
register_error_handlers(app)
app.include_router(admin_router, prefix=API_PREFIX)
app.include_router(audit_router, prefix=API_PREFIX)
app.include_router(guardrails_router, prefix=API_PREFIX)
app.include_router(health_router, prefix=API_PREFIX)
app.include_router(hq_snapshot_router, prefix=API_PREFIX)
app.include_router(inventory_router, prefix=API_PREFIX)
app.include_router(jobs_router, prefix=API_PREFIX)
app.include_router(near_expiry_router, prefix=API_PREFIX)
app.include_router(pos_router, prefix=API_PREFIX)
app.include_router(products_router, prefix=API_PREFIX)
