"""JWT validation and role checks. Implementation follows; signatures are final."""

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class Principal:
    sub: str
    role: str
    store_id: str | None
    pos_id: str | None


def require_role(*roles: str) -> Callable[..., Principal]:
    raise NotImplementedError


def create_token(sub: str, role: str, store_id: str | None = None,
                 pos_id: str | None = None, expires_in_days: int = 60) -> str:
    raise NotImplementedError
