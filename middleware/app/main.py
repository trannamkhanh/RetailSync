"""FastAPI application entry point."""

from fastapi import FastAPI

from app.api.health import router as health_router
from app.core.config import API_PREFIX


app = FastAPI(title="RetailSync Middleware", version="0.1.0")
app.include_router(health_router, prefix=API_PREFIX)
