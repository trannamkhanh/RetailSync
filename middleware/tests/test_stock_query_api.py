"""GET /api/v1/stores/{store_id}/inventory on real SQL Server (PB-12, INV12-1 to INV12-5).

A Staff or Manager token may read only its own store. Every test creates its own
``TEST-`` rows through ``db_session`` and never commits.
"""

from decimal import Decimal
from unittest.mock import Mock

import pytest
from pydantic import SecretStr
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import create_token
from app.domain.models import Inventory, Product, StaffUser, Store


SECRET = "test-only-secret-with-enough-length-for-hs256"
STORE_ID = "TEST-SQ1"
OTHER_STORE_ID = "TEST-SQ2"
EMPTY_STORE_ID = "TEST-SQ3"
SKU_A = "TEST-SKU-A"
SKU_B = "TEST-SKU-B"
SKU_C = "TEST-SKU-C"
SKU_NO_STOCK = "TEST-SKU-NOSTOCK"
SKU_OTHER_ONLY = "TEST-SKU-OTHER"
UNKNOWN_SKU = "TEST-SKU-MISSING"
STAFF = "TEST-sq-staff"
MANAGER = "TEST-sq-manager"
OTHER_STAFF = "TEST-sq-other"
EMPTY_STAFF = "TEST-sq-empty"
POS_ACCOUNT = "TEST-sq-pos"
HQ_ACCOUNT = "TEST-sq-hq"
ADMIN_ACCOUNT = "TEST-sq-admin"
AUDITOR_ACCOUNT = "TEST-sq-auditor"


@pytest.fixture(autouse=True)
def jwt_secret(monkeypatch):
    monkeypatch.setattr(settings, "jwt_secret", SecretStr(SECRET))


def url(store_id: str, sku: str | None = None) -> str:
    path = f"/api/v1/stores/{store_id}/inventory"
    return f"{path}?sku={sku}" if sku is not None else path


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def assert_rejected(response, status: int, code: str) -> dict:
    assert response.status_code == status
    body = response.json()
    assert set(body) == {"outcome", "code", "message"}
    assert (body["outcome"], body["code"]) == ("REJECTED", code)
    return body


def add_store(session: Session, store_id: str) -> Store:
    store = Store(store_id=store_id, name="Stock query store", latitude=Decimal("16.000000"),
                  longitude=Decimal("108.000000"), region_id="TEST")
    session.add(store)
    return store


def add_product(session: Session, sku: str) -> Product:
    product = Product(sku=sku, barcode=f"BC-{sku}", name="Stock query product",
                      category="TEST", unit_price=Decimal("10.00"))
    session.add(product)
    return product


def add_stock(session: Session, store_id: str, sku: str, quantity: int) -> Inventory:
    row = Inventory(store_id=store_id, sku=sku, quantity=quantity)
    session.add(row)
    return row


def account(session: Session, username: str, role: str, store_id: str | None) -> StaffUser:
    user = StaffUser(username=username, full_name="Stock query account", role=role,
                     store_id=store_id)
    session.add(user)
    session.flush()
    return user


@pytest.fixture
def world(db_session: Session) -> None:
    for store_id in (STORE_ID, OTHER_STORE_ID, EMPTY_STORE_ID):
        add_store(db_session, store_id)
    db_session.flush()
    for sku in (SKU_A, SKU_B, SKU_C, SKU_NO_STOCK, SKU_OTHER_ONLY):
        add_product(db_session, sku)
    db_session.flush()
    # Inserted out of order, so the response has to sort by SKU itself.
    add_stock(db_session, STORE_ID, SKU_C, 0)
    add_stock(db_session, STORE_ID, SKU_A, 7)
    add_stock(db_session, STORE_ID, SKU_B, 3)
    add_stock(db_session, OTHER_STORE_ID, SKU_OTHER_ONLY, 42)
    db_session.flush()
    account(db_session, STAFF, "STORE_STAFF", STORE_ID)
    account(db_session, MANAGER, "STORE_MANAGER", STORE_ID)
    account(db_session, OTHER_STAFF, "STORE_STAFF", OTHER_STORE_ID)
    account(db_session, EMPTY_STAFF, "STORE_STAFF", EMPTY_STORE_ID)
    account(db_session, POS_ACCOUNT, "POS_SYSTEM", None)
    account(db_session, HQ_ACCOUNT, "HQ_OPERATOR", None)
    account(db_session, ADMIN_ACCOUNT, "ADMIN", None)
    account(db_session, AUDITOR_ACCOUNT, "AUDITOR", None)


@pytest.fixture
def staff_headers(world) -> dict[str, str]:
    return bearer(create_token(STAFF, "Staff", STORE_ID))


@pytest.fixture
def manager_headers(world) -> dict[str, str]:
    return bearer(create_token(MANAGER, "Manager", STORE_ID))


@pytest.fixture
def other_headers(world) -> dict[str, str]:
    return bearer(create_token(OTHER_STAFF, "Staff", OTHER_STORE_ID))


@pytest.fixture
def empty_headers(world) -> dict[str, str]:
    return bearer(create_token(EMPTY_STAFF, "Staff", EMPTY_STORE_ID))


# INV12-1: a Staff token reads every line of its own store, ordered by SKU.


def test_inv12_1_staff_reads_every_line_of_own_store_ordered_by_sku(client, world,
                                                                    staff_headers):
    response = client.get(url(STORE_ID), headers=staff_headers)

    assert response.status_code == 200
    assert response.json() == {
        "store_id": STORE_ID,
        "items": [
            {"sku": SKU_A, "quantity": 7},
            {"sku": SKU_B, "quantity": 3},
            {"sku": SKU_C, "quantity": 0},
        ],
    }


# INV12-2: a Manager token is allowed too.


def test_inv12_2_manager_reads_own_store(client, world, manager_headers):
    response = client.get(url(STORE_ID), headers=manager_headers)

    assert response.status_code == 200
    assert [item["sku"] for item in response.json()["items"]] == [SKU_A, SKU_B, SKU_C]


# INV12-3: the sku filter returns exactly one line.


def test_inv12_3_sku_filter_returns_one_line(client, world, staff_headers):
    response = client.get(url(STORE_ID, SKU_B), headers=staff_headers)

    assert response.status_code == 200
    assert response.json() == {"store_id": STORE_ID, "items": [{"sku": SKU_B, "quantity": 3}]}


# INV12-4: another store is forbidden, and the store check comes first.


def test_inv12_4_another_store_is_forbidden(client, world, staff_headers):
    response = client.get(url(OTHER_STORE_ID), headers=staff_headers)

    body = assert_rejected(response, 403, "FORBIDDEN")
    assert OTHER_STORE_ID in body["message"]


def test_staff_of_another_store_cannot_read_this_store(client, world, other_headers):
    assert_rejected(client.get(url(STORE_ID), headers=other_headers), 403, "FORBIDDEN")


def test_unknown_store_is_forbidden_not_not_found(client, world, staff_headers):
    assert_rejected(client.get(url("TEST-NOSTORE"), headers=staff_headers), 403, "FORBIDDEN")


# INV12-5: a SKU outside the catalogue is not found.


def test_inv12_5_unknown_sku_returns_404(client, world, staff_headers):
    response = client.get(url(STORE_ID, UNKNOWN_SKU), headers=staff_headers)

    body = assert_rejected(response, 404, "NOT_FOUND")
    assert UNKNOWN_SKU in body["message"]


# Stock edge cases.


def test_catalogue_product_without_a_stock_row_returns_zero(client, world, staff_headers):
    response = client.get(url(STORE_ID, SKU_NO_STOCK), headers=staff_headers)

    assert response.status_code == 200
    assert response.json()["items"] == [{"sku": SKU_NO_STOCK, "quantity": 0}]


def test_stock_of_another_store_is_not_returned(client, world, staff_headers):
    response = client.get(url(STORE_ID, SKU_OTHER_ONLY), headers=staff_headers)

    assert response.status_code == 200
    assert response.json()["items"] == [{"sku": SKU_OTHER_ONLY, "quantity": 0}]


def test_empty_store_returns_no_lines(client, world, empty_headers):
    response = client.get(url(EMPTY_STORE_ID), headers=empty_headers)

    assert response.status_code == 200
    assert response.json() == {"store_id": EMPTY_STORE_ID, "items": []}


# Authentication and roles.


def test_missing_token_returns_401(client, world):
    assert_rejected(client.get(url(STORE_ID)), 401, "UNAUTHORIZED")


def test_invalid_token_returns_401(client, world):
    assert_rejected(client.get(url(STORE_ID), headers=bearer("not-a-token")), 401, "UNAUTHORIZED")


@pytest.mark.parametrize("username,api_role", [
    (POS_ACCOUNT, "POS"),
    (HQ_ACCOUNT, "HQ"),
    (ADMIN_ACCOUNT, "Admin"),
    (AUDITOR_ACCOUNT, "Auditor"),
], ids=["pos", "hq", "admin", "auditor"])
def test_every_other_role_is_forbidden(client, world, username, api_role):
    response = client.get(url(STORE_ID), headers=bearer(create_token(username, api_role)))

    assert_rejected(response, 403, "FORBIDDEN")


# Validation and read-only behaviour.


def test_sku_longer_than_20_characters_returns_422(client, world, staff_headers):
    response = client.get(url(STORE_ID, "X" * 21), headers=staff_headers)

    body = assert_rejected(response, 422, "VALIDATION_ERROR")
    assert "sku" in body["message"]


def test_the_query_never_commits(client, world, staff_headers, db_session, monkeypatch):
    commit = Mock()
    monkeypatch.setattr(db_session, "commit", commit)

    assert client.get(url(STORE_ID), headers=staff_headers).status_code == 200

    commit.assert_not_called()
    assert not db_session.new
    assert not db_session.dirty
