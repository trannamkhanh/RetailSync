"""Dashboard decisions: scope, comparison set, query validation, zero fill (PB-49, B3).

Everything here is a decision, not a query. The repository answers with rows; this
module decides what the caller may see, what a valid interval is, which buckets
exist even when nothing happened in them, and how the totals and shares add up.

The two scopes are separate on purpose. The **view scope** (``store_id``) decides
the line and pie charts; the **comparison scope** (``compare_store_ids``) decides
the bar chart. A Manager may read one store and still compare it against the other
stores in that Manager's own authority, because the comparison set is intersected
with the allowed set, never unioned with it.

Authority:

* Admin and Auditor: every store.
* Manager: the store of ``staff_user``; the token claim is already merged into it
  by ``security._authorize``. A Manager with no store gets 403, because the
  account is misconfigured rather than unauthorized.

The bucket axis is aligned in Python to exactly the same instants the repository
groups by, so a bucket the query returns and a bucket this module invents are the
same ``datetime``. ``offset_hours`` is the store's business offset (UTC+7 by
default), so a day starts at local midnight and a week starts on local Monday.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import ApiError
from app.repositories import dashboard as repository
from app.repositories.dashboard import BucketRow, QualityCounts, RevenueRow

# How far one request may reach, so a single call cannot ask for a decade of
# buckets. Ten years covers the demo's 90 days and a real deployment's history.
MAX_RANGE_DAYS = 3650

# An hourly bucket multiplies the point count by 24, so its own cap is much
# smaller: 90 days is 2,160 buckets, which still draws and still answers quickly.
MAX_HOUR_RANGE_DAYS = 90

CENT = Decimal("0.01")


def _invalid(field: str, reason: str) -> ApiError:
    return ApiError(422, "VALIDATION_ERROR", f"Invalid field '{field}': {reason}")


def _forbidden(message: str) -> ApiError:
    return ApiError(403, "FORBIDDEN", message)


# --- the validated query --------------------------------------------------


@dataclass(frozen=True)
class DashboardQuery:
    """One validated Dashboard request, with both scopes already resolved."""

    store_id: str | None
    compare_store_ids: tuple[str, ...]
    start: datetime
    end: datetime
    bucket: str
    include_suspect: bool
    skew_seconds: int
    backfill_days: int
    offset_hours: int


def _to_utc(field: str, value: datetime) -> datetime:
    """A value without an offset is already UTC; an offset is converted.

    ``0001-01-01T00:00:00+07:00`` and ``9999-12-31T23:59:59-07:00`` are legal
    instants whose UTC conversion leaves the representable range, so ``astimezone``
    raises. A caller-supplied ``from``/``to`` that cannot be converted is a bad
    request, not a server fault, so it answers 422 instead of escaping as 503.
    """
    if value.tzinfo is None:
        return value
    try:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    except (OverflowError, ValueError):
        raise _invalid(
            field, "is too close to the datetime limits to convert to UTC.") from None


def parse_interval(start: datetime, end: datetime) -> tuple[datetime, datetime]:
    """Validate the half-open interval ``[start, end)`` and return it in UTC.

    Raises:
        ApiError(422, "VALIDATION_ERROR"): either bound cannot be converted to UTC,
            ``end`` is not after ``start``, or the span is longer than
            :data:`MAX_RANGE_DAYS` (or, for ``bucket="hour"``, the hourly cap).
    """
    start, end = _to_utc("from", start), _to_utc("to", end)
    if end <= start:
        raise _invalid("to", "must be later than 'from'.")
    if end - start > timedelta(days=MAX_RANGE_DAYS):
        raise _invalid("from", f"spans more than {MAX_RANGE_DAYS} days.")
    return start, end


# --- authority ------------------------------------------------------------


def _all_stores(session: Session) -> set[str]:
    return set(repository.all_store_ids(session))


def _allowed_store_ids(session: Session, principal) -> set[str]:
    """The store ids this caller may read."""
    if principal.role in ("Admin", "Auditor"):
        return _all_stores(session)
    store_id = principal.store_id
    if store_id is None or store_id not in repository.known_store_ids(session, [store_id]):
        raise _forbidden("This account has no store, so it may not read the Dashboard.")
    return {store_id}


def _require_known(session: Session, store_id: str) -> None:
    if store_id not in repository.known_store_ids(session, [store_id]):
        raise ApiError(422, "INVALID_STORE", f"Store '{store_id}' does not exist.")


def resolve_scope(session: Session, principal, store_id: str | None) -> str | None:
    """Check the view scope of charts 1 and 2, and answer the store to filter on.

    An absent ``store_id`` means the whole system for Admin and Auditor, but the
    caller's whole scope for a Manager — which is its single store. Narrowing it
    here rather than in the query keeps one place responsible for scope.

    Args:
        session: SQLAlchemy session; a read, so nothing is committed.
        principal: The authenticated caller.
        store_id: The requested store, or ``None`` for the caller's whole scope.

    Returns:
        A store id to filter on, or ``None`` when the answer spans every store.

    Raises:
        ApiError(403, "FORBIDDEN"): a Manager asking for another store, or an
            account with no store at all.
        ApiError(422, "INVALID_STORE"): Admin or Auditor named a store that does
            not exist.
    """
    if store_id is None:
        if principal.role in ("Admin", "Auditor"):
            return None
        # A Manager's whole scope is its own store, never the system's.
        allowed = _allowed_store_ids(session, principal)
        return next(iter(allowed))
    if principal.role in ("Admin", "Auditor"):
        _require_known(session, store_id)
        return store_id
    if store_id != principal.store_id:
        # A Manager outside its store gets 403, not 422: the store may well exist
        # and saying so would leak it (plan section 7.2).
        raise _forbidden(f"This account may not read revenue of store '{store_id}'.")
    return store_id


def resolve_compare(session: Session, principal,
                    compare_store_ids: list[str] | None) -> tuple[str, ...]:
    """Check the comparison set of chart 3 and answer the stores to compare.

    An absent or empty list means every store in the caller's scope. A caller may
    only narrow that set: naming a store outside the scope is 403 for a Manager,
    and a store that does not exist is 422 for anyone.

    The order matters. For a Manager, ``outside`` is checked **before** ``unknown``,
    so a probe answers 403 whether or not the store exists; checking existence first
    would answer 422 for an unknown store and 403 for a known one, which tells the
    caller that the store exists. Admin and Auditor see every store, so for them
    ``outside`` is always empty and ``unknown`` is the only possible answer.

    Args:
        session: SQLAlchemy session; a read, so nothing is committed.
        principal: The authenticated caller.
        compare_store_ids: The requested stores, or ``None`` for the whole scope.

    Returns:
        The store ids to compare, in the caller's order, without duplicates. A
        repeated id would otherwise draw the same column twice and make the shares
        add up to more than 1.

    Raises:
        ApiError(403, "FORBIDDEN"): a store outside the caller's scope.
        ApiError(422, "INVALID_STORE"): a store that does not exist.
    """
    allowed = _allowed_store_ids(session, principal)
    if not compare_store_ids:
        return tuple(sorted(allowed))

    # Order preserved, duplicates dropped: the caller's order is the column order.
    requested = tuple(dict.fromkeys(compare_store_ids))

    if principal.role not in ("Admin", "Auditor"):
        outside = sorted(set(requested) - allowed)
        if outside:
            raise _forbidden(f"This account may not compare store '{outside[0]}'.")

    unknown = sorted(set(requested) - repository.known_store_ids(session, list(requested)))
    if unknown:
        raise ApiError(422, "INVALID_STORE", f"Store '{unknown[0]}' does not exist.")
    return requested


def stores_for(session: Session, principal) -> list[tuple[str, str, str, bool]]:
    """The store list of ``GET /dashboard/stores``.

    Only the caller's role limits this answer: the endpoint accepts no ``store_id``
    and validates none, so it cannot be used to probe whether some store exists. A
    Manager with no store gets 403.
    """
    allowed = _allowed_store_ids(session, principal)
    return [row for row in repository.store_scope(session) if row[0] in allowed]


# --- the bucket axis ------------------------------------------------------


def _shift(moment: datetime, hours: int) -> datetime:
    """``moment`` shifted by ``hours``, clamped instead of raising at the limits.

    A request may reach back to year 1, and shifting the first representable instant
    by the business offset leaves the representable range, so ``timedelta`` raises
    ``OverflowError``. The repository's SQL has the same guard, and the two must agree
    on the bucket axis, so both clamp to the nearest representable instant.
    """
    try:
        return moment + timedelta(hours=hours)
    except OverflowError:
        return datetime.max.replace(microsecond=0) if hours > 0 else datetime.min


def _local_truncate(local: datetime, bucket: str) -> datetime:
    """The start of the bucket containing ``local``, in the store's local time.

    The axis is derived in local time because that is what the repository's SQL does:
    it shifts the stored moment into local time, truncates there, and shifts back. A
    day therefore starts at local midnight — 17:00Z the day before, at UTC+7 — and the
    two sides cannot disagree about which bucket a row belongs to.
    """
    if bucket == "hour":
        return local.replace(minute=0, second=0, microsecond=0)
    if bucket == "day":
        return local.replace(hour=0, minute=0, second=0, microsecond=0)
    if bucket == "week":
        return (local - timedelta(days=local.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0)
    if bucket == "month":
        return local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    raise ValueError(f"unsupported dashboard bucket: {bucket!r}")


def _local_advance(local: datetime, bucket: str) -> datetime:
    """The next bucket start in local time, clamping instead of raising.

    At the top of the type the step clamps, so the result can equal its input. The
    caller treats that as the end of the axis rather than looping on it.
    """
    if bucket == "hour":
        return _shift(local, 1)
    if bucket == "day":
        return _shift(local, 24)
    if bucket == "week":
        return _shift(local, 24 * 7)
    if bucket == "month":
        year, month = local.year + (local.month == 12), local.month % 12 + 1
        try:
            return local.replace(year=year, month=month, day=1)
        except ValueError:
            # December 9999 has nowhere to advance to; the axis ends at the ceiling.
            return datetime.max.replace(microsecond=0)
    raise ValueError(f"unsupported dashboard bucket: {bucket!r}")


def bucket_starts(start: datetime, end: datetime, bucket: str,
                  offset_hours: int) -> list[tuple[datetime, datetime]]:
    """``(from, to)`` of every bucket that meets ``[start, end)``, in order.

    Each bucket is derived as a local-time boundary and then converted to UTC with the
    same floor clamp the SQL applies, so a row's SQL ``bucket_start`` always equals one
    of these window starts. That matters because the two can only be compared with each
    other: an earlier revision aligned each window by adding 24 hours to the previous
    *UTC* edge, so once the first bucket was clamped at the floor of the type every
    later window sat 7 hours away from the SQL bucket and its revenue was silently
    dropped from the chart.

    The interval is covered exactly: the first window starts at the bucket containing
    ``start``, and the last one ends at ``end``.
    """
    local_end = _shift(end, offset_hours)
    current = _local_truncate(_shift(start, offset_hours), bucket)

    starts: list[datetime] = []
    while True:
        starts.append(_shift(current, -offset_hours))
        following = _local_advance(current, bucket)
        # Stop at the end of the interval, and also when the type cannot express the
        # next boundary: a non-advancing step would append identical windows forever.
        if following <= current or following >= local_end:
            break
        current = following

    windows: list[tuple[datetime, datetime]] = []
    for index, left in enumerate(starts):
        right = starts[index + 1] if index + 1 < len(starts) else end
        if right <= left:
            # A degenerate window can only be the last one, at the very top of the
            # type; clamping it to the interval keeps the axis usable.
            right = end if end > left else left
        windows.append((left, right))
    return windows


def _check_hourly_span(start: datetime, end: datetime, bucket: str) -> None:
    """Reject an ``hour`` request whose bucket count would exceed the cap.

    ``MAX_RANGE_DAYS`` bounds the *date* range, which is fine for a day bucket but
    lets ``bucket="hour"`` over 3,650 days ask for 87,600 buckets in one synchronous
    request. The hourly bucket therefore carries its own, tighter cap.
    """
    if bucket != "hour":
        return
    cap = timedelta(days=MAX_HOUR_RANGE_DAYS)
    if end - start > cap:
        raise _invalid(
            "from", f"spans more than {MAX_HOUR_RANGE_DAYS} days for bucket='hour'.")


def zero_fill(start: datetime, end: datetime, bucket: str, offset_hours: int,
              rows: list[BucketRow],
              windows: list[tuple[datetime, datetime]] | None = None) -> list[BucketRow]:
    """Merge the query's buckets into one row per bucket of the interval.

    Args:
        start: The interval's start, in UTC.
        end: The interval's end, in UTC and excluded.
        bucket: One of ``hour``, ``day``, ``week``, ``month``.
        offset_hours: The store's business offset.
        rows: ``BucketRow`` values, oldest first, with empty buckets missing.
        windows: The axis to fill, when the caller has already built it. Passing it
            avoids deriving the same axis twice for one request; ``revenue_series``
            needs the windows for its own points as well.

    Returns:
        One ``BucketRow`` per bucket window, in order, with revenue 0 and no
        transactions where nothing happened.
    """
    if windows is None:
        windows = bucket_starts(start, end, bucket, offset_hours)
    known = {row.start: row for row in rows}
    return [
        known.get(window_start)
        or BucketRow(start=window_start, revenue=Decimal("0.00"), transactions=0)
        for window_start, _ in windows
    ]


# --- building the query ---------------------------------------------------


def build_query(session: Session, principal, *, store_id: str | None,
                compare_store_ids: list[str] | None, start: datetime, end: datetime,
                bucket: str = "day", include_suspect: bool = True) -> DashboardQuery:
    """Validate one request and return the query the endpoints run.

    The order is deliberate: the interval first, because a bad interval is the
    caller's own mistake; then the view scope; then the comparison set. The
    thresholds and the business offset come from the settings, so the console
    never supplies them and cannot desynchronise them.
    """
    start, end = parse_interval(start, end)
    if bucket not in repository.BUCKETS:
        raise _invalid("bucket", f"must be one of {', '.join(repository.BUCKETS)}.")
    _check_hourly_span(start, end, bucket)
    return DashboardQuery(
        store_id=resolve_scope(session, principal, store_id),
        compare_store_ids=resolve_compare(session, principal, compare_store_ids),
        start=start,
        end=end,
        bucket=bucket,
        include_suspect=include_suspect,
        skew_seconds=settings.pos_max_future_skew_seconds,
        backfill_days=settings.pos_max_backfill_days,
        offset_hours=settings.business_utc_offset_hours,
    )


# --- results --------------------------------------------------------------


@dataclass(frozen=True)
class RevenuePoint:
    """One point of the line chart, over the half-open bucket ``[start, end)``."""

    start: datetime
    end: datetime
    revenue: Decimal
    transactions: int


@dataclass(frozen=True)
class RevenueSeries:
    """The line chart plus its KPI: buckets, total, count and quality."""

    scope_store_id: str | None
    time_policy: tuple[int, int]
    data_from: datetime | None
    data_to: datetime | None
    has_data: bool
    total_revenue: Decimal
    transactions: int
    quality: QualityCounts
    points: list[RevenuePoint]


@dataclass(frozen=True)
class CategoryShare:
    """One slice of the pie chart."""

    category: str
    revenue: Decimal
    share: Decimal


@dataclass(frozen=True)
class CategoryBreakdown:
    """The pie chart plus its KPI."""

    scope_store_id: str | None
    time_policy: tuple[int, int]
    total_revenue: Decimal
    transactions: int
    quality: QualityCounts
    categories: list[CategoryShare]


@dataclass(frozen=True)
class StoreShare:
    """One column of the comparison chart."""

    store_id: str
    name: str
    region_id: str
    revenue: Decimal
    share: Decimal


@dataclass(frozen=True)
class StoreComparison:
    """The bar chart plus its KPI."""

    scope_store_id: str | None
    time_policy: tuple[int, int]
    data_from: datetime | None
    data_to: datetime | None
    has_data: bool
    total_revenue: Decimal
    transactions: int
    quality: QualityCounts
    stores: list[StoreShare]


def _share(part: Decimal, total: Decimal) -> Decimal:
    """``part`` as a fraction of ``total``, or 0 when the total is 0 or negative.

    A share is only meaningful against a positive total; a negative or zero total
    is reported by the caller as the empty or loss state instead of dividing.
    """
    if total <= 0:
        return Decimal("0")
    return (part / total).quantize(Decimal("0.000001"))


def _total(rows) -> Decimal:
    return sum((row.revenue for row in rows), Decimal("0.00")).quantize(CENT)


def _filtered_transactions(quality, include_suspect: bool) -> int:
    """The transaction count that matches the money beside it.

    ``quality`` always counts the whole interval, which is what the badge shows. The
    KPI beside the pie has to match the filtered money, so with
    ``include_suspect=False`` it drops the two suspect groups but keeps ``unknown``:
    a row without ``occurred_at`` has no suspect label and its revenue is included.
    """
    if include_suspect:
        return quality.transactions
    return quality.transactions - quality.suspect_future - quality.suspect_old


def revenue_series(session: Session, query: DashboardQuery) -> RevenueSeries:
    """The line chart of the query's view scope and interval."""
    rows = repository.revenue_by_bucket(
        session, query.store_id, query.start, query.end,
        query.skew_seconds, query.backfill_days, query.offset_hours, query.bucket,
        query.include_suspect,
    )
    # The axis is built once and handed to zero_fill, which needs the same windows to
    # place a row and to know which buckets exist. Deriving it a second time inside
    # zero_fill doubled the work on a long hourly range for no benefit.
    windows = bucket_starts(query.start, query.end, query.bucket, query.offset_hours)
    filled = zero_fill(query.start, query.end, query.bucket, query.offset_hours,
                       rows, windows)
    points = [
        RevenuePoint(start=start, end=end, revenue=row.revenue, transactions=row.transactions)
        for (start, end), row in zip(windows, filled)
    ]
    quality = repository.quality_counts(
        session, query.store_id, query.start, query.end,
        query.skew_seconds, query.backfill_days,
    )
    data_from, data_to = repository.data_span(session, query.start, query.end, query.store_id)
    return RevenueSeries(
        scope_store_id=query.store_id,
        time_policy=(query.skew_seconds, query.backfill_days),
        data_from=data_from,
        data_to=data_to,
        # has_data describes the money in this answer, so it follows include_suspect:
        # an interval whose every transaction is suspect draws nothing when the filter
        # is on, even though `quality` still counts those transactions for the badge.
        has_data=sum(row.transactions for row in filled) > 0,
        total_revenue=_total(filled),
        transactions=sum(row.transactions for row in filled),
        quality=quality,
        points=points,
    )


def category_breakdown(session: Session, query: DashboardQuery) -> CategoryBreakdown:
    """The pie chart of the query's view scope and interval."""
    rows: list[RevenueRow] = repository.revenue_by_category(
        session, query.store_id, query.start, query.end,
        query.skew_seconds, query.backfill_days, query.include_suspect,
    )
    total = _total(rows)
    quality = repository.quality_counts(
        session, query.store_id, query.start, query.end,
        query.skew_seconds, query.backfill_days,
    )
    return CategoryBreakdown(
        scope_store_id=query.store_id,
        time_policy=(query.skew_seconds, query.backfill_days),
        total_revenue=total,
        # The transaction count comes from the quality read, not from the category
        # rows: COUNT(DISTINCT txn_id) is per category, so one basket holding items
        # from two categories is counted twice and the figure would disagree with
        # /dashboard/revenue over the same interval. `quality` also applies the
        # include_suspect filter, so the count matches the money beside it.
        transactions=_filtered_transactions(quality, query.include_suspect),
        quality=quality,
        categories=[
            CategoryShare(category=row.key, revenue=row.revenue, share=_share(row.revenue, total))
            for row in rows
        ],
    )


def store_comparison(session: Session, query: DashboardQuery) -> StoreComparison:
    """The bar chart over the query's comparison set, sorted by revenue descending."""
    rows = repository.revenue_by_store(
        session, list(query.compare_store_ids), query.start, query.end,
        query.skew_seconds, query.backfill_days, query.include_suspect,
    )
    total = _total(rows)
    details = repository.store_details(session, list(query.compare_store_ids))
    # A store in the set with no revenue keeps its column: the plan asks for a
    # selected store to appear even when it sold nothing.
    by_store = {row.key: row for row in rows}
    columns = []
    for store_id in query.compare_store_ids:
        name, region_id = details.get(store_id, (store_id, ""))
        revenue = by_store[store_id].revenue if store_id in by_store else Decimal("0.00")
        columns.append(StoreShare(
            store_id=store_id, name=name, region_id=region_id,
            revenue=revenue, share=_share(revenue, total),
        ))
    columns.sort(key=lambda column: (-column.revenue, column.store_id))
    quality = repository.quality_counts(
        session, None, query.start, query.end,
        query.skew_seconds, query.backfill_days, stores=list(query.compare_store_ids),
    )
    data_from, data_to = repository.data_span(
        session, query.start, query.end, stores=list(query.compare_store_ids))
    return StoreComparison(
        scope_store_id=query.store_id,
        time_policy=(query.skew_seconds, query.backfill_days),
        data_from=data_from,
        data_to=data_to,
        # has_data describes the money in this answer, so it follows include_suspect:
        # a filtered request whose every row is suspect has no data to draw even
        # though the unfiltered interval does.
        has_data=_filtered_transactions(quality, query.include_suspect) > 0,
        total_revenue=total,
        # A transaction belongs to exactly one store, so summing the per-store counts
        # is correct here; unlike categories, no row can be counted twice.
        transactions=sum(row.transactions for row in rows),
        quality=quality,
        stores=columns,
    )
