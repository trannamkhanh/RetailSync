"""Audit #5 (POS write path): one locked read of the original sale, not three.

``process_return`` and ``process_cancellation`` read the original SALE three
times for one answer: ``require_original_sale`` (a plain read), the
``lock_original_sale`` that has to come before the claim, and a second
``lock_original_sale`` after it for the business rules. Each of those was also
three statements of its own (the row, the sold quantities, the returned
quantities), so a RETURN paid for roughly seven extra queries.

The first check stays where DS-04 puts it -- an unknown sale is still
``404 ORIGINAL_SALE_NOT_FOUND`` before the claim inserts the FK-bearing row, and
the lock still comes before the claim so two reversals of one sale cannot
deadlock. What goes away is the duplicate: the lock's result is the sale, so it
is reused instead of re-read.

The suites of both endpoints already pin the behaviour; this file pins the query
count and the error order that the change must not disturb.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session

from app.core import clock
from app.core.errors import ApiError
from app.services import original_sale as original_sale_service
from app.services import pos_cancellation, pos_return
from tests.pos_test_support import seed_sale, uid

TODAY = date(2026, 11, 14)


@pytest.fixture(autouse=True)
def business_date(monkeypatch) -> None:
    monkeypatch.setattr(clock, "today_local", lambda: TODAY)


class StatementCounter:
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


def count_reads_of_the_sale(statements: list[str]) -> int:
    """How many statements read dbo.pos_transaction (the sale's own row)."""
    return sum(1 for statement in statements if "dbo.pos_transaction" in statement
               and "WITH (UPDLOCK" in statement)


def test_audit05_the_lock_is_taken_once_per_return(db_session, monkeypatch):
    world = seed_sale(db_session, sold={f"TEST-SKU-{uid(8)}": 2}, stock=10)
    calls: list[str] = []
    original_lock = original_sale_service.lock_original_sale

    def counted(*args, **kwargs):
        calls.append("lock")
        return original_lock(*args, **kwargs)

    monkeypatch.setattr(pos_return, "lock_original_sale", counted)

    from app.api.schemas.pos import PosEvent
    from app.core.security import Principal

    event = PosEvent.model_validate({
        "event_type": "RETURN", "transaction_id": f"TEST-RET-{uid(10)}",
        "original_transaction_id": world.sale_txn, "store_id": world.store_id,
        "pos_id": world.pos_id, "timestamp": "2026-11-14T03:15:00Z",
        "items": [{"sku": world.skus[0], "quantity": 1, "unit_price": "10.00"}],
    })
    principal = Principal(sub=world.username, role="POS", store_id=world.store_id,
                          pos_id=world.pos_id)

    pos_return.process_return(db_session, event, principal)
    db_session.rollback()

    # One locked read before the claim, and none after it.
    assert calls == ["lock"]


def test_audit05_an_unknown_sale_is_still_404_before_the_claim(db_session):
    world = seed_sale(db_session, sold={f"TEST-SKU-{uid(8)}": 2}, stock=10)
    from app.api.schemas.pos import PosEvent
    from app.core.security import Principal

    event = PosEvent.model_validate({
        "event_type": "RETURN", "transaction_id": f"TEST-RET-{uid(10)}",
        "original_transaction_id": f"TEST-MISSING-{uid(8)}", "store_id": world.store_id,
        "pos_id": world.pos_id, "timestamp": "2026-11-14T03:15:00Z",
        "items": [{"sku": world.skus[0], "quantity": 1, "unit_price": "10.00"}],
    })
    principal = Principal(sub=world.username, role="POS", store_id=world.store_id,
                          pos_id=world.pos_id)

    with pytest.raises(ApiError) as raised:
        pos_return.process_return(db_session, event, principal)

    assert (raised.value.status, raised.value.code) == (404, "ORIGINAL_SALE_NOT_FOUND")


def test_audit05_a_return_reads_the_sale_once_under_the_lock(db_session):
    world = seed_sale(db_session, sold={f"TEST-SKU-{uid(8)}": 2}, stock=10)
    from app.api.schemas.pos import PosEvent
    from app.core.security import Principal

    event = PosEvent.model_validate({
        "event_type": "RETURN", "transaction_id": f"TEST-RET-{uid(10)}",
        "original_transaction_id": world.sale_txn, "store_id": world.store_id,
        "pos_id": world.pos_id, "timestamp": "2026-11-14T03:15:00Z",
        "items": [{"sku": world.skus[0], "quantity": 1, "unit_price": "10.00"}],
    })
    principal = Principal(sub=world.username, role="POS", store_id=world.store_id,
                          pos_id=world.pos_id)

    with StatementCounter(db_session) as counter:
        pos_return.process_return(db_session, event, principal)
        db_session.rollback()

    assert count_reads_of_the_sale(counter.statements) == 1, [
        statement for statement in counter.statements if "pos_transaction" in statement]


def test_audit05_a_cancellation_reads_the_sale_once_under_the_lock(db_session):
    world = seed_sale(db_session, sold={f"TEST-SKU-{uid(8)}": 2}, stock=10)
    from app.api.schemas.pos import PosEvent
    from app.core.security import Principal

    event = PosEvent.model_validate({
        "event_type": "CANCELLATION", "transaction_id": f"TEST-CAN-{uid(10)}",
        "original_transaction_id": world.sale_txn, "store_id": world.store_id,
        "pos_id": world.pos_id, "timestamp": "2026-11-14T03:15:00Z", "items": [],
    })
    principal = Principal(sub=world.username, role="POS", store_id=world.store_id,
                          pos_id=world.pos_id)

    with StatementCounter(db_session) as counter:
        pos_cancellation.process_cancellation(db_session, event, principal)
        db_session.rollback()

    assert count_reads_of_the_sale(counter.statements) == 1
