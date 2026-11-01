"""scripts/issue_demo_tokens.py. Needs the whole repository, not only middleware/."""

from dataclasses import asdict
import importlib.util
import json
from pathlib import Path

import jwt
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.core.config import settings
from app.core.db import get_db
from app.core.errors import register_error_handlers
from app.core.security import API_ROLE_BY_DB_ROLE, require_role
from app.domain.models import StaffUser


SECRET = "test-only-secret-with-enough-length-for-hs256"
SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "issue_demo_tokens.py"

EXPECTED = {
    "staff_dn1": ("staff_dn1", "Staff", "STORE-DN1", None),
    "staff_dn2": ("staff_dn2", "Staff", "STORE-DN2", None),
    "staff_dn3": ("staff_dn3", "Staff", "STORE-DN3", None),
    "manager_dn1": ("manager_dn1", "Manager", "STORE-DN1", None),
    "admin": ("admin", "Admin", None, None),
    "auditor": ("auditor", "Auditor", None, None),
    "hq_operator": ("hq_operator", "HQ", None, None),
    "POS-DN1-01": ("pos_system", "POS", "STORE-DN1", "POS-DN1-01"),
    "POS-DN1-02": ("pos_system", "POS", "STORE-DN1", "POS-DN1-02"),
    "POS-DN2-01": ("pos_system", "POS", "STORE-DN2", "POS-DN2-01"),
    "POS-DN2-02": ("pos_system", "POS", "STORE-DN2", "POS-DN2-02"),
    "POS-DN3-01": ("pos_system", "POS", "STORE-DN3", "POS-DN3-01"),
    "POS-DN3-02": ("pos_system", "POS", "STORE-DN3", "POS-DN3-02"),
}


@pytest.fixture
def script():
    if not SCRIPT.exists():
        pytest.skip("scripts/ is not mounted; run from the repository root mount.")
    spec = importlib.util.spec_from_file_location("issue_demo_tokens", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def jwt_secret(monkeypatch):
    monkeypatch.setattr(settings, "jwt_secret", SecretStr(SECRET))


def claims_of(token: str) -> tuple:
    claims = jwt.decode(token, SECRET, algorithms=["HS256"])
    return claims["sub"], claims["role"], claims["store_id"], claims["pos_id"]


def test_writes_thirteen_contract_tokens(script, tmp_path):
    output = tmp_path / ".tokens" / "demo_tokens.json"

    assert script.main(output) == 0

    tokens = json.loads(output.read_text(encoding="utf-8"))
    assert {name: claims_of(token) for name, token in tokens.items()} == EXPECTED


def test_prints_names_but_never_token_values(script, tmp_path, capsys):
    output = tmp_path / "demo_tokens.json"

    script.main(output)

    printed = capsys.readouterr()
    for name, token in json.loads(output.read_text(encoding="utf-8")).items():
        assert name in printed.out
        assert token not in printed.out + printed.err
    assert SECRET not in printed.out + printed.err


def test_refuses_without_secret_and_writes_nothing(script, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(settings, "jwt_secret", None)
    output = tmp_path / "demo_tokens.json"

    assert script.main(output) == 1

    assert not output.exists()
    assert "JWT_SECRET" in capsys.readouterr().err


def test_issued_tokens_pass_require_role(script, tmp_path, db_session, monkeypatch):
    """Uses TEST- accounts: the real demo accounts are seeded separately (PB-08-6)."""
    db_role_by_api_role = {api: db for db, api in API_ROLE_BY_DB_ROLE.items()}
    accounts = [(f"TEST-{name}", role, None) for name, role, _ in script.ACCOUNTS]
    monkeypatch.setattr(script, "ACCOUNTS", accounts)
    monkeypatch.setattr(script, "POS_ACCOUNT", "TEST-pos_system")
    for username, role in [(name, role) for name, role, _ in accounts] + [("TEST-pos_system", "POS")]:
        db_session.add(StaffUser(username=username, full_name="Test user",
                                 role=db_role_by_api_role[role]))
    db_session.flush()

    test_app = FastAPI()
    register_error_handlers(test_app)
    test_app.dependency_overrides[get_db] = lambda: db_session
    roles = sorted(set(API_ROLE_BY_DB_ROLE.values()))

    @test_app.get("/any")
    def any_role(principal=Depends(require_role(*roles))):
        return asdict(principal)

    client = TestClient(test_app)
    tokens = script.issue_tokens()
    assert len(tokens) == 13
    for name, token in tokens.items():
        response = client.get("/any", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200, name
