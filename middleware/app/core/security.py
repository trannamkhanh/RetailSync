"""JWT validation and role checks. Tokens are pre-issued; there is no login API."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.core.errors import ApiError
from app.domain.models import StaffUser


ALGORITHM = "HS256"
API_ROLE_BY_DB_ROLE = {
    "STORE_STAFF": "Staff",
    "STORE_MANAGER": "Manager",
    "HQ_OPERATOR": "HQ",
    "ADMIN": "Admin",
    "AUDITOR": "Auditor",
    "POS_SYSTEM": "POS",
}

_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class Principal:
    sub: str
    role: str
    store_id: str | None
    pos_id: str | None


def _secret() -> str:
    secret = settings.jwt_secret
    if secret is None or not secret.get_secret_value().strip():
        raise RuntimeError("Set JWT_SECRET before issuing or validating tokens.")
    return secret.get_secret_value()


def _unauthorized() -> ApiError:
    return ApiError(401, "UNAUTHORIZED", "Missing, invalid or expired token.")


def _forbidden() -> ApiError:
    return ApiError(403, "FORBIDDEN", "This account may not perform this action.")


def create_token(sub: str, role: str, store_id: str | None = None,
                 pos_id: str | None = None, expires_in_days: int = 60) -> str:
    expires_at = datetime.now(timezone.utc) + timedelta(days=expires_in_days)
    claims = {"sub": sub, "role": role, "store_id": store_id, "pos_id": pos_id, "exp": expires_at}
    return jwt.encode(claims, _secret(), algorithm=ALGORITHM)


def _decode_token(token: str) -> dict[str, Any]:
    secret = _secret()
    try:
        claims = jwt.decode(token, secret, algorithms=[ALGORITHM],
                            options={"require": ["exp", "sub", "role"]})
    except jwt.InvalidTokenError:
        raise _unauthorized() from None
    scope_is_text = all(isinstance(claims.get(name), str | None) for name in ("store_id", "pos_id"))
    if not isinstance(claims["role"], str) or not scope_is_text:
        raise _unauthorized()
    return claims


def _authorize(claims: dict[str, Any], session: Session, allowed: frozenset[str]) -> Principal:
    user = session.scalar(select(StaffUser).where(StaffUser.username == claims["sub"]))
    if user is None:
        raise _unauthorized()
    role = API_ROLE_BY_DB_ROLE.get(user.role)
    if not user.is_active or role != claims["role"] or role not in allowed:
        raise _forbidden()
    # The POS service account spans terminals, so only its token carries a store.
    return Principal(user.username, role, user.store_id or claims.get("store_id"), claims.get("pos_id"))


def require_role(*roles: str) -> Callable[..., Principal]:
    unknown = sorted(set(roles) - set(API_ROLE_BY_DB_ROLE.values()))
    if unknown or not roles:
        raise ValueError(f"require_role needs known API roles, got: {unknown or 'none'}")
    allowed = frozenset(roles)

    def dependency(credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
                   session: Session = Depends(get_db)) -> Principal:
        if credentials is None:
            raise _unauthorized()
        return _authorize(_decode_token(credentials.credentials), session, allowed)

    return dependency
