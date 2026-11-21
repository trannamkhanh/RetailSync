"""Regression tests for PR KH-C (Audit #13, registry errors/layering, guardrail update locking)."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
import threading
from unittest.mock import patch
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.core import clock
from app.core.config import settings
from app.core.errors import ApiError
from app.core.security import Principal, create_token
from app.domain.models import AuditLog, GuardrailRule, PosTerminal, Product, StaffUser, Store
from app.services import guardrail_rules, registry
from tests.pos_test_support import add_stock, uid


SECRET = "test-only-secret-with-enough-length-for-hs256"
STORES = "/api/v1/admin/stores"
TERMINALS = "/api/v1/admin/pos-terminals"
POS_EVENTS = "/api/v1/pos/events"


@pytest.fixture(autouse=True)
def jwt_secret(monkeypatch):
    monkeypatch.setattr(settings, "jwt_secret", SecretStr(SECRET))


def _admin_headers(db_session: Session) -> dict[str, str]:
    username = f"TEST-khc-{uid(6)}"
    db_session.add(StaffUser(username=username, full_name="KH-C Admin", role="ADMIN"))
    db_session.commit()
    return {"Authorization": f"Bearer {create_token(username, 'Admin')}"}


def test_audit13_lowercase_store_registration_accepts_uppercase_pos_event(client, db_session):
    headers = _admin_headers(db_session)
    store_id = f"TEST-{uid(5).upper()}"
    pos_id = f"TEST-POS-{uid(6).upper()}"
    sku = f"TEST-SKU-{uid(6).upper()}"

    store_resp = client.post(
        STORES,
        json={
            "store_id": store_id,
            "name": "Audit 13 store",
            "latitude": 16.0678,
            "longitude": 108.2208,
            "region_id": "TEST",
        },
        headers=headers,
    )
    assert store_resp.status_code == 201, store_resp.text

    # Register terminal using lowercase store_id; SQL Server CI_AS finds the store,
    # and the service must store the canonical store_id from dbo.store.
    term_resp = client.post(
        TERMINALS,
        json={"pos_id": pos_id, "store_id": store_id.lower()},
        headers=headers,
    )
    assert term_resp.status_code == 201, term_resp.text
    assert term_resp.json()["store_id"] == store_id
    assert db_session.get(PosTerminal, pos_id).store_id == store_id

    db_session.add(Product(sku=sku, barcode=sku, name="Audit 13 SKU", category="Dairy",
                           unit_price=Decimal("10000.00")))
    db_session.flush()
    add_stock(db_session, store_id, sku, 10, expiry_date=clock.today_local() + timedelta(days=5))
    db_session.commit()

    pos_token = create_token("pos_system", "POS", store_id=store_id, pos_id=pos_id)
    event_resp = client.post(
        POS_EVENTS,
        json={
            "event_type": "SALE",
            "transaction_id": f"TEST-A13-{uuid4().hex[:12]}",
            "store_id": store_id,
            "pos_id": pos_id,
            "timestamp": "2026-11-21T10:00:00Z",
            "items": [{"sku": sku, "quantity": 1, "unit_price": 10000.00}],
        },
        headers={"Authorization": f"Bearer {pos_token}"},
    )
    assert event_resp.status_code == 200, event_resp.text
    assert event_resp.json()["outcome"] == "OK"


def test_audit13_duplicate_fingerprint_race_reports_fingerprint_not_pos_id(
    client, db_session, monkeypatch,
):
    headers = _admin_headers(db_session)
    store_id = f"TEST-{uid(5).upper()}"
    pos_one = f"TEST-POS-{uid(6).upper()}"
    pos_two = f"TEST-POS-{uid(6).upper()}"
    fingerprint = "b" * 64

    assert client.post(
        STORES,
        json={"store_id": store_id, "name": "FP race", "latitude": 16.0, "longitude": 108.0, "region_id": "TEST"},
        headers=headers,
    ).status_code == 201
    assert client.post(
        TERMINALS,
        json={"pos_id": pos_one, "store_id": store_id, "cert_fingerprint": fingerprint},
        headers=headers,
    ).status_code == 201

    # Bypass the pre-check so SQL Server enforces uq_pos_terminal_cert during flush.
    monkeypatch.setattr("app.services.registry.repository.find_terminal_by_fingerprint",
                        lambda session, fp: None)

    resp = client.post(
        TERMINALS,
        json={"pos_id": pos_two, "store_id": store_id, "cert_fingerprint": fingerprint},
        headers=headers,
    )
    assert resp.status_code == 409, resp.text
    body = resp.json()
    assert body["code"] == "ALREADY_EXISTS"
    assert "fingerprint" in body["message"].lower()
    assert fingerprint in body["message"]
    assert pos_two not in body["message"]


def test_audit13_unknown_store_fk_race_returns_422(client, db_session, monkeypatch):
    headers = _admin_headers(db_session)
    missing_store = f"TEST-{uid(5).upper()}"
    pos_id = f"TEST-POS-{uid(6).upper()}"

    # Simulate the store disappearing between find_store and flush (FK 547).
    monkeypatch.setattr(
        "app.services.registry.repository.find_store",
        lambda session, store_id: Store(store_id=missing_store, name="Gone", latitude=0, longitude=0, region_id="TEST"),
    )

    resp = client.post(
        TERMINALS,
        json={"pos_id": pos_id, "store_id": missing_store},
        headers=headers,
    )
    assert resp.status_code == 422, resp.text
    body = resp.json()
    assert body["code"] == "VALIDATION_ERROR"
    assert missing_store in body["message"]


def test_audit13_registry_service_never_rolls_back_caller_session(db_session, monkeypatch):
    store_id = f"TEST-{uid(5).upper()}"
    pos_id = f"TEST-POS-{uid(6).upper()}"
    principal = Principal("TEST-ADMIN", "Admin", None, None)

    db_session.add(Store(store_id=store_id, name="Rollback check", latitude=0, longitude=0, region_id="TEST"))
    db_session.flush()
    db_session.add(PosTerminal(pos_id=pos_id, store_id=store_id, status="ACTIVE"))
    db_session.commit()

    monkeypatch.setattr("app.services.registry.repository.find_pos_terminal", lambda session, pid: None)
    with patch.object(db_session, "rollback", wraps=db_session.rollback) as rollback_spy:
        with pytest.raises(ApiError) as exc_info:
            registry.register_pos_terminal(
                db_session,
                PosTerminal(pos_id=pos_id, store_id=store_id, status="ACTIVE"),
                principal,
            )
        assert exc_info.value.status == 409
        rollback_spy.assert_not_called()
    db_session.rollback()


def test_audit13_parallel_guardrail_rule_puts_preserve_tightening_invariant(test_engine, monkeypatch):
    suffix = uid(5).upper()
    username = f"TEST-GRLOCK-{suffix}"
    category = f"TEST-CAT-{suffix}"
    principal = Principal(username, "Admin", None, None)

    with Session(test_engine) as setup, setup.begin():
        general = setup.scalar(
            select(GuardrailRule).where(
                GuardrailRule.rule_type == "MAX_DISCOUNT",
                GuardrailRule.category.is_(None),
            )
        )
        assert general is not None
        general_id = general.rule_id
        orig_threshold = general.threshold
        orig_active = general.is_active
        orig_updated_by = general.updated_by
        orig_updated_at = general.updated_at

        general.threshold = Decimal("50.00")
        general.is_active = True

        user = StaffUser(username=username, full_name="Lock Admin", role="ADMIN")
        setup.add(user)
        cat_rule = GuardrailRule(
            rule_type="MAX_DISCOUNT",
            threshold=Decimal("30.00"),
            category=category,
            is_active=True,
        )
        setup.add(cat_rule)
        setup.flush()
        cat_id = cat_rule.rule_id
        user_id = user.user_id

    start_barrier = threading.Barrier(2)
    check_barrier = threading.Barrier(2)
    orig_check = guardrail_rules._check_tightening

    def synchronized_check(*args, **kwargs):
        try:
            check_barrier.wait(timeout=0.5)
        except threading.BrokenBarrierError:
            pass
        return orig_check(*args, **kwargs)

    monkeypatch.setattr(guardrail_rules, "_check_tightening", synchronized_check)

    def run_update(rule_id: int, new_threshold: Decimal) -> int:
        with Session(test_engine) as session:
            try:
                start_barrier.wait(timeout=5)
                guardrail_rules.update_rule(session, rule_id, new_threshold, True, principal)
                session.commit()
                return 200
            except ApiError as error:
                session.rollback()
                return error.status

    try:
        # Both edits are individually valid against (general=50, category=30),
        # but applying both yields (general=35, category=45), breaking DS-07.
        with ThreadPoolExecutor(max_workers=2) as pool:
            f_general = pool.submit(run_update, general_id, Decimal("35"))
            f_category = pool.submit(run_update, cat_id, Decimal("45"))
            statuses = [f_general.result(timeout=15), f_category.result(timeout=15)]

        with Session(test_engine) as verify:
            final_general = verify.get(GuardrailRule, general_id)
            final_category = verify.get(GuardrailRule, cat_id)
            assert final_category.threshold <= final_general.threshold, (
                f"Tightening broken: category={final_category.threshold} > general={final_general.threshold}"
            )
        assert sorted(statuses) == [200, 422]
    finally:
        with Session(test_engine) as cleanup, cleanup.begin():
            cleanup.execute(
                update(GuardrailRule)
                .where(GuardrailRule.rule_id == general_id)
                .values(
                    threshold=orig_threshold,
                    is_active=orig_active,
                    updated_by=orig_updated_by,
                    updated_at=orig_updated_at,
                )
            )
            cleanup.execute(delete(AuditLog).where(AuditLog.user_id == user_id))
            cleanup.execute(delete(GuardrailRule).where(GuardrailRule.rule_id == cat_id))
            cleanup.execute(delete(StaffUser).where(StaffUser.user_id == user_id))
