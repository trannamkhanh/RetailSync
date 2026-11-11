"""Customer accounts: password hashing, sessions and the httpOnly cookie.

Passwords use PBKDF2-HMAC-SHA256 from the standard library, so no extra
dependency is needed. The session cookie holds a random token; only its SHA-256
digest is stored, so a database leak does not expose usable sessions.
"""

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Depends, Request, Response
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import settings
from app.customer_db import get_customer_db
from app.customer_models import Customer, CustomerSession
from app.errors import ApiError

COOKIE_NAME = "rts_customer"
PBKDF2_ITERATIONS = 210_000
_SALT_BYTES = 16


def hash_password(password: str) -> str:
    """``pbkdf2_sha256$<iterations>$<salt hex>$<digest hex>``."""
    salt = secrets.token_bytes(_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """Constant-time check of a password against a stored hash."""
    try:
        algorithm, iterations, salt_hex, digest_hex = stored.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            bytes.fromhex(salt_hex),
            int(iterations),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest.hex(), digest_hex)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def create_session(session: Session, customer_id: int) -> str:
    """Store a new session row and return the raw token for the cookie."""
    token = secrets.token_urlsafe(32)
    now = _utcnow()
    session.add(
        CustomerSession(
            token_hash=_token_hash(token),
            customer_id=customer_id,
            created_at=now,
            expires_at=now + timedelta(hours=settings.store_web_session_hours),
        )
    )
    return token


def delete_session(session: Session, token: str | None) -> None:
    if token:
        session.execute(delete(CustomerSession).where(CustomerSession.token_hash == _token_hash(token)))


def purge_expired_sessions(session: Session) -> None:
    session.execute(delete(CustomerSession).where(CustomerSession.expires_at < _utcnow()))


def set_session_cookie(response: Response, token: str) -> None:
    """httpOnly and SameSite=Lax: the SPA never reads the token in JavaScript."""
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=settings.store_web_session_hours * 3600,
        httponly=True,
        samesite="lax",
        secure=False,  # local demo over http; set True behind TLS
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")


def current_customer(
    request: Request,
    session: Session = Depends(get_customer_db),
) -> Customer:
    """Resolve the signed-in customer, or fail with 401."""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise ApiError(401, "UNAUTHENTICATED", "Vui lòng đăng nhập để tiếp tục.")

    row = session.execute(
        select(CustomerSession, Customer)
        .join(Customer, Customer.customer_id == CustomerSession.customer_id)
        .where(CustomerSession.token_hash == _token_hash(token))
    ).first()

    if row is None:
        raise ApiError(401, "UNAUTHENTICATED", "Phiên đăng nhập không còn hợp lệ.")

    stored_session, customer = row
    if stored_session.expires_at < _utcnow():
        session.delete(stored_session)
        session.commit()
        raise ApiError(401, "UNAUTHENTICATED", "Phiên đăng nhập đã hết hạn.")

    return customer


def optional_customer(
    request: Request,
    session: Session = Depends(get_customer_db),
) -> Customer | None:
    """The signed-in customer when there is one, otherwise ``None``."""
    try:
        return current_customer(request, session)
    except ApiError:
        return None
