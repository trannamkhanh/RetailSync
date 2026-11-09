"""Cached plans for the raw POS queries (PB-06, PB-07, PB-10).

The driver declares Python ``str`` parameters as ``nvarchar``, and SQLAlchemy
does not call ``setinputsizes()`` for ``text()`` statements (the execution
context short-circuits on ``is_text``). The two repositories therefore cast
every string parameter to its column's type and length. These checks run the
real functions and read their cached plans: each key predicate must carry the
explicit varchar conversion, the plan must have no ``CONVERT_IMPLICIT`` on the
key column, and the access to ``pos_transaction`` or ``inventory`` must be a
seek instead of a scan.

The cached batch still declares the parameter ``nvarchar``; the cast is what
makes the value and the predicate varchar. A driver-level varchar declaration
would require a raw DBAPI cursor or a non-``text()`` statement, which this
change does not introduce.
"""

import xml.etree.ElementTree as ET
from collections.abc import Generator
from dataclasses import dataclass

import pytest
from sqlalchemy import delete, text
from sqlalchemy.orm import Session

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
from app.repositories.inventory import (
    add_movement,
    get_stock,
    insert_stock_row,
    update_stock_with_guard,
)
from app.repositories.original_sale import (
    find_sale,
    lock_sale,
    returned_quantities,
    sold_quantities,
)
from tests.pos_test_support import add_stock, uid


NS = "{http://schemas.microsoft.com/sqlserver/2004/07/showplan}"


@dataclass(frozen=True)
class QueryCase:
    name: str
    fragment: str
    exclude: str | None
    conversions: tuple[str, ...]
    seeks: tuple[str, ...]


ORIGINAL_SALE_CASES = (
    QueryCase("find_sale", "%FROM dbo.pos_transaction%WHERE txn_id = CAST%", "UPDLOCK",
              ("CONVERT(varchar(40)", "CONVERT(varchar(10)"), ("pos_transaction",)),
    QueryCase("lock_sale", "%WITH (UPDLOCK, ROWLOCK)%txn_id = CAST%", None,
              ("CONVERT(varchar(40)", "CONVERT(varchar(10)"), ("pos_transaction",)),
    QueryCase("sold_quantities", "%FROM dbo.transaction_item%txn_id = CAST%", "JOIN",
              ("CONVERT(varchar(40)",), ()),
    QueryCase("returned_quantities", "%ref_txn_id = CAST%", None,
              ("CONVERT(varchar(40)", "CONVERT(varchar(10)"), ("pos_transaction",)),
)

INVENTORY_CASES = (
    QueryCase("get_stock", "%SELECT quantity%FROM dbo.inventory%store_id = CAST%", None,
              ("CONVERT(varchar(10)", "CONVERT(varchar(20)"), ("inventory",)),
    QueryCase("update_stock_with_guard", "%UPDATE dbo.inventory%OUTPUT inserted.quantity%", None,
              ("CONVERT(varchar(10)", "CONVERT(varchar(20)"), ("inventory",)),
    QueryCase("insert_stock_row", "%INSERT INTO dbo.inventory %", None,
              ("CONVERT(varchar(10)", "CONVERT(varchar(20)"), ()),
    QueryCase("add_movement", "%INSERT INTO dbo.inventory_movement%", None,
              ("CONVERT(varchar(10)", "CONVERT(varchar(20)", "CONVERT(varchar(40)",
               "CONVERT(varchar(30)", "CONVERT(nvarchar(200)"), ()),
)


@pytest.fixture
def world(test_engine) -> Generator[dict, None, None]:
    suffix = uid(5)
    store = f"TEST-{suffix}"
    pos = f"TEST-P-{suffix}"
    user = f"TEST-U-{suffix}"
    sale = f"TEST-T-{suffix}"
    skus = [f"TEST-S-{suffix}{index}" for index in range(3)]

    with Session(test_engine) as session:
        session.add(Store(store_id=store, name="Param type test", latitude=0, longitude=0,
                          region_id="TEST"))
        session.add_all(Product(sku=sku, barcode=f"BC-{suffix}{index}", name="Param product",
                                category="TEST", unit_price=10)
                        for index, sku in enumerate(skus))
        session.flush()
        session.add(PosTerminal(pos_id=pos, store_id=store, status="ACTIVE"))
        staff = StaffUser(username=user, full_name="Param user", role="POS_SYSTEM")
        session.add(staff)
        session.flush()
        user_id = staff.user_id
        session.add(PosTransaction(txn_id=sale, store_id=store, pos_id=pos, txn_type="SALE",
                                   status="OK", payload_hash="0" * 64))
        for sku in skus[:2]:
            add_stock(session, store, sku, 10)
            session.add(TransactionItem(txn_id=sale, sku=sku, qty=1, unit_price=10))
        session.commit()

    try:
        yield {"store": store, "pos": pos, "user": user, "user_id": user_id, "sale": sale,
               "skus": skus}
    finally:
        with Session(test_engine) as session:
            session.execute(delete(InventoryMovement).where(InventoryMovement.store_id == store))
            session.execute(delete(TransactionItem).where(TransactionItem.txn_id == sale))
            session.execute(delete(Inventory).where(Inventory.store_id == store))
            session.execute(delete(ProductBatch).where(ProductBatch.store_id == store))
            session.execute(delete(PosTransaction).where(PosTransaction.txn_id == sale))
            session.execute(delete(PosTerminal).where(PosTerminal.pos_id == pos))
            session.execute(delete(Product).where(Product.sku.in_(skus)))
            session.execute(delete(StaffUser).where(StaffUser.username == user))
            session.execute(delete(Store).where(Store.store_id == store))
            session.commit()


def _exercise_original_sale(engine, world: dict) -> None:
    with Session(engine) as session:
        find_sale(session, world["store"], world["sale"])
        lock_sale(session, world["store"], world["sale"])
        sold_quantities(session, world["sale"])
        returned_quantities(session, world["store"], world["sale"])
        session.rollback()


def _exercise_inventory(engine, world: dict) -> None:
    with Session(engine) as session:
        get_stock(session, world["store"], world["skus"][0])
        update_stock_with_guard(session, world["store"], world["skus"][0], 1)
        insert_stock_row(session, world["store"], world["skus"][2], 5)
        add_movement(session, world["store"], world["skus"][0], "ADJUSTMENT", 1,
                     txn_id=world["sale"], batch_id=None, reason="TEST reason",
                     created_by=world["user_id"])
        session.rollback()


def _cached_plan(engine, case: QueryCase) -> str:
    where = "st.text LIKE :fragment"
    params = {"fragment": case.fragment}
    if case.exclude is not None:
        where += " AND st.text NOT LIKE :exclude"
        params["exclude"] = f"%{case.exclude}%"
    with engine.connect() as connection:
        plan = connection.scalar(
            text(
                f"""
                SELECT TOP 1 qp.query_plan
                FROM sys.dm_exec_query_stats AS qs
                CROSS APPLY sys.dm_exec_sql_text(qs.sql_handle) AS st
                CROSS APPLY sys.dm_exec_query_plan(qs.plan_handle) AS qp
                WHERE {where}
                ORDER BY qs.last_execution_time DESC
                """
            ),
            params,
        )
    assert plan is not None, f"no cached plan for {case.name} ({case.fragment})"
    return str(plan)


def _table_operations(xml: str) -> list[tuple[str, str]]:
    root = ET.fromstring(xml)
    operations: list[tuple[str, str]] = []
    for relop in root.iter(f"{NS}RelOp"):
        physical = relop.get("PhysicalOp") or ""
        for table_object in relop.iter(f"{NS}Object"):
            table = (table_object.get("Table") or "").strip("[]")
            if table:
                operations.append((physical, table))
    return operations


def _assert_case(engine, case: QueryCase) -> None:
    xml = _cached_plan(engine, case)

    assert "CONVERT_IMPLICIT" not in xml, f"{case.name}: implicit conversion in the plan"
    for conversion in case.conversions:
        assert conversion in xml, f"{case.name}: missing {conversion} in the plan"

    operations = _table_operations(xml)
    for table in case.seeks:
        table_operations = [physical for physical, name in operations if name == table]
        assert any("Seek" in physical for physical in table_operations), (
            f"{case.name}: no seek on {table}, got {table_operations}"
        )
        assert not any("Scan" in physical for physical in table_operations), (
            f"{case.name}: scan on {table}, got {table_operations}"
        )


@pytest.mark.parametrize("case", ORIGINAL_SALE_CASES, ids=lambda case: case.name)
def test_pb06_original_sale_queries_use_varchar_predicates(world, test_engine, case) -> None:
    _exercise_original_sale(test_engine, world)
    _assert_case(test_engine, case)


@pytest.mark.parametrize("case", INVENTORY_CASES, ids=lambda case: case.name)
def test_pb10_inventory_queries_use_varchar_predicates(world, test_engine, case) -> None:
    _exercise_inventory(test_engine, world)
    _assert_case(test_engine, case)
