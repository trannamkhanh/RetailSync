"""INV10 and PB-10-4 end-to-end stock checks through the POS event API."""

from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier

from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import create_token
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
from app.main import app
from tests.pos_test_support import (
    World,
    assert_error,
    assert_ledger_balanced,
    count,
    movements,
    post,
    return_payload,
    sale_payload,
    stock,
    stock_changes,
    transaction_items,
    uid,
)


def _seed_world(session: Session, quantities: dict[str, int]) -> World:
    store_id = f"TEST-{uid(5)}"
    pos_id = f"TEST-POS-{uid(8)}"
    username = f"TEST-USER-{uid(8)}"
    skus = list(quantities)

    session.add(Store(
        store_id=store_id,
        name="Stock sequence test store",
        latitude=Decimal("10.500000"),
        longitude=Decimal("106.500000"),
        region_id="TEST",
    ))
    session.flush()
    for sku in skus:
        session.add(Product(
            sku=sku,
            barcode=f"BC-{sku}",
            name="Stock sequence test product",
            category="TEST",
            unit_price=Decimal("10.00"),
        ))
    session.flush()
    session.add(PosTerminal(pos_id=pos_id, store_id=store_id, status="ACTIVE"))
    user = StaffUser(
        username=username,
        full_name="Stock sequence test user",
        role="POS_SYSTEM",
        store_id=None,
    )
    session.add(user)
    session.flush()
    for sku, quantity in quantities.items():
        session.add(Inventory(store_id=store_id, sku=sku, quantity=quantity))
    session.commit()
    token = create_token(username, "POS", store_id=store_id, pos_id=pos_id)
    return World(store_id, pos_id, skus, username, token, "", user.user_id)


def _cancellation(world: World, original_id: str) -> dict:
    return {
        "event_type": "CANCELLATION",
        "transaction_id": f"TEST-CAN-{uid(10)}",
        "original_transaction_id": original_id,
        "store_id": world.store_id,
        "pos_id": world.pos_id,
        "timestamp": "2026-11-14T03:15:00Z",
        "items": [],
    }


def _assert_stock(session: Session, world: World, expected: dict[str, int]) -> None:
    assert set(expected) == set(world.skus)
    for sku, quantity in expected.items():
        assert stock(session, world, sku) == quantity


def _applied(client, db_session: Session, world: World, opening: dict[str, int],
             event: dict, response_stock: dict[str, int],
             expected_stock: dict[str, int]):
    response = post(client, event, world.token)
    assert response.status_code == 200, response.text
    assert response.json() == {
        "outcome": "OK",
        "code": "OK",
        "message": "Event applied",
        "current_stock": response_stock,
    }
    assert count(db_session, PosTransaction, txn_id=event["transaction_id"]) == 1
    assert len(stock_changes(db_session, event["transaction_id"])) == 1
    _assert_stock(db_session, world, expected_stock)
    assert_ledger_balanced(db_session, world.store_id, world.skus, opening)
    return response


def _rejected(client, db_session: Session, world: World, opening: dict[str, int],
              event: dict, status: int, code: str,
              expected_stock: dict[str, int]):
    response = post(client, event, world.token)
    assert_error(response, status, code)
    assert count(db_session, PosTransaction, txn_id=event["transaction_id"]) == 0
    assert transaction_items(db_session, event["transaction_id"]) == []
    assert movements(db_session, event["transaction_id"]) == []
    assert stock_changes(db_session, event["transaction_id"]) == []
    _assert_stock(db_session, world, expected_stock)
    assert_ledger_balanced(db_session, world.store_id, world.skus, opening)
    return response


def _duplicate_applied(client, db_session: Session, world: World,
                       opening: dict[str, int], event: dict,
                       response_stock: dict[str, int],
                       final_stock: dict[str, int]) -> None:
    txn_id = event["transaction_id"]
    before_movements = movements(db_session, txn_id)
    before_audits = stock_changes(db_session, txn_id)
    assert len(before_audits) == 1
    response = post(client, event, world.token)
    assert response.status_code == 200, response.text
    assert response.json() == {
        "outcome": "DUPLICATE",
        "code": "DUPLICATE_IGNORED",
        "message": "Transaction already recorded",
        "current_stock": response_stock,
    }
    assert movements(db_session, txn_id) == before_movements
    assert len(stock_changes(db_session, txn_id)) == len(before_audits) == 1
    _assert_stock(db_session, world, final_stock)
    assert_ledger_balanced(db_session, world.store_id, world.skus, opening)


def _resend_applied(client, db_session: Session, world: World,
                    opening: dict[str, int], applied_events: list[dict],
                    final_stock: dict[str, int]) -> None:
    for event in applied_events:
        items = transaction_items(db_session, event["transaction_id"])
        expected = {item.sku: final_stock[item.sku] for item in items}
        _duplicate_applied(client, db_session, world, opening, event, expected, final_stock)


def test_inv10_1_sale_updates_stock_and_writes_movement(client, db_session) -> None:
    sku = f"TEST-SKU-{uid()}"
    opening = {sku: 10}
    world = _seed_world(db_session, opening)
    event = sale_payload(world, [(sku, 2, "10.00")])

    _applied(client, db_session, world, opening, event, {sku: 8}, {sku: 8})

    movement = movements(db_session, event["transaction_id"])
    assert len(movement) == 1
    assert (movement[0].sku, movement[0].movement_type, movement[0].quantity) == (sku, "SALE", -2)


def test_inv10_2_sale_of_last_unit_leaves_zero_stock(client, db_session) -> None:
    sku = f"TEST-SKU-{uid()}"
    opening = {sku: 1}
    world = _seed_world(db_session, opening)
    event = sale_payload(world, [(sku, 1, "10.00")])

    _applied(client, db_session, world, opening, event, {sku: 0}, {sku: 0})


def test_inv10_3_sale_beyond_last_unit_is_rejected(client, db_session) -> None:
    sku = f"TEST-SKU-{uid()}"
    opening = {sku: 1}
    world = _seed_world(db_session, opening)
    last_unit = sale_payload(world, [(sku, 1, "10.00")])
    _applied(client, db_session, world, opening, last_unit, {sku: 0}, {sku: 0})

    one_more = sale_payload(world, [(sku, 1, "10.00")])
    _rejected(client, db_session, world, opening, one_more, 409,
              "INSUFFICIENT_STOCK", {sku: 0})


def test_inv10_4_parallel_sales_of_last_unit_have_one_winner(test_engine) -> None:
    sku = f"TEST-SKU-{uid()}"
    opening = {sku: 1}
    with Session(test_engine) as session:
        world = _seed_world(session, opening)
    first = sale_payload(world, [(sku, 1, "10.00")])
    second = sale_payload(world, [(sku, 1, "10.00")])
    event_ids = [first["transaction_id"], second["transaction_id"]]
    barrier = Barrier(2)

    def independent_db() -> Generator[Session, None, None]:
        with Session(test_engine) as session:
            try:
                yield session
            except BaseException:
                session.rollback()
                raise

    def send(client: TestClient, event: dict):
        barrier.wait(timeout=10)
        return post(client, event, world.token)

    previous = app.dependency_overrides.copy()
    app.dependency_overrides[get_db] = independent_db
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            with ThreadPoolExecutor(max_workers=2) as pool:
                responses = list(pool.map(lambda event: send(client, event), [first, second]))
        assert sorted(response.status_code for response in responses) == [200, 409]
        rejected = next(response for response in responses if response.status_code == 409)
        assert rejected.json()["code"] == "INSUFFICIENT_STOCK"
        success = next(response for response in responses if response.status_code == 200)
        assert success.json()["outcome"] == "OK"
        assert success.json()["current_stock"] == {sku: 0}
        with Session(test_engine) as verification:
            assert count(verification, PosTransaction, store_id=world.store_id) == 1
            successful_id = next(
                txn_id for txn_id in event_ids
                if count(verification, PosTransaction, txn_id=txn_id) == 1
            )
            failed_id = next(txn_id for txn_id in event_ids if txn_id != successful_id)
            assert len(movements(verification, successful_id)) == 1
            assert len(stock_changes(verification, successful_id)) == 1
            assert count(verification, PosTransaction, txn_id=failed_id) == 0
            assert movements(verification, failed_id) == []
            assert stock_changes(verification, failed_id) == []
            assert_ledger_balanced(verification, world.store_id, world.skus, opening)
            _assert_stock(verification, world, {sku: 0})
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)
        with Session(test_engine) as session:
            session.execute(delete(AuditLog).where(AuditLog.entity_key.in_(event_ids)))
            session.execute(delete(InventoryMovement).where(InventoryMovement.txn_id.in_(event_ids)))
            session.execute(delete(TransactionItem).where(TransactionItem.txn_id.in_(event_ids)))
            session.execute(delete(PosTransaction).where(PosTransaction.txn_id.in_(event_ids)))
            session.execute(delete(Inventory).where(Inventory.store_id == world.store_id))
            session.execute(delete(PosTerminal).where(PosTerminal.pos_id == world.pos_id))
            session.execute(delete(StaffUser).where(StaffUser.username == world.username))
            session.execute(delete(Product).where(Product.sku.in_(world.skus)))
            session.execute(delete(Store).where(Store.store_id == world.store_id))
            session.commit()


def test_inv10_5_short_last_basket_item_rolls_back_every_sku(client, db_session) -> None:
    first = f"TEST-SKU-A-{uid(5)}"
    last = f"TEST-SKU-B-{uid(5)}"
    opening = {first: 10, last: 1}
    world = _seed_world(db_session, opening)
    event = sale_payload(world, [(first, 1, "10.00"), (last, 2, "10.00")])

    _rejected(client, db_session, world, opening, event, 409,
              "INSUFFICIENT_STOCK", opening)


def test_inv10_6_sale_of_two_records_sale_movement_minus_two(client, db_session) -> None:
    sku = f"TEST-SKU-{uid()}"
    opening = {sku: 10}
    world = _seed_world(db_session, opening)
    event = sale_payload(world, [(sku, 2, "10.00")])

    _applied(client, db_session, world, opening, event, {sku: 8}, {sku: 8})

    [movement] = movements(db_session, event["transaction_id"])
    assert (movement.movement_type, movement.quantity) == ("SALE", -2)


def test_inv10_7_sell_return_sell_cancel_ends_at_36(client, db_session) -> None:
    sku = f"TEST-SKU-{uid()}"
    opening = {sku: 40}
    world = _seed_world(db_session, opening)

    sale_a = sale_payload(world, [(sku, 5, "10.00")])
    _applied(client, db_session, world, opening, sale_a, {sku: 35}, {sku: 35})
    returned = return_payload(
        world, [(sku, 1, "10.00")],
        original_transaction_id=sale_a["transaction_id"],
    )
    _applied(client, db_session, world, opening, returned, {sku: 36}, {sku: 36})
    sale_b = sale_payload(world, [(sku, 2, "10.00")])
    _applied(client, db_session, world, opening, sale_b, {sku: 34}, {sku: 34})
    cancelled = _cancellation(world, sale_b["transaction_id"])
    _applied(client, db_session, world, opening, cancelled, {sku: 36}, {sku: 36})


def test_pb10_4_sale_and_two_returns_balance_and_resend(client, db_session) -> None:
    sku = f"TEST-SKU-{uid()}"
    opening = {sku: 10}
    world = _seed_world(db_session, opening)
    sold = sale_payload(world, [(sku, 4, "10.00")])
    first_return = return_payload(
        world, [(sku, 1, "10.00")], original_transaction_id=sold["transaction_id"]
    )
    final_return = return_payload(
        world, [(sku, 3, "10.00")], original_transaction_id=sold["transaction_id"]
    )

    _applied(client, db_session, world, opening, sold, {sku: 6}, {sku: 6})
    _applied(client, db_session, world, opening, first_return, {sku: 7}, {sku: 7})
    _applied(client, db_session, world, opening, final_return, {sku: 10}, {sku: 10})
    _resend_applied(client, db_session, world, opening,
                    [sold, first_return, final_return], {sku: 10})


def test_pb10_4_sale_and_cancellation_balance_and_resend(client, db_session) -> None:
    sku = f"TEST-SKU-{uid()}"
    opening = {sku: 10}
    world = _seed_world(db_session, opening)
    sold = sale_payload(world, [(sku, 4, "10.00")])
    cancelled = _cancellation(world, sold["transaction_id"])

    _applied(client, db_session, world, opening, sold, {sku: 6}, {sku: 6})
    _applied(client, db_session, world, opening, cancelled, {sku: 10}, {sku: 10})
    _resend_applied(client, db_session, world, opening, [sold, cancelled], {sku: 10})


def test_pb10_4_cancel_first_sale_then_return_part_of_second(client, db_session) -> None:
    sku = f"TEST-SKU-{uid()}"
    opening = {sku: 20}
    world = _seed_world(db_session, opening)
    sale_a = sale_payload(world, [(sku, 3, "10.00")])
    sale_b = sale_payload(world, [(sku, 5, "10.00")])
    cancellation_a = _cancellation(world, sale_a["transaction_id"])
    return_b = return_payload(
        world, [(sku, 2, "10.00")], original_transaction_id=sale_b["transaction_id"]
    )

    _applied(client, db_session, world, opening, sale_a, {sku: 17}, {sku: 17})
    _applied(client, db_session, world, opening, sale_b, {sku: 12}, {sku: 12})
    _applied(client, db_session, world, opening, cancellation_a, {sku: 15}, {sku: 15})
    _applied(client, db_session, world, opening, return_b, {sku: 17}, {sku: 17})
    _resend_applied(client, db_session, world, opening,
                    [sale_a, sale_b, cancellation_a, return_b], {sku: 17})


def test_pb10_4_returned_sale_cannot_be_cancelled(client, db_session) -> None:
    sku = f"TEST-SKU-{uid()}"
    opening = {sku: 10}
    world = _seed_world(db_session, opening)
    sold = sale_payload(world, [(sku, 4, "10.00")])
    returned = return_payload(
        world, [(sku, 1, "10.00")], original_transaction_id=sold["transaction_id"]
    )
    cancellation = _cancellation(world, sold["transaction_id"])

    _applied(client, db_session, world, opening, sold, {sku: 6}, {sku: 6})
    _applied(client, db_session, world, opening, returned, {sku: 7}, {sku: 7})
    _rejected(client, db_session, world, opening, cancellation, 409,
              "SALE_HAS_RETURNS", {sku: 7})
    _resend_applied(client, db_session, world, opening, [sold, returned], {sku: 7})


def test_pb10_4_cancelled_sale_cannot_be_returned(client, db_session) -> None:
    sku = f"TEST-SKU-{uid()}"
    opening = {sku: 10}
    world = _seed_world(db_session, opening)
    sold = sale_payload(world, [(sku, 4, "10.00")])
    cancellation = _cancellation(world, sold["transaction_id"])
    returned = return_payload(
        world, [(sku, 1, "10.00")], original_transaction_id=sold["transaction_id"]
    )

    _applied(client, db_session, world, opening, sold, {sku: 6}, {sku: 6})
    _applied(client, db_session, world, opening, cancellation, {sku: 10}, {sku: 10})
    _rejected(client, db_session, world, opening, returned, 409,
              "SALE_ALREADY_CANCELLED", {sku: 10})
    _resend_applied(client, db_session, world, opening, [sold, cancellation], {sku: 10})


def test_pb10_4_return_allows_sale_retry_after_stock_exhaustion(client, db_session) -> None:
    sku = f"TEST-SKU-{uid()}"
    opening = {sku: 1}
    world = _seed_world(db_session, opening)
    sold = sale_payload(world, [(sku, 1, "10.00")])
    retry = sale_payload(world, [(sku, 1, "10.00")])
    returned = return_payload(
        world, [(sku, 1, "10.00")], original_transaction_id=sold["transaction_id"]
    )

    _applied(client, db_session, world, opening, sold, {sku: 0}, {sku: 0})
    _rejected(client, db_session, world, opening, retry, 409,
              "INSUFFICIENT_STOCK", {sku: 0})
    _applied(client, db_session, world, opening, returned, {sku: 1}, {sku: 1})
    _applied(client, db_session, world, opening, retry, {sku: 0}, {sku: 0})
    _resend_applied(client, db_session, world, opening, [sold, returned, retry], {sku: 0})


def test_pb10_4_repeated_sku_basket_partial_return_and_remainder(client, db_session) -> None:
    first, second, third = (f"TEST-SKU-{label}-{uid(5)}" for label in "ABC")
    opening = {first: 8, second: 8, third: 8}
    world = _seed_world(db_session, opening)
    sold = sale_payload(world, [
        (first, 2, "10.00"), (second, 3, "10.00"),
        (first, 1, "10.00"), (third, 4, "10.00"),
    ])
    partial = return_payload(
        world, [(first, 2, "10.00"), (second, 1, "10.00")],
        original_transaction_id=sold["transaction_id"],
    )
    remainder = return_payload(
        world, [(first, 1, "10.00"), (second, 2, "10.00"), (third, 4, "10.00")],
        original_transaction_id=sold["transaction_id"],
    )

    _applied(client, db_session, world, opening, sold,
             {first: 5, second: 5, third: 4}, {first: 5, second: 5, third: 4})
    _applied(client, db_session, world, opening, partial,
             {first: 7, second: 6}, {first: 7, second: 6, third: 4})
    _applied(client, db_session, world, opening, remainder,
             {first: 8, second: 8, third: 8}, {first: 8, second: 8, third: 8})
    _resend_applied(client, db_session, world, opening,
                    [sold, partial, remainder], {first: 8, second: 8, third: 8})
