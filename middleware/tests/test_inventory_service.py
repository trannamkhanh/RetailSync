"""Stock service tests: atomic changes, movement rows, deduction and races.

The brief (PB-10-1, PB-10-2, PB-10-3) fixes the contract; these tests run
against the real ``RTS_DB_TEST`` database through the ``db_session`` fixture.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from decimal import Decimal
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.domain.models import (
    Inventory,
    InventoryMovement,
    PosTerminal,
    PosTransaction,
    Product,
    ProductBatch,
    StaffUser,
    Store,
)
from app.repositories.inventory import get_stock as repository_get_stock
from app.services.inventory import apply_stock_change, deduct_items, get_stock
from tests.pos_test_support import add_stock


def _uid(length: int = 8) -> str:
    return uuid4().hex[:length].upper()


@dataclass
class StockWorld:
    store_id: str
    pos_id: str
    skus: list[str]
    txn_ids: list[str]
    user_id: int


def _seed(
    session: Session,
    *,
    quantities: dict[str, int] | None = None,
    transactions: int = 1,
    commit: bool = True,
) -> StockWorld:
    """Create one store, two products, one terminal and the stock rows."""
    store_id = f"TEST-{_uid(5)}"
    pos_id = f"TEST-POS-{_uid(8)}"
    skus = [f"TEST-SKU-{_uid(8)}", f"TEST-SKU-{_uid(8)}"]
    if quantities is None:
        quantities = {skus[0]: 10, skus[1]: 5}

    session.add(
        Store(
            store_id=store_id,
            name="Test Stock Store",
            latitude=Decimal("10.500000"),
            longitude=Decimal("106.500000"),
            region_id="TEST",
        )
    )
    for sku in skus:
        session.add(
            Product(
                sku=sku,
                barcode=f"BC-{sku}",
                name="Test Stock Product",
                category="TEST",
                unit_price=Decimal("10.00"),
            )
        )
    # The ORM orders INSERTs by relationships, not by raw foreign keys, so
    # flush each parent level before adding its children.
    session.flush()

    session.add(PosTerminal(pos_id=pos_id, store_id=store_id, status="ACTIVE"))
    user = StaffUser(
        username=f"TEST-USER-{_uid(8)}",
        full_name="Test Stock User",
        role="STORE_STAFF",
        store_id=store_id,
    )
    session.add(user)
    session.flush()

    for sku, quantity in quantities.items():
        add_stock(session, store_id, sku, quantity)

    txn_ids: list[str] = []
    for _ in range(transactions):
        txn_id = f"TEST-TXN-{_uid(8)}"
        session.add(
            PosTransaction(
                txn_id=txn_id,
                store_id=store_id,
                pos_id=pos_id,
                txn_type="SALE",
                status="OK",
                payload_hash="0" * 64,
            )
        )
        txn_ids.append(txn_id)

    session.flush()
    if commit:
        # The fixture still rolls back the outer transaction; committing here
        # only protects the seed from a rollback later in a test.
        session.commit()

    return StockWorld(
        store_id=store_id,
        pos_id=pos_id,
        skus=skus,
        txn_ids=txn_ids,
        user_id=user.user_id,
    )


def _movements(session: Session, store_id: str) -> list[InventoryMovement]:
    return list(
        session.execute(
            select(InventoryMovement)
            .where(InventoryMovement.store_id == store_id)
            .order_by(InventoryMovement.movement_id)
        ).scalars()
    )


# ---- apply_stock_change ----------------------------------------------------


def test_apply_stock_change_decreases_stock_and_returns_new_quantity(db_session: Session) -> None:
    world = _seed(db_session)
    sku = world.skus[0]

    new_quantity = apply_stock_change(
        db_session,
        store_id=world.store_id,
        sku=sku,
        delta=-3,
        movement_type="SALE",
        txn_id=world.txn_ids[0],
        created_by=world.user_id,
        reason="unit test sale",
    )

    assert new_quantity == 7
    assert get_stock(db_session, world.store_id, sku) == 7
    assert repository_get_stock(db_session, world.store_id, sku) == 7


def test_apply_stock_change_increases_stock(db_session: Session) -> None:
    world = _seed(db_session)
    sku = world.skus[0]

    assert (
        apply_stock_change(
            db_session,
            store_id=world.store_id,
            sku=sku,
            delta=5,
            movement_type="STOCK_RECEIVED",
            reason="restock",
        )
        == 15
    )
    assert get_stock(db_session, world.store_id, sku) == 15


def test_stock_can_reach_exactly_zero(db_session: Session) -> None:
    world = _seed(db_session, quantities={})
    sku = world.skus[0]
    add_stock(db_session, world.store_id, sku, 5)

    new_quantity = apply_stock_change(
        db_session,
        store_id=world.store_id,
        sku=sku,
        delta=-5,
        movement_type="SALE",
        txn_id=world.txn_ids[0],
    )

    assert new_quantity == 0
    assert get_stock(db_session, world.store_id, sku) == 0


def test_selling_more_than_stock_is_rejected_without_change(db_session: Session) -> None:
    world = _seed(db_session)
    sku = world.skus[0]

    with pytest.raises(ApiError) as error:
        apply_stock_change(
            db_session,
            store_id=world.store_id,
            sku=sku,
            delta=-11,
            movement_type="SALE",
            txn_id=world.txn_ids[0],
        )

    assert error.value.status == 409
    assert error.value.code == "INSUFFICIENT_STOCK"
    assert get_stock(db_session, world.store_id, sku) == 10
    assert _movements(db_session, world.store_id) == []


def test_negative_change_for_a_missing_row_is_insufficient_stock(db_session: Session) -> None:
    world = _seed(db_session, quantities={})
    sku = world.skus[0]

    with pytest.raises(ApiError) as error:
        apply_stock_change(
            db_session,
            store_id=world.store_id,
            sku=sku,
            delta=-1,
            movement_type="SALE",
            txn_id=world.txn_ids[0],
        )

    assert error.value.code == "INSUFFICIENT_STOCK"
    assert get_stock(db_session, world.store_id, sku) == 0
    assert _movements(db_session, world.store_id) == []


def test_positive_change_for_a_missing_row_inserts_it(db_session: Session) -> None:
    world = _seed(db_session, quantities={})
    sku = world.skus[0]

    new_quantity = apply_stock_change(
        db_session,
        store_id=world.store_id,
        sku=sku,
        delta=7,
        movement_type="STOCK_RECEIVED",
    )

    assert new_quantity == 7
    assert get_stock(db_session, world.store_id, sku) == 7


def test_delta_zero_is_rejected(db_session: Session) -> None:
    world = _seed(db_session)
    with pytest.raises(ValueError):
        apply_stock_change(
            db_session,
            store_id=world.store_id,
            sku=world.skus[0],
            delta=0,
            movement_type="ADJUSTMENT",
        )


def test_unknown_movement_type_is_rejected(db_session: Session) -> None:
    world = _seed(db_session)
    with pytest.raises(ValueError):
        apply_stock_change(
            db_session,
            store_id=world.store_id,
            sku=world.skus[0],
            delta=1,
            movement_type="TELEPORT",
        )


def test_movement_row_records_signed_quantity_and_context(db_session: Session) -> None:
    world = _seed(db_session)
    sku = world.skus[0]

    apply_stock_change(
        db_session,
        store_id=world.store_id,
        sku=sku,
        delta=-4,
        movement_type="SALE",
        txn_id=world.txn_ids[0],
        created_by=world.user_id,
        reason="cashier rang it up",
    )

    [movement] = _movements(db_session, world.store_id)
    assert movement.quantity == -4
    assert movement.movement_type == "SALE"
    assert movement.txn_id == world.txn_ids[0]
    assert movement.created_by == world.user_id
    assert movement.reason == "cashier rang it up"
    assert movement.batch_id is None


def test_apply_stock_change_leaves_the_commit_to_the_caller(db_session: Session) -> None:
    world = _seed(db_session)
    sku = world.skus[0]

    apply_stock_change(
        db_session,
        store_id=world.store_id,
        sku=sku,
        delta=-2,
        movement_type="SALE",
        txn_id=world.txn_ids[0],
    )
    assert get_stock(db_session, world.store_id, sku) == 8

    db_session.rollback()

    assert get_stock(db_session, world.store_id, sku) == 10
    assert _movements(db_session, world.store_id) == []


# ---- deduct_items -----------------------------------------------------------


def test_deduct_items_handles_several_skus(db_session: Session) -> None:
    world = _seed(db_session)
    first, second = world.skus

    new_quantities = deduct_items(
        db_session,
        world.store_id,
        [(first, 3), (second, 2)],
        world.txn_ids[0],
    )

    assert new_quantities == {first: 7, second: 3}
    assert get_stock(db_session, world.store_id, first) == 7
    assert get_stock(db_session, world.store_id, second) == 3
    movements = _movements(db_session, world.store_id)
    assert [(m.sku, m.movement_type, m.quantity) for m in movements] == sorted(
        [(first, "SALE", -3), (second, "SALE", -2)]
    )


def test_deduct_items_merges_repeated_skus(db_session: Session) -> None:
    world = _seed(db_session)
    sku = world.skus[0]

    new_quantities = deduct_items(
        db_session,
        world.store_id,
        [(sku, 2), (sku, 3)],
        world.txn_ids[0],
    )

    assert new_quantities == {sku: 5}
    movements = _movements(db_session, world.store_id)
    assert [(m.movement_type, m.quantity) for m in movements] == [("SALE", -5)]


def test_deduct_items_failure_rolls_back_every_sku(db_session: Session) -> None:
    world = _seed(db_session, quantities={})
    first, second = sorted(world.skus)  # the service processes SKUs in this order
    add_stock(db_session, world.store_id, first, 10)
    add_stock(db_session, world.store_id, second, 1)
    db_session.commit()

    with pytest.raises(ApiError) as error:
        deduct_items(
            db_session,
            world.store_id,
            [(first, 1), (second, 2)],
            world.txn_ids[0],
        )

    assert error.value.code == "INSUFFICIENT_STOCK"
    db_session.rollback()
    assert get_stock(db_session, world.store_id, first) == 10
    assert get_stock(db_session, world.store_id, second) == 1
    assert _movements(db_session, world.store_id) == []


@pytest.mark.parametrize("quantity", [0, -1])
def test_deduct_items_rejects_non_positive_quantity(db_session: Session, quantity: int) -> None:
    world = _seed(db_session)
    with pytest.raises(ValueError):
        deduct_items(db_session, world.store_id, [(world.skus[0], quantity)], world.txn_ids[0])


def test_deduct_items_rejects_an_empty_basket(db_session: Session) -> None:
    world = _seed(db_session)
    with pytest.raises(ValueError):
        deduct_items(db_session, world.store_id, [], world.txn_ids[0])


# ---- get_stock ---------------------------------------------------------------


def test_get_stock_returns_zero_for_a_missing_row(db_session: Session) -> None:
    world = _seed(db_session, quantities={})
    assert get_stock(db_session, world.store_id, world.skus[0]) == 0


# ---- concurrency -------------------------------------------------------------


def _cleanup(engine, store_id: str, sku: str, txn_ids: list[str]) -> None:
    """Remove the rows the concurrency test commits for real."""
    with Session(engine) as session:
        session.execute(delete(InventoryMovement).where(InventoryMovement.store_id == store_id))
        session.execute(delete(PosTransaction).where(PosTransaction.txn_id.in_(txn_ids)))
        session.execute(delete(ProductBatch).where(ProductBatch.store_id == store_id))
        session.execute(delete(Inventory).where(Inventory.store_id == store_id))
        session.execute(delete(PosTerminal).where(PosTerminal.store_id == store_id))
        session.execute(delete(Product).where(Product.sku == sku))
        session.execute(delete(Store).where(Store.store_id == store_id))
        session.commit()


def test_two_sessions_cannot_sell_the_last_unit(test_engine) -> None:
    store_id = f"TEST-{_uid(5)}"
    pos_id = f"TEST-POS-{_uid(8)}"
    sku = f"TEST-SKU-{_uid(8)}"
    txn_ids = [f"TEST-TXN-{_uid(8)}", f"TEST-TXN-{_uid(8)}"]

    with Session(test_engine) as setup:
        setup.add(
            Store(
                store_id=store_id,
                name="Test Race Store",
                latitude=Decimal("10.500000"),
                longitude=Decimal("106.500000"),
                region_id="TEST",
            )
        )
        setup.add(
            Product(
                sku=sku,
                barcode=f"BC-{sku}",
                name="Test Race Product",
                category="TEST",
                unit_price=Decimal("10.00"),
            )
        )
        # Same rule as _seed: insert parents before the rows that reference them.
        setup.flush()
        setup.add(PosTerminal(pos_id=pos_id, store_id=store_id, status="ACTIVE"))
        setup.flush()
        for txn_id in txn_ids:
            setup.add(
                PosTransaction(
                    txn_id=txn_id,
                    store_id=store_id,
                    pos_id=pos_id,
                    txn_type="SALE",
                    status="OK",
                    payload_hash="0" * 64,
                )
            )
        add_stock(setup, store_id, sku, 1)
        setup.commit()
    def sell(txn_id: str) -> bool:
        with Session(test_engine) as session:
            try:
                apply_stock_change(
                    session,
                    store_id=store_id,
                    sku=sku,
                    delta=-1,
                    movement_type="SALE",
                    txn_id=txn_id,
                )
                session.commit()
                return True
            except ApiError as error:
                assert error.code == "INSUFFICIENT_STOCK"
                session.rollback()
                return False

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(sell, txn_ids))

        assert sorted(outcomes) == [False, True]
        with Session(test_engine) as verification:
            assert verification.get(Inventory, (store_id, sku)).quantity == 0
            sold = verification.execute(
                select(InventoryMovement).where(InventoryMovement.store_id == store_id)
            ).scalars().all()
            assert [(movement.movement_type, movement.quantity) for movement in sold] == [
                ("SALE", -1)
            ]
    finally:
        _cleanup(test_engine, store_id, sku, txn_ids)


def test_two_sessions_creating_the_same_stock_row_keep_both_changes(test_engine) -> None:
    store_id = f"TEST-{_uid(5)}"
    sku = f"TEST-SKU-{_uid(8)}"

    with Session(test_engine) as setup:
        setup.add(
            Store(
                store_id=store_id,
                name="Test Insert Race Store",
                latitude=Decimal("10.500000"),
                longitude=Decimal("106.500000"),
                region_id="TEST",
            )
        )
        setup.add(
            Product(
                sku=sku,
                barcode=f"BC-{sku}",
                name="Test Insert Race Product",
                category="TEST",
                unit_price=Decimal("10.00"),
            )
        )
        setup.flush()
        setup.commit()

    barrier = Barrier(2)

    def receive() -> int:
        with Session(test_engine) as session:
            barrier.wait(timeout=10)
            new_quantity = apply_stock_change(
                session,
                store_id=store_id,
                sku=sku,
                delta=3,
                movement_type="STOCK_RECEIVED",
            )
            session.commit()
            return new_quantity

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = sorted(pool.map(lambda _: receive(), range(2)))

        # One session inserts the row and returns 3; the other loses the insert
        # race, retries as an update and returns 6. Neither change is lost.
        assert outcomes == [3, 6]
        with Session(test_engine) as verification:
            assert verification.get(Inventory, (store_id, sku)).quantity == 6
            movements = (
                verification.execute(
                    select(InventoryMovement)
                    .where(InventoryMovement.store_id == store_id)
                    .order_by(InventoryMovement.movement_id)
                )
                .scalars()
                .all()
            )
            assert [(movement.movement_type, movement.quantity) for movement in movements] == [
                ("STOCK_RECEIVED", 3),
                ("STOCK_RECEIVED", 3),
            ]
    finally:
        _cleanup(test_engine, store_id, sku, [])
