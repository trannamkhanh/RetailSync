"""STOCK_CHANGE audit tests (PS04-1, PS04-2) against real SQL Server."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.domain.models import PosTransaction
from app.main import app
from tests.pos_test_support import (
    assert_error,
    count,
    post,
    return_payload,
    sale_payload,
    seed_sale,
    stock,
    stock_changes,
    uid,
)


def test_ps04_1_applied_sale_and_return_write_one_stock_change(client, db_session) -> None:
    world = seed_sale(db_session, sold={f"TEST-SKU-{uid(8)}": 2}, stock=10)
    sku = world.skus[0]
    sale = sale_payload(world, [(sku, 1, 1000)])
    returned = return_payload(world, [(sku, 1, 1000)])

    assert post(client, sale, world.token).status_code == 200
    assert post(client, returned, world.token).status_code == 200

    sale_audits = stock_changes(db_session, sale["transaction_id"])
    assert len(sale_audits) == 1
    assert sale_audits[0].entity_name == "pos_transaction"
    assert sale_audits[0].user_id == world.user_id
    assert "SALE" in sale_audits[0].details
    assert f"{sku}=9" in sale_audits[0].details

    return_audits = stock_changes(db_session, returned["transaction_id"])
    assert len(return_audits) == 1
    assert return_audits[0].entity_name == "pos_transaction"
    assert return_audits[0].user_id == world.user_id
    assert "RETURN" in return_audits[0].details
    assert f"{sku}=10" in return_audits[0].details


def test_ps04_1_duplicate_writes_no_stock_change(client, db_session) -> None:
    world = seed_sale(db_session, sold={f"TEST-SKU-{uid(8)}": 2})
    payload = sale_payload(world, [(world.skus[0], 1, 1000)])

    assert post(client, payload, world.token).status_code == 200
    duplicate = post(client, {**payload, "timestamp": "2026-11-15T03:15:00Z"}, world.token)

    assert duplicate.status_code == 200
    assert duplicate.json()["outcome"] == "DUPLICATE"
    assert len(stock_changes(db_session, payload["transaction_id"])) == 1


def test_ps04_2_forced_failure_writes_no_stock_change(client, db_session, monkeypatch) -> None:
    world = seed_sale(db_session, sold={f"TEST-SKU-{uid(8)}": 2}, stock=10)
    sku = world.skus[0]
    payload = sale_payload(world, [(sku, 1, 1000)])
    txn_id = payload["transaction_id"]

    def fail_once() -> None:
        raise OperationalError("simulated commit failure", {}, RuntimeError("offline"))

    monkeypatch.setattr(db_session, "commit", fail_once)

    with TestClient(app, raise_server_exceptions=False) as failing_client:
        response = post(failing_client, payload, world.token)

    assert_error(response, 503, "SERVICE_UNAVAILABLE")
    db_session.expire_all()
    assert count(db_session, PosTransaction, txn_id=txn_id) == 0
    assert stock(db_session, world, sku) == 10
    assert stock_changes(db_session, txn_id) == []
