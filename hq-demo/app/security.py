"""The middleware service token of PB-18-2: HS256, sub and role checked."""

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import jwt
from jwt import InvalidTokenError

from app.config import settings
from app.errors import HqError


bearer = HTTPBearer(auto_error=False)

_SUBJECT = "rts-middleware"
_ROLE = "MIDDLEWARE"


def require_middleware(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> None:
    secret = settings.hq_jwt_secret
    if credentials is None or secret is None or not secret.get_secret_value():
        raise HqError(401, "UNAUTHORIZED", "Missing, invalid or expired token.")
    try:
        claims = jwt.decode(
            credentials.credentials, secret.get_secret_value(), algorithms=["HS256"],
            options={"require": ["exp", "sub", "role"]},
        )
    except InvalidTokenError as error:
        raise HqError(401, "UNAUTHORIZED", "Missing, invalid or expired token.") from error
    if claims.get("sub") != _SUBJECT or claims.get("role") != _ROLE:
        raise HqError(401, "UNAUTHORIZED", "Missing, invalid or expired token.")
