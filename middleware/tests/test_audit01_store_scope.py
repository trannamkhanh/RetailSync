"""Audit #1: a Staff/Manager token may not widen the account's store scope.

Per DS-04 only the POS service account spans terminals and takes its store from
the token; a Staff or Manager principal is scoped to the store of its account.
Before this fix ``_authorize`` returned ``user.store_id or claims.get("store_id")``
for every role, so an account whose ``store_id`` was cleared, or moved to
another store, kept reading and deciding for the store of its old 60-day token.

Every test creates its own stores, product, batches, account and recommendation
with ``TEST-`` ids and commits inside the ``db_session`` savepoint the fixture
rolls back, so nothing stays behind.
"""

from __future__ import annotations

from collections.abc import Generator
from dataclasses import asdict
from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import APIRouter, Depends, FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import clock
from app.core.config import settings
from app.core.db import get_db
from app.core.errors import register_error_handlers
from app.core.security import Principal, create_token, require_role
from app.domain.models import Product, Recommendation, StaffUser, Store
from tests.pos_test_support import add_stock

TODAY = date(2026, 11, 17)
SECRET = "test-only-secret-with-enough-length-for-hs256"
ALERTS_URL = "/api/v1/near-expiry-alerts"
RECOMMENDATIONS_URL = "/api/v1/recommendations"

router = APIRouter()


@router.get("/principal")
def principal_route(principal: Principal = Depends(require_role("POS"))):
    """A test-only POS route, so the POS scope can be read without a store route."""
    return asdict(principal)


def _uid(length: int = 5) -> str:
    return uuid4().hex[:length].upper()


@pytest.fixture(autouse=True)
def business_date(monkeypatch) -> None:
    monkeypatch.setattr(clock, "today_local", lambda: TODAY)


@pytest.fixture(autouse=True)
def jwt_secret(monkeypatch) -> None:
    monkeypatch.setattr(settings, "jwt_secret", SecretStr(SECRET))


@pytest.fixture
def pos_client(db_session: Session) -> TestClient:
    def override_get_db() -> Generator[Session, None, None]:
        yield db_session

    test_app = FastAPI()
    register_error_handlers(test_app)
    test_app.include_router(router)
    test_app.dependency_overrides[get_db] = override_get_db
    return TestClient(test_app)


class World:
    """Two stocked stores, the caller's account and one PENDING recommendation."""

    def __init__(self, store_id: str, other_store_id: str, sku: str,
                 rec_id: int, username: str, token: str) -> None:
        self.store_id = store_id
        self.other_store_id = other_store_id
        self.sku = sku
        self.rec_id = rec_id
        self.username = username
        self.token = token

    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}


def make_world(db_session: Session, *, account_store: str | None,
               role: str = "STORE_STAFF") -> World:
    """Store A and store B, both stocked; an account that may be without a store.

    The token always names store A, which is what the old 60-day token of a
    removed or moved account still says.
    """
    suffix = _uid()
    store_id = f"TEST-A{suffix[:4]}"
    other_store_id = f"TEST-B{suffix[:4]}"
    for name in (store_id, other_store_id):
        db_session.add(Store(store_id=name, name=f"Store {name}",
                             latitude=Decimal("16.000000"), longitude=Decimal("108.000000"),
                             region_id="TEST"))
    db_session.flush()
    sku = f"TEST-SKU-{suffix}"
    db_session.add(Product(sku=sku, barcode=f"BC-{sku}", name="Audit store scope product",
                           category="TEST", unit_price=Decimal("10.00")))
    db_session.flush()
    batch_id = add_stock(db_session, store_id, sku, 10)
    add_stock(db_session, other_store_id, sku, 10)
    username = f"TEST-staff-{suffix}"
    db_session.add(StaffUser(username=username, full_name="Audit store scope account",
                             role=role, store_id=account_store))
    recommendation = Recommendation(
        store_id=store_id, sku=sku, batch_id=batch_id, action_type="DISCOUNT",
        discount_pct=Decimal("30"), proposed_qty=None, reason="Near expiry",
        status="PENDING",
    )
    db_session.add(recommendation)
    db_session.flush()
    db_session.commit()
    api_role = "Staff" if role == "STORE_STAFF" else "Manager"
    return World(store_id, other_store_id, sku, recommendation.rec_id, username,
                 create_token(username, api_role, store_id=store_id))


def inventory_url(store_id: str) -> str:
    return f"/api/v1/stores/{store_id}/inventory"


def assert_rejected(response, status: int, code: str) -> None:
    assert response.status_code == status, response.text
    body = response.json()
    assert set(body) == {"outcome", "code", "message"}
    assert (body["outcome"], body["code"]) == ("REJECTED", code)


# A Staff/Manager removed from its store keeps no store-scoped access.


def test_audit01_staff_without_store_is_forbidden_on_inventory(client, db_session):
    world = make_world(db_session, account_store=None)

    response = client.get(inventory_url(world.store_id), headers=world.headers())

    assert_rejected(response, 403, "FORBIDDEN")


def test_audit01_staff_without_store_is_forbidden_on_alerts(client, db_session):
    world = make_world(db_session, account_store=None)

    response = client.get(ALERTS_URL, headers=world.headers())

    assert_rejected(response, 403, "FORBIDDEN")


def test_audit01_staff_without_store_is_forbidden_on_recommendation_list(client, db_session):
    world = make_world(db_session, account_store=None)

    response = client.get(RECOMMENDATIONS_URL, headers=world.headers())

    assert_rejected(response, 403, "FORBIDDEN")


def test_audit01_staff_without_store_is_forbidden_on_decision(client, db_session):
    world = make_world(db_session, account_store=None)

    response = client.post(f"{RECOMMENDATIONS_URL}/{world.rec_id}/decision",
                           headers=world.headers(), json={"decision": "ACCEPT"})

    assert_rejected(response, 403, "FORBIDDEN")


def test_audit01_manager_without_store_is_forbidden_on_inventory(client, db_session):
    world = make_world(db_session, account_store=None, role="STORE_MANAGER")

    response = client.get(inventory_url(world.store_id), headers=world.headers())

    assert_rejected(response, 403, "FORBIDDEN")


# An account moved to another store reads the new store only.


def test_audit01_moved_account_reads_only_its_new_store(client, db_session):
    world = make_world(db_session, account_store=None)
    account = db_session.scalar(select(StaffUser).where(StaffUser.username == world.username))
    account.store_id = world.other_store_id
    db_session.commit()

    new_store = client.get(inventory_url(world.other_store_id), headers=world.headers())
    old_store = client.get(inventory_url(world.store_id), headers=world.headers())

    assert new_store.status_code == 200, new_store.text
    assert [(item["sku"], item["quantity"]) for item in new_store.json()["items"]] == [
        (world.sku, 10)]
    assert_rejected(old_store, 403, "FORBIDDEN")


def test_audit01_moved_account_cannot_decide_for_its_old_store(client, db_session):
    world = make_world(db_session, account_store=None)
    account = db_session.scalar(select(StaffUser).where(StaffUser.username == world.username))
    account.store_id = world.other_store_id
    db_session.commit()

    response = client.post(f"{RECOMMENDATIONS_URL}/{world.rec_id}/decision",
                           headers=world.headers(), json={"decision": "ACCEPT"})

    # The recommendation belongs to store A, which the account no longer has.
    assert_rejected(response, 404, "NOT_FOUND")


# The POS service account keeps taking its store from the token.


def test_audit01_pos_still_takes_its_store_from_the_token(pos_client, db_session):
    world = make_world(db_session, account_store=None)
    username = f"TEST-pos-{_uid()}"
    db_session.add(StaffUser(username=username, full_name="Audit POS account",
                             role="POS_SYSTEM", store_id=None))
    db_session.commit()
    token = create_token(username, "POS", store_id=world.store_id, pos_id="TEST-POS-01")

    response = pos_client.get("/principal", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200, response.text
    assert response.json() == {"sub": username, "role": "POS",
                               "store_id": world.store_id, "pos_id": "TEST-POS-01"}
