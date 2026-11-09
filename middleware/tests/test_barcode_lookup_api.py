"""STF31 barcode lookup: own-store data, role-first validation, no writes."""

from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select

from app.core import clock
from app.core.security import create_token
from app.domain.models import AuditLog, Inventory, Product, ProductBatch, StaffUser, Store
from app.repositories import product_lookup as repository
from tests.pos_test_support import add_batch, add_stock


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
    for role, db_role in [("Staff", "STORE_STAFF"), ("Manager", "STORE_MANAGER"), ("Auditor", "AUDITOR")]:
        username = f"TEST-{role}-{suffix}"
        db_session.add(StaffUser(username=username, full_name=role, role=db_role, store_id=store))
        tokens[role] = create_token(username, role, store_id=store)
    add_stock(db_session, store, sku, 4)
    add_stock(db_session, other, sku, 99)
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
    body = response.json()
    assert {key: value for key, value in body.items() if key != "batches"} == {
        "sku": world[2], "barcode": world[3], "name": "Test product",
        "category": "TEST", "unit_price": 12.5, "quantity": 4,
    }
    assert db_session.get(Inventory, (world[1], world[2])).quantity == 99
    assert not db_session.new and not db_session.dirty and not db_session.deleted
    assert db_session.scalar(select(func.count()).select_from(AuditLog)) == before


def test_stf31_2_unknown_barcode_reads_no_inventory(client, world, monkeypatch):
    def unexpected(*args):
        pytest.fail("Unknown barcode must not query inventory")
    monkeypatch.setattr(repository, "quantity", unexpected)
    monkeypatch.setattr(repository, "batches", unexpected)
    response = lookup(client, world, "TEST-UNKNOWN")
    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"


def test_stf31_3_lists_positive_own_store_batches_by_expiry(client, db_session, world):
    store, _, sku, _, _ = world
    today = clock.today_local()
    expired = today - timedelta(days=1)
    recent = today + timedelta(days=3)
    expired_id = add_stock(db_session, store, sku, 2, expiry_date=expired)
    recent_id = add_stock(db_session, store, sku, 3, expiry_date=recent)
    add_batch(db_session, store, sku, 0, expiry_date=today)
    db_session.commit()

    response = lookup(client, world)

    assert response.status_code == 200
    body = response.json()
    assert body["quantity"] == 9
    assert body["batches"][:2] == [
        {"batch_id": expired_id, "expiry_date": expired.isoformat(), "quantity": 2},
        {"batch_id": recent_id, "expiry_date": recent.isoformat(), "quantity": 3},
    ]
    assert len(body["batches"]) == 3
    assert body["batches"][2]["quantity"] == 4


def test_pb31_barcode_matches_case_exactly(client, world):
    barcode = world[3]
    assert lookup(client, world, barcode).status_code == 200
    response = lookup(client, world, barcode.lower())
    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"


def test_pb31_manager_forbidden_even_with_invalid_barcode(client, world):
    response = lookup(client, world, "invalid_barcode", role="Manager")
    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN"


def test_stf31_4_auditor_is_forbidden(client, world):
    response = lookup(client, world, role="Auditor")
    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN"


def test_stf31_5_missing_token(client, world):
    response = client.get(f"/api/v1/products/barcode/{world[3]}")
    assert response.status_code == 401


def test_pb31_zero_stock_does_not_expose_other_store(client, db_session, world):
    db_session.execute(delete(ProductBatch).where(
        ProductBatch.store_id == world[0], ProductBatch.sku == world[2],
    ))
    db_session.delete(db_session.get(Inventory, (world[0], world[2])))
    db_session.commit()
    response = lookup(client, world)
    assert response.status_code == 200
    assert response.json()["quantity"] == 0
    assert response.json()["batches"] == []


@pytest.mark.parametrize("barcode", [" ", "bad_code", "é", "x" * 31, "bad.code"])
def test_pb31_invalid_barcode(client, world, barcode):
    response = lookup(client, world, barcode)
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert "barcode" in response.json()["message"]


@pytest.mark.parametrize("barcode", ["A", "A" * 30])
def test_pb31_valid_length_boundaries(client, db_session, world, barcode):
    db_session.get(Product, world[2]).barcode = barcode
    db_session.commit()
    assert lookup(client, world, barcode).status_code == 200


def test_pb31_empty_path_has_no_lookup_route(client, world):
    response = client.get("/api/v1/products/barcode/", headers={"Authorization": f"Bearer {world[4]['Staff']}"})
    assert response.status_code == 404
