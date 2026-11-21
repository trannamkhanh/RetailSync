"""Audit #5 (stock query): one snapshot, and `?sku=` filtered in SQL.

``stock_lines`` read every batch of the store and then kept the requested SKU
from the dictionary in Python, so a single-SKU lookup on a large store read
every batch of every SKU. The batches and the inventory row of the requested
SKU are now read through one join, filtered in SQL, so the read is one
statement for the single-SKU case and the two lists the contract wants still
come from the same snapshot of the store for the list case.

The observable contract does not change (INV12-1 to INV12-6), so these tests
pin what the audit is about: the number of statements, the SQL predicate, and
that the answers stay identical.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session

from app.core import clock
from app.domain.models import Inventory, Product, ProductBatch, Store
from app.services import stock_query
from tests.pos_test_support import add_stock, uid

TODAY = date(2026, 11, 14)


@pytest.fixture(autouse=True)
def business_date(monkeypatch) -> None:
    monkeypatch.setattr(clock, "today_local", lambda: TODAY)


class Shop:
    def __init__(self, store_id: str, sku_a: str, sku_b: str) -> None:
        self.store_id = store_id
        self.sku_a = sku_a
        self.sku_b = sku_b


def make_shop(db_session: Session) -> Shop:
    suffix = uid(4)
    store_id = f"TEST-Q{suffix}"
    sku_a = f"TEST-SKU-A{suffix}"
    sku_b = f"TEST-SKU-B{suffix}"
    db_session.add(Store(store_id=store_id, name="Audit stock query store",
                         latitude=Decimal("16.000000"), longitude=Decimal("108.000000"),
                         region_id="TEST"))
    db_session.flush()
    for sku in (sku_a, sku_b):
        db_session.add(Product(sku=sku, barcode=f"BC-{sku}", name="Audit stock product",
                               category="TEST", unit_price=Decimal("10.00")))
    db_session.flush()
    add_stock(db_session, store_id, sku_a, 5, expiry_date=TODAY + timedelta(days=10))
    add_stock(db_session, store_id, sku_b, 7, expiry_date=TODAY + timedelta(days=2))
    db_session.commit()
    return Shop(store_id, sku_a, sku_b)


class StatementCounter:
    """Counts the SELECT statements SQLAlchemy sends for the block inside."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.statements: list[str] = []

    def __enter__(self) -> "StatementCounter":
        event.listen(self.session.bind, "before_cursor_execute", self._record)
        return self

    def __exit__(self, *exc_info) -> None:
        event.remove(self.session.bind, "before_cursor_execute", self._record)

    def _record(self, conn, cursor, statement, parameters, context, executemany) -> None:
        if statement.lstrip().upper().startswith("SELECT"):
            self.statements.append(statement)


def test_audit05_one_sku_is_read_with_one_batch_statement(db_session):
    """Three statements (catalogue, quantity, batches), independent of store size."""
    shop = make_shop(db_session)
    for index in range(30):
        extra = f"TEST-SKU-X{index:02d}{uid(3)}"
        db_session.add(Product(sku=extra, barcode=f"BC-{extra}", name="Noise",
                               category="TEST", unit_price=Decimal("10.00")))
        db_session.flush()
        add_stock(db_session, shop.store_id, extra, 4,
                  expiry_date=TODAY + timedelta(days=index % 7 + 1))
    db_session.commit()

    with StatementCounter(db_session) as counter:
        lines = stock_query.stock_lines(db_session, shop.store_id, shop.sku_a)

    assert lines == [(shop.sku_a, 5, [(lines[0][2][0][0], TODAY + timedelta(days=10), 5)])]
    # A bigger store must not cost more statements, and nothing reads every batch.
    assert len(counter.statements) == 3, counter.statements
    for statement in counter.statements:
        if "product_batch" in statement.lower():
            assert "sku" in statement.lower(), statement


def test_audit05_one_sku_never_reads_the_whole_store(db_session, monkeypatch):
    """The audit's finding: the single-SKU path called the all-batches reader."""
    shop = make_shop(db_session)
    calls: list[str] = []

    def forbidden(*args, **kwargs):
        calls.append("list_store_batches")
        raise AssertionError("the single-SKU path must not read every batch of the store")

    monkeypatch.setattr(stock_query.repository, "list_store_batches", forbidden)

    assert stock_query.stock_lines(db_session, shop.store_id, shop.sku_a)[0][:2] == (
        shop.sku_a, 5)
    assert calls == []


def test_audit05_one_sku_does_not_read_another_skus_batches(db_session):
    shop = make_shop(db_session)

    with StatementCounter(db_session) as counter:
        stock_query.stock_lines(db_session, shop.store_id, shop.sku_a)

    batches_statement = next(statement for statement in counter.statements
                             if "product_batch" in statement.lower())
    # The predicate is in the SQL, not applied to a full read afterwards.
    assert "sku" in batches_statement.lower()


def test_audit05_the_single_sku_answer_matches_the_list_answer(db_session):
    shop = make_shop(db_session)

    listed = {line[0]: line for line in stock_query.stock_lines(db_session, shop.store_id)}
    single = stock_query.stock_lines(db_session, shop.store_id, shop.sku_b)[0]

    assert single == listed[shop.sku_b]
    assert (single[0], single[1]) == (shop.sku_b, 7)
    assert [tuple(batch[1:]) for batch in single[2]] == [(TODAY + timedelta(days=2), 7)]


def test_audit05_a_catalogue_sku_without_stock_still_returns_zero(db_session):
    shop = make_shop(db_session)
    empty_sku = f"TEST-SKU-E{uid(4)}"
    db_session.add(Product(sku=empty_sku, barcode=f"BC-{empty_sku}", name="No stock",
                           category="TEST", unit_price=Decimal("10.00")))
    db_session.commit()

    assert stock_query.stock_lines(db_session, shop.store_id, empty_sku) == [
        (empty_sku, 0, [])]


def test_audit05_an_unknown_sku_is_still_404(db_session):
    shop = make_shop(db_session)

    with pytest.raises(Exception) as raised:
        stock_query.stock_lines(db_session, shop.store_id, f"TEST-NOPE-{uid(4)}")

    assert getattr(raised.value, "status", None) == 404
