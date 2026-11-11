"""GET /api/stores/{id}/products and its detail route."""

from fastapi.testclient import TestClient


def test_product_page_shape_and_money(seeded_client: TestClient) -> None:
    body = seeded_client.get("/api/stores/WEB-A/products").json()
    assert body["store_id"] == "WEB-A"
    assert body["total"] == 4
    item = next(item for item in body["items"] if item["sku"] == "WEB-P1")
    assert item["unit_price"] == "32000.00"
    assert isinstance(item["unit_price"], str)
    assert item["quantity"] == 60
    assert item["sellable_quantity"] == 40
    assert item["expired_quantity"] == 20
    assert item["nearest_expiry"] == "2026-11-10"
    assert all(isinstance(batch["sellable"], bool) for batch in item["batches"])


def test_total_is_before_pagination(seeded_client: TestClient) -> None:
    page = seeded_client.get("/api/stores/WEB-A/products?limit=1&offset=0").json()
    assert page["total"] == 4
    assert len(page["items"]) == 1

    second = seeded_client.get("/api/stores/WEB-A/products?limit=1&offset=1").json()
    assert second["total"] == 4
    assert second["items"][0]["sku"] != page["items"][0]["sku"]


def test_offset_past_the_end_returns_empty_items(seeded_client: TestClient) -> None:
    body = seeded_client.get("/api/stores/WEB-A/products?offset=99").json()
    assert body["total"] == 4
    assert body["items"] == []


def test_q_searches_name_and_sku(seeded_client: TestClient) -> None:
    by_name = seeded_client.get("/api/stores/WEB-A/products", params={"q": "Sản phẩm Một"}).json()
    assert [item["sku"] for item in by_name["items"]] == ["WEB-P1"]

    by_sku = seeded_client.get("/api/stores/WEB-A/products", params={"q": "WEB-P2"}).json()
    assert [item["sku"] for item in by_sku["items"]] == ["WEB-P2"]


def test_q_escapes_like_wildcards(seeded_client: TestClient) -> None:
    body = seeded_client.get("/api/stores/WEB-A/products", params={"q": "%"}).json()
    assert body["total"] == 0

    body = seeded_client.get("/api/stores/WEB-A/products", params={"q": "_"}).json()
    assert body["total"] == 0


def test_category_filter(seeded_client: TestClient) -> None:
    body = seeded_client.get("/api/stores/WEB-A/products", params={"category": "Dairy"}).json()
    assert {item["sku"] for item in body["items"]} == {"WEB-P1", "WEB-P2"}


def test_in_stock_true_uses_sellable_quantity(seeded_client: TestClient) -> None:
    body = seeded_client.get("/api/stores/WEB-A/products", params={"in_stock": "true"}).json()
    assert [item["sku"] for item in body["items"]] == ["WEB-P1"]


def test_in_stock_false_returns_everything_without_sellable_stock(seeded_client: TestClient) -> None:
    body = seeded_client.get("/api/stores/WEB-A/products", params={"in_stock": "false"}).json()
    # WEB-P2 is fully expired, WEB-P4 and WEB-P3 have no sellable stock at all.
    assert {item["sku"] for item in body["items"]} == {"WEB-P2", "WEB-P3", "WEB-P4"}
    assert body["total"] == 3
    assert all(item["sellable_quantity"] == 0 for item in body["items"])


def test_sort_price_and_sellable(seeded_client: TestClient) -> None:
    by_price = seeded_client.get("/api/stores/WEB-A/products", params={"sort": "price"}).json()
    prices = [float(item["unit_price"]) for item in by_price["items"]]
    assert prices == sorted(prices)

    by_sellable = seeded_client.get(
        "/api/stores/WEB-A/products", params={"sort": "sellable"}
    ).json()
    quantities = [item["sellable_quantity"] for item in by_sellable["items"]]
    assert quantities == sorted(quantities, reverse=True)


def test_invalid_query_parameters_are_422(seeded_client: TestClient) -> None:
    for params in ({"limit": 201}, {"sort": "abc"}, {"q": "x" * 101}, {"offset": -1}):
        response = seeded_client.get("/api/stores/WEB-A/products", params=params)
        assert response.status_code == 422, params
        assert response.json()["code"] == "VALIDATION_ERROR"


def test_sku_without_inventory_is_zero_not_404(seeded_client: TestClient) -> None:
    body = seeded_client.get("/api/stores/WEB-A/products/WEB-P3").json()
    assert body["item"]["sku"] == "WEB-P3"
    assert body["item"]["quantity"] == 0
    assert body["item"]["sellable_quantity"] == 0
    assert body["item"]["expired_quantity"] == 0
    assert body["item"]["nearest_expiry"] is None


def test_include_empty_controls_zero_quantity_batches(seeded_client: TestClient) -> None:
    hidden = seeded_client.get("/api/stores/WEB-A/products/WEB-P4").json()
    assert hidden["item"]["batches"] == []

    shown = seeded_client.get(
        "/api/stores/WEB-A/products/WEB-P4", params={"include_empty": "true"}
    ).json()
    assert [batch["batch_id"] for batch in shown["item"]["batches"]] == ["WEB-B-P4-ZERO"]


def test_unknown_sku_is_404(seeded_client: TestClient) -> None:
    response = seeded_client.get("/api/stores/WEB-A/products/WEB-NOPE")
    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"


def test_categories_are_sorted_and_distinct(seeded_client: TestClient) -> None:
    body = seeded_client.get("/api/categories").json()
    assert body["categories"] == ["Bakery", "Dairy", "Dry goods"]
