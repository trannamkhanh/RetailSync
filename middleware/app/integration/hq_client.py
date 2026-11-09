"""HTTP client for the HQ sync endpoint (PB-15-3).

``send_batch`` posts one SyncBatchMessage (DS-04) to ``{HQ_URL}/sync`` with the
middleware service token, waits at most ``HQ_TIMEOUT_SECONDS``, verifies HQ's
certificate against ``HQ_CA_FILE``, and says what came back: an ACK, a NACK, or
no answer at all. It never changes a batch; the sender decides what to do.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path
from typing import Literal

import httpx
import jwt

from app.core.config import settings


# Tests replace this with an httpx.MockTransport.
transport: httpx.BaseTransport | None = None

TOKEN_SUBJECT = "rts-middleware"
TOKEN_ROLE = "MIDDLEWARE"
TOKEN_LIFETIME = timedelta(minutes=5)
LAST_ERROR_LIMIT = 200


class HqConfigError(RuntimeError):
    """The middleware cannot call HQ as configured; no batch should be touched."""


@dataclass(frozen=True)
class HqResult:
    kind: Literal["ACK", "NACK", "NO_ANSWER"]
    duplicate: bool = False
    status: int | None = None
    code: str | None = None
    message: str = ""
    payload_bytes: int = 0

    def describe(self) -> str:
        """A short text for ``sync_batch.last_error``."""
        if self.kind == "NO_ANSWER":
            text = f"No answer from HQ: {self.message}"
        else:
            text = f"{self.status} {self.code}: {self.message}"
        return text[:LAST_ERROR_LIMIT]


def _secret() -> str:
    secret = settings.hq_jwt_secret
    if secret is None or not secret.get_secret_value().strip():
        raise HqConfigError("Set HQ_JWT_SECRET before sending batches to HQ.")
    return secret.get_secret_value()


def check_configured() -> None:
    """Fail before any batch is touched when HQ cannot be called as configured."""
    _secret()
    if settings.hq_ca_file and not Path(settings.hq_ca_file).is_file():
        raise HqConfigError(f"HQ_CA_FILE {settings.hq_ca_file} does not exist.")


def service_token() -> str:
    claims = {"sub": TOKEN_SUBJECT, "role": TOKEN_ROLE,
              "exp": datetime.now(timezone.utc) + TOKEN_LIFETIME}
    return jwt.encode(claims, _secret(), algorithm="HS256")


def tls_verify() -> str | bool:
    return settings.hq_ca_file or True


def message_json(message: dict) -> bytes:
    """Compact JSON in which a Decimal is a JSON number with its exact digits.

    ``net_revenue`` therefore goes out as ``20.10``, which HQ reads back as a
    two-decimal value, rather than through a float.
    """
    numbers: dict[str, str] = {}

    def placeholder(value: object) -> str:
        if not isinstance(value, Decimal):
            raise TypeError(f"{type(value).__name__} is not JSON serializable")
        key = f"\x00{len(numbers)}\x00"
        numbers[json.dumps(key)] = format(value, "f")
        return key

    text = json.dumps(message, separators=(",", ":"), default=placeholder)
    for quoted, number in numbers.items():
        text = text.replace(quoted, number)
    return text.encode("utf-8")


def _answer(response: httpx.Response, batch_id: str, payload_bytes: int) -> HqResult:
    try:
        body = response.json()
    except ValueError:
        body = None
    if not isinstance(body, dict):
        body = {}
    if response.status_code == 200:
        if body.get("status") == "ACK" and body.get("batch_id") == batch_id \
                and isinstance(body.get("duplicate"), bool):
            return HqResult("ACK", duplicate=body["duplicate"], status=200, payload_bytes=payload_bytes)
        return HqResult("NACK", status=200, code="UNEXPECTED_ANSWER",
                        message="HQ answered 200 without an ACK for this batch.", payload_bytes=payload_bytes)
    code = body.get("code") if isinstance(body.get("code"), str) else f"HTTP_{response.status_code}"
    message = body.get("message") if isinstance(body.get("message"), str) else response.reason_phrase
    return HqResult("NACK", status=response.status_code, code=code, message=message, payload_bytes=payload_bytes)


def send_batch(message: dict) -> HqResult:
    token = service_token()
    payload = message_json(message)
    url = settings.hq_url.rstrip("/") + "/sync"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    try:
        with httpx.Client(timeout=settings.hq_timeout_seconds, verify=tls_verify(), transport=transport) as client:
            response = client.post(url, content=payload, headers=headers)
    except httpx.TransportError as error:
        return HqResult("NO_ANSWER", message=f"{type(error).__name__}: {error}"[:LAST_ERROR_LIMIT],
                        payload_bytes=len(payload))
    return _answer(response, message["batch_id"], len(payload))
