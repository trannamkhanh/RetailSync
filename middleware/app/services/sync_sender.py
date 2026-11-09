"""What the sender does with a batch and HQ's answer (PB-15-3, 15-4, PB-16-1, 16-2).

These functions take a session and never commit; ``app/jobs/sync_send.py``
owns the transactions (DS-05 sections 5 and 6).
"""

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.integration.hq_client import HqResult
from app.repositories import sync_batches as repository
from app.services.audit import record_audit


# DS-05 section 5: a batch SENT for longer than this returns to PENDING.
STALE_AFTER = timedelta(seconds=60)


def release_stale(session: Session, now: datetime) -> int:
    return repository.release_stale_sent(session, now)


def claim_next(session: Session, now: datetime) -> str | None:
    """Mark the oldest due PENDING batch, of any store, SENT and return its id."""
    while (batch_id := repository.next_due_batch(session, now)) is not None:
        if repository.mark_sent(session, batch_id, now + STALE_AFTER):
            return batch_id
    return None


def record_answer(session: Session, batch_id: str, answer: HqResult, now: datetime) -> bool:
    """Apply HQ's answer. Returns True when the cycle may send the next batch.

    An ACK, including ``duplicate: true`` after a lost ACK, sets ACKED and
    ``acked_at`` and writes SYNC_ACKED in the same transaction.
    """
    if answer.kind == "ACK":
        if repository.mark_acked(session, batch_id, now, answer.payload_bytes):
            details = f"ACK{' (duplicate)' if answer.duplicate else ''}, {answer.payload_bytes} bytes"
            record_audit(session, "SYNC_ACKED", "sync_batch", batch_id, None, details)
        return True
    return _after_failure(session, batch_id, answer, now)


def _after_failure(session: Session, batch_id: str, answer: HqResult, now: datetime) -> bool:
    """Any answer but an ACK, in phase 5: back to PENDING, attempts + 1, stop the cycle.

    Phase 6 (PB-16-3, PB-16-4) replaces this with DS-05 section 5:
    - 400, 409, 422 NACK: FAILED, last_error, audit, and the next batch is still sent.
    - Timeout, connection error, 5xx, 401, 403, 404, 408, 429: PENDING, attempts + 1,
      ``next_retry_at`` from the backoff (1, 2, 4 ... 60 minutes), and the cycle stops.
    """
    repository.mark_pending_after_attempt(session, batch_id, answer.describe(), answer.payload_bytes,
                                          next_retry_at=None)
    return False
