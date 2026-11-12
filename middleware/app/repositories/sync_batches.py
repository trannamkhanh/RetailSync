"""SQL for sending sync batches (PB-15). Every function takes a session and never commits.

Ids are cast to the column's ``varchar`` type, as in ``repositories.inventory``,
so the keys stay seekable. ``next_retry_at`` is the time after which a batch may
be sent again: for a PENDING batch the retry time, for a SENT batch the moment it
counts as stale (DS-05 section 5).

Order (decided 12 Nov 2026): only the oldest PENDING batch of all stores may be
sent next. While its retry is not due, no newer batch is sent, so batches always
reach HQ oldest first, also after an outage.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.domain.models import SyncBatch


def find_batch(session: Session, sync_batch_id: str) -> SyncBatch | None:
    return session.get(SyncBatch, sync_batch_id)


def summary_lines(session: Session, sync_batch_id: str) -> list[Any]:
    return list(session.execute(
        text(
            """
            SELECT sku, sold_qty, returned_qty, net_revenue
            FROM dbo.sales_summary_line
            WHERE sync_batch_id = CAST(:batch_id AS varchar(40))
            ORDER BY sku
            """
        ),
        {"batch_id": sync_batch_id},
    ))


def release_stale_sent(session: Session, now: datetime) -> int:
    return session.execute(
        text(
            """
            UPDATE dbo.sync_batch
            SET status = 'PENDING', next_retry_at = NULL
            WHERE status = 'SENT' AND (next_retry_at IS NULL OR next_retry_at <= :now)
            """
        ),
        {"now": now},
    ).rowcount


def next_due_batch(session: Session, now: datetime) -> str | None:
    """The oldest PENDING batch of any store, or None while its retry is not due."""
    oldest = session.execute(
        text(
            """
            SELECT TOP 1 sync_batch_id, next_retry_at
            FROM dbo.sync_batch
            WHERE status = 'PENDING'
            ORDER BY created_at, sync_batch_id
            """
        )
    ).first()
    if oldest is None or (oldest.next_retry_at is not None and oldest.next_retry_at > now):
        return None
    return oldest.sync_batch_id


def count_pending(session: Session) -> int:
    return session.execute(text("SELECT COUNT(*) FROM dbo.sync_batch WHERE status = 'PENDING'")).scalar_one()


def sent_attempts(session: Session, sync_batch_id: str) -> int | None:
    """Attempts so far of a SENT batch; None when it is no longer SENT."""
    return session.execute(
        text(
            """
            SELECT attempts FROM dbo.sync_batch
            WHERE sync_batch_id = CAST(:batch_id AS varchar(40)) AND status = 'SENT'
            """
        ),
        {"batch_id": sync_batch_id},
    ).scalar()


def mark_sent(session: Session, sync_batch_id: str, stale_at: datetime) -> bool:
    return session.execute(
        text(
            """
            UPDATE dbo.sync_batch
            SET status = 'SENT', next_retry_at = :stale_at
            WHERE sync_batch_id = CAST(:batch_id AS varchar(40)) AND status = 'PENDING'
            """
        ),
        {"batch_id": sync_batch_id, "stale_at": stale_at},
    ).rowcount == 1


def mark_acked(session: Session, sync_batch_id: str, now: datetime, payload_bytes: int) -> bool:
    """False when the batch was already ACKED, so its audit is written once."""
    return session.execute(
        text(
            """
            UPDATE dbo.sync_batch
            SET status = 'ACKED', acked_at = :now, next_retry_at = NULL, payload_bytes = :payload_bytes
            WHERE sync_batch_id = CAST(:batch_id AS varchar(40)) AND status <> 'ACKED'
            """
        ),
        {"batch_id": sync_batch_id, "now": now, "payload_bytes": payload_bytes},
    ).rowcount == 1


def mark_pending_after_attempt(session: Session, sync_batch_id: str, last_error: str,
                               payload_bytes: int, next_retry_at: datetime | None) -> bool:
    return session.execute(
        text(
            """
            UPDATE dbo.sync_batch
            SET status = 'PENDING', attempts = attempts + 1, last_error = :last_error,
                payload_bytes = :payload_bytes, next_retry_at = :next_retry_at
            WHERE sync_batch_id = CAST(:batch_id AS varchar(40)) AND status = 'SENT'
            """
        ),
        {"batch_id": sync_batch_id, "last_error": last_error, "payload_bytes": payload_bytes,
         "next_retry_at": next_retry_at},
    ).rowcount == 1


def mark_failed(session: Session, sync_batch_id: str, last_error: str, payload_bytes: int) -> bool:
    """A NACK: FAILED for good. Its transactions stay linked, so they join no later batch."""
    return session.execute(
        text(
            """
            UPDATE dbo.sync_batch
            SET status = 'FAILED', attempts = attempts + 1, last_error = :last_error,
                payload_bytes = :payload_bytes, next_retry_at = NULL
            WHERE sync_batch_id = CAST(:batch_id AS varchar(40)) AND status = 'SENT'
            """
        ),
        {"batch_id": sync_batch_id, "last_error": last_error, "payload_bytes": payload_bytes},
    ).rowcount == 1
