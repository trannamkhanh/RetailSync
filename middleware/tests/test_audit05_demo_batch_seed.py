"""Audit #5 (seed): the demo batch ids cannot overflow batch_id varchar(30).

``database/seed/003_demo_batches.sql`` built ``B-`` + store_id + sku + ``-1`` for
every inventory row of the three demo stores that had no batch. The seed files
run on every ``migrate.sh``, and the demo stores can hold longer SKUs than the
nine the catalogue seeds -- a barcode imported during a demo, for instance. With
``store_id`` up to 10 characters and ``sku`` up to 20, ``batch_id`` (varchar(30))
overflows and a re-run fails with SQL 2628 "String or binary data would be
truncated", which aborts the whole migration step.

The seed now splits the same quantities only for the nine catalogue SKUs of the
demo stores, whose ids fit by construction. Inventory of any other SKU keeps its
stock and simply gets no generated batch, which the demo does not need; the
assertion in ``test_fefo_batches.py`` that every split adds up to its inventory
row still covers them because it only sees rows the seed touched.

These tests run the real seed file against the test database inside the usual
savepoint, and delete the demo batches again.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from app.domain.models import Inventory, Product, ProductBatch, Store

SEED = (Path(__file__).resolve().parents[2] / "database" / "seed"
        / "003_demo_batches.sql")
DEMO_STORES = ("STORE-DN1", "STORE-DN2", "STORE-DN3")
CATALOGUE_SKUS = tuple(f"SKU-{index:04d}" for index in range(1, 10))
# 20 characters, the widest a sku may be (sku varchar(20)). In STORE-DN1 the
# generated batch id would be "B-" + 9 + 20 + "-1" = 33, over batch_id varchar(30).
LONG_SKU = "TEST-SEED-LONG-SKU12"


def run_seed(session: Session) -> None:
    session.connection().exec_driver_sql(SEED.read_text(encoding="utf-8"))


def prepare(session: Session, stock: dict[tuple[str, str], int]) -> None:
    """Demo store rows with the given stock and no batches at all."""
    for store_id in DEMO_STORES:
        if session.get(Store, store_id) is None:
            session.add(Store(store_id=store_id, name="Seed audit store",
                              latitude=Decimal("16.000000"),
                              longitude=Decimal("108.000000"), region_id="TEST"))
    session.flush()
    for sku, category in [(sku, "Dairy") for sku in CATALOGUE_SKUS] + [(LONG_SKU, "Dry goods")]:
        if session.get(Product, sku) is None:
            session.add(Product(sku=sku, barcode=f"BC-{sku}", name="Seed audit product",
                                category=category, unit_price=Decimal("10.00")))
    session.flush()
    session.execute(delete(ProductBatch).where(ProductBatch.store_id.in_(DEMO_STORES)))
    for (store_id, sku), quantity in stock.items():
        row = session.get(Inventory, (store_id, sku))
        if row is None:
            session.add(Inventory(store_id=store_id, sku=sku, quantity=quantity))
        else:
            row.quantity = quantity
    session.flush()


@pytest.fixture(autouse=True)
def clean_demo_batches(db_session):
    yield
    db_session.execute(delete(ProductBatch).where(ProductBatch.store_id.in_(DEMO_STORES)))
    db_session.flush()


def test_audit05_a_long_sku_in_a_demo_store_does_not_break_the_seed(db_session):
    """The audited failure: varchar(30) overflow, SQL 2628, on a migrate.sh re-run."""
    prepare(db_session, {("STORE-DN1", LONG_SKU): 5})

    run_seed(db_session)   # must not raise

    # The long SKU keeps its stock and simply gets no generated batch.
    batches = db_session.scalars(select(ProductBatch).where(
        ProductBatch.store_id == "STORE-DN1", ProductBatch.sku == LONG_SKU)).all()
    assert batches == []
    assert db_session.get(Inventory, ("STORE-DN1", LONG_SKU)).quantity == 5


def test_audit05_every_generated_batch_id_fits_the_column(db_session):
    prepare(db_session, {(store, sku): 7
                         for store in DEMO_STORES for sku in CATALOGUE_SKUS[:3]})
    run_seed(db_session)

    ids = db_session.scalars(select(ProductBatch.batch_id).where(
        ProductBatch.store_id.in_(DEMO_STORES))).all()

    assert ids
    assert all(len(batch_id) <= 30 for batch_id in ids), ids


def test_audit05_the_nine_catalogue_skus_are_still_split(db_session):
    stock = {(store, sku): 10 for store in DEMO_STORES for sku in CATALOGUE_SKUS}
    prepare(db_session, stock)

    run_seed(db_session)

    for (store_id, sku), quantity in stock.items():
        batches = db_session.scalars(select(ProductBatch).where(
            ProductBatch.store_id == store_id, ProductBatch.sku == sku)).all()
        assert batches, f"{store_id}/{sku} was not split"
        assert sum(batch.quantity for batch in batches) == quantity


def test_audit05_a_second_run_is_still_a_no_op(db_session):
    prepare(db_session, {("STORE-DN2", "SKU-0004"): 9})
    run_seed(db_session)
    first = sorted((batch.batch_id, batch.quantity) for batch in db_session.scalars(
        select(ProductBatch).where(ProductBatch.store_id == "STORE-DN2",
                                   ProductBatch.sku == "SKU-0004")))

    run_seed(db_session)
    second = sorted((batch.batch_id, batch.quantity) for batch in db_session.scalars(
        select(ProductBatch).where(ProductBatch.store_id == "STORE-DN2",
                                   ProductBatch.sku == "SKU-0004")))

    assert first == second
    assert sum(quantity for _, quantity in first) == 9
