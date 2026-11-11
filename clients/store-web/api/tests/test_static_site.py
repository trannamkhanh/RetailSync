"""The SPA fallback: client routes get index.html, unknown API routes get JSON."""

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import static_site
from app.errors import register_error_handlers


@pytest.fixture
def spa_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html><body>spa-shell</body></html>", encoding="utf-8")
    (dist / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")

    monkeypatch.setattr(static_site, "DIST", dist)

    app = FastAPI()
    register_error_handlers(app)
    static_site.mount_spa(app)
    return TestClient(app)


def test_client_route_returns_the_shell(spa_client: TestClient) -> None:
    response = spa_client.get("/stores/STORE-DN1/products/SKU-0001")
    assert response.status_code == 200
    assert "spa-shell" in response.text
    assert response.headers["cache-control"] == "no-cache"


def test_unknown_api_route_is_json_not_the_shell(spa_client: TestClient) -> None:
    response = spa_client.get("/api/unknown")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert body["outcome"] == "REJECTED"
    assert body["code"] == "NOT_FOUND"
    assert "spa-shell" not in response.text


def test_asset_is_served_with_a_long_cache(spa_client: TestClient) -> None:
    response = spa_client.get("/assets/app.js")
    assert response.status_code == 200
    assert "immutable" in response.headers["cache-control"]
