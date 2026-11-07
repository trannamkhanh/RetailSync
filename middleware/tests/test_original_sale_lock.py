"""Unit checks for how the original-sale readers consume their result.

The readers run against real SQL Server in the other suites. These checks model
the driver behaviour that matters for a deadlock: SQL Server can stream the
matching row and report the deadlock victim (1205) only when the statement is
read to the end. ``CursorResult.first()`` returns the row and closes the cursor,
so the error is lost; the reader must use ``one_or_none()`` instead.
"""

from types import SimpleNamespace

import pytest
from sqlalchemy.exc import OperationalError

from app.repositories import original_sale as repository


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
        self.row = SimpleNamespace(txn_id="TEST-SALE-0001", status="OK")

    def first(self):
        return self.row

    def one_or_none(self):
        raise self._error


class _StubSession:
    def __init__(self, result: _LateErrorResult) -> None:
        self._result = result

    def execute(self, *_args, **_kwargs) -> _LateErrorResult:
        return self._result


@pytest.mark.parametrize("reader", [repository.find_sale, repository.lock_sale])
def test_original_sale_reader_does_not_lose_a_late_deadlock(reader) -> None:
    error = _late_deadlock()
    session = _StubSession(_LateErrorResult(error))

    with pytest.raises(OperationalError) as raised:
        reader(session, "TEST-STORE", "TEST-SALE-0001")

    assert raised.value is error
