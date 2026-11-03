"""FastAPI application entry point."""

from fastapi import FastAPI

from app.api.admin import router as admin_router
from app.api.audit import router as audit_router
from app.api.health import router as health_router
from app.api.inventory import router as inventory_router
from app.api.pos import router as pos_router
from app.core.config import API_PREFIX
from app.core.errors import register_error_handlers


app = FastAPI(title="RetailSync Middleware", version="0.1.0")
register_error_handlers(app)
app.include_router(admin_router, prefix=API_PREFIX)
app.include_router(audit_router, prefix=API_PREFIX)
app.include_router(health_router, prefix=API_PREFIX)
app.include_router(inventory_router, prefix=API_PREFIX)
app.include_router(pos_router, prefix=API_PREFIX)
