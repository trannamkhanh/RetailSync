"""Standard error body, on a test-only app and on the real one."""

import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.core.errors import ApiError, register_error_handlers
from app.main import app as main_app


class Line(BaseModel):
    sku: str


class Sale(BaseModel):
    store_id: str
    items: list[Line]


error_app = FastAPI()
register_error_handlers(error_app)


@error_app.get("/rejected")
def rejected():
    raise ApiError(409, "INSUFFICIENT_STOCK", "Not enough stock.")


@error_app.get("/retryable")
def retryable():
    raise ApiError(503, "HQ_DOWN", "Try later.", outcome="ERROR")


@error_app.get("/crash")
def crash():
    raise RuntimeError("secret internal detail")


@error_app.post("/sales")
def create_sale(sale: Sale):
    return sale


@error_app.get("/items/{item_id}")
def get_item(item_id: int):
    return item_id


@pytest.fixture
def errors() -> TestClient:
    return TestClient(error_app, raise_server_exceptions=False)


def test_api_error_returns_status_and_standard_body(errors):
    response = errors.get("/rejected")

    assert response.status_code == 409
    assert response.json() == {
        "outcome": "REJECTED", "code": "INSUFFICIENT_STOCK", "message": "Not enough stock.",
    }


def test_api_error_keeps_explicit_outcome(errors):
    response = errors.get("/retryable")

    assert response.status_code == 503
    assert response.json()["outcome"] == "ERROR"


def test_validation_error_names_first_invalid_field(errors):
    response = errors.post("/sales", json={"items": []})

    assert response.status_code == 422
    body = response.json()
    assert set(body) == {"outcome", "code", "message"}
    assert (body["outcome"], body["code"]) == ("REJECTED", "VALIDATION_ERROR")
    assert "store_id" in body["message"]


def test_validation_error_names_nested_field(errors):
    response = errors.post("/sales", json={"store_id": "S1", "items": [{}]})

    assert response.status_code == 422
    assert "items.0.sku" in response.json()["message"]


def test_validation_error_names_path_parameter(errors):
    response = errors.get("/items/abc")

    assert response.status_code == 422
    assert "item_id" in response.json()["message"]


def test_malformed_json_is_reported_as_body(errors):
    response = errors.post("/sales", content="{", headers={"Content-Type": "application/json"})

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert "'body'" in response.json()["message"]


def test_unhandled_exception_is_logged_and_hides_details(errors, caplog):
    with caplog.at_level(logging.ERROR, logger="app.core.errors"):
        response = errors.get("/crash")

    assert response.status_code == 503
    body = response.json()
    assert set(body) == {"outcome", "code", "message"}
    assert (body["outcome"], body["code"]) == ("ERROR", "SERVICE_UNAVAILABLE")
    assert "secret internal detail" not in response.text
    assert any(record.exc_info for record in caplog.records)


def test_unknown_route_uses_standard_body_on_main_app():
    response = TestClient(main_app).get("/api/v1/no-such-route")

    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"
    assert response.json()["outcome"] == "REJECTED"


def test_main_app_maps_unhandled_exceptions_to_503():
    assert Exception in main_app.exception_handlers


def test_wrong_method_uses_standard_body(errors):
    response = errors.delete("/rejected")

    assert response.status_code == 405
    assert set(response.json()) == {"outcome", "code", "message"}
