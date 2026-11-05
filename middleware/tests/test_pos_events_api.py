"""POS SALE endpoint tests (PB-05-5), against the real SQL Server test DB.

The ``client`` fixture shares one session with the test, so every test creates
its own ``TEST-`` rows and commits them before calling the API. The fixture's
outer transaction still rolls everything back at teardown.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from math import ceil
from time import perf_counter
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core.security import create_token
from app.domain.models import (
    Inventory,
    InventoryMovement,
    PosTerminal,
    PosTransaction,
    Product,
    StaffUser,
    Store,
    TransactionItem,
)
from app.main import app
from app.services.idempotency import content_hash


URL = "/api/v1/pos/events"


@dataclass(frozen=True)
class World:
    store_id: str
    pos_id: str
    skus: list[str]
    username: str
    token: str


def _uid(length: int = 8) -> str:
    return uuid4().hex[:length].upper()


def _seed(session: Session, *, quantity: int = 10, products: int = 1) -> World:
    store_id = f"TEST-{_uid(5)}"
    pos_id = f"TEST-POS-{_uid(8)}"
    username = f"TEST-USER-{_uid(8)}"
    skus = [f"TEST-SKU-{_uid(8)}" for _ in range(products)]

    session.add(
        Store(
            store_id=store_id,
            name="POS event store",
            latitude=Decimal("10.500000"),
            longitude=Decimal("106.500000"),
            region_id="TEST",
        )
    )
    session.flush()
    for sku in skus:
        session.add(
            Product(
                sku=sku,
                barcode=f"BC-{sku}",
                name="POS event product",
                category="TEST",
                unit_price=Decimal("10.00"),
            )
        )
    session.flush()
    session.add(PosTerminal(pos_id=pos_id, store_id=store_id, status="ACTIVE"))
    session.add(
        StaffUser(
            username=username,
            full_name="POS event user",
            role="POS_SYSTEM",
            store_id=None,
        )
    )
    session.flush()
    for sku in skus:
        session.add(Inventory(store_id=store_id, sku=sku, quantity=quantity))
    session.flush()

    token = create_token(username, "POS", store_id=store_id, pos_id=pos_id)
    session.commit()
    return World(store_id, pos_id, skus, username, token)


def _payload(world: World, items: list[tuple[str, int, object]], *,
             txn_id: str | None = None, **overrides) -> dict:
    payload = {
        "event_type": "SALE",
        "transaction_id": txn_id if txn_id is not None else f"TXN-{_uid(10)}",
        "store_id": world.store_id,
        "pos_id": world.pos_id,
        "timestamp": "2026-11-14T03:15:00Z",
        "items": [
            {"sku": sku, "quantity": quantity, "unit_price": price}
            for sku, quantity, price in items
        ],
    }
    payload.update(overrides)
    return payload


def _post(client, payload: dict, token: str | None):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return client.post(URL, json=payload, headers=headers)


def _assert_error(response, status: int, code: str) -> None:
    assert response.status_code == status, response.text
    body = response.json()
    assert body["outcome"] == ("ERROR" if status == 503 else "REJECTED")
    assert body["code"] == code
    assert body["message"]


def _count(session: Session, model, **filters) -> int:
    statement = select(func.count()).select_from(model)
    for name, value in filters.items():
        statement = statement.where(getattr(model, name) == value)
    return session.scalar(statement)


def _transaction_items(session: Session, txn_id: str) -> list[TransactionItem]:
    return list(
        session.scalars(
            select(TransactionItem)
            .where(TransactionItem.txn_id == txn_id)
            .order_by(TransactionItem.item_id)
        )
    )


def _movements(session: Session, txn_id: str) -> list[InventoryMovement]:
    return list(
        session.scalars(
            select(InventoryMovement)
            .where(InventoryMovement.txn_id == txn_id)
            .order_by(InventoryMovement.movement_id)
        )
    )


def _assert_store_unchanged(session: Session, world: World, quantity: int = 10) -> None:
    session.expire_all()
    assert _count(session, PosTransaction, store_id=world.store_id) == 0
    assert _count(session, InventoryMovement, store_id=world.store_id) == 0
    for sku in world.skus:
        assert session.get(Inventory, (world.store_id, sku)).quantity == quantity


# --- accepted SALE ---------------------------------------------------------


def test_valid_sale_applies_stock_and_records_rows(client, db_session) -> None:
    world = _seed(db_session)
    sku = world.skus[0]
    payload = _payload(world, [(sku, 2, 7000)])
    txn_id = payload["transaction_id"]

    response = _post(client, payload, world.token)

    assert response.status_code == 200, response.text
    assert response.json() == {
        "outcome": "OK",
        "code": "OK",
        "message": "Event applied",
        "current_stock": {sku: 8},
    }
    db_session.expire_all()
    assert db_session.get(Inventory, (world.store_id, sku)).quantity == 8

    transaction = db_session.get(PosTransaction, txn_id)
    assert transaction is not None
    assert (
        transaction.store_id,
        transaction.pos_id,
        transaction.txn_type,
        transaction.status,
        transaction.ref_txn_id,
    ) == (world.store_id, world.pos_id, "SALE", "OK", None)
    expected_hash = content_hash(
        "SALE", world.store_id, world.pos_id, None, [(sku, 2, Decimal("7000.00"))]
    )
    assert transaction.payload_hash == expected_hash

    items = _transaction_items(db_session, txn_id)
    assert [(item.sku, item.qty, item.unit_price) for item in items] == [
        (sku, 2, Decimal("7000.00"))
    ]
    movements = _movements(db_session, txn_id)
    assert len(movements) == 1
    movement = movements[0]
    assert (
        movement.store_id,
        movement.sku,
        movement.movement_type,
        movement.quantity,
        movement.created_by,
        movement.reason,
        movement.batch_id,
    ) == (world.store_id, sku, "SALE", -2, None, None, None)


def test_several_and_repeated_skus_keep_lines_and_merge_stock(client, db_session) -> None:
    world = _seed(db_session, products=2)
    first, second = world.skus
    payload = _payload(world, [(first, 1, 1000), (second, 2, 2000), (first, 3, 1000)])
    txn_id = payload["transaction_id"]

    response = _post(client, payload, world.token)

    assert response.status_code == 200, response.text
    assert response.json()["current_stock"] == {first: 6, second: 8}
    db_session.expire_all()
    assert [(item.sku, item.qty) for item in _transaction_items(db_session, txn_id)] == [
        (first, 1),
        (second, 2),
        (first, 3),
    ]
    movements = {movement.sku: movement.quantity for movement in _movements(db_session, txn_id)}
    assert movements == {first: -4, second: -2}
    assert db_session.get(Inventory, (world.store_id, first)).quantity == 6
    assert db_session.get(Inventory, (world.store_id, second)).quantity == 8


# --- source check ----------------------------------------------------------


def test_unknown_store_or_terminal_returns_422(client, db_session) -> None:
    world = _seed(db_session)

    payload = _payload(world, [(world.skus[0], 1, 1000)])
    payload["store_id"] = "TEST-NOST"
    payload["pos_id"] = "TEST-NOPOS"
    response = _post(client, payload, world.token)
    _assert_error(response, 422, "UNREGISTERED_STORE_OR_POS")
    assert _count(db_session, PosTransaction, txn_id=payload["transaction_id"]) == 0

    payload = _payload(world, [(world.skus[0], 1, 1000)])
    payload["pos_id"] = "TEST-NOPOS"
    response = _post(client, payload, world.token)
    _assert_error(response, 422, "UNREGISTERED_STORE_OR_POS")
    assert _count(db_session, PosTransaction, txn_id=payload["transaction_id"]) == 0


def test_token_for_another_terminal_or_without_scope_returns_403(client, db_session) -> None:
    world = _seed(db_session)
    other_pos = f"TEST-POS-{_uid(8)}"
    db_session.add(PosTerminal(pos_id=other_pos, store_id=world.store_id, status="ACTIVE"))
    db_session.commit()

    payload = _payload(world, [(world.skus[0], 1, 1000)])
    other_token = create_token(world.username, "POS", store_id=world.store_id, pos_id=other_pos)
    response = _post(client, payload, other_token)
    _assert_error(response, 403, "FORBIDDEN")
    assert _count(db_session, PosTransaction, txn_id=payload["transaction_id"]) == 0

    scope_less = create_token(world.username, "POS")
    payload = _payload(world, [(world.skus[0], 1, 1000)])
    response = _post(client, payload, scope_less)
    _assert_error(response, 403, "FORBIDDEN")
    assert _count(db_session, PosTransaction, txn_id=payload["transaction_id"]) == 0


# --- field validation ------------------------------------------------------


def test_unknown_sku_returns_422_without_changes(client, db_session) -> None:
    world = _seed(db_session)
    payload = _payload(world, [("TEST-SKU-UNKNOWN", 1, 1000)])

    response = _post(client, payload, world.token)

    _assert_error(response, 422, "INVALID_EVENT")
    assert "items" in response.json()["message"]
    assert _count(db_session, PosTransaction, txn_id=payload["transaction_id"]) == 0
    db_session.expire_all()
    assert db_session.get(Inventory, (world.store_id, world.skus[0])).quantity == 10


@pytest.mark.parametrize("quantity", [0, -1, 1.5])
def test_invalid_quantity_returns_422(client, db_session, quantity) -> None:
    world = _seed(db_session)
    payload = _payload(world, [(world.skus[0], quantity, 1000)])

    response = _post(client, payload, world.token)

    _assert_error(response, 422, "INVALID_EVENT")
    assert _count(db_session, PosTransaction, txn_id=payload["transaction_id"]) == 0


@pytest.mark.parametrize("price", [1.234, -1, 10000000000.00])
def test_invalid_unit_price_returns_422(client, db_session, price) -> None:
    world = _seed(db_session)
    payload = _payload(world, [(world.skus[0], 1, price)])

    response = _post(client, payload, world.token)

    _assert_error(response, 422, "INVALID_EVENT")
    assert _count(db_session, PosTransaction, txn_id=payload["transaction_id"]) == 0


def test_missing_timestamp_returns_422(client, db_session) -> None:
    world = _seed(db_session)
    payload = _payload(world, [(world.skus[0], 1, 1000)])
    payload.pop("timestamp")

    response = _post(client, payload, world.token)

    _assert_error(response, 422, "INVALID_EVENT")
    assert "timestamp" in response.json()["message"]


@pytest.mark.parametrize("items", [None, []], ids=["omitted", "empty"])
def test_sale_requires_at_least_one_item(client, db_session, items) -> None:
    world = _seed(db_session)
    payload = _payload(world, [(world.skus[0], 1, 1000)])
    if items is None:
        payload.pop("items")
    else:
        payload["items"] = items

    response = _post(client, payload, world.token)

    _assert_error(response, 422, "INVALID_EVENT")
    assert "items" in response.json()["message"]
    assert _count(db_session, PosTransaction, txn_id=payload["transaction_id"]) == 0


def test_sale_must_not_carry_original_transaction_id(client, db_session) -> None:
    world = _seed(db_session)
    payload = _payload(world, [(world.skus[0], 1, 1000)],
                       original_transaction_id="TEST-ORIGINAL")

    response = _post(client, payload, world.token)

    _assert_error(response, 422, "INVALID_EVENT")
    assert "original_transaction_id" in response.json()["message"]
    assert _count(db_session, PosTransaction, txn_id=payload["transaction_id"]) == 0


@pytest.mark.parametrize("transaction_id", ["", "TXN-Á", "A" * 41])
def test_invalid_transaction_id_returns_422(client, db_session, transaction_id) -> None:
    world = _seed(db_session)
    payload = _payload(world, [(world.skus[0], 1, 1000)], txn_id=transaction_id)

    response = _post(client, payload, world.token)

    _assert_error(response, 422, "INVALID_EVENT")
    if transaction_id:
        assert _count(db_session, PosTransaction, txn_id=transaction_id) == 0


def test_more_than_100_items_returns_422(client, db_session) -> None:
    world = _seed(db_session)
    payload = _payload(
        world,
        [(world.skus[0], 1, 1000) for _ in range(101)],
    )

    response = _post(client, payload, world.token)

    _assert_error(response, 422, "INVALID_EVENT")
    assert _count(db_session, PosTransaction, txn_id=payload["transaction_id"]) == 0


def test_cancellation_with_unknown_original_is_rejected(client, db_session) -> None:
    world = _seed(db_session)
    payload = _payload(
        world,
        [(world.skus[0], 1, 1000)],
        event_type="CANCELLATION",
        original_transaction_id="TEST-ORIGINAL",
    )
    payload.pop("items", None)

    response = _post(client, payload, world.token)

    _assert_error(response, 404, "ORIGINAL_SALE_NOT_FOUND")
    assert response.json()["code"] == "ORIGINAL_SALE_NOT_FOUND"
    assert _count(db_session, PosTransaction, txn_id=payload["transaction_id"]) == 0


# --- stock and idempotency -------------------------------------------------


def test_insufficient_stock_rolls_back_every_item(client, db_session) -> None:
    world = _seed(db_session, products=2, quantity=3)
    first, second = sorted(world.skus)  # the service processes SKUs in this order
    payload = _payload(world, [(first, 1, 1000), (second, 4, 1000)])

    response = _post(client, payload, world.token)

    _assert_error(response, 409, "INSUFFICIENT_STOCK")
    db_session.expire_all()
    assert _count(db_session, PosTransaction, txn_id=payload["transaction_id"]) == 0
    assert _transaction_items(db_session, payload["transaction_id"]) == []
    assert _movements(db_session, payload["transaction_id"]) == []
    assert db_session.get(Inventory, (world.store_id, first)).quantity == 3
    assert db_session.get(Inventory, (world.store_id, second)).quantity == 3


def test_database_error_after_stock_change_is_503_and_retry_is_new(
    client, db_session, monkeypatch
) -> None:
    world = _seed(db_session)
    sku = world.skus[0]
    payload = _payload(world, [(sku, 2, 1000)])
    txn_id = payload["transaction_id"]

    original_commit = db_session.commit
    calls = {"count": 0}

    def flaky_commit() -> None:
        calls["count"] += 1
        if calls["count"] == 1:
            raise OperationalError("simulated commit failure", {}, RuntimeError("offline"))
        original_commit()

    monkeypatch.setattr(db_session, "commit", flaky_commit)

    with TestClient(app, raise_server_exceptions=False) as failing_client:
        response = _post(failing_client, payload, world.token)

    _assert_error(response, 503, "SERVICE_UNAVAILABLE")
    db_session.expire_all()
    assert _count(db_session, PosTransaction, txn_id=txn_id) == 0
    assert db_session.get(Inventory, (world.store_id, sku)).quantity == 10

    retry = _post(client, payload, world.token)

    assert retry.status_code == 200, retry.text
    assert retry.json()["outcome"] == "OK"
    db_session.expire_all()
    assert _count(db_session, PosTransaction, txn_id=txn_id) == 1
    assert db_session.get(Inventory, (world.store_id, sku)).quantity == 8


def test_duplicate_returns_current_stock_and_changes_nothing(client, db_session) -> None:
    world = _seed(db_session)
    sku = world.skus[0]
    payload = _payload(world, [(sku, 2, 1000)])
    txn_id = payload["transaction_id"]

    first = _post(client, payload, world.token)
    assert first.status_code == 200, first.text
    second = _post(client, {**payload, "timestamp": "2026-11-15T03:15:00Z"}, world.token)

    assert second.status_code == 200, second.text
    assert second.json() == {
        "outcome": "DUPLICATE",
        "code": "DUPLICATE_IGNORED",
        "message": "Transaction already recorded",
        "current_stock": {sku: 8},
    }
    db_session.expire_all()
    assert _count(db_session, PosTransaction, txn_id=txn_id) == 1
    assert len(_transaction_items(db_session, txn_id)) == 1
    assert len(_movements(db_session, txn_id)) == 1

    later = _payload(world, [(sku, 1, 1000)])
    assert _post(client, later, world.token).status_code == 200
    third = _post(client, payload, world.token)

    assert third.status_code == 200, third.text
    assert third.json()["current_stock"] == {sku: 7}
    db_session.expire_all()
    assert db_session.get(Inventory, (world.store_id, sku)).quantity == 7


def test_same_transaction_with_different_content_returns_conflict(client, db_session) -> None:
    world = _seed(db_session)
    sku = world.skus[0]
    payload = _payload(world, [(sku, 2, 1000)])
    txn_id = payload["transaction_id"]

    assert _post(client, payload, world.token).status_code == 200
    changed = _payload(world, [(sku, 3, 1000)], txn_id=txn_id)

    response = _post(client, changed, world.token)

    _assert_error(response, 409, "CONFLICT")
    db_session.expire_all()
    assert _count(db_session, PosTransaction, txn_id=txn_id) == 1
    assert len(_transaction_items(db_session, txn_id)) == 1
    assert len(_movements(db_session, txn_id)) == 1
    assert db_session.get(Inventory, (world.store_id, sku)).quantity == 8


# --- authentication and malformed JSON -------------------------------------


def _add_user(session: Session, role: str, store_id: str | None) -> str:
    username = f"TEST-USER-{_uid(8)}"
    session.add(
        StaffUser(username=username, full_name="POS event role user", role=role, store_id=store_id)
    )
    session.commit()
    return username


def test_authentication_and_role_matrix(client, db_session) -> None:
    world = _seed(db_session)
    other_pos = f"TEST-POS-{_uid(8)}"
    db_session.add(PosTerminal(pos_id=other_pos, store_id=world.store_id, status="ACTIVE"))
    db_session.commit()

    payload = _payload(world, [(world.skus[0], 1, 1000)])
    response = _post(client, payload, None)
    _assert_error(response, 401, "UNAUTHORIZED")
    assert _count(db_session, PosTransaction, txn_id=payload["transaction_id"]) == 0

    for db_role, api_role in [
        ("STORE_STAFF", "Staff"),
        ("STORE_MANAGER", "Manager"),
        ("HQ_OPERATOR", "HQ"),
        ("ADMIN", "Admin"),
        ("AUDITOR", "Auditor"),
    ]:
        username = _add_user(db_session, db_role, world.store_id)
        token = create_token(username, api_role, store_id=world.store_id, pos_id=world.pos_id)
        payload = _payload(world, [(world.skus[0], 1, 1000)])
        response = _post(client, payload, token)
        _assert_error(response, 403, "FORBIDDEN")
        assert _count(db_session, PosTransaction, txn_id=payload["transaction_id"]) == 0

    foreign_token = create_token(world.username, "POS", store_id=world.store_id, pos_id=other_pos)
    payload = _payload(world, [(world.skus[0], 1, 1000)])
    response = _post(client, payload, foreign_token)
    _assert_error(response, 403, "FORBIDDEN")
    assert _count(db_session, PosTransaction, txn_id=payload["transaction_id"]) == 0


@pytest.mark.parametrize("body_kind", ["empty", "array"])
def test_missing_or_non_object_body_returns_invalid_event(client, db_session, body_kind) -> None:
    world = _seed(db_session)
    headers = {"Authorization": f"Bearer {world.token}"}

    if body_kind == "empty":
        response = client.post(URL, headers=headers)
    else:
        response = client.post(URL, json=[], headers=headers)

    _assert_error(response, 422, "INVALID_EVENT")
    assert "body" in response.json()["message"]
    _assert_store_unchanged(db_session, world)


def test_malformed_json_is_validation_error_before_authentication(client, db_session) -> None:
    world = _seed(db_session)

    response = client.post(
        URL,
        content="{not-json",
        headers={"Content-Type": "application/json"},
    )

    _assert_error(response, 422, "VALIDATION_ERROR")
    _assert_store_unchanged(db_session, world)


# --- latency smoke check ---------------------------------------------------


def test_fifty_sequential_sales_have_p95_under_400_ms(client, db_session) -> None:
    world = _seed(db_session, quantity=100)
    sku = world.skus[0]
    latencies: list[float] = []

    for _ in range(50):
        payload = _payload(world, [(sku, 1, 1000)])
        started = perf_counter()
        response = _post(client, payload, world.token)
        latencies.append(perf_counter() - started)
        assert response.status_code == 200, response.text

    p95 = sorted(latencies)[max(0, ceil(0.95 * len(latencies)) - 1)] * 1000
    print(f"p95 latency: {p95:.2f} ms over {len(latencies)} requests")
    assert p95 < 400
    db_session.expire_all()
    assert db_session.get(Inventory, (world.store_id, sku)).quantity == 50
