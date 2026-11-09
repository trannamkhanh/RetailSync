"""Business date: "today" in store local time (PB-20).

Every comparison with ``product_batch.expiry_date`` and every daily schedule
uses :func:`today_local`, so the business date has one definition. Tests replace
the module attribute:

    monkeypatch.setattr("app.core.clock.today_local", lambda: date(2026, 11, 14))

Callers must therefore look the function up at call time (``clock.today_local()``)
instead of binding it with ``from app.core.clock import today_local``, or the
replacement would not be seen.
"""

from datetime import date, datetime, timedelta, timezone

from app.core.config import settings


def today_local() -> date:
    """Return today's date at UTC plus ``settings.business_utc_offset_hours``."""
    offset = timedelta(hours=settings.business_utc_offset_hours)
    return (datetime.now(timezone.utc) + offset).date()
