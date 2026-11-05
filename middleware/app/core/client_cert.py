"""Client certificate check behind the POS gateway (PB-48-4).

The gateway terminates mutual TLS and forwards the client certificate,
URL-escaped, in ``X-Client-Cert``, together with a shared secret in
``X-Gateway-Secret``. Port 8443 is published too, so the secret is what stops a
client from skipping the gateway or forging the certificate header.
"""

import hashlib
import hmac
import logging
import ssl
from urllib.parse import unquote

from fastapi import Header
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import ApiError
from app.domain.models import PosTerminal


logger = logging.getLogger(__name__)


def _forbidden(message: str) -> ApiError:
    return ApiError(403, "FORBIDDEN", message)


def _gateway_secret() -> bytes:
    secret = settings.pos_gateway_secret
    if secret is None or not secret.get_secret_value().strip():
        raise RuntimeError("Set POS_GATEWAY_SECRET when MTLS_REQUIRED is on.")
    return secret.get_secret_value().encode()


def certificate_fingerprint(pem: str) -> str:
    """SHA-256 of the certificate in DER form, as 64 lower-case hex characters."""
    return hashlib.sha256(ssl.PEM_cert_to_DER_cert(pem.strip())).hexdigest()


def require_gateway(x_gateway_secret: str | None = Header(default=None),
                    x_client_cert: str | None = Header(default=None)) -> str | None:
    """Return the forwarded certificate's fingerprint, or None with mutual TLS off.

    Used as a dependency ahead of ``require_role``, so these refusals come
    before the bearer token is read. There is no principal yet: they are
    logged, not audited.
    """
    if not settings.mtls_required:
        return None
    expected = _gateway_secret()
    if x_gateway_secret is None or not hmac.compare_digest(x_gateway_secret.encode(), expected):
        logger.warning("Refused a POS request that did not come through the gateway")
        raise _forbidden("POS requests must come through the POS gateway.")
    if not x_client_cert:
        raise _forbidden("A client certificate is required.")
    try:
        return certificate_fingerprint(unquote(x_client_cert))
    except ValueError:
        raise _forbidden("The client certificate could not be read.") from None


def require_terminal_certificate(session: Session, pos_id: str, fingerprint: str | None) -> None:
    """The certificate must be the one registered for the event's terminal."""
    if fingerprint is None:
        return
    terminal = session.get(PosTerminal, pos_id)
    if terminal is None or terminal.cert_fingerprint != fingerprint:
        raise _forbidden(f"The client certificate does not belong to terminal '{pos_id}'.")
