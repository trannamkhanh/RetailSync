"""Client certificate check behind the POS gateway (PB-48-4, PS48-5, PS48-6).

MTLS_REQUIRED is on here. Certificates are made with openssl in a temporary
directory, never read from .certs/, and their expected fingerprints come from
openssl itself. The POS account is committed for real, as in
test_event_audit.py, so EVENT_REJECTED rows from the separate audit session
can be checked; it is deleted afterwards with its audit rows.
"""

from collections.abc import Generator
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
import subprocess
from urllib.parse import quote
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine, delete, select
from sqlalchemy.orm import Session

from app.core.client_cert import certificate_fingerprint
from app.core.config import settings
from app.core.security import create_token
from app.domain.models import AuditLog, Inventory, PosTerminal, PosTransaction, Product, StaffUser, Store
from app.main import app
from tests.pos_test_support import add_stock


SECRET = "test-only-secret-with-enough-length-for-hs256"
GATEWAY_SECRET = "test-only-gateway-secret"
URL = "/api/v1/pos/events"


def _uid(length: int = 8) -> str:
    return uuid4().hex[:length].upper()


@dataclass(frozen=True)
class Certificate:
    pem: str
    fingerprint: str

    @property
    def header(self) -> str:
        """As nginx forwards it in $ssl_client_escaped_cert: the PEM, URL-escaped."""
        return quote(self.pem, safe="")


def _make_certificate(directory: Path, common_name: str) -> Certificate:
    key, cert = directory / f"{common_name}.key", directory / f"{common_name}.crt"
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "2",
                    "-subj", f"/CN={common_name}", "-keyout", str(key), "-out", str(cert)],
                   check=True, capture_output=True)
    printed = subprocess.run(["openssl", "x509", "-in", str(cert), "-noout", "-fingerprint", "-sha256"],
                             check=True, capture_output=True, text=True).stdout
    fingerprint = printed.strip().split("=", 1)[1].replace(":", "").lower()
    return Certificate(cert.read_text(encoding="ascii"), fingerprint)


@pytest.fixture(scope="module")
def certificates(tmp_path_factory) -> dict[str, Certificate]:
    directory = tmp_path_factory.mktemp("client-certificates")
    return {name: _make_certificate(directory, f"TEST-CC-{name}") for name in ("A", "B", "C")}


@dataclass(frozen=True)
class World:
    store_id: str
    terminals: dict[str, str]
    sku: str
    user_id: int
    username: str

    def token(self, terminal: str) -> str:
        return create_token(self.username, "POS", store_id=self.store_id, pos_id=self.terminals[terminal])


@pytest.fixture(autouse=True)
def mtls_on(monkeypatch):
    monkeypatch.setattr(settings, "jwt_secret", SecretStr(SECRET))
    monkeypatch.setattr(settings, "mtls_required", True)
    monkeypatch.setattr(settings, "pos_gateway_secret", SecretStr(GATEWAY_SECRET))


@pytest.fixture(autouse=True)
def pos_account(test_engine: Engine) -> Generator[StaffUser, None, None]:
    """Committed for real; autouse, so it is torn down after db_session rolls back."""
    with Session(test_engine) as session:
        user = StaffUser(username=f"TEST-CC-{_uid()}", full_name="Client cert POS", role="POS_SYSTEM")
        session.add(user)
        session.commit()
        user_id, username = user.user_id, user.username
    try:
        yield StaffUser(user_id=user_id, username=username)
    finally:
        with Session(test_engine) as session:
            session.execute(delete(AuditLog).where(AuditLog.user_id == user_id))
            session.execute(delete(StaffUser).where(StaffUser.user_id == user_id))
            session.commit()


@pytest.fixture
def world(db_session: Session, pos_account: StaffUser, certificates) -> World:
    """Terminal A holds certificate A, B holds B, and C has no fingerprint."""
    store_id, sku = f"TEST-{_uid(5)}", f"TEST-SKU-{_uid()}"
    terminals = {name: f"TEST-POS-{name}-{_uid(6)}" for name in ("A", "B", "C")}
    db_session.add(Store(store_id=store_id, name="Client cert store", latitude=Decimal("16.000000"),
                         longitude=Decimal("108.000000"), region_id="TEST"))
    db_session.add(Product(sku=sku, barcode=f"BC-{sku}", name="Client cert product",
                           category="TEST", unit_price=Decimal("10.00")))
    db_session.flush()
    for name, pos_id in terminals.items():
        fingerprint = certificates[name].fingerprint if name != "C" else None
        db_session.add(PosTerminal(pos_id=pos_id, store_id=store_id, status="ACTIVE",
                                   cert_fingerprint=fingerprint))
    add_stock(db_session, store_id, sku, 10)
    db_session.commit()
    return World(store_id, terminals, sku, pos_account.user_id, pos_account.username)


def sale(world: World, terminal: str = "A", pos_id: str | None = None) -> dict:
    return {
        "event_type": "SALE", "transaction_id": f"TEST-TXN-{_uid(10)}",
        "store_id": world.store_id, "pos_id": pos_id or world.terminals[terminal],
        "timestamp": "2026-11-14T03:15:00Z",
        "items": [{"sku": world.sku, "quantity": 1, "unit_price": "10.00"}],
    }


def gateway_headers(certificate: Certificate | None = None, secret: str | None = GATEWAY_SECRET,
                    token: str | None = None) -> dict[str, str]:
    headers = {}
    if secret is not None:
        headers["X-Gateway-Secret"] = secret
    if certificate is not None:
        headers["X-Client-Cert"] = certificate.header
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def assert_forbidden(response) -> None:
    assert response.status_code == 403, response.text
    assert response.json()["outcome"] == "REJECTED"
    assert response.json()["code"] == "FORBIDDEN"


def rejections(db_session: Session, world: World) -> list[tuple[str, str | None]]:
    query = select(AuditLog.entity_key, AuditLog.details).where(
        AuditLog.user_id == world.user_id, AuditLog.action == "EVENT_REJECTED")
    return [(key, details.split(":", 1)[0]) for key, details in db_session.execute(query)]


def stock(db_session: Session, world: World) -> int:
    db_session.expire_all()
    return db_session.get(Inventory, (world.store_id, world.sku)).quantity


# PS48-6 and PS48-5


def test_ps48_6_valid_certificate_and_token_succeed(client, db_session, world, certificates):
    response = client.post(URL, json=sale(world), headers=gateway_headers(certificates["A"], token=world.token("A")))

    assert response.status_code == 200, response.text
    assert response.json()["outcome"] == "OK"
    assert stock(db_session, world) == 9


def test_ps48_5_certificate_of_another_pos_is_refused(client, db_session, world, certificates):
    body = sale(world, "A")

    response = client.post(URL, json=body, headers=gateway_headers(certificates["B"], token=world.token("A")))

    assert_forbidden(response)
    assert stock(db_session, world) == 10
    assert db_session.get(PosTransaction, body["transaction_id"]) is None
    assert rejections(db_session, world) == [(body["transaction_id"], "FORBIDDEN")]


def test_pb48_4_terminal_without_fingerprint_is_refused(client, db_session, world, certificates):
    body = sale(world, "C")

    response = client.post(URL, json=body, headers=gateway_headers(certificates["C"], token=world.token("C")))

    assert_forbidden(response)
    assert rejections(db_session, world) == [(body["transaction_id"], "FORBIDDEN")]


def test_pb48_4_unregistered_terminal_is_refused(client, db_session, world, certificates, pos_account):
    unknown = f"TEST-POS-X-{_uid(6)}"
    token = create_token(pos_account.username, "POS", store_id=world.store_id, pos_id=unknown)
    body = sale(world, pos_id=unknown)

    response = client.post(URL, json=body, headers=gateway_headers(certificates["A"], token=token))

    assert_forbidden(response)
    assert rejections(db_session, world) == [(body["transaction_id"], "FORBIDDEN")]


def test_pb48_4_certificate_check_follows_field_validation(client, db_session, world, certificates):
    body = sale(world, "A")
    del body["timestamp"]

    response = client.post(URL, json=body, headers=gateway_headers(certificates["B"], token=world.token("A")))

    assert (response.status_code, response.json()["code"]) == (422, "INVALID_EVENT")


# Gateway headers: checked before the token, and never audited


@pytest.mark.parametrize("secret", [None, "", "wrong-secret", GATEWAY_SECRET[:-1], GATEWAY_SECRET + "x",
                                    GATEWAY_SECRET.upper()],
                         ids=["missing", "empty", "wrong", "shorter", "longer", "other-case"])
def test_pb48_4_missing_or_wrong_gateway_secret_is_refused(client, db_session, world, certificates, secret):
    response = client.post(URL, json=sale(world), headers=gateway_headers(certificates["A"], secret,
                                                                          world.token("A")))

    assert_forbidden(response)
    assert stock(db_session, world) == 10
    assert rejections(db_session, world) == []


@pytest.mark.parametrize("header", [None, "", "not-a-certificate", quote("-----BEGIN CERTIFICATE-----\n"),
                                    quote("-----BEGIN CERTIFICATE-----\nÄÖ\n-----END CERTIFICATE-----\n")],
                         ids=["missing", "empty", "not-pem", "no-footer", "non-ascii"])
def test_pb48_4_missing_or_malformed_certificate_is_refused(client, db_session, world, header):
    headers = gateway_headers(token=world.token("A"))
    if header is not None:
        headers["X-Client-Cert"] = header

    response = client.post(URL, json=sale(world), headers=headers)

    assert_forbidden(response)
    assert rejections(db_session, world) == []


def test_pb48_4_gateway_check_runs_before_the_token(client, world):
    response = client.post(URL, json=sale(world), headers=gateway_headers(secret=None))

    assert_forbidden(response)


def test_pb48_4_token_is_still_required_behind_the_gateway(client, world, certificates):
    response = client.post(URL, json=sale(world), headers=gateway_headers(certificates["A"]))

    assert response.status_code == 401


def test_pb48_4_missing_gateway_secret_setting_fails_closed(db_session, world, certificates, monkeypatch):
    monkeypatch.setattr(settings, "pos_gateway_secret", None)
    from app.core.db import get_db
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        response = TestClient(app, raise_server_exceptions=False).post(
            URL, json=sale(world), headers=gateway_headers(certificates["A"], "", world.token("A")))
    finally:
        app.dependency_overrides.pop(get_db)

    assert (response.status_code, response.json()["code"]) == (503, "SERVICE_UNAVAILABLE")


def test_pb48_4_headers_are_ignored_with_mtls_off(client, db_session, world, monkeypatch):
    monkeypatch.setattr(settings, "mtls_required", False)

    response = client.post(URL, json=sale(world, "C"), headers={"Authorization": f"Bearer {world.token('C')}"})

    assert response.json()["outcome"] == "OK"


# Fingerprint


def test_pb48_5_fingerprint_matches_openssl(certificates):
    for certificate in certificates.values():
        assert certificate_fingerprint(certificate.pem) == certificate.fingerprint
