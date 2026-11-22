"""Phase 8 Q5 (minor, stock query): one statement, `?sku=` filtered in SQL.

``stock_lines`` read every batch of the store and then kept the requested SKU
from the dictionary in Python, so a single-SKU lookup on a large store read every
batch of every SKU. The inventory row and its batches were also two separate
SELECTs, so a sale committing between them could return a quantity that no longer
matched the ``batches`` list in the same answer.

Both cases are now one statement with the batches LEFT JOINed onto the inventory
row (and, for a single SKU, onto the catalogue row, so a catalogue product with
no stock row still answers quantity 0).

The name carries no audit number: this is the unnumbered "Minor backend/POS"
group of PR Q5, not audit finding #5, which is Kiệt's `SYNC_SEND_POLL_SECONDS`
work and lives in `test_sync_sender.py` under `test_q5_*` (review of PR #78).
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
    db_session.add(Store(store_id=store_id, name="Q5 stock query store",
                         latitude=Decimal("16.000000"), longitude=Decimal("108.000000"),
                         region_id="TEST"))
    db_session.flush()
    for sku in (sku_a, sku_b):
        db_session.add(Product(sku=sku, barcode=f"BC-{sku}", name="Q5 stock product",
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
            self.statements.append(" ".join(statement.split()))


def test_q5_one_sku_is_one_statement_however_big_the_store(db_session):
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

    assert len(counter.statements) == 1, counter.statements
    assert [tuple(batch[1:]) for batch in lines[0][2]] == [(TODAY + timedelta(days=10), 5)]
    assert (lines[0][0], lines[0][1]) == (shop.sku_a, 5)


def test_q5_the_whole_store_is_one_statement(db_session):
    shop = make_shop(db_session)

    with StatementCounter(db_session) as counter:
        lines = stock_query.stock_lines(db_session, shop.store_id)

    assert len(counter.statements) == 1, counter.statements
    assert [(line[0], line[1]) for line in lines] == [(shop.sku_a, 5), (shop.sku_b, 7)]


def test_q5_one_sku_does_not_read_another_skus_batches(db_session):
    shop = make_shop(db_session)

    with StatementCounter(db_session) as counter:
        stock_query.stock_lines(db_session, shop.store_id, shop.sku_a)

    statement = counter.statements[0]
    assert "sku" in statement.lower()
    # The single-SKU read starts from the catalogue row, so an unknown SKU is
    # decided by the same statement that fetches the answer.
    assert "dbo.product" in statement.lower()


def test_q5_the_single_sku_answer_matches_the_list_answer(db_session):
    shop = make_shop(db_session)

    listed = {line[0]: line for line in stock_query.stock_lines(db_session, shop.store_id)}
    single = stock_query.stock_lines(db_session, shop.store_id, shop.sku_b)[0]

    assert single == listed[shop.sku_b]
    assert (single[0], single[1]) == (shop.sku_b, 7)
    assert [tuple(batch[1:]) for batch in single[2]] == [(TODAY + timedelta(days=2), 7)]


def test_q5_a_catalogue_sku_without_stock_still_returns_zero(db_session):
    shop = make_shop(db_session)
    empty_sku = f"TEST-SKU-E{uid(4)}"
    db_session.add(Product(sku=empty_sku, barcode=f"BC-{empty_sku}", name="No stock",
                           category="TEST", unit_price=Decimal("10.00")))
    db_session.commit()

    assert stock_query.stock_lines(db_session, shop.store_id, empty_sku) == [
        (empty_sku, 0, [])]


def test_q5_a_sold_out_sku_keeps_its_inventory_row(db_session):
    """The batch filter is in the JOIN, so a line with no batches still appears."""
    shop = make_shop(db_session)
    db_session.execute(
        ProductBatch.__table__.update()
        .where(ProductBatch.store_id == shop.store_id, ProductBatch.sku == shop.sku_a)
        .values(quantity=0))
    db_session.commit()

    listed = {line[0]: line for line in stock_query.stock_lines(db_session, shop.store_id)}
    single = stock_query.stock_lines(db_session, shop.store_id, shop.sku_a)[0]

    assert (single[0], single[1], single[2]) == (shop.sku_a, 5, [])
    assert listed[shop.sku_a] == single


def test_q5_an_unknown_sku_is_still_404(db_session):
    shop = make_shop(db_session)

    with pytest.raises(Exception) as raised:
        stock_query.stock_lines(db_session, shop.store_id, f"TEST-NOPE-{uid(4)}")

    assert getattr(raised.value, "status", None) == 404


def test_q5_the_quantity_and_its_batches_come_from_the_same_read(db_session, monkeypatch):
    """A sale between the old two SELECTs could disagree; one statement cannot.

    The old code called ``list_store_stock`` and ``list_store_batches``
    separately, so a commit landing in between gave a ``quantity`` that no longer
    matched the ``batches`` beside it. With one statement there is no second read
    to interleave, which this asserts by counting the reads of each table.
    """
    shop = make_shop(db_session)
    reads: list[str] = []
    original = stock_query.repository.store_stock_lines

    def counted(session, store_id):
        reads.append("store_stock_lines")
        return original(session, store_id)

    monkeypatch.setattr(stock_query.repository, "store_stock_lines", counted)

    with StatementCounter(db_session) as counter:
        lines = stock_query.stock_lines(db_session, shop.store_id)

    assert reads == ["store_stock_lines"], reads
    assert len(counter.statements) == 1
    assert "dbo.inventory" in counter.statements[0].lower()
    assert "product_batch" in counter.statements[0].lower()
    for sku, quantity, batches in lines:
        assert quantity == sum(batch[2] for batch in batches), sku
