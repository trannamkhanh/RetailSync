"""Tests for customer auth and shop APIs (search, suggestions, addresses)."""

import pytest
from fastapi.testclient import TestClient


def test_sample_addresses_list(client: TestClient) -> None:
    res = client.get("/api/shop/addresses")
    assert res.status_code == 200
    addresses = res.json()["addresses"]
    assert len(addresses) >= 3
    assert any("Hải Châu" in a["label"] for a in addresses)


def test_shop_search_requires_coordinates(client: TestClient) -> None:
    res = client.get("/api/shop/search?q=milk")
    assert res.status_code == 422
    assert res.json()["code"] == "VALIDATION_ERROR"


def test_shop_search_suggests_nearest_store_with_stock(seeded_client: TestClient) -> None:
    # WEB-A is at (16.0, 108.0). Query with lat/long right next to it:
    res = seeded_client.get(
        "/api/shop/search",
        params={"q": "Một", "latitude": 16.001, "longitude": 108.001},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["total"] >= 1
    item = next(i for i in data["items"] if i["sku"] == "WEB-P1")
    assert item["nearest"] is not None
    assert item["nearest"]["store_id"] == "WEB-A"
    assert item["nearest"]["sellable_quantity"] == 40
    assert item["nearest"]["distance_km"] < 1.0


def test_shop_search_distance_is_routed_or_flagged(seeded_client: TestClient) -> None:
    """Every suggestion says which kind of distance it carries.

    The test suite never reaches the real routing server: the URL points at a
    closed port, so the API must fall back to the straight-line distance and say
    so instead of returning a wrong ``road`` label.
    """
    res = seeded_client.get(
        "/api/shop/search",
        params={"q": "Một", "latitude": 16.001, "longitude": 108.001},
    )
    assert res.status_code == 200
    item = next(i for i in res.json()["items"] if i["sku"] == "WEB-P1")
    assert item["nearest"]["distance_kind"] == "straight"
    for store in item["stores"]:
        assert store["distance_kind"] in {"road", "straight"}


def test_store_suggestions_carry_the_street_address(seeded_client: TestClient) -> None:
    """The web shows where the store is, so the address travels with the suggestion."""
    res = seeded_client.get(
        "/api/shop/search",
        params={"q": "Một", "latitude": 16.001, "longitude": 108.001},
    )
    item = next(i for i in res.json()["items"] if i["sku"] == "WEB-P1")
    assert "address_text" in item["nearest"]
    assert item["nearest"]["address_text"] is None or isinstance(
        item["nearest"]["address_text"], str
    )


def test_shop_search_skips_stores_without_sellable_stock(seeded_client: TestClient) -> None:
    # WEB-P2 in seeded data has no sellable stock (only expired batch)
    res = seeded_client.get(
        "/api/shop/search",
        params={"q": "Hai", "latitude": 16.0, "longitude": 108.0},
    )
    assert res.status_code == 200
    data = res.json()
    item = next(i for i in data["items"] if i["sku"] == "WEB-P2")
    assert item["nearest"] is None
    assert item["stores"] == []


def test_auth_and_saved_addresses_lifecycle(client: TestClient) -> None:
    # 1. Unauthenticated me
    assert client.get("/api/auth/me").status_code == 401

    # 2. Register
    email = "tester_lifecycle@example.test"
    reg = client.post(
        "/api/auth/register",
        json={"email": email, "full_name": "Nguyen Van Test", "password": "password123"},
    )
    assert reg.status_code == 201
    assert "rts_customer" in reg.cookies
    assert reg.json()["customer"]["email"] == email

    # 3. Duplicate register rejected
    dup = client.post(
        "/api/auth/register",
        json={"email": email, "full_name": "Nguyen Van Test", "password": "password123"},
    )
    assert dup.status_code == 409
    assert dup.json()["code"] == "EMAIL_TAKEN"

    # 4. Authenticated me
    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["customer"]["full_name"] == "Nguyen Van Test"

    # 5. Saved addresses
    empty_addr = client.get("/api/shop/addresses/mine")
    assert empty_addr.status_code == 200
    assert empty_addr.json()["addresses"] == []

    add_res = client.post(
        "/api/shop/addresses/mine",
        json={
            "label": "Nhà riêng",
            "address_text": "123 Đường Test, Đà Nẵng",
            "latitude": 16.05,
            "longitude": 108.20,
        },
    )
    assert add_res.status_code == 201
    addr_id = add_res.json()["address_id"]
    assert add_res.json()["label"] == "Nhà riêng"

    # List saved
    listed = client.get("/api/shop/addresses/mine")
    assert len(listed.json()["addresses"]) == 1

    # Delete saved
    del_res = client.delete(f"/api/shop/addresses/mine/{addr_id}")
    assert del_res.status_code == 204

    listed_after = client.get("/api/shop/addresses/mine")
    assert len(listed_after.json()["addresses"]) == 0

    # 6. Logout
    logout_res = client.post("/api/auth/logout")
    assert logout_res.status_code == 204
    assert client.get("/api/auth/me").status_code == 401

    # 7. Login again
    login_res = client.post(
        "/api/auth/login",
        json={"email": email, "password": "password123"},
    )
    assert login_res.status_code == 200
    assert client.get("/api/auth/me").status_code == 200
