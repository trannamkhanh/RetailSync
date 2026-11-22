"""The send cycle job (PB-15-3, 15-4, PB-16-1 to 16-4).

Runs every min(SYNC_INTERVAL, SYNC_SEND_POLL_SECONDS) seconds (DS-05 section 6).
Like a router, this module owns its transactions:

1. Return batches SENT for more than 60 seconds to PENDING.
2. Take the oldest unfinished batch of any store; if it is PENDING and its retry
   is due, mark it SENT and commit. While it is SENT or waits for its retry,
   nothing newer is sent.
3. Build and send its message; record HQ's answer in its own transaction.
4. Repeat until no batch is due. A NACK (400, 409, 422) fails that batch and the
   cycle goes on; any other answer but an ACK backs the batch off and stops it.

Only one cycle runs at a time in the process; a second call returns at once.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import logging
import threading

from app.core.db import SessionLocal
from app.integration import hq_client
from app.services import sync_sender
from app.services.sync_message import build_message


logger = logging.getLogger(__name__)

session_factory = SessionLocal

_cycle = threading.Lock()


def clock() -> datetime:
    """UTC now without a time zone, as datetime2 columns store it."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


@dataclass
class SendResult:
    skipped: bool = False
    released: int = 0
    acked: list[str] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)  # NACKed, now FAILED
    failed: str | None = None  # the batch that stopped the cycle, back to PENDING
    error: str | None = None


def release_stale_batches() -> int:
    """Return batches SENT for more than 60 seconds to PENDING (DS-05 section 5).

    Runs before each cycle and when the scheduler takes the job lock at startup.
    """
    with session_factory() as session:
        released = sync_sender.release_stale(session, clock())
        session.commit()
    return released


def run_send_cycle() -> SendResult:
    if not _cycle.acquire(blocking=False):
        return SendResult(skipped=True)
    try:
        return _send_due_batches()
    finally:
        _cycle.release()


def _send_due_batches() -> SendResult:
    result = SendResult()
    try:
        hq_client.check_configured()
    except hq_client.HqConfigError as error:
        logger.error("Sync send skipped: %s", error)
        result.error = str(error)
        return result

    result.released = release_stale_batches()

    while True:
        with session_factory() as session:
            batch_id = sync_sender.claim_next(session, clock())
            session.commit()
        if batch_id is None:
            return result
        with session_factory() as session:
            message = build_message(session, batch_id)
        answer = hq_client.send_batch(message)
        with session_factory() as session:
            keep_going = sync_sender.record_answer(session, batch_id, answer, clock())
            session.commit()
        if answer.kind == "ACK":
            result.acked.append(batch_id)
        elif sync_sender.is_nack(answer):
            logger.warning("Sync batch %s rejected by HQ: %s", batch_id, answer.describe())
            result.rejected.append(batch_id)
        if not keep_going:
            logger.warning("Sync batch %s not acknowledged: %s", batch_id, answer.describe())
            result.failed, result.error = batch_id, answer.describe()
            return result
