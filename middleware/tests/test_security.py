"""JWT validation and role checks through a test-only router on real SQL Server."""

from collections.abc import Generator
from dataclasses import asdict, FrozenInstanceError
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import subprocess
import sys

import jwt
import pytest
from fastapi import APIRouter, Depends, FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.core.errors import register_error_handlers
from app.core.security import Principal, create_token, require_role
from app.domain.models import StaffUser, Store


SECRET = "test-only-secret-with-enough-length-for-hs256"
STORE_ID = "TEST-S1"
USERNAME = "TEST-staff"

router = APIRouter()


@router.get("/staff")
def staff_route(principal: Principal = Depends(require_role("Staff", "Manager"))):
    return asdict(principal)


@router.get("/pos")
def pos_route(principal: Principal = Depends(require_role("POS"))):
    return asdict(principal)


@pytest.fixture(autouse=True)
def jwt_secret(monkeypatch):
    monkeypatch.setattr(settings, "jwt_secret", SecretStr(SECRET))


@pytest.fixture
def auth_app(db_session: Session) -> FastAPI:
    def override_get_db() -> Generator[Session, None, None]:
        yield db_session

    test_app = FastAPI()
    register_error_handlers(test_app)
    test_app.include_router(router)
    test_app.dependency_overrides[get_db] = override_get_db
    return test_app


@pytest.fixture
def auth_client(auth_app: FastAPI) -> TestClient:
    return TestClient(auth_app)


@pytest.fixture
def store(db_session: Session) -> str:
    db_session.add(Store(
        store_id=STORE_ID, name="Test store", latitude=Decimal("16.0"),
        longitude=Decimal("108.0"), region_id="TEST",
    ))
    db_session.flush()
    return STORE_ID


def add_user(session: Session, username: str = USERNAME, role: str = "STORE_STAFF",
             store_id: str | None = None, is_active: bool = True) -> StaffUser:
    user = StaffUser(username=username, full_name="Test user", role=role,
                     store_id=store_id, is_active=is_active)
    session.add(user)
    session.flush()
    return user


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def raw_token(secret: str = SECRET, algorithm: str = "HS256", **overrides) -> str:
    claims = {
        "sub": USERNAME, "role": "Staff", "store_id": None, "pos_id": None,
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
    }
    claims.update(overrides)
    return jwt.encode({k: v for k, v in claims.items() if v is not ...}, secret, algorithm=algorithm)


def assert_error(response, status: int, code: str) -> None:
    assert response.status_code == status
    body = response.json()
    assert set(body) == {"outcome", "code", "message"}
    assert (body["outcome"], body["code"]) == ("REJECTED", code)


# Token issuing


def test_create_token_writes_contract_claims():
    token = create_token("someone", "Staff", store_id="S1", pos_id="P1", expires_in_days=2)

    claims = jwt.decode(token, SECRET, algorithms=["HS256"])
    assert jwt.get_unverified_header(token)["alg"] == "HS256"
    assert set(claims) == {"sub", "role", "store_id", "pos_id", "exp"}
    assert (claims["sub"], claims["role"], claims["store_id"], claims["pos_id"]) == ("someone", "Staff", "S1", "P1")
    remaining = claims["exp"] - datetime.now(timezone.utc).timestamp()
    assert timedelta(days=1, hours=23) < timedelta(seconds=remaining) <= timedelta(days=2)


def test_create_token_defaults_to_sixty_days_and_null_scope():
    claims = jwt.decode(create_token("someone", "Admin"), SECRET, algorithms=["HS256"])

    remaining = claims["exp"] - datetime.now(timezone.utc).timestamp()
    assert timedelta(days=59, hours=23) < timedelta(seconds=remaining) <= timedelta(days=60)
    assert claims["store_id"] is None and claims["pos_id"] is None


@pytest.mark.parametrize("value", [None, SecretStr(""), SecretStr("   ")], ids=["missing", "empty", "blank"])
def test_create_token_refuses_without_secret(monkeypatch, value):
    monkeypatch.setattr(settings, "jwt_secret", value)

    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        create_token("someone", "Staff")


# Token validation


def test_missing_token_returns_401(auth_client):
    assert_error(auth_client.get("/staff"), 401, "UNAUTHORIZED")


def test_non_bearer_scheme_returns_401(auth_client):
    response = auth_client.get("/staff", headers={"Authorization": "Basic abc"})

    assert_error(response, 401, "UNAUTHORIZED")


def test_malformed_token_returns_401(auth_client):
    assert_error(auth_client.get("/staff", headers=bearer("not-a-token")), 401, "UNAUTHORIZED")


def test_bad_signature_returns_401(auth_client):
    token = raw_token(secret="another-secret-with-enough-length-for-hs256")

    assert_error(auth_client.get("/staff", headers=bearer(token)), 401, "UNAUTHORIZED")


def test_expired_token_returns_401(auth_client):
    token = create_token(USERNAME, "Staff", expires_in_days=-1)

    assert_error(auth_client.get("/staff", headers=bearer(token)), 401, "UNAUTHORIZED")


@pytest.mark.parametrize("claim", ["exp", "sub", "role"])
def test_missing_claim_returns_401(auth_client, db_session, claim):
    add_user(db_session)
    token = raw_token(**{claim: ...})

    assert_error(auth_client.get("/staff", headers=bearer(token)), 401, "UNAUTHORIZED")


@pytest.mark.parametrize("claim", ["role", "store_id", "pos_id"])
def test_non_string_claim_returns_401(auth_client, db_session, claim):
    add_user(db_session)
    token = raw_token(**{claim: 123})

    assert_error(auth_client.get("/staff", headers=bearer(token)), 401, "UNAUTHORIZED")


@pytest.mark.parametrize("algorithm", ["HS512", "none"])
def test_other_algorithms_return_401(auth_client, db_session, algorithm):
    add_user(db_session)
    token = raw_token(secret=None if algorithm == "none" else SECRET + SECRET, algorithm=algorithm)

    assert_error(auth_client.get("/staff", headers=bearer(token)), 401, "UNAUTHORIZED")


def test_validation_refuses_without_secret(auth_app, db_session, monkeypatch):
    add_user(db_session)
    token = raw_token()
    monkeypatch.setattr(settings, "jwt_secret", None)

    response = TestClient(auth_app, raise_server_exceptions=False).get("/staff", headers=bearer(token))

    assert response.status_code == 503
    assert response.json()["code"] == "SERVICE_UNAVAILABLE"


def test_empty_secret_cannot_validate_token_signed_with_empty_key(auth_app, db_session, monkeypatch):
    add_user(db_session)
    monkeypatch.setattr(settings, "jwt_secret", SecretStr(""))
    token = raw_token(secret="")

    response = TestClient(auth_app, raise_server_exceptions=False).get("/staff", headers=bearer(token))

    assert response.status_code == 503


def test_app_imports_and_serves_health_without_secret():
    code = """
import os
os.environ.pop("JWT_SECRET", None)
from app.core import config
config.settings.jwt_secret = None
from fastapi.testclient import TestClient
from app.main import app
assert TestClient(app).get("/api/v1/health").status_code == 200
"""
    subprocess.run([sys.executable, "-c", code], check=True)


# Role checks


def test_allowed_role_returns_principal_fields(auth_client, db_session, store):
    add_user(db_session, store_id=store)
    token = create_token(USERNAME, "Staff", store_id=store)

    response = auth_client.get("/staff", headers=bearer(token))

    assert response.status_code == 200
    assert response.json() == {"sub": USERNAME, "role": "Staff", "store_id": store, "pos_id": None}


def test_second_allowed_role_passes(auth_client, db_session, store):
    add_user(db_session, role="STORE_MANAGER", store_id=store)
    token = create_token(USERNAME, "Manager", store_id=store)

    assert auth_client.get("/staff", headers=bearer(token)).json()["role"] == "Manager"


def test_pos_principal_keeps_terminal_scope_from_token(auth_client, db_session):
    add_user(db_session, "TEST-pos", role="POS_SYSTEM")
    token = create_token("TEST-pos", "POS", store_id="STORE-DN1", pos_id="POS-DN1-01")

    response = auth_client.get("/pos", headers=bearer(token))

    assert response.json() == {
        "sub": "TEST-pos", "role": "POS", "store_id": "STORE-DN1", "pos_id": "POS-DN1-01",
    }


def test_account_store_overrides_token_store(auth_client, db_session, store):
    add_user(db_session, store_id=store)
    token = create_token(USERNAME, "Staff", store_id="STORE-OLD")

    assert auth_client.get("/staff", headers=bearer(token)).json()["store_id"] == store


def test_unknown_account_returns_401(auth_client):
    token = create_token("TEST-nobody", "Staff")

    assert_error(auth_client.get("/staff", headers=bearer(token)), 401, "UNAUTHORIZED")


def test_inactive_account_returns_403(auth_client, db_session):
    add_user(db_session, is_active=False)
    token = create_token(USERNAME, "Staff")

    assert_error(auth_client.get("/staff", headers=bearer(token)), 403, "FORBIDDEN")


def test_role_not_allowed_returns_403(auth_client, db_session):
    add_user(db_session)
    token = create_token(USERNAME, "Staff")

    assert_error(auth_client.get("/pos", headers=bearer(token)), 403, "FORBIDDEN")


def test_token_role_differing_from_account_returns_403(auth_client, db_session):
    add_user(db_session, role="STORE_STAFF")
    token = create_token(USERNAME, "Manager")

    assert_error(auth_client.get("/staff", headers=bearer(token)), 403, "FORBIDDEN")


@pytest.mark.parametrize(("db_role", "api_role"), [
    ("STORE_STAFF", "Staff"), ("STORE_MANAGER", "Manager"), ("HQ_OPERATOR", "HQ"),
    ("ADMIN", "Admin"), ("AUDITOR", "Auditor"), ("POS_SYSTEM", "POS"),
])
def test_each_db_role_maps_to_its_api_role(db_session, auth_app, db_role, api_role):
    add_user(db_session, role=db_role)
    token = create_token(USERNAME, api_role)
    auth_app.add_api_route("/role", lambda p=Depends(require_role(api_role)): asdict(p))

    response = TestClient(auth_app).get("/role", headers=bearer(token))

    assert response.status_code == 200


def test_unknown_role_name_fails_at_declaration():
    with pytest.raises(ValueError, match="Cashier"):
        require_role("Staff", "Cashier")


def test_require_role_needs_at_least_one_role():
    with pytest.raises(ValueError):
        require_role()


def test_principal_is_immutable():
    principal = Principal(sub="a", role="Staff", store_id=None, pos_id=None)

    with pytest.raises(FrozenInstanceError):
        principal.role = "Admin"
