"""Active discounts for staff and POS (PB-50). Read-only: never commits.

The rules are in DS-04 ("Active discounts"): an accepted DISCOUNT
recommendation of an active store whose batch still has unexpired stock, or a
SKU-level one decided today. The percentage is the one stored at decision time,
and the price is rounded down to 100 VND here only, so the POS and the Staff
App show the same number.
"""

from datetime import datetime, time, timedelta, timezone
from decimal import ROUND_FLOOR, Decimal

from sqlalchemy.orm import Session

from app.core import clock
from app.core.client_cert import require_terminal_certificate
from app.core.config import settings
from app.core.errors import ApiError
from app.core.security import Principal
from app.domain.models import PosTerminal
from app.repositories import discounts as repository
from app.services.cross_store import haversine_km

HUNDRED = Decimal(100)


def discounted_price(list_price: Decimal, discount_pct: Decimal) -> Decimal:
    """``floor(list_price * (1 - pct / 100) / 100) * 100``."""
    raw = list_price * (HUNDRED - discount_pct) / HUNDRED / HUNDRED
    return raw.to_integral_value(rounding=ROUND_FLOOR) * HUNDRED


def _rows(session: Session, store_ids: list[str]):
    today = clock.today_local()
    day_start = datetime.combine(today, time()) - timedelta(hours=settings.business_utc_offset_hours)
    return today, repository.active_discounts(session, store_ids, today, day_start,
                                              day_start + timedelta(days=1))


def staff_discounts(session: Session, store_id: str, scope: str) -> list[dict]:
    """The active discounts of the caller's store, or of every active store for ``all``.

    Own store first, then by distance (ties by ``store_id``); inside a store by
    SKU, then expiry date. One item per store, SKU and batch: the highest
    percentage, then the latest decision. A caller whose store is missing or
    inactive gets an empty list.
    """
    stores = {store.store_id: store for store in repository.list_stores(session)}
    own = stores.get(store_id)
    if own is None or not own.is_active:
        return []
    distances: dict[str, float | None] = {store_id: None}
    if scope == "all":
        for store in stores.values():
            if store.is_active and store.store_id != store_id:
                distances[store.store_id] = round(haversine_km(
                    own.latitude, own.longitude, store.latitude, store.longitude), 2)
    _, rows = _rows(session, list(distances))
    best: dict[tuple, repository.DiscountRow] = {}
    for row in rows:
        key = (row.store_id, row.sku, row.batch_id)
        kept = best.get(key)
        if kept is None or (row.discount_pct, row.decided_at) > (kept.discount_pct, kept.decided_at):
            best[key] = row

    def order(row: repository.DiscountRow) -> tuple:
        distance = distances[row.store_id]
        return (distance is not None, distance or 0.0, row.store_id, row.sku,
                row.expiry_date is None, row.expiry_date or row.decided_at.date(), row.batch_id or "")

    return [
        {
            "store_id": row.store_id,
            "store_name": stores[row.store_id].name,
            "distance_km": distances[row.store_id],
            "sku": row.sku,
            "name": row.name,
            "batch_id": row.batch_id,
            "expiry_date": row.expiry_date,
            "discount_pct": row.discount_pct,
            "list_price": row.list_price,
            "discounted_price": discounted_price(row.list_price, row.discount_pct),
            "decided_at": row.decided_at.replace(tzinfo=timezone.utc),
            "sold_at_discount": row.sold_at_discount,
        }
        for row in sorted(best.values(), key=order)
    ]


def terminal_store(session: Session, principal: Principal, fingerprint: str | None) -> str:
    """The store of the caller's terminal, after the terminal and certificate checks.

    Raises:
        ApiError(403, "FORBIDDEN"): no terminal in the token, an unknown or
            inactive terminal, a token for another store, or a certificate
            that is not the terminal's.
    """
    terminal = session.get(PosTerminal, principal.pos_id) if principal.pos_id else None
    if terminal is None or terminal.status != "ACTIVE" or terminal.store_id != principal.store_id:
        raise ApiError(403, "FORBIDDEN", "This token is not scoped to an active POS terminal.")
    require_terminal_certificate(session, terminal.pos_id, fingerprint)
    return terminal.store_id


def pos_discounts(session: Session, store_id: str) -> dict:
    """One entry per SKU with the highest active percentage, ordered by SKU."""
    today, rows = _rows(session, [store_id])
    best: dict[str, Decimal] = {}
    prices: dict[str, Decimal] = {}
    for row in rows:
        if row.sku not in best or row.discount_pct > best[row.sku]:
            best[row.sku], prices[row.sku] = row.discount_pct, row.list_price
    return {
        "business_date": today,
        "items": [{"sku": sku, "discount_pct": pct, "discounted_price": discounted_price(prices[sku], pct)}
                  for sku, pct in sorted(best.items())],
    }
