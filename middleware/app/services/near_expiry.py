"""Near-expiry thresholds and the daily alert check (PB-21-1 to PB-21-4).

The threshold endpoints commit in the router, like the guardrail endpoints. The
daily check commits once per store in ``app/jobs/near_expiry.py``, so a failure
rolls back that store and leaves no partial alerts.

Every function that compares an expiry date takes ``today`` from
``clock.today_local()`` at call time; tests replace that function.
"""

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.core.security import Principal
from app.domain.models import NearExpiryAlert, NearExpiryConfig
from app.repositories import near_expiry as repository
from app.repositories.registry import find_user_id
from app.services.audit import record_audit

MIN_THRESHOLD_DAYS = 0
MAX_THRESHOLD_DAYS = 3650


def list_thresholds(session: Session) -> list[NearExpiryConfig]:
    return repository.list_thresholds(session)


def _invalid_days(reason: str) -> ApiError:
    return ApiError(422, "VALIDATION_ERROR", f"Invalid field 'threshold_days': {reason}")


def set_threshold(session: Session, category: str, threshold_days: int,
                  principal: Principal) -> NearExpiryConfig:
    """Store one category threshold and write its audit row.

    Raises:
        ApiError(422, "VALIDATION_ERROR"): the value is outside 0 to 3650. The
            schema already rejects a decimal, string, boolean or missing value.
    """
    if not MIN_THRESHOLD_DAYS <= threshold_days <= MAX_THRESHOLD_DAYS:
        raise _invalid_days(f"must be between {MIN_THRESHOLD_DAYS} and {MAX_THRESHOLD_DAYS}.")

    config = repository.find_config(session, category)
    if config is None:
        config = NearExpiryConfig(category=category, threshold_days=threshold_days)
        session.add(config)
        old_days: int | None = None
    else:
        old_days = config.threshold_days
        config.threshold_days = threshold_days
    config.updated_by = find_user_id(session, principal.sub)
    config.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    record_audit(session, "NEAR_EXPIRY_THRESHOLD_UPDATED", "near_expiry_config", category,
                 user_id=config.updated_by,
                 details=f"threshold_days {old_days} -> {threshold_days}")
    session.flush()
    return config


def threshold_for(category: str, thresholds: dict[str, int], default_days: int) -> int:
    """The configured window of a category, else the configured default.

    SQL Server compares varchar case-insensitively, so a category whose case
    differs still finds its row.
    """
    for known, days in thresholds.items():
        if known.casefold() == category.casefold():
            return days
    return default_days


@dataclass(frozen=True)
class StoreCheck:
    """What one store's run did, for the job log and the tests."""

    created: int = 0
    expired: int = 0
    resolved: int = 0


def check_store(session: Session, store_id: str, today, thresholds: dict[str, int],
                default_days: int) -> StoreCheck:
    """Create, expire and resolve the alerts of one store in the caller's transaction.

    The contract, for every batch with quantity above zero:

    - ``0 <= days_to_expiry <= threshold`` is NEAR_EXPIRY;
    - ``days_to_expiry < 0`` is EXPIRED, whatever the threshold is;
    - a batch with an OPEN alert keeps that one alert, and its numbers follow the
      batch. An OPEN NEAR_EXPIRY alert whose batch has expired becomes EXPIRED
      but stays OPEN;
    - an OPEN alert whose batch reached quantity zero, or whose batch row is
      gone, becomes RESOLVED.

    A second run on the same business date therefore creates nothing, and only
    an assignment whose value really moved is written.

    Args:
        session: SQLAlchemy session; the caller commits or rolls back.
        store_id: Store to check.
        today: Business date from ``clock.today_local()``.
        thresholds: ``category -> threshold_days`` from ``near_expiry_config``.
        default_days: Window for a category without a config row.

    Returns:
        Counts of the alerts created, turned EXPIRED and RESOLVED.
    """
    batches = repository.list_batches_in_stock(session, store_id)
    in_stock = {batch.batch_id for batch in batches}
    open_alerts = {alert.batch_id: alert for alert in repository.list_open_alerts(session, store_id)}

    created = expired = resolved = 0
    for alert in open_alerts.values():
        if alert.batch_id not in in_stock:
            alert.status = "RESOLVED"
            alert.remaining_qty = 0
            resolved += 1

    for batch in batches:
        days_left = (batch.expiry_date - today).days
        alert = open_alerts.get(batch.batch_id)
        if alert is None:
            threshold = threshold_for(batch.category, thresholds, default_days)
            if days_left > threshold:
                continue
            session.add(NearExpiryAlert(
                batch_id=batch.batch_id,
                store_id=store_id,
                sku=batch.sku,
                days_to_expiry=days_left,
                remaining_qty=batch.quantity,
                alert_type="EXPIRED" if days_left < 0 else "NEAR_EXPIRY",
                status="OPEN",
            ))
            created += 1
            continue
        if alert.alert_type == "NEAR_EXPIRY" and days_left < 0:
            alert.alert_type = "EXPIRED"
            expired += 1
        if alert.days_to_expiry != days_left:
            alert.days_to_expiry = days_left
        if alert.remaining_qty != batch.quantity:
            alert.remaining_qty = batch.quantity
    session.flush()
    return StoreCheck(created=created, expired=expired, resolved=resolved)
