"""Read-only store web API: JSON only, plus the built SPA at the root."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import auth, health, meta, products, shop, stores
from app.config import settings
from app.customer_db import prepare_customer_database
from app.errors import register_error_handlers
from app.static_site import mount_spa

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Prepare the customer database; a failure only disables login."""
    prepare_customer_database()
    yield


app = FastAPI(title="RetailSync Store Web API", version="0.2.0", lifespan=lifespan)

register_error_handlers(app)

# Only needed when a development server calls the API without the Vite proxy.
if settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["*"],
    )

app.include_router(health.router, prefix="/api")
app.include_router(stores.router, prefix="/api")
app.include_router(products.router, prefix="/api")
app.include_router(meta.router, prefix="/api")
app.include_router(auth.router, prefix="/api")
app.include_router(shop.router, prefix="/api")

# After every /api router, so a missing API route still answers JSON.
mount_spa(app)
