"""HQ client (PB-15-3). Every test injects an httpx.MockTransport; none needs the real HQ."""

from datetime import datetime, timezone
from decimal import Decimal
import json

import httpx
import jwt
import pytest
from pydantic import SecretStr, ValidationError

from app.core.config import Settings, settings
from app.integration import hq_client
from app.integration.hq_client import HqConfigError, send_batch


HQ_SECRET = "test-only-hq-secret-with-enough-length-for-hs256"
MESSAGE = {
    "batch_id": "SB-TEST-S1-20261114010203",
    "store_id": "TEST-S1",
    "created_at": "2026-11-14T01:02:03Z",
    "txn_count": 3,
    "lines": [
        {"sku": "TEST-SKU-A", "sold_qty": 2, "returned_qty": 0, "net_revenue": Decimal("20.10")},
        {"sku": "TEST-SKU-B", "sold_qty": 1, "returned_qty": 1, "net_revenue": Decimal("0.00")},
    ],
}


class FakeHq:
    """Records each request and answers with the response it was given."""

    def __init__(self, respond) -> None:
        self.respond = respond
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.respond(request)


@pytest.fixture(autouse=True)
def hq_settings(monkeypatch):
    monkeypatch.setattr(settings, "hq_url", "https://hq.test/api/v1")
    monkeypatch.setattr(settings, "hq_jwt_secret", SecretStr(HQ_SECRET))
    monkeypatch.setattr(settings, "hq_timeout_seconds", 3.0)


def install(monkeypatch, respond) -> FakeHq:
    fake = FakeHq(respond)
    monkeypatch.setattr(hq_client, "transport", httpx.MockTransport(fake))
    return fake


def ack(duplicate: bool = False, batch_id: str = MESSAGE["batch_id"]):
    return lambda request: httpx.Response(200, json={"status": "ACK", "batch_id": batch_id, "duplicate": duplicate})


def nack(status: int, code: str, message: str = "No."):
    return lambda request: httpx.Response(status, json={
        "status": "NACK", "batch_id": MESSAGE["batch_id"], "code": code, "message": message})


# The request


def test_pb15_3_posts_the_message_to_hq_sync_with_the_service_token(monkeypatch):
    fake = install(monkeypatch, ack())

    send_batch(MESSAGE)

    request = fake.requests[0]
    assert (request.method, str(request.url)) == ("POST", "https://hq.test/api/v1/sync")
    assert request.headers["content-type"] == "application/json"
    token = request.headers["authorization"].removeprefix("Bearer ")
    claims = jwt.decode(token, HQ_SECRET, algorithms=["HS256"])
    assert (claims["sub"], claims["role"]) == ("rts-middleware", "MIDDLEWARE")
    assert 0 < claims["exp"] - datetime.now(timezone.utc).timestamp() <= 300


def test_pb15_3_body_is_compact_json_with_exact_two_decimal_revenue(monkeypatch):
    fake = install(monkeypatch, ack())

    result = send_batch(MESSAGE)

    body = fake.requests[0].content
    assert b" " not in body
    assert b'"net_revenue":20.10' in body and b'"net_revenue":0.00' in body
    parsed = json.loads(body, parse_float=Decimal)
    assert parsed["lines"][0]["net_revenue"] == Decimal("20.10")
    assert parsed["txn_count"] == 3
    assert result.payload_bytes == len(body)


def test_pb15_3_uses_the_configured_timeout(monkeypatch):
    fake = install(monkeypatch, ack())
    monkeypatch.setattr(settings, "hq_timeout_seconds", 1.5)

    send_batch(MESSAGE)

    timeout = fake.requests[0].extensions["timeout"]
    assert timeout["connect"] == timeout["read"] == 1.5


def test_pb15_3_trailing_slash_in_hq_url_is_tolerated(monkeypatch):
    fake = install(monkeypatch, ack())
    monkeypatch.setattr(settings, "hq_url", "https://hq.test/api/v1/")

    send_batch(MESSAGE)

    assert str(fake.requests[0].url) == "https://hq.test/api/v1/sync"


# The answer


def test_pb15_3_ack(monkeypatch):
    install(monkeypatch, ack())

    result = send_batch(MESSAGE)

    assert (result.kind, result.duplicate) == ("ACK", False)


def test_pb15_3_duplicate_ack(monkeypatch):
    install(monkeypatch, ack(duplicate=True))

    result = send_batch(MESSAGE)

    assert (result.kind, result.duplicate) == ("ACK", True)


@pytest.mark.parametrize(("status", "code"), [
    (409, "CONFLICT"), (422, "INVALID_BATCH"), (503, "HQ_OFFLINE"), (500, "HQ_ERROR"),
    (500, "ACK_DROPPED"), (401, "UNAUTHORIZED"),
])
def test_pb15_3_nack_keeps_status_and_code(monkeypatch, status, code):
    install(monkeypatch, nack(status, code, "HQ said no."))

    result = send_batch(MESSAGE)

    assert (result.kind, result.status, result.code) == ("NACK", status, code)
    assert result.message == "HQ said no."
    assert result.payload_bytes > 0


def test_pb15_3_answer_without_a_nack_body_uses_the_http_status(monkeypatch):
    install(monkeypatch, lambda request: httpx.Response(502, text="<html>Bad gateway</html>"))

    result = send_batch(MESSAGE)

    assert (result.kind, result.status, result.code) == ("NACK", 502, "HTTP_502")


@pytest.mark.parametrize("respond", [
    lambda request: httpx.Response(200, text="not json"),
    lambda request: httpx.Response(200, json={"status": "ACK", "batch_id": "SB-OTHER", "duplicate": False}),
    lambda request: httpx.Response(200, json={"status": "ACK", "batch_id": MESSAGE["batch_id"]}),
    lambda request: httpx.Response(200, json={"status": "ACK", "batch_id": MESSAGE["batch_id"], "duplicate": "no"}),
    lambda request: httpx.Response(200, json=["ACK"]),
], ids=["not-json", "other-batch", "no-duplicate", "duplicate-not-bool", "array"])
def test_pb15_3_a_200_that_is_not_an_ack_of_this_batch_is_not_an_ack(monkeypatch, respond):
    install(monkeypatch, respond)

    result = send_batch(MESSAGE)

    assert (result.kind, result.status, result.code) == ("NACK", 200, "UNEXPECTED_ANSWER")


@pytest.mark.parametrize("error", [httpx.ReadTimeout("slow"), httpx.ConnectTimeout("slow"),
                                   httpx.ConnectError("refused"), httpx.RemoteProtocolError("dropped")],
                         ids=["read-timeout", "connect-timeout", "connect-error", "protocol-error"])
def test_pb15_3_timeout_or_connection_error_is_no_answer(monkeypatch, error):
    def fail(request):
        raise error

    install(monkeypatch, fail)

    result = send_batch(MESSAGE)

    assert (result.kind, result.status, result.code) == ("NO_ANSWER", None, None)
    assert result.message
    assert result.payload_bytes > 0


def test_pb15_3_describe_fits_last_error():
    result = hq_client.HqResult("NACK", status=409, code="CONFLICT", message="x" * 500)

    assert result.describe().startswith("409 CONFLICT: x")
    assert len(result.describe()) <= 200


# Configuration


@pytest.mark.parametrize("secret", [None, SecretStr(""), SecretStr("   ")], ids=["missing", "empty", "blank"])
def test_pb15_3_refuses_to_send_without_a_service_secret(monkeypatch, secret):
    fake = install(monkeypatch, ack())
    monkeypatch.setattr(settings, "hq_jwt_secret", secret)

    with pytest.raises(HqConfigError, match="HQ_JWT_SECRET"):
        send_batch(MESSAGE)
    assert fake.requests == []


def test_pb15_3_tls_is_verified_against_the_configured_ca(monkeypatch):
    monkeypatch.setattr(settings, "hq_ca_file", "/certs/ca.crt")
    assert hq_client.tls_verify() == "/certs/ca.crt"

    monkeypatch.setattr(settings, "hq_ca_file", None)
    assert hq_client.tls_verify() is True


def test_pb15_3_settings_defaults(monkeypatch):
    for name in ("HQ_CA_FILE", "HQ_JWT_SECRET", "HQ_TIMEOUT_SECONDS"):
        monkeypatch.delenv(name, raising=False)

    defaults = Settings(_env_file=None)

    assert (defaults.hq_ca_file, defaults.hq_jwt_secret, defaults.hq_timeout_seconds) == (None, None, 3)


@pytest.mark.parametrize("value", [0, -1, "abc"])
def test_pb15_3_timeout_must_be_positive(value):
    with pytest.raises(ValidationError, match="hq_timeout_seconds"):
        Settings(_env_file=None, hq_timeout_seconds=value)
