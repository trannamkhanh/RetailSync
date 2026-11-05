"""POS07-1 to POS07-6: cancellation, retries and serialization with RETURN."""

from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.domain.models import (
    AuditLog, Inventory, InventoryMovement, PosTerminal, PosTransaction,
    Product, StaffUser, Store, TransactionItem,
)
from app.main import app
from app.repositories import original_sale as original_repository
from app.repositories import pos_cancellation as cancellation_repository
from app.services import pos_cancellation
from tests.pos_test_support import (
    add_sale, assert_error, count, movements, post, return_payload, sale_payload,
    seed_sale, stock, stock_changes, transaction_items, uid,
)


def cancellation(world, **overrides) -> dict:
    return {
        "event_type": "CANCELLATION", "transaction_id": f"TEST-CAN-{uid(12)}",
        "original_transaction_id": world.sale_txn, "store_id": world.store_id,
        "pos_id": world.pos_id, "timestamp": "2026-11-05T03:00:00Z", **overrides,
    }


def assert_not_saved(session, event) -> None:
    assert count(session, PosTransaction, txn_id=event["transaction_id"]) == 0
    assert transaction_items(session, event["transaction_id"]) == []
    assert movements(session, event["transaction_id"]) == []
    assert stock_changes(session, event["transaction_id"]) == []


def test_pos07_1_reverses_real_sale_copies_prices_and_audits_once(client, db_session):
    world = seed_sale(db_session)
    first, second = sorted(world.skus)
    sale = sale_payload(world, [(first, 1, "10.25"), (second, 2, "9.50"), (first, 2, "12.75")])
    assert post(client, sale, world.token).status_code == 200
    event = cancellation(world, original_transaction_id=sale["transaction_id"], items=[
        {"sku": "TEST-NOT-IN-SALE", "quantity": 999, "unit_price": 1},
    ])
    response = post(client, event, world.token)
    assert response.status_code == 200, response.text
    assert response.json() == {"outcome": "OK", "code": "OK", "message": "Event applied", "current_stock": {first: 10, second: 10}}
    db_session.expire_all()
    assert db_session.get(PosTransaction, sale["transaction_id"]).status == "CANCELLED"
    row = db_session.get(PosTransaction, event["transaction_id"])
    assert (row.txn_type, row.ref_txn_id, row.status) == ("CANCELLATION", sale["transaction_id"], "OK")
    assert [(i.sku, i.qty, i.unit_price) for i in transaction_items(db_session, event["transaction_id"])] == [
        (first, 1, Decimal("10.25")), (second, 2, Decimal("9.50")), (first, 2, Decimal("12.75")),
    ]
    assert [(m.sku, m.quantity, m.movement_type) for m in movements(db_session, event["transaction_id"])] == [
        (first, 3, "CANCELLATION"), (second, 2, "CANCELLATION"),
    ]
    audits = stock_changes(db_session, event["transaction_id"])
    assert len(audits) == 1 and audits[0].user_id == world.user_id
    assert "CANCELLATION" in audits[0].details


def test_pos07_4_second_cancellation_with_new_id_is_rejected(client, db_session):
    world = seed_sale(db_session)
    assert post(client, cancellation(world), world.token).status_code == 200
    event = cancellation(world)
    response = post(client, event, world.token)
    assert_error(response, 409, "SALE_ALREADY_CANCELLED")
    assert_not_saved(db_session, event)
    for sku, quantity in zip(world.skus, [12, 11]):
        assert stock(db_session, world, sku) == quantity


def test_pos07_5_sale_with_return_cannot_be_cancelled(client, db_session):
    world = seed_sale(db_session)
    returned = return_payload(world, [(world.skus[0], 1, 10)])
    assert post(client, returned, world.token).status_code == 200
    event = cancellation(world)
    assert_error(post(client, event, world.token), 409, "SALE_HAS_RETURNS")
    assert_not_saved(db_session, event)
    assert stock(db_session, world, world.skus[0]) == 11
    assert db_session.get(PosTransaction, world.sale_txn).status == "OK"


@pytest.mark.parametrize("source", ["unknown", "other-store", "not-sale"])
def test_pos07_6_original_must_be_sale_of_same_store(client, db_session, source):
    world = seed_sale(db_session)
    original = "TEST-NO-SALE"
    if source == "other-store":
        other = f"TEST-{uid(5)}"
        db_session.add(Store(store_id=other, name="Other", latitude=0, longitude=0, region_id="TEST"))
        db_session.flush()
        original = add_sale(db_session, other, world.pos_id, skus=[world.skus[0]])
    elif source == "not-sale":
        returned = return_payload(world, [(world.skus[0], 1, 10)])
        assert post(client, returned, world.token).status_code == 200
        original = returned["transaction_id"]
    event = cancellation(world, original_transaction_id=original)
    assert_error(post(client, event, world.token), 404, "ORIGINAL_SALE_NOT_FOUND")
    assert_not_saved(db_session, event)


def test_pb07_return_after_cancellation_is_rejected(client, db_session):
    world = seed_sale(db_session)
    assert post(client, cancellation(world), world.token).status_code == 200
    event = return_payload(world, [(world.skus[0], 1, 10)])
    assert_error(post(client, event, world.token), 409, "SALE_ALREADY_CANCELLED")
    assert_not_saved(db_session, event)
    assert stock(db_session, world, world.skus[0]) == 12


def test_pb07_resend_ignores_items_and_changes_stock_once(client, db_session):
    world = seed_sale(db_session)
    event = cancellation(world)
    assert post(client, event, world.token).status_code == 200
    changed = {**event, "timestamp": "2026-11-06T00:00:00Z", "items": [
        {"sku": "TEST-IGNORED", "quantity": 25, "unit_price": 123},
    ]}
    response = post(client, changed, world.token)
    assert response.status_code == 200, response.text
    assert response.json()["outcome"] == "DUPLICATE"
    assert response.json()["code"] == "DUPLICATE_IGNORED"
    assert response.json()["current_stock"] == {world.skus[0]: 12, world.skus[1]: 11}
    assert len(transaction_items(db_session, event["transaction_id"])) == 2
    assert len(movements(db_session, event["transaction_id"])) == 2
    assert len(stock_changes(db_session, event["transaction_id"])) == 1


@pytest.mark.parametrize("original", [None, "", " ", "é"])
def test_pb07_invalid_reference_is_422(client, db_session, original):
    world = seed_sale(db_session)
    event = cancellation(world, original_transaction_id=original)
    assert_error(post(client, event, world.token), 422, "INVALID_EVENT")
    assert_not_saved(db_session, event)


def test_pb07_failure_after_stock_change_rolls_back_and_can_retry(client, db_session, monkeypatch):
    world = seed_sale(db_session)
    event = cancellation(world)
    def fail(*args):
        raise OperationalError("mark cancelled failed", {}, RuntimeError("offline"))
    with monkeypatch.context() as patch:
        patch.setattr(cancellation_repository, "mark_cancelled", fail)
        with TestClient(app, raise_server_exceptions=False) as failing_client:
            assert_error(post(failing_client, event, world.token), 503, "SERVICE_UNAVAILABLE")
    assert_not_saved(db_session, event)
    assert stock(db_session, world, world.skus[0]) == 10
    assert db_session.get(PosTransaction, world.sale_txn).status == "OK"
    assert post(client, event, world.token).status_code == 200


def test_pb07_corrected_lock_order(client, db_session, monkeypatch):
    world = seed_sale(db_session)
    calls = []
    for name in ("require_original_sale", "lock_original_sale", "claim_transaction"):
        original = getattr(pos_cancellation, name)
        def traced(*args, _name=name, _original=original, **kwargs):
            calls.append(_name)
            return _original(*args, **kwargs)
        monkeypatch.setattr(pos_cancellation, name, traced)
    assert post(client, cancellation(world), world.token).status_code == 200
    assert calls == ["require_original_sale", "lock_original_sale", "claim_transaction", "lock_original_sale"]


def cleanup(engine, world, txn_ids):
    with Session(engine) as session:
        session.execute(delete(AuditLog).where(AuditLog.entity_key.in_(txn_ids)))
        session.execute(delete(InventoryMovement).where(InventoryMovement.txn_id.in_(txn_ids)))
        session.execute(delete(TransactionItem).where(TransactionItem.txn_id.in_(txn_ids + [world.sale_txn])))
        session.execute(delete(PosTransaction).where(PosTransaction.txn_id.in_(txn_ids)))
        session.execute(delete(PosTransaction).where(PosTransaction.txn_id == world.sale_txn))
        session.execute(delete(Inventory).where(Inventory.store_id == world.store_id))
        session.execute(delete(PosTerminal).where(PosTerminal.pos_id == world.pos_id))
        session.execute(delete(StaffUser).where(StaffUser.username == world.username))
        session.execute(delete(Product).where(Product.sku.in_(world.skus)))
        session.execute(delete(Store).where(Store.store_id == world.store_id))
        session.commit()


@pytest.mark.parametrize("competitor", ["RETURN", "CANCELLATION", "SAME-ID"])
def test_pb07_concurrent_events_serialize_without_deadlock(test_engine, monkeypatch, competitor):
    with Session(test_engine) as session:
        world = seed_sale(session, sold={f"TEST-SKU-{uid(8)}": 2})
    first = cancellation(world)
    second = (return_payload(world, [(world.skus[0], 1, 10)]) if competitor == "RETURN"
              else cancellation(world) if competitor == "CANCELLATION" else dict(first))
    ids = list({first["transaction_id"], second["transaction_id"]})
    barrier = Barrier(2)
    original_lock = original_repository.lock_sale
    def synchronized_lock(session, store_id, txn_id):
        if not session.info.get("original_lock_started"):
            session.info["original_lock_started"] = True
            barrier.wait(timeout=10)
        return original_lock(session, store_id, txn_id)
    monkeypatch.setattr(original_repository, "lock_sale", synchronized_lock)

    def independent_db() -> Generator[Session, None, None]:
        with Session(test_engine) as session:
            try:
                yield session
            except BaseException:
                session.rollback()
                raise
    previous = app.dependency_overrides.copy()
    app.dependency_overrides[get_db] = independent_db
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(post, client, event, world.token) for event in (first, second)]
                responses = [f.result(timeout=25) for f in futures]
        assert sorted(r.status_code for r in responses) == ([200, 200] if competitor == "SAME-ID" else [200, 409])
        winner = next(r for r in responses if r.json()["outcome"] == "OK")
        if competitor == "SAME-ID":
            assert sorted(r.json()["outcome"] for r in responses) == ["DUPLICATE", "OK"]
        else:
            rejected = next(r for r in responses if r.status_code == 409)
            assert rejected.json()["code"] in {"SALE_HAS_RETURNS", "SALE_ALREADY_CANCELLED"}
        with Session(test_engine) as verification:
            rows = list(verification.scalars(select(PosTransaction).where(PosTransaction.txn_id.in_(ids))))
            assert len(rows) == 1
            row = rows[0]
            expected_stock = 11 if row.txn_type == "RETURN" else 12
            assert winner.json()["current_stock"] == {world.skus[0]: expected_stock}
            assert stock(verification, world, world.skus[0]) == expected_stock
            assert verification.get(PosTransaction, world.sale_txn).status == ("OK" if row.txn_type == "RETURN" else "CANCELLED")
            assert len(movements(verification, row.txn_id)) == 1
            assert len(stock_changes(verification, row.txn_id)) == 1
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)
        cleanup(test_engine, world, ids)
