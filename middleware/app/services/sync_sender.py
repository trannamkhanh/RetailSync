"""What the sender does with a batch and HQ's answer (PB-15-3, 15-4, PB-16-1 to 16-4).

These functions take a session and never commit; ``app/jobs/sync_send.py``
owns the transactions (DS-05 sections 5 and 6).
"""

from datetime import datetime, timedelta
import logging

from sqlalchemy.orm import Session

from app.core.config import settings
from app.integration.hq_client import HqResult
from app.repositories import sync_batches as repository
from app.services.audit import record_audit


logger = logging.getLogger(__name__)

# DS-05 section 5: a batch SENT for longer than this returns to PENDING.
STALE_AFTER = timedelta(seconds=60)
# DS-05 section 5: HQ refused the batch itself, so resending it cannot help.
NACK_STATUSES = frozenset({400, 409, 422})
# DS-05 section 5: a configuration or capacity problem; logged, then retried.
CONFIG_STATUSES = frozenset({401, 403, 404, 408, 429})
# DS-05 section 6: the backoff doubles up to 60 minutes.
RETRY_CAP_SECONDS = 3600
# sync_batch.last_error is nvarchar(200), which counts UTF-16 code units.
LAST_ERROR_LIMIT = 200


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


def retry_delay(attempts: int) -> timedelta:
    """SYNC_RETRY_BASE_SECONDS x 2^(attempts - 1), at most 3600 s; ``attempts`` counts this one."""
    exponent = min(max(attempts - 1, 0), 32)
    return timedelta(seconds=min(settings.sync_retry_base_seconds * 2 ** exponent, RETRY_CAP_SECONDS))


def fit_last_error(answer: HqResult) -> str:
    """Status, code and message, cut to the column's 200 UTF-16 code units."""
    encoded = answer.describe().encode("utf-16-le")[:LAST_ERROR_LIMIT * 2]
    return encoded.decode("utf-16-le", errors="ignore")


def is_nack(answer: HqResult) -> bool:
    return answer.kind == "NACK" and answer.status in NACK_STATUSES


def _after_failure(session: Session, batch_id: str, answer: HqResult, now: datetime) -> bool:
    """DS-05 section 5 for any answer but an ACK.

    - 400, 409, 422 (NACK): FAILED, ``last_error``, audit SYNC_FAILED; the next batch is still sent.
    - Anything else (timeout, connection error, 5xx, 401, 403, 404, 408, 429, an
      unexpected answer): PENDING, attempts + 1, ``last_error``, ``next_retry_at``
      from the backoff, and the cycle stops.
    """
    last_error = fit_last_error(answer)
    if is_nack(answer):
        if repository.mark_failed(session, batch_id, last_error, answer.payload_bytes):
            record_audit(session, "SYNC_FAILED", "sync_batch", batch_id, None, last_error)
        return True
    if answer.status in CONFIG_STATUSES:
        logger.error("HQ answered %s to batch %s; check the HQ configuration or capacity: %s",
                     answer.status, batch_id, last_error)
    attempts = repository.sent_attempts(session, batch_id)
    if attempts is not None:
        repository.mark_pending_after_attempt(session, batch_id, last_error, answer.payload_bytes,
                                              next_retry_at=now + retry_delay(attempts + 1))
    return False
