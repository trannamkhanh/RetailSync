"""Cross-store stock lookup (PB-35, STF35-1 to STF35-7).

Every test creates its own stores, product and batches with ``TEST-`` ids and
commits inside the ``db_session`` savepoint, which the fixture rolls back, so
nothing stays behind. The lookup is read-only, so no cleanup is needed.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import delete, select, update

from app.core import clock
from app.core.config import settings
from app.core.security import create_token
from app.domain.models import Inventory, Product, ProductBatch, StaffUser, Store
from app.services.cross_store import EARTH_RADIUS_KM, haversine_km
from tests.pos_test_support import add_stock

TODAY = date(2026, 11, 14)
SECRET = "test-only-secret-with-enough-length-for-hs256"
URL = "/api/v1/products/barcode/{barcode}/stock"


def _uid(length: int = 5) -> str:
    return uuid4().hex[:length].upper()


@pytest.fixture(autouse=True)
def business_date(monkeypatch) -> None:
    monkeypatch.setattr(clock, "today_local", lambda: TODAY)


@pytest.fixture(autouse=True)
def jwt_secret(monkeypatch) -> None:
    monkeypatch.setattr(settings, "jwt_secret", SecretStr(SECRET))


class World:
    """The caller's store plus the other stores of the same Middleware."""

    def __init__(self, store_id: str, sku: str, barcode: str,
                 stores: dict[str, Store], token: str) -> None:
        self.store_id = store_id
        self.sku = sku
        self.barcode = barcode
        self.stores = stores
        self.token = token

    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    def other_stores(self) -> set[str]:
        return {store.store_id for name, store in self.stores.items() if name != "origin"}


def _add_store(session, store_id: str, latitude: str, longitude: str,
               *, is_active: bool = True) -> Store:
    store = Store(store_id=store_id, name=f"Store {store_id}", latitude=Decimal(latitude),
                  longitude=Decimal(longitude), region_id="TEST", is_active=is_active)
    session.add(store)
    session.flush()
    return store


def _make_world(db_session) -> World:
    suffix = _uid()
    origin_id = f"TEST-O{suffix[:4]}"
    # 0.01 degree of latitude is about 1.11 km, so the near store is nearest.
    stores = {
        "origin": _add_store(db_session, origin_id, "16.000000", "108.000000"),
        "near": _add_store(db_session, f"TEST-N{suffix[:4]}", "16.010000", "108.000000"),
        "far": _add_store(db_session, f"TEST-F{suffix[:4]}", "16.100000", "108.000000"),
        "inactive": _add_store(db_session, f"TEST-I{suffix[:4]}", "16.001000", "108.000000",
                               is_active=False),
        "empty": _add_store(db_session, f"TEST-E{suffix[:4]}", "16.200000", "108.000000"),
    }
    sku = f"TEST-SKU-{suffix}"
    barcode = f"TEST-BC-{suffix}"
    db_session.add(Product(sku=sku, barcode=barcode, name="Cross-store product",
                           category="TEST", unit_price=Decimal("9.50")))
    db_session.flush()
    add_stock(db_session, origin_id, sku, 2)
    add_stock(db_session, stores["near"].store_id, sku, 7)
    add_stock(db_session, stores["far"].store_id, sku, 3)
    add_stock(db_session, stores["inactive"].store_id, sku, 99)

    username = f"TEST-staff-{suffix}"
    db_session.add(StaffUser(username=username, full_name="Cross-store staff",
                             role="STORE_STAFF", store_id=origin_id))
    db_session.commit()
    return World(origin_id, sku, barcode, stores,
                 create_token(username, "Staff", store_id=origin_id))


@pytest.fixture
def world(db_session) -> World:
    return _make_world(db_session)


def get_stock(client, world: World, *, barcode: str | None = None,
              from_store: str | None = None, token: str | None = None):
    return client.get(
        URL.format(barcode=barcode if barcode is not None else world.barcode),
        params={"from_store": from_store if from_store is not None else world.store_id},
        headers={"Authorization": f"Bearer {token or world.token}"},
    )


def assert_rejected(response, status: int, code: str) -> None:
    assert response.status_code == status, response.text
    body = response.json()
    assert set(body) == {"outcome", "code", "message"}
    assert (body["outcome"], body["code"]) == ("REJECTED", code)


def snapshot(db_session, world: World) -> list[tuple]:
    inventory = db_session.execute(
        select(Inventory.store_id, Inventory.sku, Inventory.quantity)
        .where(Inventory.sku == world.sku)
        .order_by(Inventory.store_id)
    ).all()
    batches = db_session.execute(
        select(ProductBatch.store_id, ProductBatch.batch_id, ProductBatch.quantity,
               ProductBatch.expiry_date)
        .where(ProductBatch.sku == world.sku)
        .order_by(ProductBatch.batch_id)
    ).all()
    return [tuple(row) for row in inventory] + [tuple(row) for row in batches]


# STF35-1, STF35-2


def test_stf35_1_stores_are_ordered_nearest_first(client, world):
    response = get_stock(client, world)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["sku"] == world.sku
    assert [line["store_id"] for line in body["stores"] if line["store_id"] in world.other_stores()] == [
        world.stores["near"].store_id,
        world.stores["far"].store_id,
        world.stores["empty"].store_id,
    ]
    distances = [line["distance_km"] for line in body["stores"]]
    assert distances == sorted(distances)
    assert all(round(distance, 2) == distance for distance in distances)
    expected_near = round(haversine_km(16.0, 108.0, 16.01, 108.0), 2)
    near_line = next(line for line in body["stores"]
                     if line["store_id"] == world.stores["near"].store_id)
    assert near_line["distance_km"] == expected_near


def test_stf35_1_the_caller_store_is_left_out(client, world):
    body = get_stock(client, world).json()

    assert world.store_id not in [line["store_id"] for line in body["stores"]]


def test_stf35_1_quantities_are_sellable_stock(client, world):
    quantities = {line["store_id"]: line["qty"]
                  for line in get_stock(client, world).json()["stores"]}

    assert quantities[world.stores["near"].store_id] == 7
    assert quantities[world.stores["far"].store_id] == 3


def test_stf35_2_only_active_stores_of_this_middleware_are_listed(client, world):
    listed = {line["store_id"] for line in get_stock(client, world).json()["stores"]}

    assert world.stores["inactive"].store_id not in listed
    assert listed & world.other_stores() == world.other_stores() - {
        world.stores["inactive"].store_id}


# STF35-3


def test_stf35_3_the_lookup_changes_nothing(client, db_session, world):
    before = snapshot(db_session, world)

    response = get_stock(client, world)

    assert response.status_code == 200, response.text
    assert snapshot(db_session, world) == before
    assert not db_session.new and not db_session.dirty and not db_session.deleted


# STF35-4, STF35-5


def test_stf35_4_no_store_has_stock(client, db_session, world):
    db_session.execute(update(ProductBatch)
                       .where(ProductBatch.sku == world.sku,
                              ProductBatch.store_id != world.store_id)
                       .values(quantity=0))
    db_session.commit()

    response = get_stock(client, world)

    assert response.status_code == 200, response.text
    lines = response.json()["stores"]
    assert lines
    assert all(line["qty"] == 0 for line in lines)


def test_stf35_4_no_other_store_returns_an_empty_list(client, db_session, world):
    for name in ("near", "far", "inactive", "empty"):
        store_id = world.stores[name].store_id
        db_session.execute(delete(ProductBatch).where(ProductBatch.store_id == store_id))
        db_session.execute(delete(Inventory).where(Inventory.store_id == store_id))
        db_session.delete(db_session.get(Store, store_id))
    db_session.commit()

    response = get_stock(client, world)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["sku"] == world.sku
    assert [line for line in body["stores"] if line["store_id"] in world.other_stores()] == []


def test_stf35_5_an_unknown_barcode_is_not_found(client, world):
    response = get_stock(client, world, barcode=f"TEST-UNKNOWN-{_uid(5)}")

    assert_rejected(response, 404, "NOT_FOUND")


# STF35-6, STF35-7


def test_stf35_6_from_store_must_be_the_caller_store(client, world):
    response = get_stock(client, world, from_store=world.stores["near"].store_id)

    assert_rejected(response, 403, "FORBIDDEN")


def test_stf35_6_an_unknown_from_store_is_forbidden(client, world):
    response = get_stock(client, world, from_store=f"TEST-X{_uid(4)}"[:10])

    assert_rejected(response, 403, "FORBIDDEN")


def test_stf35_7_other_roles_are_forbidden(client, db_session, world):
    suffix = _uid()
    for role, db_role in (("Manager", "STORE_MANAGER"), ("Auditor", "AUDITOR"),
                          ("Admin", "ADMIN")):
        username = f"TEST-{role.lower()}-{suffix}"
        store_id = world.store_id if role == "Manager" else None
        db_session.add(StaffUser(username=username, full_name=role, role=db_role,
                                store_id=store_id))
        db_session.flush()
        response = get_stock(client, world,
                             token=create_token(username, role, store_id=store_id))
        assert_rejected(response, 403, "FORBIDDEN")


def test_stf35_7_a_staff_account_without_a_store_is_forbidden(client, db_session, world):
    username = f"TEST-nostore-{_uid()}"
    db_session.add(StaffUser(username=username, full_name="No store", role="STORE_STAFF"))
    db_session.flush()

    response = get_stock(client, world, token=create_token(username, "Staff"),
                         from_store=world.store_id)

    assert_rejected(response, 403, "FORBIDDEN")


def test_stf35_7_a_missing_token_is_unauthorized(client, world):
    response = client.get(URL.format(barcode=world.barcode),
                          params={"from_store": world.store_id})

    assert_rejected(response, 401, "UNAUTHORIZED")


# PB-35 scenarios without a sheet id


def test_pb35_an_inactive_store_is_left_out(client, world):
    listed = [line["store_id"] for line in get_stock(client, world).json()["stores"]]

    assert world.stores["inactive"].store_id not in listed


def test_pb35_expired_batches_do_not_count(client, db_session, world):
    near_id = world.stores["near"].store_id
    db_session.execute(update(ProductBatch)
                       .where(ProductBatch.sku == world.sku,
                              ProductBatch.store_id == near_id)
                       .values(expiry_date=TODAY - timedelta(days=1)))
    db_session.commit()

    quantities = {line["store_id"]: line["qty"]
                  for line in get_stock(client, world).json()["stores"]}

    assert quantities[near_id] == 0


def test_pb35_a_batch_expiring_today_still_counts(client, db_session, world):
    far_id = world.stores["far"].store_id
    db_session.execute(update(ProductBatch)
                       .where(ProductBatch.sku == world.sku,
                              ProductBatch.store_id == far_id)
                       .values(expiry_date=TODAY))
    db_session.commit()

    quantities = {line["store_id"]: line["qty"]
                  for line in get_stock(client, world).json()["stores"]}

    assert quantities[far_id] == 3


def test_pb35_ties_in_distance_keep_a_stable_order(client, db_session, world):
    suffix = _uid(3)
    tied_stores = [
        _add_store(db_session, f"TEST-TA{suffix}", "16.050000", "108.050000"),
        _add_store(db_session, f"TEST-TB{suffix}", "16.050000", "108.050000"),
    ]
    for store in tied_stores:
        add_stock(db_session, store.store_id, world.sku, 1)
    db_session.commit()

    body = get_stock(client, world).json()
    tied = [line for line in body["stores"]
            if line["store_id"] in {store.store_id for store in tied_stores}]

    assert len(tied) == 2
    assert tied[0]["distance_km"] == tied[1]["distance_km"]
    assert [line["store_id"] for line in tied] == sorted(
        line["store_id"] for line in tied)


def test_pb35_haversine_matches_a_known_distance():
    one_degree = EARTH_RADIUS_KM * 3.141592653589793 / 180

    assert round(haversine_km(0.0, 0.0, 1.0, 0.0), 2) == round(one_degree, 2)
    assert haversine_km(16.0, 108.0, 16.0, 108.0) == 0.0


def test_pb35_barcode_matches_case_exactly(client, world):
    response = get_stock(client, world, barcode=world.barcode.lower())

    assert_rejected(response, 404, "NOT_FOUND")


@pytest.mark.parametrize("barcode", [" ", "bad_code", "x" * 31, "bad.code"])
def test_pb35_an_invalid_barcode_is_rejected(client, world, barcode):
    response = get_stock(client, world, barcode=barcode)

    assert_rejected(response, 422, "VALIDATION_ERROR")


def test_pb35_a_missing_from_store_is_rejected(client, world):
    response = client.get(URL.format(barcode=world.barcode), headers=world.headers())

    assert_rejected(response, 422, "VALIDATION_ERROR")
