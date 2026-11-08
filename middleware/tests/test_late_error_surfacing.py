"""Checks that a late SQL Server error is not lost by the repository readers.

A plan can scan, stream the matching row and only then report the deadlock
victim (1205) while it finishes. ``CursorResult.first()`` returns that row and
closes the cursor, so the error is lost and the request continues in the
transaction SQL Server already rolled back. The readers must read the result to
the end. The stub checks model that driver behaviour; the SQL Server check
proves it with the real driver.
"""

from types import SimpleNamespace

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DataError, OperationalError
from sqlalchemy.orm import Session

from app.repositories import inventory, original_sale


def _late_deadlock() -> OperationalError:
    return OperationalError(
        "SELECT txn_id, status FROM dbo.pos_transaction WITH (UPDLOCK, ROWLOCK)",
        {},
        RuntimeError("(1205) Transaction was deadlocked on lock resources"),
    )


class _LateErrorResult:
    """One streamed row, then the deadlock error the driver reports last."""

    def __init__(self, error: Exception) -> None:
        self._error = error
        self.row = SimpleNamespace(txn_id="TEST-SALE-0001", status="OK", quantity=1)

    def first(self):
        return self.row

    def one_or_none(self):
        raise self._error


class _StubSession:
    def __init__(self, result: _LateErrorResult) -> None:
        self._result = result

    def execute(self, *_args, **_kwargs) -> _LateErrorResult:
        return self._result


@pytest.mark.parametrize("reader", [original_sale.find_sale, original_sale.lock_sale])
def test_original_sale_reader_does_not_lose_a_late_deadlock(reader) -> None:
    error = _late_deadlock()
    session = _StubSession(_LateErrorResult(error))

    with pytest.raises(OperationalError) as raised:
        reader(session, "TEST-STORE", "TEST-SALE-0001")

    assert raised.value is error


def test_stock_update_does_not_lose_a_late_deadlock() -> None:
    error = _late_deadlock()
    session = _StubSession(_LateErrorResult(error))

    with pytest.raises(OperationalError) as raised:
        inventory.update_stock_with_guard(session, "TEST-STORE", "TEST-SKU-0001", -1)

    assert raised.value is error


def test_sql_server_reports_a_late_error_only_when_the_result_is_read(test_engine) -> None:
    """The first row arrives, then the error; only a further read raises it."""
    statement = text("SELECT 10 / v AS x FROM (VALUES (1), (0)) AS t(v)")

    with Session(test_engine) as session:
        assert session.execute(statement).first() == (10,)

    with Session(test_engine) as session:
        with pytest.raises(DataError):
            session.execute(statement).one_or_none()
