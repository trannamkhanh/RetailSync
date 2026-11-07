"""Registration API on real SQL Server: DS-04 paths, roles, duplicates and validation."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import jwt
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import create_token
from app.domain.models import AuditLog, PosTerminal, StaffUser, Store


SECRET = "test-only-secret-with-enough-length-for-hs256"
ADMIN = "TEST-registry-admin"
STORE_ID = "TEST-REG1"
POS_ID = "TEST-POS-REG1"
FINGERPRINT = "a" * 64
STORES = "/api/v1/admin/stores"
TERMINALS = "/api/v1/admin/pos-terminals"


@pytest.fixture(autouse=True)
def jwt_secret(monkeypatch):
    monkeypatch.setattr(settings, "jwt_secret", SecretStr(SECRET))


def account(session: Session, username: str, role: str, store_id: str | None = None) -> StaffUser:
    user = StaffUser(username=username, full_name="Registry test account", role=role, store_id=store_id)
    session.add(user)
    session.flush()
    return user


@pytest.fixture
def admin(db_session: Session) -> StaffUser:
    return account(db_session, ADMIN, "ADMIN")


@pytest.fixture
def admin_token(admin: StaffUser) -> str:
    return create_token(ADMIN, "Admin")


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def store_payload(**overrides) -> dict:
    payload = {
        "store_id": STORE_ID,
        "name": "Test store",
        "latitude": 16.0678,
        "longitude": 108.2208,
        "region_id": "TEST",
    }
    payload.update(overrides)
    return payload


def terminal_payload(**overrides) -> dict:
    payload = {"pos_id": POS_ID, "store_id": STORE_ID}
    payload.update(overrides)
    return payload


def register_store(client: TestClient, token: str, **overrides):
    return client.post(STORES, json=store_payload(**overrides), headers=bearer(token))


def register_terminal(client: TestClient, token: str, **overrides):
    return client.post(TERMINALS, json=terminal_payload(**overrides), headers=bearer(token))


def count(session: Session, model, *where) -> int:
    session.flush()
    return session.scalar(select(func.count()).select_from(model).where(*where))


def terminal_rows(session: Session) -> int:
    """Seed data belongs to other ids; a test only ever owns its TEST- rows."""
    return count(session, PosTerminal, PosTerminal.pos_id.like("TEST-%"))


def audits(session: Session, entity_key: str) -> list[AuditLog]:
    session.flush()
    return list(session.scalars(select(AuditLog).where(AuditLog.entity_key == entity_key)))


def assert_error(response, status: int, code: str) -> dict:
    assert response.status_code == status
    body = response.json()
    assert set(body) == {"outcome", "code", "message"}
    assert body["code"] == code
    return body


# --- stores: success -------------------------------------------------------


def test_create_store_returns_201_with_the_created_resource(client, admin_token, db_session):
    response = register_store(client, admin_token)

    assert response.status_code == 201
    assert response.json() == {
        "store_id": STORE_ID, "name": "Test store", "latitude": 16.0678,
        "longitude": 108.2208, "region_id": "TEST", "is_active": True,
    }
    row = db_session.get(Store, STORE_ID)
    assert (row.name, row.region_id, row.is_active) == ("Test store", "TEST", True)
    assert (float(row.latitude), float(row.longitude)) == (16.0678, 108.2208)


def test_create_store_honours_is_active(client, admin_token, db_session):
    response = register_store(client, admin_token, is_active=False)

    assert response.status_code == 201
    assert response.json()["is_active"] is False
    assert db_session.get(Store, STORE_ID).is_active is False


@pytest.mark.parametrize("latitude,longitude", [(90, 180), (-90, -180), (0, 0)],
                         ids=["max", "min", "zero"])
def test_store_coordinates_accept_the_boundaries(client, admin_token, db_session,
                                                 latitude, longitude):
    response = register_store(client, admin_token, latitude=latitude, longitude=longitude)

    assert response.status_code == 201
    assert (response.json()["latitude"], response.json()["longitude"]) == (latitude, longitude)


def test_store_coordinates_accept_six_decimal_places(client, admin_token, db_session):
    response = register_store(client, admin_token, latitude=89.999999, longitude=-108.220812)

    assert response.status_code == 201
    assert (response.json()["latitude"], response.json()["longitude"]) == (89.999999, -108.220812)
    row = db_session.get(Store, STORE_ID)
    assert (row.latitude, row.longitude) == (Decimal("89.999999"), Decimal("-108.220812"))


def test_ids_accept_letters_digits_hyphen_and_underscore(client, admin_token, db_session):
    response = register_store(client, admin_token, store_id="DN_1-A", region_id="DN-1_A",
                              name="Cửa hàng 1")

    assert response.status_code == 201
    assert (response.json()["store_id"], response.json()["region_id"]) == ("DN_1-A", "DN-1_A")
    row = db_session.get(Store, "DN_1-A")
    assert (row.name, row.region_id) == ("Cửa hàng 1", "DN-1_A")


def test_created_store_is_audited_in_the_same_transaction(client, admin_token, admin, db_session):
    register_store(client, admin_token)

    rows = audits(db_session, STORE_ID)
    assert len(rows) == 1
    assert (rows[0].action, rows[0].entity_name) == ("STORE_REGISTERED", "store")
    assert rows[0].user_id == admin.user_id
    assert rows[0].created_at is not None


# --- stores: errors --------------------------------------------------------


def test_create_store_without_a_token_returns_401(client, db_session):
    response = client.post(STORES, json=store_payload())

    body = assert_error(response, 401, "UNAUTHORIZED")
    assert body["outcome"] == "REJECTED"
    assert count(db_session, Store, Store.store_id == STORE_ID) == 0


def test_create_store_with_an_expired_token_returns_401(client, admin):
    expired = jwt.encode(
        {"sub": ADMIN, "role": "Admin", "store_id": None, "pos_id": None,
         "exp": datetime.now(timezone.utc) - timedelta(minutes=1)},
        SECRET, algorithm="HS256",
    )

    assert_error(client.post(STORES, json=store_payload(), headers=bearer(expired)),
                 401, "UNAUTHORIZED")


@pytest.mark.parametrize("role,profile", [
    ("Staff", "STORE_STAFF"),
    ("Manager", "STORE_MANAGER"),
    ("HQ", "HQ_OPERATOR"),
    ("Auditor", "AUDITOR"),
    ("POS", "POS_SYSTEM"),
])
def test_only_the_admin_role_may_register_stores(client, db_session, role, profile):
    username = f"TEST-{role.lower()}-store"
    account(db_session, username, profile)
    token = create_token(username, role)

    response = client.post(STORES, json=store_payload(), headers=bearer(token))

    body = assert_error(response, 403, "FORBIDDEN")
    assert body["outcome"] == "REJECTED"
    assert count(db_session, Store, Store.store_id == STORE_ID) == 0


def test_duplicate_store_id_returns_409_and_writes_nothing_else(client, admin_token, db_session):
    assert register_store(client, admin_token).status_code == 201

    response = register_store(client, admin_token, name="Second name")

    body = assert_error(response, 409, "ALREADY_EXISTS")
    assert "TEST-REG1" in body["message"]
    assert count(db_session, Store, Store.store_id == STORE_ID) == 1
    assert len(audits(db_session, STORE_ID)) == 1
    assert db_session.get(Store, STORE_ID).name == "Test store"


def test_store_registration_race_returns_409(client, admin_token, db_session, monkeypatch):
    assert register_store(client, admin_token).status_code == 201
    monkeypatch.setattr("app.services.registry.repository.find_store",
                        lambda session, store_id: None)

    response = register_store(client, admin_token)

    assert_error(response, 409, "ALREADY_EXISTS")
    assert count(db_session, Store, Store.store_id == STORE_ID) == 1
    assert len(audits(db_session, STORE_ID)) == 1


@pytest.mark.parametrize("overrides,field", [
    ({"store_id": "X" * 11}, "store_id"),
    ({"store_id": None}, "store_id"),
    ({"store_id": ""}, "store_id"),
    ({"store_id": "STORE 1"}, "store_id"),
    ({"store_id": "STORE.1"}, "store_id"),
    ({"store_id": "STORE\x00"}, "store_id"),
    ({"store_id": "日本語"}, "store_id"),
    ({"name": "x" * 101}, "name"),
    ({"name": ""}, "name"),
    ({"latitude": 90.0001}, "latitude"),
    ({"latitude": -90.0001}, "latitude"),
    ({"latitude": 89.9999999}, "latitude"),
    ({"longitude": 180.0001}, "longitude"),
    ({"longitude": -180.0001}, "longitude"),
    ({"longitude": 108.1234567}, "longitude"),
    ({"region_id": "R" * 11}, "region_id"),
    ({"region_id": ""}, "region_id"),
    ({"region_id": "DN 1"}, "region_id"),
    ({"region_id": "ĐN"}, "region_id"),
    ({"latitude": "north"}, "latitude"),
])
def test_invalid_store_input_returns_422_naming_the_field(client, admin_token, db_session,
                                                          overrides, field):
    response = register_store(client, admin_token, **overrides)

    body = assert_error(response, 422, "VALIDATION_ERROR")
    assert body["outcome"] == "REJECTED"
    assert field in body["message"]
    assert count(db_session, Store, Store.store_id == STORE_ID) == 0


def test_pb08_fifty_emoji_in_a_store_name_are_accepted(client, admin_token, db_session):
    name = "\U0001F600" * 50

    response = register_store(client, admin_token, name=name)

    assert response.status_code == 201, response.text
    assert response.json()["name"] == name
    assert count(db_session, Store, Store.store_id == STORE_ID) == 1


def test_pb08_a_fifty_first_emoji_returns_422_naming_name(client, admin_token, db_session):
    response = register_store(client, admin_token, name="\U0001F600" * 51)

    body = assert_error(response, 422, "VALIDATION_ERROR")
    assert "name" in body["message"]
    assert count(db_session, Store, Store.store_id == STORE_ID) == 0


def test_pb08_one_hundred_ascii_characters_still_fit_a_store_name(client, admin_token, db_session):
    name = "x" * 100

    response = register_store(client, admin_token, name=name)

    assert response.status_code == 201, response.text
    assert response.json()["name"] == name


def test_missing_store_field_returns_422(client, admin_token):
    payload = store_payload()
    del payload["store_id"]

    body = assert_error(client.post(STORES, json=payload, headers=bearer(admin_token)),
                        422, "VALIDATION_ERROR")
    assert "store_id" in body["message"]


def test_malformed_store_body_returns_422(client, admin_token):
    response = client.post(STORES, content="{", headers={**bearer(admin_token),
                                                         "Content-Type": "application/json"})

    assert_error(response, 422, "VALIDATION_ERROR")


# --- POS terminals: success ------------------------------------------------


@pytest.fixture
def store(client, admin_token) -> str:
    assert register_store(client, admin_token).status_code == 201
    return STORE_ID


def test_create_terminal_returns_201_with_the_created_resource(client, admin_token, store, db_session):
    response = register_terminal(client, admin_token)

    assert response.status_code == 201
    assert response.json() == {
        "pos_id": POS_ID, "store_id": STORE_ID, "cert_fingerprint": None, "status": "ACTIVE",
    }
    row = db_session.get(PosTerminal, POS_ID)
    assert (row.store_id, row.status, row.cert_fingerprint) == (STORE_ID, "ACTIVE", None)
    assert row.registered_at is not None


def test_certificate_fingerprint_is_optional_and_unique(client, admin_token, store, db_session):
    response = register_terminal(client, admin_token, cert_fingerprint=FINGERPRINT)

    assert response.status_code == 201
    assert response.json()["cert_fingerprint"] == FINGERPRINT
    assert db_session.get(PosTerminal, POS_ID).cert_fingerprint == FINGERPRINT

    duplicate = register_terminal(client, admin_token, pos_id="TEST-POS-REG2",
                                  cert_fingerprint=FINGERPRINT)

    body = assert_error(duplicate, 409, "ALREADY_EXISTS")
    assert "fingerprint" in body["message"].lower()
    assert terminal_rows(db_session) == 1


def test_terminal_status_inactive_is_accepted(client, admin_token, store, db_session):
    response = register_terminal(client, admin_token, status="INACTIVE")

    assert response.status_code == 201
    assert response.json()["status"] == "INACTIVE"
    assert db_session.get(PosTerminal, POS_ID).status == "INACTIVE"


def test_created_terminal_is_audited(client, admin_token, store, admin, db_session):
    register_terminal(client, admin_token)

    rows = audits(db_session, POS_ID)
    assert len(rows) == 1
    assert (rows[0].action, rows[0].entity_name) == ("POS_REGISTERED", "pos_terminal")
    assert rows[0].user_id == admin.user_id


# --- POS terminals: errors -------------------------------------------------


def test_terminal_for_an_unknown_store_returns_404(client, admin_token, db_session):
    response = register_terminal(client, admin_token)

    body = assert_error(response, 404, "NOT_FOUND")
    assert STORE_ID in body["message"]
    assert terminal_rows(db_session) == 0
    assert audits(db_session, POS_ID) == []


def test_duplicate_pos_id_returns_409(client, admin_token, store, db_session):
    assert register_terminal(client, admin_token).status_code == 201

    response = register_terminal(client, admin_token)

    assert_error(response, 409, "ALREADY_EXISTS")
    assert terminal_rows(db_session) == 1
    assert len(audits(db_session, POS_ID)) == 1


def test_terminal_registration_race_returns_409(client, admin_token, store, db_session, monkeypatch):
    assert register_terminal(client, admin_token).status_code == 201
    monkeypatch.setattr("app.services.registry.repository.find_pos_terminal",
                        lambda session, pos_id: None)

    response = register_terminal(client, admin_token)

    assert_error(response, 409, "ALREADY_EXISTS")
    assert terminal_rows(db_session) == 1
    assert len(audits(db_session, POS_ID)) == 1


def test_terminal_without_a_token_returns_401(client, store, db_session):
    response = client.post(TERMINALS, json=terminal_payload())

    assert_error(response, 401, "UNAUTHORIZED")
    assert terminal_rows(db_session) == 0


def test_only_the_admin_role_may_register_terminals(client, db_session, store):
    username = "TEST-staff-terminal"
    account(db_session, username, "STORE_STAFF", STORE_ID)

    response = client.post(TERMINALS, json=terminal_payload(),
                           headers=bearer(create_token(username, "Staff", STORE_ID)))

    assert_error(response, 403, "FORBIDDEN")
    assert terminal_rows(db_session) == 0


@pytest.mark.parametrize("overrides,field", [
    ({"pos_id": "P" * 21}, "pos_id"),
    ({"pos_id": None}, "pos_id"),
    ({"pos_id": ""}, "pos_id"),
    ({"pos_id": "POS 1"}, "pos_id"),
    ({"pos_id": "POS.1"}, "pos_id"),
    ({"pos_id": "日本語"}, "pos_id"),
    ({"store_id": "S" * 11}, "store_id"),
    ({"store_id": ""}, "store_id"),
    ({"store_id": "STORE 1"}, "store_id"),
    ({"store_id": "STORE\x00"}, "store_id"),
    ({"store_id": "STORE-ĐN1"}, "store_id"),
    ({"cert_fingerprint": "A" * 64}, "cert_fingerprint"),
    ({"cert_fingerprint": "a" * 63}, "cert_fingerprint"),
    ({"cert_fingerprint": "g" * 64}, "cert_fingerprint"),
    ({"status": "DOWN"}, "status"),
    ({"pos_id": 42}, "pos_id"),
])
def test_invalid_terminal_input_returns_422_naming_the_field(client, admin_token, store,
                                                            db_session, overrides, field):
    response = register_terminal(client, admin_token, **overrides)

    body = assert_error(response, 422, "VALIDATION_ERROR")
    assert field in body["message"]
    assert terminal_rows(db_session) == 0
