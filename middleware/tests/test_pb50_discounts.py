"""Active discounts for staff and POS (PB-50-1).

Every test creates its own stores, products, batches, recommendations,
decisions and sales with ``TEST-`` ids and commits inside the ``db_session``
savepoint, which the fixture rolls back, so nothing stays behind. The business
date is fixed at 23 Nov 2026 (UTC+7): it runs from 22 Nov 17:00 to 23 Nov
17:00 UTC.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import SecretStr

from app.core import clock
from app.core.config import settings
from app.core.security import create_token
from app.domain.models import (
    GuardrailRule,
    PosTerminal,
    PosTransaction,
    Product,
    ProductBatch,
    Recommendation,
    StaffDecision,
    StaffUser,
    Store,
    TransactionItem,
)
from app.services.discounts import discounted_price
from tests.test_client_cert import GATEWAY_SECRET, _make_certificate

TODAY = date(2026, 11, 23)
DAY_START = datetime(2026, 11, 22, 17, 0)  # 00:00 on 23 Nov, UTC+7
DECIDED = datetime(2026, 11, 23, 2, 0)     # 09:00 local
SECRET = "test-only-secret-with-enough-length-for-hs256"
STAFF_URL = "/api/v1/staff/discounts"
POS_URL = "/api/v1/pos/discounts"


def _uid(length: int = 6) -> str:
    return uuid4().hex[:length].upper()


@pytest.fixture(autouse=True)
def business_date(monkeypatch) -> None:
    monkeypatch.setattr(clock, "today_local", lambda: TODAY)
    monkeypatch.setattr(settings, "business_utc_offset_hours", 7)


@pytest.fixture(autouse=True)
def jwt_secret(monkeypatch) -> None:
    monkeypatch.setattr(settings, "jwt_secret", SecretStr(SECRET))


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


class World:
    """Helpers that write rows into the test savepoint."""

    def __init__(self, session) -> None:
        self.session = session
        self.decider_id = self.add_user(None, "ADMIN")[1]

    def add_store(self, lat: str = "16.000000", lon: str = "108.000000", *,
                  active: bool = True, store_id: str | None = None) -> str:
        store_id = store_id or f"TEST-D{_uid(4)}"
        self.session.add(Store(store_id=store_id, name=f"Store {store_id}", latitude=Decimal(lat),
                               longitude=Decimal(lon), region_id="TEST", is_active=active))
        self.session.flush()
        return store_id

    def add_user(self, store_id: str | None, role: str = "STORE_STAFF") -> tuple[str, int]:
        username = f"TEST-pb50-{_uid(8)}"
        user = StaffUser(username=username, full_name="PB-50 account", role=role, store_id=store_id)
        self.session.add(user)
        self.session.flush()
        return username, user.user_id

    def staff_token(self, store_id: str | None, role: str = "Staff") -> str:
        db_role = {"Staff": "STORE_STAFF", "Manager": "STORE_MANAGER"}[role]
        username, _ = self.add_user(store_id, db_role)
        self.session.commit()
        return create_token(username, role, store_id=store_id)

    def add_product(self, price: str = "32000.00", name: str = "Sữa tươi") -> str:
        sku = f"TEST-P{_uid(8)}"
        self.session.add(Product(sku=sku, barcode=f"BC-{sku}", name=name, category="TEST-PB50",
                                 unit_price=Decimal(price)))
        self.session.flush()
        return sku

    def add_batch(self, store_id: str, sku: str, *, quantity: int = 10, days: int = 3) -> str:
        batch_id = f"TEST-B{_uid(10)}"
        self.session.add(ProductBatch(batch_id=batch_id, sku=sku, store_id=store_id,
                                      expiry_date=TODAY + timedelta(days=days), quantity=quantity))
        self.session.flush()
        return batch_id

    def add_discount(self, store_id: str, sku: str, pct: str = "30", *,
                     batch_id: str | None = None, status: str = "ACCEPTED",
                     decided_at: datetime | None = DECIDED,
                     action_type: str = "DISCOUNT") -> int:
        rec = Recommendation(store_id=store_id, sku=sku, batch_id=batch_id, action_type=action_type,
                             discount_pct=Decimal(pct), reason="Near expiry", status=status)
        self.session.add(rec)
        self.session.flush()
        if status in ("ACCEPTED", "REJECTED") and decided_at is not None:
            self.session.add(StaffDecision(rec_id=rec.rec_id, user_id=self.decider_id,
                                           decision="ACCEPT" if status == "ACCEPTED" else "REJECT",
                                           decided_at=decided_at))
        self.session.commit()
        return rec.rec_id

    def add_terminal(self, store_id: str, *, status: str = "ACTIVE",
                     fingerprint: str | None = None) -> str:
        pos_id = f"TEST-T{_uid(8)}"
        self.session.add(PosTerminal(pos_id=pos_id, store_id=store_id, status=status,
                                     cert_fingerprint=fingerprint))
        self.session.commit()
        return pos_id

    def add_sale(self, store_id: str, sku: str, unit_price: str, at: datetime, *,
                 status: str = "OK") -> None:
        pos_id = self.add_terminal(store_id)
        txn_id = f"TEST-S{_uid(10)}"
        self.session.add(PosTransaction(txn_id=txn_id, store_id=store_id, pos_id=pos_id,
                                        txn_type="SALE", status=status, payload_hash="0" * 64,
                                        occurred_at=at))
        self.session.flush()
        self.session.add(TransactionItem(txn_id=txn_id, sku=sku, qty=1,
                                         unit_price=Decimal(unit_price)))
        self.session.commit()

    def pos_token(self, store_id: str | None, pos_id: str | None) -> str:
        username, _ = self.add_user(None, "POS_SYSTEM")
        self.session.commit()
        return create_token(username, "POS", store_id=store_id, pos_id=pos_id)


@pytest.fixture
def world(db_session) -> World:
    return World(db_session)


def staff_items(client, token: str, scope: str | None = None) -> list[dict]:
    params = {} if scope is None else {"scope": scope}
    response = client.get(STAFF_URL, headers=bearer(token), params=params)
    assert response.status_code == 200, response.text
    return response.json()["items"]


def assert_error(response, status: int, code: str) -> None:
    assert response.status_code == status, response.text
    assert response.json()["code"] == code


# Price


@pytest.mark.parametrize(("price", "pct", "expected"), [
    ("32000.00", "30", "22400"),
    ("7000.00", "15", "5900"),
    ("10000.00", "0", "10000"),
    ("12345.00", "33.33", "8200"),
])
def test_pb50_price_is_rounded_down_to_100_vnd(price, pct, expected):
    assert discounted_price(Decimal(price), Decimal(pct)) == Decimal(expected)


# Staff: which discounts are active


def test_pb50_staff_sees_an_accepted_batch_discount_with_numbers(client, world):
    store = world.add_store()
    sku = world.add_product("32000.00", "Sữa tươi")
    batch = world.add_batch(store, sku, days=2)
    world.add_discount(store, sku, "30", batch_id=batch)

    items = staff_items(client, world.staff_token(store))

    assert items == [{
        "store_id": store, "store_name": f"Store {store}", "distance_km": None,
        "sku": sku, "name": "Sữa tươi", "batch_id": batch,
        "expiry_date": (TODAY + timedelta(days=2)).isoformat(),
        "discount_pct": 30.0, "list_price": 32000.0, "discounted_price": 22400.0,
        "decided_at": "2026-11-23T02:00:00Z", "sold_at_discount": False,
    }]


def test_pb50_sold_out_or_expired_batch_is_not_active(client, world):
    store = world.add_store()
    sold_out, expired, today = world.add_product(), world.add_product(), world.add_product()
    world.add_discount(store, sold_out, batch_id=world.add_batch(store, sold_out, quantity=0))
    world.add_discount(store, expired, batch_id=world.add_batch(store, expired, days=-1))
    world.add_discount(store, today, batch_id=world.add_batch(store, today, days=0))

    items = staff_items(client, world.staff_token(store))

    assert [item["sku"] for item in items] == [today]


@pytest.mark.parametrize(("decided_at", "active"), [
    (DAY_START, True),
    (DAY_START - timedelta(seconds=1), False),
    (DAY_START + timedelta(hours=23, minutes=59), True),
])
def test_pb50_sku_level_discount_counts_only_on_its_business_date(client, world, decided_at, active):
    store = world.add_store()
    sku = world.add_product()
    world.add_discount(store, sku, decided_at=decided_at)

    items = staff_items(client, world.staff_token(store))

    assert [(item["sku"], item["batch_id"], item["expiry_date"]) for item in items] == (
        [(sku, None, None)] if active else [])


@pytest.mark.parametrize("status", ["REJECTED", "PENDING", "GENERATED", "BLOCKED", "EXPIRED"])
def test_pb50_only_accepted_recommendations_count(client, world, status):
    store = world.add_store()
    sku = world.add_product()
    world.add_discount(store, sku, batch_id=world.add_batch(store, sku), status=status)

    assert staff_items(client, world.staff_token(store)) == []


def test_pb50_accepted_clearance_is_not_a_discount(client, world):
    store = world.add_store()
    sku = world.add_product()
    world.add_discount(store, sku, batch_id=world.add_batch(store, sku), action_type="CLEARANCE")

    assert staff_items(client, world.staff_token(store)) == []


def test_pb50_guardrail_rule_changed_after_acceptance_keeps_the_percentage(client, world, db_session):
    store = world.add_store()
    sku = world.add_product()
    world.add_discount(store, sku, "50", batch_id=world.add_batch(store, sku))
    db_session.add(GuardrailRule(rule_type="MAX_DISCOUNT", threshold=Decimal("10.00"),
                                 category="TEST-PB50", is_active=True))
    db_session.commit()

    items = staff_items(client, world.staff_token(store))

    assert [(item["discount_pct"], item["discounted_price"]) for item in items] == [(50.0, 16000.0)]


def test_pb50_two_accepted_discounts_on_one_batch_show_the_highest(client, world):
    store = world.add_store()
    sku, tie = world.add_product(), world.add_product()
    batch, tie_batch = world.add_batch(store, sku), world.add_batch(store, tie)
    world.add_discount(store, sku, "50", batch_id=batch, decided_at=DECIDED - timedelta(days=1))
    world.add_discount(store, sku, "30", batch_id=batch)
    world.add_discount(store, tie, "20", batch_id=tie_batch, decided_at=DECIDED - timedelta(days=1))
    world.add_discount(store, tie, "20", batch_id=tie_batch)

    items = staff_items(client, world.staff_token(store))

    assert sorted((item["sku"], item["discount_pct"], item["decided_at"]) for item in items) == sorted([
        (sku, 50.0, "2026-11-22T02:00:00Z"),
        (tie, 20.0, "2026-11-23T02:00:00Z"),
    ])


def test_pb50_items_are_ordered_by_sku_then_expiry(client, world):
    store = world.add_store()
    first, second = sorted([world.add_product(), world.add_product()])
    late, early = world.add_batch(store, first, days=5), world.add_batch(store, first, days=1)
    world.add_discount(store, second, batch_id=world.add_batch(store, second))
    world.add_discount(store, first, batch_id=late)
    world.add_discount(store, first, batch_id=early)

    items = staff_items(client, world.staff_token(store))

    assert [(item["sku"], item["batch_id"]) for item in items] == [
        (first, early), (first, late), (second, items[2]["batch_id"])]


# Staff: scope


def test_pb50_scope_own_lists_only_the_callers_store(client, world):
    own, other = world.add_store(), world.add_store("16.100000")
    sku = world.add_product()
    world.add_discount(own, sku)
    world.add_discount(other, sku)
    token = world.staff_token(own)

    assert [item["store_id"] for item in staff_items(client, token)] == [own]
    assert [item["store_id"] for item in staff_items(client, token, "own")] == [own]


def test_pb50_scope_all_puts_own_store_first_then_nearest(client, world):
    own = world.add_store("16.000000", "108.000000")
    far = world.add_store("16.200000", "108.000000")
    near_b = world.add_store("16.100000", "108.000000", store_id=f"TEST-B{_uid(4)}")
    near_a = world.add_store("16.100000", "108.000000", store_id=f"TEST-A{_uid(4)}")
    closed = world.add_store("16.050000", "108.000000", active=False)
    sku = world.add_product()
    for store in (own, far, near_b, near_a, closed):
        world.add_discount(store, sku)
    mine = {own, far, near_a, near_b, closed}

    items = [item for item in staff_items(client, world.staff_token(own), "all")
             if item["store_id"] in mine]

    assert [(item["store_id"], item["distance_km"]) for item in items] == [
        (own, None), (near_a, 11.12), (near_b, 11.12), (far, 22.24)]


def test_pb50_inactive_own_store_gets_an_empty_list(client, world):
    own = world.add_store(active=False)
    other = world.add_store("16.100000")
    sku = world.add_product()
    world.add_discount(own, sku)
    world.add_discount(other, sku)
    token = world.staff_token(own)

    assert staff_items(client, token, "own") == []
    assert staff_items(client, token, "all") == []


def test_pb50_unknown_scope_is_a_validation_error(client, world):
    response = client.get(STAFF_URL, headers=bearer(world.staff_token(world.add_store())),
                          params={"scope": "nearby"})

    assert_error(response, 422, "VALIDATION_ERROR")


# Staff: sold at discount


@pytest.mark.parametrize(("price", "at", "status", "sold"), [
    ("20000.00", DECIDED - timedelta(minutes=1), "OK", False),       # before the decision
    ("32000.00", DECIDED + timedelta(hours=1), "OK", False),         # at list price
    ("22400.00", DECIDED + timedelta(hours=1), "OK", True),          # below, after the decision
    ("22400.00", DECIDED + timedelta(hours=1), "CANCELLED", False),  # cancelled sale
])
def test_pb50_sold_at_discount(client, world, price, at, status, sold):
    store = world.add_store()
    sku = world.add_product("32000.00")
    world.add_discount(store, sku, batch_id=world.add_batch(store, sku))
    world.add_sale(store, sku, price, at, status=status)

    items = staff_items(client, world.staff_token(store))

    assert [item["sold_at_discount"] for item in items] == [sold]


def test_pb50_sale_yesterday_is_not_sold_at_discount(client, world):
    store = world.add_store()
    sku = world.add_product("32000.00")
    world.add_discount(store, sku, batch_id=world.add_batch(store, sku),
                       decided_at=DAY_START - timedelta(hours=5))
    world.add_sale(store, sku, "22400.00", DAY_START - timedelta(hours=1))

    assert [item["sold_at_discount"] for item in staff_items(client, world.staff_token(store))] == [False]

    world.add_sale(store, sku, "22400.00", DAY_START + timedelta(hours=1))

    assert [item["sold_at_discount"] for item in staff_items(client, world.staff_token(store))] == [True]


def test_pb50_sale_in_another_store_does_not_count(client, world):
    store, other = world.add_store(), world.add_store("16.100000")
    sku = world.add_product("32000.00")
    world.add_discount(store, sku, batch_id=world.add_batch(store, sku))
    world.add_sale(other, sku, "22400.00", DECIDED + timedelta(hours=1))

    assert [item["sold_at_discount"] for item in staff_items(client, world.staff_token(store))] == [False]


# Staff: auth


def test_pb50_staff_without_token_is_401(client):
    assert_error(client.get(STAFF_URL), 401, "UNAUTHORIZED")


def test_pb50_manager_may_read_discounts(client, world):
    store = world.add_store()
    sku = world.add_product()
    world.add_discount(store, sku)

    assert [item["sku"] for item in staff_items(client, world.staff_token(store, "Manager"))] == [sku]


def test_pb50_staff_endpoint_refuses_other_roles(client, world):
    store = world.add_store()
    token = world.pos_token(store, world.add_terminal(store))

    assert_error(client.get(STAFF_URL, headers=bearer(token)), 403, "FORBIDDEN")


def test_pb50_staff_without_store_is_403(client, world):
    assert_error(client.get(STAFF_URL, headers=bearer(world.staff_token(None))), 403, "FORBIDDEN")


# POS


def test_pb50_pos_gets_the_highest_discount_per_sku(client, world):
    store, other = world.add_store(), world.add_store("16.100000")
    milk = world.add_product("32000.00")
    bread = world.add_product("7000.00")
    world.add_discount(store, milk, "30", batch_id=world.add_batch(store, milk))
    world.add_discount(store, milk, "40")
    world.add_discount(store, milk, "20", batch_id=world.add_batch(store, milk, days=5))
    world.add_discount(store, bread, "15", batch_id=world.add_batch(store, bread))
    world.add_discount(other, bread, "50")
    pos_id = world.add_terminal(store)

    # A store_id parameter is ignored: the store is the terminal's.
    response = client.get(POS_URL, headers=bearer(world.pos_token(store, pos_id)),
                          params={"store_id": other})

    assert response.status_code == 200, response.text
    assert response.json() == {"business_date": "2026-11-23", "items": sorted([
        {"sku": milk, "discount_pct": 40.0, "discounted_price": 19200.0},
        {"sku": bread, "discount_pct": 15.0, "discounted_price": 5900.0},
    ], key=lambda item: item["sku"])}


def test_pb50_pos_of_an_inactive_store_gets_no_discounts(client, world):
    store = world.add_store(active=False)
    sku = world.add_product()
    world.add_discount(store, sku)
    pos_id = world.add_terminal(store)

    response = client.get(POS_URL, headers=bearer(world.pos_token(store, pos_id)))

    assert response.status_code == 200, response.text
    assert response.json()["items"] == []


def test_pb50_pos_without_token_is_401(client):
    assert_error(client.get(POS_URL), 401, "UNAUTHORIZED")


def test_pb50_pos_endpoint_refuses_other_roles(client, world):
    assert_error(client.get(POS_URL, headers=bearer(world.staff_token(world.add_store()))),
                 403, "FORBIDDEN")


def test_pb50_pos_token_without_terminal_is_403(client, world):
    store = world.add_store()

    assert_error(client.get(POS_URL, headers=bearer(world.pos_token(store, None))), 403, "FORBIDDEN")


def test_pb50_pos_unknown_terminal_is_403(client, world):
    store = world.add_store()

    assert_error(client.get(POS_URL, headers=bearer(world.pos_token(store, "TEST-T-NONE"))),
                 403, "FORBIDDEN")


def test_pb50_pos_inactive_terminal_is_403(client, world):
    store = world.add_store()
    pos_id = world.add_terminal(store, status="INACTIVE")

    assert_error(client.get(POS_URL, headers=bearer(world.pos_token(store, pos_id))), 403, "FORBIDDEN")


def test_pb50_pos_token_for_another_store_is_403(client, world):
    store, other = world.add_store(), world.add_store("16.100000")
    pos_id = world.add_terminal(store)

    assert_error(client.get(POS_URL, headers=bearer(world.pos_token(other, pos_id))), 403, "FORBIDDEN")


@pytest.fixture
def mtls_on(monkeypatch) -> None:
    monkeypatch.setattr(settings, "mtls_required", True)
    monkeypatch.setattr(settings, "pos_gateway_secret", SecretStr(GATEWAY_SECRET))


@pytest.fixture(scope="module")
def certificates(tmp_path_factory):
    directory = tmp_path_factory.mktemp("pb50-certificates")
    return {name: _make_certificate(directory, f"TEST-PB50-{name}") for name in ("A", "B")}


def _gateway_headers(token: str, certificate=None) -> dict[str, str]:
    headers = {**bearer(token), "X-Gateway-Secret": GATEWAY_SECRET}
    if certificate is not None:
        headers["X-Client-Cert"] = certificate.header
    return headers


def test_pb50_pos_with_its_own_certificate_is_answered(client, world, mtls_on, certificates):
    store = world.add_store()
    pos_id = world.add_terminal(store, fingerprint=certificates["A"].fingerprint)

    response = client.get(POS_URL, headers=_gateway_headers(world.pos_token(store, pos_id),
                                                            certificates["A"]))

    assert response.status_code == 200, response.text


def test_pb50_pos_without_certificate_is_403(client, world, mtls_on, certificates):
    store = world.add_store()
    pos_id = world.add_terminal(store, fingerprint=certificates["A"].fingerprint)

    assert_error(client.get(POS_URL, headers=_gateway_headers(world.pos_token(store, pos_id))),
                 403, "FORBIDDEN")


def test_pb50_pos_with_another_terminals_certificate_is_403(client, world, mtls_on, certificates):
    store = world.add_store()
    pos_id = world.add_terminal(store, fingerprint=certificates["A"].fingerprint)
    world.add_terminal(store, fingerprint=certificates["B"].fingerprint)

    response = client.get(POS_URL, headers=_gateway_headers(world.pos_token(store, pos_id),
                                                            certificates["B"]))

    assert_error(response, 403, "FORBIDDEN")
