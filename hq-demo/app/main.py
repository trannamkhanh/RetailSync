"""HQ demo service (PB-18): HTTPS on 9000, POST /sync, demo endpoints."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import json
import logging
from threading import Thread

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app import modes
from app.db import get_db, get_engine
from app.errors import HqError, hq_error_handler
from app.hashing import batch_hash
from app.models import HqSalesTotal, HqSyncBatch
from app.schemas import ModeUpdate, SyncBatchMessage
from app.security import require_middleware
from app.service import apply_batch


logger = logging.getLogger(__name__)


def _warm_up() -> None:
    """Open the engine and run one query in the background after startup.

    The first connection costs about 6 seconds on a cold container, which is
    longer than the Middleware's 3 second send timeout (PB-18). Once warmup
    succeeds, /sync can reuse the connection. Failure is logged.
    """
    try:
        with get_engine().connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception:
        logger.warning("HQ demo warm start could not reach the database; "
                       "the first request may be slow", exc_info=True)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    Thread(target=_warm_up, name="hq-db-warm-up", daemon=True).start()
    yield


app = FastAPI(title="RetailSync HQ demo", version="0.1.0", lifespan=lifespan)
app.add_exception_handler(HqError, hq_error_handler)


def nack(status_code: int, code: str, message: str, batch_id: str | None = None) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"status": "NACK", "batch_id": batch_id, "code": code, "message": message},
    )


def _first_error(error: ValidationError) -> str:
    detail = error.errors()[0]
    location = ".".join(str(part) for part in detail["loc"])
    return f"{location}: {detail['msg']}"


def _store_batch(session: Session, message: SyncBatchMessage, payload_hash: str) -> bool:
    """Run the blocking database part off the event loop."""
    duplicate = apply_batch(session, message, payload_hash)
    session.commit()
    return duplicate


@app.get("/api/v1/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/api/v1/sync")
async def receive_batch(request: Request, _: None = Depends(require_middleware),
                        session: Session = Depends(get_db)):
    raw = await request.body()
    try:
        payload = json.loads(raw)
    except ValueError:
        return nack(422, "INVALID_BATCH", "Body must be a JSON object.")
    if not isinstance(payload, dict):
        return nack(422, "INVALID_BATCH", "Body must be a JSON object.")
    batch_id = payload.get("batch_id") if isinstance(payload.get("batch_id"), str) else None

    mode = modes.get_mode()
    if mode is modes.Mode.OFFLINE:
        return nack(503, "HQ_OFFLINE", "HQ is offline for this demo.", batch_id)
    if mode is modes.Mode.ERROR:
        return nack(500, "HQ_ERROR", "HQ failed for this demo.", batch_id)

    try:
        message = SyncBatchMessage.model_validate(payload)
    except ValidationError as error:
        return nack(422, "INVALID_BATCH", _first_error(error), batch_id)

    if mode is modes.Mode.SLOW:
        await asyncio.sleep(4)

    duplicate = await run_in_threadpool(_store_batch, session, message, batch_hash(message))

    if mode is modes.Mode.DROP_ACK:
        return nack(500, "ACK_DROPPED", "Batch stored, ACK dropped.", message.batch_id)
    return {"status": "ACK", "batch_id": message.batch_id, "duplicate": duplicate}


@app.get("/api/v1/demo/batches")
def demo_batches(session: Session = Depends(get_db)) -> dict:
    batches = session.scalars(
        select(HqSyncBatch).order_by(HqSyncBatch.received_at, HqSyncBatch.sync_batch_id)
    ).all()
    totals = session.scalars(
        select(HqSalesTotal).order_by(HqSalesTotal.store_id, HqSalesTotal.sku)
    ).all()
    return {
        "batches": [
            {
                "batch_id": batch.sync_batch_id,
                "store_id": batch.store_id,
                "txn_count": batch.txn_count,
                "received_at": batch.received_at.isoformat() + "Z",
                "duplicate_count": batch.duplicate_count,
            }
            for batch in batches
        ],
        "totals": [
            {
                "sku": total.sku,
                "store_id": total.store_id,
                "sold_qty": total.sold_qty,
                "returned_qty": total.returned_qty,
                "net_revenue": float(total.net_revenue),
            }
            for total in totals
        ],
    }


@app.put("/api/v1/demo/mode")
def set_mode(update: ModeUpdate) -> dict:
    modes.set_mode(update.mode)
    return {"mode": update.mode.value}
