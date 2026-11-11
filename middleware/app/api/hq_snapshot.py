"""HQ snapshot intake (PB-13-1, 13-3): refuse every snapshot, audit the attempt."""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.errors import ApiError
from app.core.security import Principal, require_role
from app.services import hq_snapshot


router = APIRouter(tags=["Sync"])


async def _read_limited(request: Request) -> tuple[bytes | None, int]:
    """Read the body, stopping as soon as it passes the limit.

    Returns ``(raw, size)``; ``raw`` is None when the body is too large and
    ``size`` then says how much was seen, which is over the limit. The declared
    ``content-length`` is not trusted: a body is judged by what it contains.
    """
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > hq_snapshot.MAX_SNAPSHOT_BYTES:
            return None, size
        chunks.append(chunk)
    return b"".join(chunks), size


@router.post("/hq/snapshot")
async def receive_hq_snapshot(request: Request,
                              principal: Principal = Depends(require_role("HQ")),
                              session: Session = Depends(get_db)) -> dict:
    """Answer 422 ``SNAPSHOT_REJECTED`` to every authorized call and change no stock.

    The body is read only to count its bytes and to pick ``store_id`` for the
    audit details; nothing in it is applied or converted (DS-05 section 9). A
    body over 1 MB is refused with 413 ``PAYLOAD_TOO_LARGE`` before it is read
    in full and is not audited (DS-04).

    The audit row is written in the request's own transaction, which the router
    commits before the rejection is raised, so it is kept even though the call
    fails.
    """
    raw, size = await _read_limited(request)
    if raw is None:
        raise hq_snapshot.too_large(size)
    error: ApiError = hq_snapshot.reject(session, principal, raw)
    session.commit()
    raise error
