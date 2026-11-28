"""PB-53 own-store forecast list; never writes or commits."""
from datetime import timedelta
from app.core import clock
from app.repositories.forecast import utc_start
from app.repositories.staff_forecasts import latest_forecasts


def list_forecasts(session, store: str) -> dict:
    today = clock.today_local()
    return {"business_date": today, "items": latest_forecasts(
        session, store, today, utc_start(today - timedelta(days=7)), utc_start(today),
    )}
