"""Audit #7: the recommendation money fields are JSON numbers, not strings.

``RecommendationSummary.discount_pct`` and the two guardrail values are
``Decimal`` in Pydantic v2, which writes them as ``"30.00"`` unless a
``field_serializer`` says otherwise. ``docs/design/openapi.yaml`` says
``number``, and ``api/schemas/products.py`` already serialises ``unit_price``
this way. The clients must keep reading both forms, which their own suites
check; this file pins the middleware side of the contract.

Every test creates its own store, product, batch and recommendation with
``TEST-`` ids inside the ``db_session`` savepoint, so nothing stays behind.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import SecretStr

from app.core import clock
from app.core.config import settings
from app.core.security import create_token
from app.domain.models import (
    GuardrailResult,
    GuardrailRule,
    Product,
    ProductBatch,
    Recommendation,
    StaffUser,
    Store,
)

TODAY = date(2026, 11, 17)
SECRET = "test-only-secret-with-enough-length-for-hs256"
LIST_URL = "/api/v1/recommendations"


def _uid(length: int = 5) -> str:
    return uuid4().hex[:length].upper()


@pytest.fixture(autouse=True)
def business_date(monkeypatch) -> None:
    monkeypatch.setattr(clock, "today_local", lambda: TODAY)


@pytest.fixture(autouse=True)
def jwt_secret(monkeypatch) -> None:
    monkeypatch.setattr(settings, "jwt_secret", SecretStr(SECRET))


class World:
    def __init__(self, store_id: str, token: str) -> None:
        self.store_id = store_id
        self.token = token

    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}


@pytest.fixture
def world(db_session) -> World:
    suffix = _uid()
    store_id = f"TEST-A{suffix[:4]}"
    db_session.add(Store(store_id=store_id, name=f"Store {store_id}",
                         latitude=Decimal("16.067800"), longitude=Decimal("108.220800"),
                         region_id="TEST"))
    db_session.flush()
    username = f"TEST-staff-{suffix}"
    db_session.add(StaffUser(username=username, full_name="Audit money staff",
                             role="STORE_STAFF", store_id=store_id))
    db_session.commit()
    return World(store_id, create_token(username, "Staff", store_id=store_id))


def add_recommendation(db_session, world: World, *, discount_pct: Decimal | None,
                       action_type: str = "DISCOUNT",
                       guardrail_values: tuple[Decimal, Decimal] | None = None,
                       outcome: str = "ADJUSTED") -> Recommendation:
    suffix = _uid()
    sku = f"TEST-SKU-{suffix}"
    batch_id = f"TEST-BATCH-{suffix}"
    db_session.add(Product(sku=sku, barcode=f"BC-{sku}", name="Audit money product",
                           category="TEST", unit_price=Decimal("10.00")))
    db_session.flush()
    db_session.add(ProductBatch(batch_id=batch_id, sku=sku, store_id=world.store_id,
                                expiry_date=TODAY + timedelta(days=5), quantity=10))
    db_session.flush()
    rec = Recommendation(store_id=world.store_id, sku=sku, batch_id=batch_id,
                         action_type=action_type, discount_pct=discount_pct,
                         proposed_qty=None, reason="Near expiry", status="PENDING")
    db_session.add(rec)
    db_session.flush()
    rule = GuardrailRule(rule_type="MAX_DISCOUNT", threshold=Decimal("10.00"),
                         category="TEST", is_active=True)
    db_session.add(rule)
    db_session.flush()
    original, adjusted = guardrail_values if guardrail_values else (None, None)
    db_session.add(GuardrailResult(rec_id=rec.rec_id, rule_id=rule.rule_id,
                                   outcome=outcome, original_value=original,
                                   adjusted_value=adjusted, message="Capped."))
    db_session.flush()
    return rec


def is_json_number(value: object) -> bool:
    """A JSON number arrives as int or float; a Decimal string arrives as str."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


# The list


def test_audit07_the_list_returns_discount_pct_as_a_number(client, db_session, world):
    rec = add_recommendation(db_session, world, discount_pct=Decimal("30.00"))
    db_session.commit()

    response = client.get(LIST_URL, headers=world.headers())

    assert response.status_code == 200, response.text
    item = response.json()["items"][0]
    assert item["rec_id"] == rec.rec_id
    assert is_json_number(item["discount_pct"]), item["discount_pct"]
    assert float(item["discount_pct"]) == 30.0


def test_audit07_the_list_keeps_a_null_discount_null(client, db_session, world):
    add_recommendation(db_session, world, discount_pct=None, action_type="CLEARANCE")
    db_session.commit()

    body = client.get(LIST_URL, headers=world.headers()).json()

    assert body["items"][0]["discount_pct"] is None


# The detail


def test_audit07_the_detail_returns_discount_pct_as_a_number(client, db_session, world):
    rec = add_recommendation(db_session, world, discount_pct=Decimal("50.00"))
    db_session.commit()

    response = client.get(f"{LIST_URL}/{rec.rec_id}", headers=world.headers())

    assert response.status_code == 200, response.text
    body = response.json()
    assert is_json_number(body["discount_pct"]), body["discount_pct"]
    assert float(body["discount_pct"]) == 50.0


def test_audit07_the_detail_returns_guardrail_values_as_numbers(client, db_session, world):
    rec = add_recommendation(db_session, world, discount_pct=Decimal("30.00"),
                             guardrail_values=(Decimal("30.00"), Decimal("10.00")))
    db_session.commit()

    body = client.get(f"{LIST_URL}/{rec.rec_id}", headers=world.headers()).json()

    result = body["guardrail_results"][0]
    assert is_json_number(result["original_value"]), result["original_value"]
    assert is_json_number(result["adjusted_value"]), result["adjusted_value"]
    assert (float(result["original_value"]), float(result["adjusted_value"])) == (30.0, 10.0)


def test_audit07_a_passed_guardrail_keeps_both_values_null(client, db_session, world):
    rec = add_recommendation(db_session, world, discount_pct=Decimal("30.00"),
                             outcome="PASSED")
    db_session.commit()

    body = client.get(f"{LIST_URL}/{rec.rec_id}", headers=world.headers()).json()

    result = body["guardrail_results"][0]
    assert (result["original_value"], result["adjusted_value"]) == (None, None)


@pytest.mark.parametrize("value,expected", [
    (Decimal("0"), 0.0),
    (Decimal("0.50"), 0.5),
    (Decimal("99.99"), 99.99),
])
def test_audit07_the_number_is_the_stored_value(client, db_session, world, value, expected):
    rec = add_recommendation(db_session, world, discount_pct=value)
    db_session.commit()

    body = client.get(f"{LIST_URL}/{rec.rec_id}", headers=world.headers()).json()

    assert body["discount_pct"] == expected
