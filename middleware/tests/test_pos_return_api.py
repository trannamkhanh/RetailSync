"""RETURN endpoint tests (PB-06-4), against the real SQL Server test database."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.api.schemas.pos import PosEvent
from app.core.errors import ApiError
from app.core.security import Principal
from app.domain.models import (
    AuditLog,
    Inventory,
    InventoryMovement,
    PosTerminal,
    PosTransaction,
    Product,
    StaffUser,
    Store,
    TransactionItem,
)
from app.services.idempotency import content_hash
from app.services.pos_events import process_event
from tests.pos_test_support import (
    add_sale,
    assert_error,
    count,
    movements,
    post,
    return_payload,
    seed_sale,
    stock,
    stock_changes,
    transaction_items,
    uid,
)


def test_pos06_1_valid_return_increases_stock_and_records_rows(client, db_session) -> None:
    world = seed_sale(db_session, sold={f"TEST-SKU-{uid(8)}": 2}, stock=10)
    sku = world.skus[0]
    payload = return_payload(world, [(sku, 1, 10.0)])
    txn_id = payload["transaction_id"]

    response = post(client, payload, world.token)

    assert response.status_code == 200, response.text
    assert response.json() == {
        "outcome": "OK",
        "code": "OK",
        "message": "Event applied",
        "current_stock": {sku: 11},
    }
    db_session.expire_all()
    assert stock(db_session, world, sku) == 11

    transaction = db_session.get(PosTransaction, txn_id)
    assert transaction is not None
    assert (
        transaction.txn_type,
        transaction.status,
        transaction.ref_txn_id,
        transaction.store_id,
        transaction.pos_id,
    ) == ("RETURN", "OK", world.sale_txn, world.store_id, world.pos_id)
    assert transaction.payload_hash == content_hash(
        "RETURN", world.store_id, world.pos_id, world.sale_txn,
        [(sku, 1, Decimal("10.00"))],
    )

    assert [(item.sku, item.qty, item.unit_price) for item in transaction_items(db_session, txn_id)] == [
        (sku, 1, Decimal("10.00"))
    ]
    return_movements = movements(db_session, txn_id)
    assert len(return_movements) == 1
    assert (return_movements[0].movement_type, return_movements[0].quantity) == ("RETURN", 1)

    audits = stock_changes(db_session, txn_id)
    assert len(audits) == 1
    assert audits[0].entity_name == "pos_transaction"
    assert audits[0].user_id == world.user_id
    assert "RETURN" in audits[0].details
    assert f"{sku}=11" in audits[0].details


def test_pos06_2_unknown_original_sale_returns_404(client, db_session) -> None:
    world = seed_sale(db_session, sold={f"TEST-SKU-{uid(8)}": 2})
    payload = return_payload(
        world, [(world.skus[0], 1, 1000)], original_transaction_id="TEST-NOSALE"
    )

    response = post(client, payload, world.token)

    assert_error(response, 404, "ORIGINAL_SALE_NOT_FOUND")
    assert count(db_session, PosTransaction, txn_id=payload["transaction_id"]) == 0
    assert stock_changes(db_session, payload["transaction_id"]) == []


def test_pos06_5_sale_of_another_store_returns_404(client, db_session) -> None:
    world = seed_sale(db_session, sold={f"TEST-SKU-{uid(8)}": 2})
    other_store = f"TEST-{uid(5)}"
    db_session.add(
        Store(
            store_id=other_store,
            name="Other return store",
            latitude=Decimal("10.500000"),
            longitude=Decimal("106.500000"),
            region_id="TEST",
        )
    )
    db_session.flush()
    other_sale = add_sale(db_session, other_store, world.pos_id, skus=[world.skus[0]])
    payload = return_payload(world, [(world.skus[0], 1, 1000)],
                             original_transaction_id=other_sale)

    response = post(client, payload, world.token)

    assert_error(response, 404, "ORIGINAL_SALE_NOT_FOUND")
    assert count(db_session, PosTransaction, txn_id=payload["transaction_id"]) == 0


def test_pb06_reference_to_a_return_returns_404(client, db_session) -> None:
    world = seed_sale(db_session, sold={f"TEST-SKU-{uid(8)}": 2})
    return_txn = f"TEST-RET-{uid(8)}"
    db_session.add(
        PosTransaction(
            txn_id=return_txn,
            store_id=world.store_id,
            pos_id=world.pos_id,
            txn_type="RETURN",
            ref_txn_id=world.sale_txn,
            status="OK",
            payload_hash="0" * 64,
        )
    )
    db_session.commit()
    payload = return_payload(world, [(world.skus[0], 1, 1000)],
                             original_transaction_id=return_txn)

    response = post(client, payload, world.token)

    assert_error(response, 404, "ORIGINAL_SALE_NOT_FOUND")
    assert count(db_session, PosTransaction, txn_id=payload["transaction_id"]) == 0


def test_pos06_3_partial_return_then_limit_and_exact_rest(client, db_session) -> None:
    world = seed_sale(db_session, sold={f"TEST-SKU-{uid(8)}": 2}, stock=10)
    sku = world.skus[0]

    first = return_payload(world, [(sku, 1, 1000)])
    assert post(client, first, world.token).status_code == 200
    assert stock(db_session, world, sku) == 11

    too_many = return_payload(world, [(sku, 2, 1000)])
    response = post(client, too_many, world.token)
    assert_error(response, 409, "RETURN_QTY_EXCEEDED")
    assert stock(db_session, world, sku) == 11
    assert count(db_session, PosTransaction, txn_id=too_many["transaction_id"]) == 0
    assert stock_changes(db_session, too_many["transaction_id"]) == []

    exact_rest = return_payload(world, [(sku, 1, 1000)])
    assert post(client, exact_rest, world.token).status_code == 200
    assert stock(db_session, world, sku) == 12


def test_pb06_sku_not_in_sale_returns_409(client, db_session) -> None:
    world = seed_sale(db_session, sold={f"TEST-SKU-{uid(8)}": 2})
    outside_sku = f"TEST-SKU-{uid(8)}"
    db_session.add(
        Product(
            sku=outside_sku,
            barcode=f"BC-{outside_sku}",
            name="Outside product",
            category="TEST",
            unit_price=Decimal("10.00"),
        )
    )
    db_session.flush()
    db_session.add(Inventory(store_id=world.store_id, sku=outside_sku, quantity=10))
    db_session.commit()

    payload = return_payload(world, [(outside_sku, 1, 1000)])
    response = post(client, payload, world.token)

    assert_error(response, 409, "RETURN_QTY_EXCEEDED")
    assert count(db_session, PosTransaction, txn_id=payload["transaction_id"]) == 0


def test_pos06_4_cancelled_sale_returns_409(client, db_session) -> None:
    world = seed_sale(db_session, sold={f"TEST-SKU-{uid(8)}": 2}, status="CANCELLED")
    payload = return_payload(world, [(world.skus[0], 1, 1000)])

    response = post(client, payload, world.token)

    assert_error(response, 409, "SALE_ALREADY_CANCELLED")
    assert count(db_session, PosTransaction, txn_id=payload["transaction_id"]) == 0
    assert stock_changes(db_session, payload["transaction_id"]) == []


@pytest.mark.parametrize("case", ["missing-original", "missing-items", "empty-items"])
def test_pb06_4_missing_fields_return_422(client, db_session, case) -> None:
    world = seed_sale(db_session, sold={f"TEST-SKU-{uid(8)}": 2})
    payload = return_payload(world, [(world.skus[0], 1, 1000)])
    if case == "missing-original":
        payload.pop("original_transaction_id")
    elif case == "missing-items":
        payload.pop("items")
    else:
        payload["items"] = []

    response = post(client, payload, world.token)

    assert_error(response, 422, "INVALID_EVENT")
    assert count(db_session, PosTransaction, txn_id=payload["transaction_id"]) == 0
    assert stock_changes(db_session, payload["transaction_id"]) == []


def test_pb06_resend_is_duplicate_and_changes_stock_once(client, db_session) -> None:
    world = seed_sale(db_session, sold={f"TEST-SKU-{uid(8)}": 2})
    sku = world.skus[0]
    payload = return_payload(world, [(sku, 1, 1000)])

    assert post(client, payload, world.token).status_code == 200
    response = post(client, {**payload, "timestamp": "2026-11-15T03:15:00Z"}, world.token)

    assert response.status_code == 200, response.text
    assert response.json()["outcome"] == "DUPLICATE"
    assert response.json()["code"] == "DUPLICATE_IGNORED"
    assert stock(db_session, world, sku) == 11
    assert count(db_session, PosTransaction, txn_id=payload["transaction_id"]) == 1
    assert len(transaction_items(db_session, payload["transaction_id"])) == 1
    assert len(movements(db_session, payload["transaction_id"])) == 1
    assert len(stock_changes(db_session, payload["transaction_id"])) == 1


def test_pb06_concurrent_returns_cannot_exceed_sale(test_engine) -> None:
    sku = f"TEST-SKU-{uuid4().hex[:8].upper()}"
    with Session(test_engine) as setup:
        world = seed_sale(setup, sold={sku: 3}, stock=10)
    txn_ids = [f"TEST-RET-{uuid4().hex[:8].upper()}" for _ in range(2)]
    barrier = Barrier(2)

    def event(txn_id: str) -> PosEvent:
        return PosEvent.model_validate({
            "event_type": "RETURN",
            "transaction_id": txn_id,
            "original_transaction_id": world.sale_txn,
            "store_id": world.store_id,
            "pos_id": world.pos_id,
            "timestamp": "2026-11-14T03:15:00Z",
            "items": [{"sku": sku, "quantity": 2, "unit_price": 1000}],
        })

    principal = Principal(world.username, "POS", world.store_id, world.pos_id)

    def run(txn_id: str) -> str:
        with Session(test_engine) as session:
            try:
                barrier.wait(timeout=10)
                process_event(session, event(txn_id), principal)
                session.commit()
                return "OK"
            except ApiError as error:
                session.rollback()
                return error.code

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = sorted(pool.map(run, txn_ids))

        assert outcomes == ["OK", "RETURN_QTY_EXCEEDED"]
        with Session(test_engine) as verification:
            assert verification.get(Inventory, (world.store_id, sku)).quantity == 12
            accepted_rows = verification.execute(
                select(PosTransaction).where(PosTransaction.txn_id.in_(txn_ids))
            ).scalars().all()
            assert len(accepted_rows) == 1
            accepted_id = accepted_rows[0].txn_id
            assert len(movements(verification, accepted_id)) == 1
            assert len(stock_changes(verification, accepted_id)) == 1
    finally:
        with Session(test_engine) as cleanup:
            cleanup.execute(delete(AuditLog).where(AuditLog.entity_key.in_(txn_ids)))
            cleanup.execute(delete(InventoryMovement).where(InventoryMovement.txn_id.in_(txn_ids)))
            cleanup.execute(delete(TransactionItem).where(TransactionItem.txn_id.in_(txn_ids + [world.sale_txn])))
            cleanup.execute(delete(PosTransaction).where(PosTransaction.txn_id.in_(txn_ids)))
            cleanup.execute(delete(PosTransaction).where(PosTransaction.txn_id == world.sale_txn))
            cleanup.execute(delete(Inventory).where(Inventory.store_id == world.store_id))
            cleanup.execute(delete(PosTerminal).where(PosTerminal.pos_id == world.pos_id))
            cleanup.execute(delete(Product).where(Product.sku == sku))
            cleanup.execute(delete(StaffUser).where(StaffUser.username == world.username))
            cleanup.execute(delete(Store).where(Store.store_id == world.store_id))
            cleanup.commit()
