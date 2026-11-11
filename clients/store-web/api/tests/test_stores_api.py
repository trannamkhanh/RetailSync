"""GET /api/stores and GET /api/stores/{store_id}."""

from fastapi.testclient import TestClient


def test_only_active_stores_are_listed(seeded_client: TestClient) -> None:
    body = seeded_client.get("/api/stores").json()
    ids = [store["store_id"] for store in body["stores"]]
    assert "WEB-A" in ids
    assert "WEB-B" in ids
    assert "WEB-C" not in ids


def test_store_counts_and_sellable_units(seeded_client: TestClient) -> None:
    body = seeded_client.get("/api/stores").json()
    store_a = next(store for store in body["stores"] if store["store_id"] == "WEB-A")
    assert store_a["product_count"] == 3
    # WEB-P1 has 15 today + 25 later sellable; WEB-P2 is all expired; WEB-P4 is 0.
    assert store_a["sellable_units"] == 40


def test_store_detail_has_expired_units(seeded_client: TestClient) -> None:
    body = seeded_client.get("/api/stores/WEB-A").json()
    assert body["store_id"] == "WEB-A"
    assert body["name"] == "Cửa hàng Test A"
    assert body["region_id"] == "DN"
    assert body["product_count"] == 3
    assert body["sellable_units"] == 40
    assert body["expired_units"] == 30


def test_unknown_store_is_404(seeded_client: TestClient) -> None:
    response = seeded_client.get("/api/stores/WEB-NONE")
    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"


def test_inactive_store_detail_is_404(seeded_client: TestClient) -> None:
    response = seeded_client.get("/api/stores/WEB-C")
    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"


def test_products_of_inactive_store_is_404(seeded_client: TestClient) -> None:
    response = seeded_client.get("/api/stores/WEB-C/products")
    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"


def test_store_id_outside_pattern_is_422(seeded_client: TestClient) -> None:
    response = seeded_client.get("/api/stores/BAD_ID_TOO_LONG")
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
