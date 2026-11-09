"""FEFO batches through the POS API (PB-20, EXP20-1 to 20-7 and INV12-6).

Every test replaces ``app.core.clock.today_local``, so the expiry comparisons use
a fixed business date and never depend on the day the suite runs. Each test owns
its store, SKU and batch ids with the ``TEST-`` prefix.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.security import create_token
from app.domain.models import (
    Inventory,
    InventoryMovement,
    PosTerminal,
    PosTransaction,
    Product,
    ProductBatch,
    StaffUser,
    Store,
    TransactionItem,
)
from app.services.inventory import apply_stock_change, sellable_stock
from tests.pos_test_support import (
    add_batch,
    assert_error,
    count,
    movements,
    post,
    stock,
    stock_changes,
    uid,
)


TODAY = date(2026, 11, 14)

DEMO_STORES = ("STORE-DN1", "STORE-DN2", "STORE-DN3")
DEMO_PRODUCTS = {"SKU-0001": "Dairy", "SKU-0004": "Bakery", "SKU-0007": "Dry goods"}
DEMO_BATCH_SEED = Path(__file__).resolve().parents[2] / "database" / "seed" / "003_demo_batches.sql"


@pytest.fixture(autouse=True)
def business_date(monkeypatch) -> None:
    """Fix the business date so every expiry comparison is deterministic."""
    monkeypatch.setattr("app.core.clock.today_local", lambda: TODAY)


@dataclass(frozen=True)
class Shop:
    store_id: str
    pos_id: str
    token: str
    username: str


def make_shop(session: Session, plan: dict[str, list[tuple[int, date]]]) -> Shop:
    """Create a store, its products, the batches in ``plan`` and their stock.

    ``plan`` maps a SKU to ``(quantity, expiry_date)`` batches. The inventory row
    of the SKU is the sum of its batches, as PB-20 requires.
    """
    store_id = f"TEST-{uid(5)}"
    pos_id = f"TEST-POS-{uid(8)}"
    username = f"TEST-USER-{uid(8)}"
    session.add(Store(store_id=store_id, name="FEFO store", latitude=Decimal("16.000000"),
                      longitude=Decimal("108.000000"), region_id="TEST"))
    session.flush()
    for sku in plan:
        session.add(Product(sku=sku, barcode=f"BC-{sku}", name="FEFO product",
                            category="TEST", unit_price=Decimal("10.00")))
    session.flush()
    session.add(PosTerminal(pos_id=pos_id, store_id=store_id, status="ACTIVE"))
    session.add(StaffUser(username=username, full_name="FEFO POS", role="POS_SYSTEM"))
    session.flush()
    for sku, batches in plan.items():
        session.add(Inventory(store_id=store_id, sku=sku,
                              quantity=sum(quantity for quantity, _ in batches)))
        session.flush()
        for quantity, expiry_date in batches:
            add_batch(session, store_id, sku, quantity, expiry_date=expiry_date)
    session.commit()
    token = create_token(username, "POS", store_id=store_id, pos_id=pos_id)
    return Shop(store_id, pos_id, token, username)


def staff_token(session: Session, shop: Shop) -> str:
    """A Staff account of the shop, for the stock query endpoint."""
    username = f"TEST-STAFF-{uid(8)}"
    session.add(StaffUser(username=username, full_name="FEFO staff", role="STORE_STAFF",
                          store_id=shop.store_id))
    session.flush()
    return create_token(username, "Staff", store_id=shop.store_id)


def sale_event(shop: Shop, items: list[tuple[str, int]]) -> dict:
    return {
        "event_type": "SALE",
        "transaction_id": f"TEST-TXN-{uid(10)}",
        "store_id": shop.store_id,
        "pos_id": shop.pos_id,
        "timestamp": "2026-11-14T03:15:00Z",
        "items": [{"sku": sku, "quantity": quantity, "unit_price": "10.00"}
                  for sku, quantity in items],
    }


def return_event(shop: Shop, original_id: str, items: list[tuple[str, int]]) -> dict:
    return {
        "event_type": "RETURN",
        "transaction_id": f"TEST-RET-{uid(10)}",
        "original_transaction_id": original_id,
        "store_id": shop.store_id,
        "pos_id": shop.pos_id,
        "timestamp": "2026-11-14T03:15:00Z",
        "items": [{"sku": sku, "quantity": quantity, "unit_price": "10.00"}
                  for sku, quantity in items],
    }


def cancellation_event(shop: Shop, original_id: str) -> dict:
    return {
        "event_type": "CANCELLATION",
        "transaction_id": f"TEST-CAN-{uid(10)}",
        "original_transaction_id": original_id,
        "store_id": shop.store_id,
        "pos_id": shop.pos_id,
        "timestamp": "2026-11-14T03:15:00Z",
        "items": [],
    }


def batches_of(session: Session, shop: Shop, sku: str) -> list[tuple[str, date, int]]:
    """The batches of a SKU, earliest expiry first, as ``(id, date, quantity)``."""
    session.expire_all()
    rows = session.execute(
        select(ProductBatch.batch_id, ProductBatch.expiry_date, ProductBatch.quantity)
        .where(ProductBatch.store_id == shop.store_id, ProductBatch.sku == sku)
        .order_by(ProductBatch.expiry_date, ProductBatch.batch_id)
    ).all()
    return [(str(batch_id), expiry, int(quantity)) for batch_id, expiry, quantity in rows]


def quantities_of(session: Session, shop: Shop, sku: str) -> list[int]:
    return [quantity for _, _, quantity in batches_of(session, shop, sku)]


def apply(client, db_session: Session, shop: Shop, event: dict) -> dict:
    response = post(client, event, shop.token)
    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["outcome"], body["code"]) == ("OK", "OK")
    assert count(db_session, PosTransaction, txn_id=event["transaction_id"]) == 1
    return body


# ---- EXP20 ------------------------------------------------------------------


def test_exp20_1_sale_takes_the_earliest_expiring_batch_first(client, db_session) -> None:
    """EXP20-1: the FEFO rule itself."""
    sku = f"TEST-SKU-{uid(8)}"
    shop = make_shop(db_session, {sku: [
        (5, TODAY + timedelta(days=3)),
        (5, TODAY + timedelta(days=30)),
    ]})
    earliest, later = [batch_id for batch_id, _, _ in batches_of(db_session, shop, sku)]

    apply(client, db_session, shop, sale_event(shop, [(sku, 3)]))

    assert quantities_of(db_session, shop, sku) == [2, 5]
    assert stock(db_session, shop, sku) == 7
    rows = movements(db_session, db_session.scalar(
        select(PosTransaction.txn_id).where(
            PosTransaction.store_id == shop.store_id,
            PosTransaction.txn_type == "SALE",
        )
    ))
    assert [(row.batch_id, row.quantity) for row in rows] == [(earliest, -3)]
    assert later not in {row.batch_id for row in rows}


def test_exp20_2_sale_splits_across_batches_in_expiry_order(client, db_session) -> None:
    """EXP20-2: a sale larger than the first batch continues with the next one."""
    sku = f"TEST-SKU-{uid(8)}"
    shop = make_shop(db_session, {sku: [
        (2, TODAY + timedelta(days=2)),
        (4, TODAY + timedelta(days=10)),
        (9, TODAY + timedelta(days=60)),
    ]})
    ids = [batch_id for batch_id, _, _ in batches_of(db_session, shop, sku)]

    event = sale_event(shop, [(sku, 5)])
    apply(client, db_session, shop, event)

    assert quantities_of(db_session, shop, sku) == [0, 1, 9]
    rows = movements(db_session, event["transaction_id"])
    assert [(row.batch_id, row.quantity) for row in rows] == [
        (ids[0], -2), (ids[1], -3),
    ]
    assert stock(db_session, shop, sku) == 10


def test_exp20_3_expired_batch_is_never_sold(client, db_session) -> None:
    """EXP20-3: expired stock stays in inventory and is untouchable."""
    sku = f"TEST-SKU-{uid(8)}"
    shop = make_shop(db_session, {sku: [
        (4, TODAY - timedelta(days=1)),
        (6, TODAY + timedelta(days=20)),
    ]})

    event = sale_event(shop, [(sku, 5)])
    apply(client, db_session, shop, event)

    assert quantities_of(db_session, shop, sku) == [4, 1]
    assert stock(db_session, shop, sku) == 5
    assert all(row.batch_id is not None for row in movements(db_session, event["transaction_id"]))


def test_exp20_4_only_an_expired_batch_is_left(client, db_session) -> None:
    """EXP20-4: 409 INSUFFICIENT_STOCK, no batch, movement or transaction row."""
    sku = f"TEST-SKU-{uid(8)}"
    shop = make_shop(db_session, {sku: [
        (4, TODAY - timedelta(days=5)),
    ]})
    before = batches_of(db_session, shop, sku)
    event = sale_event(shop, [(sku, 4)])

    response = post(client, event, shop.token)

    assert_error(response, 409, "INSUFFICIENT_STOCK")
    assert batches_of(db_session, shop, sku) == before
    assert stock(db_session, shop, sku) == 4
    assert sellable_stock(db_session, shop.store_id, sku) == 0
    assert count(db_session, PosTransaction, txn_id=event["transaction_id"]) == 0
    assert movements(db_session, event["transaction_id"]) == []
    assert stock_changes(db_session, event["transaction_id"]) == []


def test_exp20_5_return_puts_stock_back_into_the_batch_it_came_from(client, db_session) -> None:
    """EXP20-5: a RETURN restores the batch the sale took, newest expiry first."""
    sku = f"TEST-SKU-{uid(8)}"
    shop = make_shop(db_session, {sku: [
        (3, TODAY + timedelta(days=2)),
        (5, TODAY + timedelta(days=10)),
    ]})
    earliest, later = [batch_id for batch_id, _, _ in batches_of(db_session, shop, sku)]
    sale = sale_event(shop, [(sku, 4)])
    apply(client, db_session, shop, sale)
    assert quantities_of(db_session, shop, sku) == [0, 4]

    first_return = return_event(shop, sale["transaction_id"], [(sku, 1)])
    apply(client, db_session, shop, first_return)

    # Sole unit of the sale taken from the later batch goes back into it.
    assert quantities_of(db_session, shop, sku) == [0, 5]
    rows = movements(db_session, first_return["transaction_id"])
    assert [(row.batch_id, row.quantity) for row in rows] == [(later, 1)]

    second_return = return_event(shop, sale["transaction_id"], [(sku, 3)])
    apply(client, db_session, shop, second_return)

    # The later batch is already whole again, so the rest returns to the earliest.
    assert quantities_of(db_session, shop, sku) == [3, 5]
    rows = movements(db_session, second_return["transaction_id"])
    assert [(row.batch_id, row.quantity) for row in rows] == [(earliest, 3)]
    assert stock(db_session, shop, sku) == 8


def test_exp20_6_cancellation_restores_both_batches(client, db_session) -> None:
    """EXP20-6: CANCELLATION puts both batches back to their exact quantities."""
    sku = f"TEST-SKU-{uid(8)}"
    shop = make_shop(db_session, {sku: [
        (2, TODAY + timedelta(days=1)),
        (3, TODAY + timedelta(days=15)),
    ]})
    earliest, later = [batch_id for batch_id, _, _ in batches_of(db_session, shop, sku)]
    sale = sale_event(shop, [(sku, 4)])
    apply(client, db_session, shop, sale)
    assert quantities_of(db_session, shop, sku) == [0, 1]

    cancellation = cancellation_event(shop, sale["transaction_id"])
    apply(client, db_session, shop, cancellation)

    assert quantities_of(db_session, shop, sku) == [2, 3]
    assert stock(db_session, shop, sku) == 5
    rows = movements(db_session, cancellation["transaction_id"])
    assert [(row.batch_id, row.quantity, row.movement_type) for row in rows] == [
        (later, 2, "CANCELLATION"), (earliest, 2, "CANCELLATION"),
    ]
    assert db_session.get(PosTransaction, sale["transaction_id"]).status == "CANCELLED"


def test_exp20_7_inventory_equals_the_sum_of_batches_after_sales(client, db_session) -> None:
    """EXP20-7: the invariant the ledger helper checks, after two FEFO sales."""
    sku = f"TEST-SKU-{uid(8)}"
    shop = make_shop(db_session, {sku: [
        (2, TODAY + timedelta(days=1)),
        (2, TODAY + timedelta(days=2)),
        (2, TODAY + timedelta(days=3)),
    ]})

    apply(client, db_session, shop, sale_event(shop, [(sku, 3)]))
    apply(client, db_session, shop, sale_event(shop, [(sku, 2)]))

    session_total = db_session.scalar(
        select(func.coalesce(func.sum(ProductBatch.quantity), 0)).where(
            ProductBatch.store_id == shop.store_id, ProductBatch.sku == sku,
        )
    )
    assert stock(db_session, shop, sku) == 1
    assert int(session_total) == 1


# ---- PB-20-4 extras ---------------------------------------------------------


def test_pb20_4_sellable_stock_counts_only_unexpired_batches(db_session) -> None:
    """The service other backlog items call: expired batches never count."""
    sku = f"TEST-SKU-{uid(8)}"
    shop = make_shop(db_session, {sku: [
        (3, TODAY),
        (2, TODAY + timedelta(days=1)),
        (7, TODAY - timedelta(days=1)),
    ]})

    assert sellable_stock(db_session, shop.store_id, sku) == 5
    assert stock(db_session, shop, sku) == 12


def test_pb20_4_a_sale_that_empties_one_batch_leaves_no_stock(client, db_session) -> None:
    """The boundary of a batch that is taken exactly."""
    sku = f"TEST-SKU-{uid(8)}"
    shop = make_shop(db_session, {sku: [
        (4, TODAY + timedelta(days=4)),
        (1, TODAY + timedelta(days=40)),
    ]})

    apply(client, db_session, shop, sale_event(shop, [(sku, 4)]))

    assert quantities_of(db_session, shop, sku) == [0, 1]
    assert stock(db_session, shop, sku) == 1


def test_pb20_4_a_batch_expiring_today_is_still_sold(client, db_session) -> None:
    """A batch is sellable through its expiry date, so today still counts."""
    sku = f"TEST-SKU-{uid(8)}"
    shop = make_shop(db_session, {sku: [
        (3, TODAY),
        (3, TODAY + timedelta(days=30)),
    ]})

    apply(client, db_session, shop, sale_event(shop, [(sku, 3)]))

    assert quantities_of(db_session, shop, sku) == [0, 3]


def test_pb20_4_short_second_sku_changes_no_batch(client, db_session) -> None:
    """The basket is rejected as a whole: the first SKU keeps its batches."""
    first, second = f"TEST-SKU-{uid(8)}", f"TEST-SKU-{uid(8)}"
    shop = make_shop(db_session, {
        first: [(5, TODAY + timedelta(days=5))],
        second: [(1, TODAY + timedelta(days=5))],
    })
    before = {sku: batches_of(db_session, shop, sku) for sku in (first, second)}
    event = sale_event(shop, [(first, 2), (second, 3)])

    response = post(client, event, shop.token)

    assert_error(response, 409, "INSUFFICIENT_STOCK")
    assert {sku: batches_of(db_session, shop, sku) for sku in (first, second)} == before
    assert movements(db_session, event["transaction_id"]) == []
    assert count(db_session, PosTransaction, txn_id=event["transaction_id"]) == 0


def test_pb20_4_partial_return_then_the_rest(client, db_session) -> None:
    """A sale of two batches is returned in two events, newest expiry first."""
    sku = f"TEST-SKU-{uid(8)}"
    shop = make_shop(db_session, {sku: [
        (2, TODAY + timedelta(days=1)),
        (3, TODAY + timedelta(days=15)),
    ]})
    sale = sale_event(shop, [(sku, 4)])
    apply(client, db_session, shop, sale)
    assert quantities_of(db_session, shop, sku) == [0, 1]

    first_return = return_event(shop, sale["transaction_id"], [(sku, 2)])
    apply(client, db_session, shop, first_return)
    # The newest batch of the sale comes back first.
    assert quantities_of(db_session, shop, sku) == [0, 3]

    second_return = return_event(shop, sale["transaction_id"], [(sku, 2)])
    apply(client, db_session, shop, second_return)
    assert quantities_of(db_session, shop, sku) == [2, 3]
    assert stock(db_session, shop, sku) == 5

    restored = movements(db_session, first_return["transaction_id"]) + movements(
        db_session, second_return["transaction_id"]
    )
    assert all(row.movement_type == "RETURN" and row.batch_id for row in restored)
    assert sum(row.quantity for row in restored) == 4


def test_pb20_4_return_after_the_restored_batch_expired(client, db_session, monkeypatch) -> None:
    """An expired batch still gets its stock back; it simply is not sellable."""
    sku = f"TEST-SKU-{uid(8)}"
    shop = make_shop(db_session, {sku: [(4, TODAY + timedelta(days=2))]})
    sale = sale_event(shop, [(sku, 4)])
    apply(client, db_session, shop, sale)
    assert quantities_of(db_session, shop, sku) == [0]

    monkeypatch.setattr("app.core.clock.today_local", lambda: TODAY + timedelta(days=30))
    apply(client, db_session, shop, return_event(shop, sale["transaction_id"], [(sku, 4)]))

    assert quantities_of(db_session, shop, sku) == [4]
    assert stock(db_session, shop, sku) == 4
    assert sellable_stock(db_session, shop.store_id, sku) == 0


def test_pb20_4_legacy_return_creates_an_expired_batch(client, db_session) -> None:
    """A sale from before PB-20 with no batch at all: LEGACY- expires yesterday.

    PO decision of 09/11: the stock still comes back into inventory, but it
    cannot be sold and PB-21 alerts staff to check the expired batch.
    """
    sku = f"TEST-SKU-{uid(8)}"
    shop = make_shop(db_session, {sku: []})
    # Stock on hand before PB-20 had no batch rows; the sale below takes it.
    db_session.get(Inventory, (shop.store_id, sku)).quantity = 2
    sale = sale_event(shop, [(sku, 2)])
    db_session.add(PosTransaction(txn_id=sale["transaction_id"], store_id=shop.store_id,
                                  pos_id=shop.pos_id, txn_type="SALE", status="OK",
                                  payload_hash="0" * 64))
    db_session.add(TransactionItem(txn_id=sale["transaction_id"], sku=sku, qty=2,
                                   unit_price=Decimal("10.00")))
    db_session.flush()
    # A pre-PB-20 sale left its movement without a batch_id.
    apply_stock_change(db_session, shop.store_id, sku, -2, "SALE",
                       txn_id=sale["transaction_id"])
    db_session.commit()
    assert batches_of(db_session, shop, sku) == []
    assert stock(db_session, shop, sku) == 0

    apply(client, db_session, shop, return_event(shop, sale["transaction_id"], [(sku, 2)]))

    [(batch_id, expiry_date, quantity)] = batches_of(db_session, shop, sku)
    assert batch_id.startswith("LEGACY-")
    assert expiry_date == TODAY - timedelta(days=1)
    assert quantity == 2
    assert stock(db_session, shop, sku) == 2
    assert sellable_stock(db_session, shop.store_id, sku) == 0


# ---- INV12-6 ----------------------------------------------------------------


def test_inv12_6_stock_query_lists_batches_by_expiry(client, db_session) -> None:
    """INV12-6: every batch with stock, expired ones included, earliest first."""
    sku = f"TEST-SKU-{uid(8)}"
    shop = make_shop(db_session, {sku: [
        (2, TODAY - timedelta(days=3)),
        (5, TODAY + timedelta(days=7)),
    ]})
    token = staff_token(db_session, shop)
    expected = batches_of(db_session, shop, sku)

    response = client.get(f"/api/v1/stores/{shop.store_id}/inventory",
                          headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["store_id"] == shop.store_id
    assert [(item["sku"], item["quantity"]) for item in body["items"]] == [(sku, 7)]
    assert [
        (batch["batch_id"], date.fromisoformat(batch["expiry_date"]), batch["quantity"])
        for batch in body["items"][0]["batches"]
    ] == expected
    assert body["items"][0]["batches"][0]["expiry_date"] < body["items"][0]["batches"][1]["expiry_date"]


def test_inv12_6_batches_of_a_single_sku_query(client, db_session) -> None:
    """The same detail comes back when the query asks for one SKU."""
    sku = f"TEST-SKU-{uid(8)}"
    other = f"TEST-SKU-{uid(8)}"
    shop = make_shop(db_session, {
        sku: [(3, TODAY + timedelta(days=5))],
        other: [(1, TODAY + timedelta(days=9))],
    })
    token = staff_token(db_session, shop)

    response = client.get(f"/api/v1/stores/{shop.store_id}/inventory",
                          params={"sku": sku},
                          headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200, response.text
    [line] = response.json()["items"]
    assert line["sku"] == sku
    assert line["quantity"] == 3
    assert [batch["quantity"] for batch in line["batches"]] == [3]


# ---- database/seed/003_demo_batches.sql -------------------------------------


def business_today() -> date:
    """The date the seed computes, from the same UTC offset."""
    return (datetime.now(timezone.utc) + timedelta(hours=7)).date()


def run_demo_batch_seed(session: Session) -> None:
    session.connection().exec_driver_sql(DEMO_BATCH_SEED.read_text(encoding="utf-8"))


def prepare_demo_stock(session: Session, quantities: dict[tuple[str, str], int]) -> None:
    """Give the demo stores the stock the seed has to split, with no batches."""
    for store_id in DEMO_STORES:
        if session.get(Store, store_id) is None:
            session.add(Store(store_id=store_id, name="Demo batch store",
                              latitude=Decimal("16.000000"), longitude=Decimal("108.000000"),
                              region_id="TEST"))
    for sku, category in DEMO_PRODUCTS.items():
        if session.get(Product, sku) is None:
            session.add(Product(sku=sku, barcode=f"BC-{sku}", name="Demo batch product",
                                category=category, unit_price=Decimal("10.00")))
    session.flush()
    session.execute(delete(ProductBatch).where(ProductBatch.store_id.in_(DEMO_STORES)))
    for (store_id, sku), quantity in quantities.items():
        row = session.get(Inventory, (store_id, sku))
        if row is None:
            session.add(Inventory(store_id=store_id, sku=sku, quantity=quantity))
        else:
            row.quantity = quantity
    session.flush()


def demo_batches(session: Session) -> dict[tuple[str, str], list[tuple[date, int]]]:
    session.expire_all()
    rows = session.execute(
        select(ProductBatch.store_id, ProductBatch.sku, ProductBatch.expiry_date,
               ProductBatch.quantity)
        .where(ProductBatch.store_id.in_(DEMO_STORES))
        .order_by(ProductBatch.expiry_date)
    ).all()
    batches: dict[tuple[str, str], list[tuple[date, int]]] = {}
    for store_id, sku, expiry_date, quantity in rows:
        batches.setdefault((str(store_id), str(sku)), []).append(
            (expiry_date, int(quantity))
        )
    return batches


def test_pb20_3_demo_batch_seed_uses_the_current_stock(db_session) -> None:
    """The seed splits what is on hand now, not the 40/25/15 of the older seed."""
    quantities = {
        ("STORE-DN1", "SKU-0001"): 1,
        ("STORE-DN1", "SKU-0004"): 7,
        ("STORE-DN2", "SKU-0007"): 41,
    }
    prepare_demo_stock(db_session, quantities)

    run_demo_batch_seed(db_session)
    first = demo_batches(db_session)
    run_demo_batch_seed(db_session)

    assert demo_batches(db_session) == first
    today = business_today()
    # A single unit gets one batch, the later date of its category.
    assert first["STORE-DN1", "SKU-0001"] == [(today + timedelta(days=20), 1)]
    # About 40% expires in 3 days, the rest on the category's later date.
    assert first["STORE-DN1", "SKU-0004"] == [
        (today + timedelta(days=3), 2),
        (today + timedelta(days=10), 5),
    ]
    assert first["STORE-DN2", "SKU-0007"] == [
        (today + timedelta(days=3), 16),
        (today + timedelta(days=180), 25),
    ]
    # Every split adds up to the stock it came from, for every demo row.
    for (store_id, sku), batches in first.items():
        session_batches = sum(quantity for _, quantity in batches)
        assert session_batches == db_session.get(Inventory, (store_id, sku)).quantity


def test_pb20_3_demo_batch_ids_follow_the_documented_shape(db_session) -> None:
    prepare_demo_stock(db_session, {("STORE-DN1", "SKU-0004"): 10})

    run_demo_batch_seed(db_session)

    session_ids = set(db_session.scalars(
        select(ProductBatch.batch_id).where(ProductBatch.store_id == "STORE-DN1",
                                            ProductBatch.sku == "SKU-0004")
    ))
    assert session_ids == {"B-STORE-DN1-SKU-0004-1", "B-STORE-DN1-SKU-0004-2"}
