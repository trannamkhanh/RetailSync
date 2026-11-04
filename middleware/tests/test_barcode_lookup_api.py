"""STF31 barcode lookup: own-store data, role-first validation, no writes."""

from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.core.security import create_token
from app.domain.models import AuditLog, Inventory, Product, StaffUser, Store
from app.repositories import product_lookup as repository


@pytest.fixture
def world(db_session):
    suffix = uuid4().hex[:5].upper()
    store, other, sku, barcode = f"TEST-{suffix}", f"TEST-X{suffix[:4]}", f"TEST-SKU-{suffix}", f"TEST-BC-{suffix}"
    db_session.add_all([
        Store(store_id=store, name="Lookup", latitude=0, longitude=0, region_id="TEST"),
        Store(store_id=other, name="Other", latitude=0, longitude=0, region_id="TEST"),
        Product(sku=sku, barcode=barcode, name="Test product", category="TEST", unit_price=Decimal("12.50")),
    ])
    db_session.flush()
    tokens = {}
    for role, db_role in [("Staff", "STORE_STAFF"), ("Manager", "STORE_MANAGER")]:
        username = f"TEST-{role}-{suffix}"
        db_session.add(StaffUser(username=username, full_name=role, role=db_role, store_id=store))
        tokens[role] = create_token(username, role, store_id=store)
    db_session.add_all([Inventory(store_id=store, sku=sku, quantity=4), Inventory(store_id=other, sku=sku, quantity=99)])
    db_session.commit()
    return store, other, sku, barcode, tokens


def lookup(client, world, barcode=None, role="Staff"):
    return client.get(f"/api/v1/products/barcode/{barcode or world[3]}", headers={"Authorization": f"Bearer {world[4][role]}"})


def test_stf31_1_lookup_returns_own_store_product(client, db_session, world, monkeypatch):
    before = db_session.scalar(select(func.count()).select_from(AuditLog))
    def no_commit():
        pytest.fail("A lookup must not commit")
    monkeypatch.setattr(db_session, "commit", no_commit)
    response = lookup(client, world)
    assert response.status_code == 200, response.text
    assert response.json() == {"sku": world[2], "barcode": world[3], "name": "Test product", "category": "TEST", "unit_price": 12.5, "quantity": 4}
    assert db_session.get(Inventory, (world[1], world[2])).quantity == 99
    assert not db_session.new and not db_session.dirty and not db_session.deleted
    assert db_session.scalar(select(func.count()).select_from(AuditLog)) == before


def test_stf31_2_unknown_barcode_reads_no_inventory(client, world, monkeypatch):
    def unexpected(*args):
        pytest.fail("Unknown barcode must not query inventory")
    monkeypatch.setattr(repository, "quantity", unexpected)
    response = lookup(client, world, "TEST-UNKNOWN")
    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"


def test_stf31_4_manager_forbidden_even_with_invalid_barcode(client, world):
    response = lookup(client, world, "invalid_barcode", role="Manager")
    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN"


def test_stf31_5_missing_token(client, world):
    response = client.get(f"/api/v1/products/barcode/{world[3]}")
    assert response.status_code == 401


def test_stf31_zero_stock_does_not_expose_other_store(client, db_session, world):
    db_session.delete(db_session.get(Inventory, (world[0], world[2])))
    db_session.commit()
    response = lookup(client, world)
    assert response.status_code == 200
    assert response.json()["quantity"] == 0
    assert "batches" not in response.json()


@pytest.mark.parametrize("barcode", [" ", "bad_code", "é", "x" * 31, "bad.code"])
def test_stf31_invalid_barcode(client, world, barcode):
    response = lookup(client, world, barcode)
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert "barcode" in response.json()["message"]


@pytest.mark.parametrize("barcode", ["A", "A" * 30])
def test_stf31_valid_length_boundaries(client, db_session, world, barcode):
    db_session.get(Product, world[2]).barcode = barcode
    db_session.commit()
    assert lookup(client, world, barcode).status_code == 200


def test_stf31_empty_path_has_no_lookup_route(client, world):
    response = client.get("/api/v1/products/barcode/", headers={"Authorization": f"Bearer {world[4]['Staff']}"})
    assert response.status_code == 404
