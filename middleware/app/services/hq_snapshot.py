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
_JSON_TOKEN = re.compile(r'[ \t\r\n]*("(?:[^"\\\x00-\x1f]|\\["\\/bfnrt]|\\u[0-9a-fA-F]{4})*"|-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?|true|false|null|[{}\[\],:])', re.ASCII)


def _deep_store_id(raw: bytes) -> str | None:
    """Validate deeply nested JSON iteratively, retaining only the root store ID."""
    try:
        text = raw.decode(json.detect_encoding(raw), "surrogatepass")
    except UnicodeDecodeError:
        return None
    # Frames contain container type and the next expected grammar element.
    stack: list[list[str]] = []
    position = 0
    root_done = False
    root_object = False
    key = None
    store = None
    while position < len(text):
        match = _JSON_TOKEN.match(text, position)
        if match is None:
            if text[position:].strip(" \t\r\n") == "":
                break
            return None
        token = match.group(1)
        position = match.end()
        if root_done:
            return None
        if stack:
            kind, state = stack[-1]
            if state in ("key_or_end", "key"):
                if state == "key_or_end" and token == "}":
                    stack.pop()
                    root_done = not stack
                    continue
                if not token.startswith('"'):
                    return None
                if len(stack) == 1:
                    key = json.loads(token)
                stack[-1][1] = "colon"
                continue
            if state == "colon":
                if token != ":":
                    return None
                stack[-1][1] = "value"
                continue
            if state == "comma_or_end":
                closing = "}" if kind == "object" else "]"
                if token == closing:
                    stack.pop()
                    root_done = not stack
                elif token == ",":
                    stack[-1][1] = "key" if kind == "object" else "value"
                else:
                    return None
                continue
            if state == "value_or_end" and token == "]":
                stack.pop()
                root_done = not stack
                continue
            if state not in ("value", "value_or_end"):
                return None
            if len(stack) == 1 and kind == "object" and key == "store_id":
                store = json.loads(token) if token.startswith('"') else None
            stack[-1][1] = "comma_or_end"
        else:
            root_object = token == "{"
        if token == "{":
            stack.append(["object", "key_or_end"])
        elif token == "[":
            stack.append(["array", "value_or_end"])
        elif token in ("}", "]", ",", ":"):
            return None
        elif not stack:
            root_done = True
    return store if root_done and root_object and isinstance(store, str) and _STORE_ID.fullmatch(store) else None


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
    except RecursionError:
        return _deep_store_id(raw)
    except (ValueError, UnicodeDecodeError):
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
