"""How far a POS-declared ``occurred_at`` can be trusted (Dashboard M5).

The classification is a pure function: it takes the two moments and the two
thresholds and returns a label. It never opens a database session, so the
Dashboard, its tests and any future client can agree on one answer without a
second source of truth.

| Label            | Condition, relative to ``received_at``          | Reading |
|------------------|-------------------------------------------------|---------|
| ``ON_TIME``      | ``-skew <= occurred - received <= +skew``       | normal, small clock drift |
| ``BACKFILL``     | ``-backfill_days < occurred - received < -skew``| offline POS sending later, trusted |
| ``SUSPECT_FUTURE`` | ``occurred - received > +skew``               | terminal clock running fast, or bad data |
| ``SUSPECT_OLD``  | ``occurred - received <= -backfill_days``       | sent far too late, or hand-entered |

The thresholds are inclusive on the ``ON_TIME`` side, exactly as the plan's
boundary cases require: at ``-5 minutes`` and ``+5 minutes`` the label is still
``ON_TIME``.

``occurred_at`` is NULL for a transaction stored before migration 004. Nothing is
claimed about those rows, so the label is ``UNKNOWN``: the Dashboard falls back
to ``created_at`` and says the moment is approximate.
"""

from datetime import datetime, timedelta, timezone

ON_TIME = "ON_TIME"
BACKFILL = "BACKFILL"
SUSPECT_FUTURE = "SUSPECT_FUTURE"
SUSPECT_OLD = "SUSPECT_OLD"
UNKNOWN = "UNKNOWN"

LABELS = (ON_TIME, BACKFILL, SUSPECT_FUTURE, SUSPECT_OLD, UNKNOWN)


class Policy:
    """The two thresholds, kept as a value so a caller can pass a fixed pair."""

    __slots__ = ("max_future_skew", "max_backfill")

    def __init__(self, max_future_skew: timedelta, max_backfill: timedelta) -> None:
        self.max_future_skew = max_future_skew
        self.max_backfill = max_backfill

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Policy):
            return NotImplemented
        return (self.max_future_skew, self.max_backfill) == (
            other.max_future_skew, other.max_backfill)

    def __hash__(self) -> int:
        return hash((self.max_future_skew, self.max_backfill))

    def __repr__(self) -> str:
        return (f"Policy(max_future_skew={self.max_future_skew!r}, "
                f"max_backfill={self.max_backfill!r})")


def _shifted(moment: datetime, delta: timedelta) -> datetime:
    """``moment + delta`` without raising at the datetime limits.

    A timestamp near ``datetime.min`` or ``datetime.max`` is legal input; adding a
    day to it is not. Clamping keeps the comparison total instead of raising.
    """
    try:
        return moment + delta
    except OverflowError:
        return datetime.max if delta > timedelta(0) else datetime.min


def _utc_naive(moment: datetime) -> datetime:
    """Drop the offset, converting first, so two naive values can be compared."""
    if moment.tzinfo is None:
        return moment
    return moment.astimezone(timezone.utc).replace(tzinfo=None)


def classify(occurred_at: datetime | None, received_at: datetime,
             policy: Policy) -> str:
    """Return the label of ``occurred_at`` as seen from ``received_at``.

    Args:
        occurred_at: The POS-declared moment, or ``None`` when it was never stored.
        received_at: The moment the Middleware stored the row (``created_at``).
        policy: The two thresholds.

    Returns:
        One of :data:`LABELS`. ``UNKNOWN`` when ``occurred_at`` is ``None``.
    """
    if occurred_at is None:
        return UNKNOWN

    occurred, received = _utc_naive(occurred_at), _utc_naive(received_at)
    skew, backfill = policy.max_future_skew, policy.max_backfill

    if occurred > _shifted(received, skew):
        return SUSPECT_FUTURE
    if occurred < _shifted(received, -skew):
        if occurred <= _shifted(received, -backfill):
            return SUSPECT_OLD
        return BACKFILL
    return ON_TIME
