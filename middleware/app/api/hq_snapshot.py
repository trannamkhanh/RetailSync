"""HQ snapshot intake (PB-13-1, 13-3): refuse every snapshot, audit the attempt."""

from dataclasses import dataclass

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core.db import get_db
from app.core.errors import ApiError
from app.core.security import Principal, bearer_claims, require_role
from app.services import hq_snapshot


router = APIRouter(tags=["Sync"])


@dataclass(frozen=True)
class SnapshotBody:
    """The raw body and its size, read under the limit before any session opens."""

    raw: bytes
    size: int


def _reject_and_commit(session: Session, principal: Principal, raw: bytes) -> ApiError:
    error = hq_snapshot.reject(session, principal, raw)
    session.commit()
    return error


async def _read_limited(request: Request) -> SnapshotBody:
    """Read the body, stopping as soon as it passes the limit.

    Raises 413 ``PAYLOAD_TOO_LARGE`` when the body is over the limit; the
    declared ``content-length`` is not trusted, because a body is judged by what
    it contains.
    """
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > hq_snapshot.MAX_SNAPSHOT_BYTES:
            raise hq_snapshot.too_large(size)
        chunks.append(chunk)
    return SnapshotBody(b"".join(chunks), size)


async def read_snapshot_body(request: Request,
                             claims: dict = Depends(bearer_claims)) -> SnapshotBody:
    """The body, read after the token check and before the database session.

    ``claims`` is only here to order the token check first; FastAPI resolves
    dependencies in declaration order, so a snapshot over the limit is answered
    413 without ``get_db`` ever opening a session (audit #5).
    """
    _ = claims
    return await _read_limited(request)


@router.post("/hq/snapshot")
async def receive_hq_snapshot(body: SnapshotBody = Depends(read_snapshot_body),
                              principal: Principal = Depends(require_role("HQ")),
                              session: Session = Depends(get_db)) -> dict:
    """Answer 422 ``SNAPSHOT_REJECTED`` to every authorized call and change no stock.

    The body is read only to count its bytes and to pick ``store_id`` for the
    audit details; nothing in it is applied or converted (DS-05 section 9). A
    body over 1 MB is refused with 413 ``PAYLOAD_TOO_LARGE`` and is not audited
    (DS-04).

    The order is deliberate (audit #5): the bearer token is checked, then the
    body is read and its size enforced, then the account is looked up, and only
    for an accepted body does the request take a pooled connection. A refused
    request therefore never holds one.

    The audit row is written in the request's own transaction, which the router
    commits before the rejection is raised, so it is kept even though the call
    fails.
    """
    error = await run_in_threadpool(_reject_and_commit, session, principal, body.raw)
    raise error
