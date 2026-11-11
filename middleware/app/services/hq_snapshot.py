"""HQ snapshot intake (PB-13): every snapshot is refused, every attempt audited.

DS-05 section 9: HQ never writes into ``RTS_DB``. A full snapshot is neither
applied nor converted into deltas, so local stock changes only through POS
events. The audit row belongs to the request's own transaction; the router
commits it and then raises the returned error.
"""

import json
import re

from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.core.security import Principal
from app.repositories.registry import find_user_id
from app.services.audit import record_audit


# 1 MB, as written in DS-04. A body of exactly this size is still read and
# rejected with 422; only a larger one gets 413 and is not audited.
MAX_SNAPSHOT_BYTES = 1_048_576

# store_id is varchar(10) in dbo.store, so anything else cannot name a store.
_STORE_ID = re.compile(r"[A-Za-z0-9_-]{1,10}")


def too_large(size: int) -> ApiError:
    return ApiError(413, "PAYLOAD_TOO_LARGE",
                    f"Snapshot body is {size} bytes; the limit is {MAX_SNAPSHOT_BYTES}.")


def store_id(raw: bytes) -> str | None:
    """The body's ``store_id`` when it is a JSON object with a usable id.

    The body is read only for this field: nothing else in it is interpreted,
    and a body that is not a JSON object simply has no store.
    """
    try:
        payload = json.loads(raw)
    except (ValueError, UnicodeDecodeError, RecursionError):
        # Deeply nested JSON raises RecursionError; the attempt is still
        # audited and answered 422, just without a store.
        return None
    value = payload.get("store_id") if isinstance(payload, dict) else None
    return value if isinstance(value, str) and _STORE_ID.fullmatch(value) else None


def details(raw: bytes) -> str:
    key = store_id(raw)
    scope = f" for store {key}" if key is not None else ""
    return f"Rejected an HQ snapshot of {len(raw)} bytes{scope}."


def reject(session: Session, principal: Principal, raw: bytes) -> ApiError:
    """Add the audit row and return the 422 to raise. The router commits first."""
    record_audit(session, "SNAPSHOT_REJECTED", "hq_snapshot", None,
                 find_user_id(session, principal.sub), details(raw))
    return ApiError(422, "SNAPSHOT_REJECTED",
                    "HQ snapshots are not applied; inventory changes only through POS deltas.")
