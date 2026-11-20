"""Dashboard time quality: the pure classifier and its thresholds (plan M5, M8).

No database session is opened. The classifier is the single answer the API and
the console show, so its boundaries are pinned here: the two ``ON_TIME`` edges,
the ``BACKFILL`` range, ``SUSPECT_OLD`` and ``SUSPECT_FUTURE``.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.services import time_quality
from app.services.time_quality import (
    BACKFILL,
    ON_TIME,
    SUSPECT_FUTURE,
    SUSPECT_OLD,
    UNKNOWN,
    Policy,
    classify,
)


RECEIVED = datetime(2026, 11, 17, 3, 15, 0)
SKEW = timedelta(minutes=5)
# The backfill window and the BACKFILL label are different things; naming the
# window BACKFILL would shadow the imported label and make every assertion below
# compare a label against a timedelta.
BACKFILL_WINDOW = timedelta(days=30)
POLICY = Policy(max_future_skew=SKEW, max_backfill=BACKFILL_WINDOW)


def policy_from(settings) -> Policy:
    """The policy the settings produce, so the defaults are tested too."""
    return Policy(
        max_future_skew=timedelta(seconds=settings.pos_max_future_skew_seconds),
        max_backfill=timedelta(days=settings.pos_max_backfill_days),
    )


# --- the four labels, plus the two boundaries of ON_TIME ------------------


@pytest.mark.parametrize("delta", [
    timedelta(0),
    timedelta(minutes=-5),
    timedelta(minutes=5),
    timedelta(minutes=-4, seconds=59),
    timedelta(minutes=4, seconds=59),
    timedelta(seconds=300),
    timedelta(seconds=-300),
])
def test_pb49_on_time_covers_the_inclusive_skew_window(delta) -> None:
    assert classify(RECEIVED + delta, RECEIVED, POLICY) == ON_TIME


@pytest.mark.parametrize("delta", [
    timedelta(minutes=-5, microseconds=-1),
    timedelta(hours=-1),
    timedelta(days=-7),
    timedelta(days=-29, hours=-23, minutes=-59),
    timedelta(days=-30) + timedelta(microseconds=1),
])
def test_pb49_backfill_covers_a_late_send_within_the_window(delta) -> None:
    """A sale sent late is earlier than ``received_at``, never later."""
    assert classify(RECEIVED + delta, RECEIVED, POLICY) == BACKFILL


@pytest.mark.parametrize("delta", [
    timedelta(minutes=5, microseconds=1),
    timedelta(minutes=6),
    timedelta(days=1),
    timedelta(days=365),
])
def test_pb49_suspect_future_is_past_the_skew_window(delta) -> None:
    assert classify(RECEIVED + delta, RECEIVED, POLICY) == SUSPECT_FUTURE


@pytest.mark.parametrize("delta", [
    timedelta(days=-30),
    timedelta(days=-31),
    timedelta(days=-365),
])
def test_pb49_suspect_old_is_past_the_backfill_window(delta) -> None:
    assert classify(RECEIVED + delta, RECEIVED, POLICY) == SUSPECT_OLD


def test_pb49_the_two_suspect_boundaries_do_not_overlap() -> None:
    """``-30 days`` exactly is SUSPECT_OLD, one microsecond inside is BACKFILL."""
    assert classify(RECEIVED - timedelta(days=30), RECEIVED, POLICY) == SUSPECT_OLD
    assert classify(RECEIVED - timedelta(days=30) + timedelta(microseconds=1),
                    RECEIVED, POLICY) == BACKFILL

def test_pb49_null_occurred_at_is_unknown() -> None:
    """A row stored before migration 004 has no declared moment."""
    assert classify(None, RECEIVED, POLICY) == UNKNOWN


def test_pb49_an_aware_timestamp_is_compared_in_utc() -> None:
    """A ``+07:00`` value and its UTC twin land on the same side of the edge."""
    utc = RECEIVED.replace(tzinfo=timezone.utc)
    bangkok = utc.astimezone(timezone(timedelta(hours=7)))

    assert bangkok.utcoffset() == timedelta(hours=7)
    assert classify(bangkok, RECEIVED, POLICY) == ON_TIME
    assert classify(utc, RECEIVED, POLICY) == ON_TIME


def test_pb49_an_aware_received_at_is_compared_in_utc() -> None:
    """``received_at`` is normalised too, so the same instant compares as ON_TIME."""
    aware_received = RECEIVED.replace(tzinfo=timezone(timedelta(hours=7)))
    same_instant = aware_received.astimezone(timezone.utc).replace(tzinfo=None)

    assert classify(same_instant, aware_received, POLICY) == ON_TIME


@pytest.mark.parametrize("delta", [
    timedelta(days=1), timedelta(days=-1),
])
def test_pb49_a_timestamp_at_the_datetime_limits_does_not_raise(delta) -> None:
    for moment in (datetime.min + timedelta(days=1), datetime.max - timedelta(days=1)):
        assert classify(moment, RECEIVED, POLICY) in {
            ON_TIME, BACKFILL, SUSPECT_FUTURE, SUSPECT_OLD, UNKNOWN,
        }


# --- the configured defaults ----------------------------------------------


def test_pb49_default_thresholds_come_from_the_settings() -> None:
    from app.core.config import settings

    assert settings.pos_max_future_skew_seconds == 300
    assert settings.pos_max_backfill_days == 30
    assert policy_from(settings) == POLICY


def test_pb49_policy_is_a_value() -> None:
    assert Policy(SKEW, BACKFILL_WINDOW) == Policy(SKEW, BACKFILL_WINDOW)
    assert Policy(SKEW, BACKFILL_WINDOW) != Policy(SKEW, timedelta(days=7))


def test_pb49_the_module_does_not_import_the_database_stack() -> None:
    """M5 asks for a pure function: no sqlalchemy, no session."""
    source = open(time_quality.__file__, encoding="utf-8").read()

    assert "sqlalchemy" not in source
    assert "Session" not in source


def test_pb49_every_label_is_reachable() -> None:
    """Guard against a label that nothing can return."""
    labels = {
        classify(RECEIVED, RECEIVED, POLICY),                        # ON_TIME
        classify(RECEIVED - timedelta(days=2), RECEIVED, POLICY),    # BACKFILL
        classify(RECEIVED + timedelta(days=2), RECEIVED, POLICY),    # SUSPECT_FUTURE
        classify(RECEIVED - timedelta(days=90), RECEIVED, POLICY),   # SUSPECT_OLD
        classify(None, RECEIVED, POLICY),                            # UNKNOWN
    }
    assert labels == {ON_TIME, BACKFILL, SUSPECT_FUTURE, SUSPECT_OLD, UNKNOWN}
    assert set(time_quality.LABELS) == labels


# --- the datetime limits (Dashboard_Review 4.4) ----------------------------


@pytest.mark.parametrize("utc_offset", [
    timedelta(hours=7),
    timedelta(hours=-7),
    timedelta(hours=14),
    timedelta(hours=-12),
])
def test_pb49_a_timestamp_at_either_limit_is_stored_and_labelled(utc_offset) -> None:
    """``0001-01-01T00:00:00+07:00`` and its mirror must not raise.

    The UTC conversion of such a value leaves the representable range, so a naive
    ``astimezone`` raises ``OverflowError``. The write path clamps instead, and the
    clamped moment is then far from ``received_at``, which is exactly what the
    classifier is for: it labels the row suspect rather than trusting it.
    """
    from app.services.idempotency import _to_utc_naive

    for edge in (datetime.min, datetime.max.replace(microsecond=0)):
        aware = edge.replace(tzinfo=timezone(utc_offset))
        stored = _to_utc_naive(aware)

        assert stored is not None
        assert stored.tzinfo is None
        assert classify(stored, RECEIVED, POLICY) in {SUSPECT_FUTURE, SUSPECT_OLD}


def test_pb49_an_in_range_offset_is_still_converted_exactly() -> None:
    """The clamp only applies at the limits; an ordinary value converts normally."""
    from app.services.idempotency import _to_utc_naive

    aware = datetime(2026, 11, 17, 3, 15, tzinfo=timezone(timedelta(hours=7)))

    assert _to_utc_naive(aware) == datetime(2026, 11, 16, 20, 15)
