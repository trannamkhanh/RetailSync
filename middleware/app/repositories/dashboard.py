"""Revenue reads for the Dashboard (PB-49, plan B2). Never commits.

Four rules shape every statement here:

* The interval is half-open: ``effective_at >= :start AND effective_at < :end``.
  This is the same meaning `/audit-logs` has, only at a different resolution.
* Revenue is ``qty * unit_price`` for a SALE minus the same product for a RETURN
  or CANCELLATION, with **no** ``status`` filter. A CANCELLATION copies the items
  of the sale it cancels and the sale row itself is marked ``CANCELLED``, so the
  pair sums to zero; filtering ``status`` would drop the sale and leave the
  cancellation counted on its own.
* Every string parameter is cast to its column's ``varchar`` length (PB-10-5).
  The driver declares a Python ``str`` as ``nvarchar`` and SQLAlchemy does not
  call ``setinputsizes`` for ``text()``, so an uncast parameter would make SQL
  Server convert the column instead of seeking it.
* Quality is read over the **whole** interval, never over the filtered set: the
  plan requires the counts even when ``include_suspect`` is ``false``, so the
  reader can see how many transactions the money left out.

A transaction's ``effective_at`` is ``COALESCE(occurred_at, created_at)`` and
already falls back for a row stored before migration 004. Those rows are counted
and labelled ``unknown`` rather than dropped, because the revenue is real and only
its timing is approximate.

One ``occurred_at`` is NULL for exactly one label: ``unknown``. The other three
are mutually exclusive and cover everything else, which is what makes ``backfill``
the remainder below.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.orm import Session

# Revenue of one item line: a SALE adds, a RETURN or CANCELLATION subtracts.
LINE_REVENUE = (
    "CASE WHEN t.txn_type = 'SALE' THEN ti.qty * ti.unit_price "
    "ELSE -ti.qty * ti.unit_price END"
)

# ``:skew`` is a whole number of seconds and ``:backfill`` a whole number of
# days, so both convert to datetime2 in SQL and the comparison stays there.
_SUSPECT_FUTURE = "t.occurred_at > DATEADD(SECOND, :skew, t.created_at)"
_SUSPECT_OLD = "t.occurred_at <= DATEADD(DAY, -:backfill, t.created_at)"

# What include_suspect=false keeps: a row that is not in either suspect group.
#
# A NULL ``occurred_at`` (a row stored before migration 004) must be kept. Both
# comparisons below are NULL for such a row, and ``NOT NULL`` is still NULL, so a
# bare ``NOT (...) AND NOT (...)`` silently drops every pre-migration row — its
# revenue is real, only its timing is approximate, so hiding it would understate
# the total. The explicit IS NULL arm makes that intent part of the predicate
# instead of a side effect of three-valued logic.
NOT_SUSPECT = f"(t.occurred_at IS NULL OR (NOT ({_SUSPECT_FUTURE}) AND NOT ({_SUSPECT_OLD})))"

# One row per transaction, and each carries exactly one of the five labels. The
# labels are computed from the two stored moments, without a helper column, as
# the plan requires. ``EXISTS`` keeps a transaction with several items from being
# counted once per item line.
QUALITY_CTE = """
    WITH tx AS (
        SELECT t.occurred_at AS occurred_at, t.created_at AS created_at
        FROM dbo.pos_transaction AS t
        WHERE t.effective_at >= CAST(:start AS datetime2)
          AND t.effective_at < CAST(:end AS datetime2)
          {predicate}
          AND EXISTS (SELECT 1 FROM dbo.transaction_item AS ti
                      WHERE ti.txn_id = t.txn_id)
    )
"""

QUALITY_SELECT = """
    SELECT COUNT(*) AS transactions,
           SUM(CASE WHEN occurred_at IS NULL THEN 1 ELSE 0 END) AS unknown,
           SUM(CASE WHEN occurred_at IS NOT NULL
                     AND occurred_at > DATEADD(SECOND, :skew, created_at)
                    THEN 1 ELSE 0 END) AS suspect_future,
           SUM(CASE WHEN occurred_at IS NOT NULL
                     AND occurred_at <= DATEADD(DAY, -:backfill, created_at)
                    THEN 1 ELSE 0 END) AS suspect_old,
           SUM(CASE WHEN occurred_at IS NOT NULL
                     AND occurred_at > DATEADD(DAY, -:backfill, created_at)
                     AND occurred_at < DATEADD(SECOND, -:skew, created_at)
                    THEN 1 ELSE 0 END) AS backfill,
           SUM(CASE WHEN occurred_at IS NOT NULL
                     AND occurred_at >= DATEADD(SECOND, -:skew, created_at)
                     AND occurred_at <= DATEADD(SECOND, :skew, created_at)
                    THEN 1 ELSE 0 END) AS on_time
    FROM tx
"""

EMPTY_CATEGORY = "Khác"

# Bucket keys are computed in the store's business time and converted back to
# UTC, so a bucket starts where the local hour, day, week or month starts.
#
# The anchor is `CAST('0001-01-01' AS datetime2)`, not the bare `0` literal. A bare
# `0` is an int that SQL Server converts to `datetime`, whose range starts in 1753, so
# `DATEDIFF(DAY, 0, <a year-1 instant>)` raised "datetime2 to datetime out of range"
# and the whole request answered 503. A datetime2 anchor covers the full range the
# column can hold; 0001-01-01 was a Monday, so a multiple of 7 days is still a week
# boundary.
_ANCHOR = "CAST('0001-01-01' AS datetime2)"

# A datetime2 column cannot hold an instant closer than the business offset to
# either end of the type: shifting such a moment into local time overflows, and so
# does shifting the bucket back. Both directions are clamped to the representable
# edge, which is the same thing the Python axis does, so the two still agree.
_DATETIME2_MIN = "CAST('0001-01-01' AS datetime2)"
_DATETIME2_MAX = "CAST('9999-12-31T23:59:59.9999999' AS datetime2)"


def _to_local(moment: str) -> str:
    """``moment`` shifted into the store's business time, clamped at the type edges.

    ``DATEADD(HOUR, :offset, ...)`` raised "Adding a value to a 'datetime2' column
    caused an overflow" for a stored ``occurred_at`` at or beyond
    ``9999-12-31T17:00Z``, which turned a whole /dashboard/revenue request into a 503.
    A CASE guard makes the shift total.
    """
    return (
        f"CASE WHEN {{moment}} > DATEADD(HOUR, -:offset, {_DATETIME2_MAX}) "
        f"THEN {_DATETIME2_MAX} ELSE DATEADD(HOUR, :offset, {{moment}}) END"
    ).format(moment=moment)


def _back_to_utc(bucket: str) -> str:
    """The bucket key back in UTC, so the answer is in the caller's interval.

    The subtraction is clamped for the same reason as the addition: a bucket that
    starts at the very first representable instant cannot move back by the business
    offset. Only a request reaching the type limits is affected.
    """
    return (
        f"CASE WHEN {bucket} < DATEADD(HOUR, :offset, {_DATETIME2_MIN}) "
        f"THEN {_DATETIME2_MIN} ELSE DATEADD(HOUR, -:offset, {bucket}) END"
    )


_BUCKET_LOCAL = {
    "hour": f"DATEADD(HOUR, DATEDIFF(HOUR, {_ANCHOR}, {_to_local('{moment}')}), {_ANCHOR})",
    "day": f"DATEADD(DAY, DATEDIFF(DAY, {_ANCHOR}, {_to_local('{moment}')}), {_ANCHOR})",
    "week": f"DATEADD(DAY, (DATEDIFF(DAY, {_ANCHOR}, {_to_local('{moment}')}) / 7) * 7, {_ANCHOR})",
    "month": f"DATEADD(MONTH, DATEDIFF(MONTH, {_ANCHOR}, {_to_local('{moment}')}), {_ANCHOR})",
}

_BUCKET_START = _back_to_utc("{bucket}")

BUCKETS = tuple(_BUCKET_LOCAL)


@dataclass(frozen=True)
class RevenueRow:
    """One aggregate row: the group key, its revenue and its transaction count."""

    key: str
    revenue: Decimal
    transactions: int


@dataclass(frozen=True)
class BucketRow:
    """One time bucket: where it starts in UTC, its revenue and its count."""

    start: datetime
    revenue: Decimal
    transactions: int


@dataclass(frozen=True)
class QualityCounts:
    """The five labels of the interval, summing to ``transactions``."""

    transactions: int
    on_time: int
    backfill: int
    suspect_future: int
    suspect_old: int
    unknown: int

    def as_dict(self) -> dict[str, int]:
        return {
            "on_time": self.on_time,
            "backfill": self.backfill,
            "suspect_future": self.suspect_future,
            "suspect_old": self.suspect_old,
            "unknown": self.unknown,
        }


# --- parameters and predicates --------------------------------------------


def _time_parameters(start: datetime, end: datetime) -> dict:
    """The interval, which every aggregate binds."""
    return {"start": start, "end": end}


def _threshold_parameters(skew: int, backfill: int) -> dict:
    """The two thresholds, bound only by a statement that compares them."""
    return {"skew": skew, "backfill": backfill}


def _store_filter(store_id: str | None) -> tuple[str, dict]:
    """The view-scope predicate and its parameter, or nothing when it is absent.

    The parameter travels with its predicate, so a statement and the values it is
    given stay in step; a store the caller did not name is simply not filtered.
    """
    if store_id is None:
        return "", {}
    return "AND t.store_id = CAST(:store AS varchar(10))", {"store": store_id}


def _list_predicate(column: str, stores: list[str]) -> tuple[str, dict]:
    """Membership in a store list, compared as varchar.

    ``STRING_SPLIT`` returns a ``varchar`` column, so the store column is not
    converted. Store ids never contain a comma: ``ID_PATTERN`` allows only
    letters, digits, ``_`` and ``-``, so joining on a comma is unambiguous.
    """
    return (
        f"AND {column} IN "
        "(SELECT CAST(value AS varchar(10)) "
        "FROM STRING_SPLIT(CAST(:stores AS nvarchar(4000)), ','))",
        {"stores": ",".join(stores)},
    )


def _as_datetime(value) -> datetime:
    return value if isinstance(value, datetime) else datetime.fromisoformat(str(value))


def _as_optional_datetime(value) -> datetime | None:
    return None if value is None else _as_datetime(value)


def _as_money(value) -> Decimal:
    """Money as an exact two-decimal ``Decimal``.

    The schema's serializer turns it into a JSON number; Pydantic v2 would
    otherwise emit a ``Decimal`` as a string, which the contract forbids. The
    column is ``decimal(14,2)``, so the value is already exact to the cent.
    """
    return Decimal(str(value)).quantize(Decimal("0.01"))


# --- the three aggregates -------------------------------------------------


def revenue_by_bucket(session: Session, store_id: str | None, start: datetime, end: datetime,
                      skew: int, backfill: int, offset_hours: int, bucket: str,
                      include_suspect: bool = True) -> list[BucketRow]:
    """Revenue and count per bucket of the interval, in UTC, oldest first.

    A bucket with no transaction is not returned; the service zero-fills it,
    because only the service knows the bucket width the caller asked for.
    """
    if bucket not in _BUCKET_LOCAL:
        raise ValueError(f"unsupported dashboard bucket: {bucket!r}")

    bucket_start = _BUCKET_START.format(bucket=_BUCKET_LOCAL[bucket].format(moment="t.effective_at"))
    params = {**_time_parameters(start, end), "offset": offset_hours}
    scope, scope_params = _store_filter(store_id)
    params.update(scope_params)
    suspect_filter = "" if include_suspect else f"AND ({NOT_SUSPECT})"
    params.update(_threshold_parameters(skew, backfill))

    # The bucket expression is computed once in a derived table and grouped by its
    # column name. Grouping by the expression itself does not work when it binds a
    # parameter: each ``:offset`` becomes its own marker, so SQL Server cannot see
    # the GROUP BY expression as equal to the select list one and rejects the
    # statement with error 8120. A bare column name cannot drift that way.
    rows = session.execute(text(f"""
        SELECT bucket AS bucket_start,
               SUM(line_revenue) AS revenue,
               COUNT(DISTINCT txn_id) AS transactions
        FROM (
            SELECT {bucket_start} AS bucket,
                   {LINE_REVENUE} AS line_revenue,
                   t.txn_id AS txn_id
            FROM dbo.pos_transaction AS t
            JOIN dbo.transaction_item AS ti ON ti.txn_id = t.txn_id
            WHERE t.effective_at >= CAST(:start AS datetime2)
              AND t.effective_at < CAST(:end AS datetime2)
              {scope}
              {suspect_filter}
        ) AS bucketed
        GROUP BY bucket
        ORDER BY bucket
    """), params).all()

    return [BucketRow(_as_datetime(row[0]), _as_money(row[1]), int(row[2])) for row in rows]


def revenue_by_category(session: Session, store_id: str | None, start: datetime, end: datetime,
                        skew: int, backfill: int,
                        include_suspect: bool = True) -> list[RevenueRow]:
    """Revenue and count per product category, in name order.

    An empty or blank category is grouped under ``Khác``, so a product with no
    category still appears in the pie instead of vanishing.
    """
    params = {**_time_parameters(start, end), **_threshold_parameters(skew, backfill),
              "empty_category": EMPTY_CATEGORY}
    scope, scope_params = _store_filter(store_id)
    params.update(scope_params)
    suspect_filter = "" if include_suspect else f"AND ({NOT_SUSPECT})"

    # Grouped over a derived table for the same reason as revenue_by_bucket: the
    # category expression binds ``:empty_category``, and a parameter inside
    # GROUP BY is a separate marker SQL Server refuses to match (error 8120).
    rows = session.execute(text(f"""
        SELECT category,
               SUM(line_revenue) AS revenue,
               COUNT(DISTINCT txn_id) AS transactions
        FROM (
            SELECT COALESCE(NULLIF(LTRIM(RTRIM(p.category)), ''), :empty_category) AS category,
                   {LINE_REVENUE} AS line_revenue,
                   t.txn_id AS txn_id
            FROM dbo.pos_transaction AS t
            JOIN dbo.transaction_item AS ti ON ti.txn_id = t.txn_id
            JOIN dbo.product AS p ON p.sku = ti.sku
            WHERE t.effective_at >= CAST(:start AS datetime2)
              AND t.effective_at < CAST(:end AS datetime2)
              {scope}
              {suspect_filter}
        ) AS categorised
        GROUP BY category
        ORDER BY category
    """), params).all()

    return [RevenueRow(str(key), _as_money(revenue), int(transactions))
            for key, revenue, transactions in rows]


def revenue_by_store(session: Session, stores: list[str], start: datetime, end: datetime,
                     skew: int, backfill: int,
                     include_suspect: bool = True) -> list[RevenueRow]:
    """Revenue and count per store of the comparison set, in id order.

    The caller has already checked the set, so the query only filters; it never
    decides what is allowed.
    """
    params = {**_time_parameters(start, end), **_threshold_parameters(skew, backfill)}
    list_sql, list_params = _list_predicate("t.store_id", stores)
    params.update(list_params)
    suspect_filter = "" if include_suspect else f"AND ({NOT_SUSPECT})"

    rows = session.execute(text(f"""
        SELECT t.store_id,
               SUM({LINE_REVENUE}) AS revenue,
               COUNT(DISTINCT t.txn_id) AS transactions
        FROM dbo.pos_transaction AS t
        JOIN dbo.transaction_item AS ti ON ti.txn_id = t.txn_id
        WHERE t.effective_at >= CAST(:start AS datetime2)
          AND t.effective_at < CAST(:end AS datetime2)
          {list_sql}
          {suspect_filter}
        GROUP BY t.store_id
        ORDER BY t.store_id
    """), params).all()

    return [RevenueRow(str(store_id), _as_money(revenue), int(transactions))
            for store_id, revenue, transactions in rows]


# --- the shared quality and span reads ------------------------------------


def quality_counts(session: Session, store_id: str | None, start: datetime, end: datetime,
                   skew: int, backfill: int, stores: list[str] | None = None) -> QualityCounts:
    """The four labels plus ``unknown``, counted over the whole interval.

    ``stores`` narrows to a comparison set; ``store_id`` narrows to one store.
    They are never both used: the comparison chart passes ``stores``, the other
    two pass ``store_id``.
    """
    params = {**_time_parameters(start, end), **_threshold_parameters(skew, backfill)}
    if stores is not None:
        predicate, filter_params = _list_predicate("t.store_id", stores)
        params.update(filter_params)
    else:
        predicate, filter_params = _store_filter(store_id)
        params.update(filter_params)

    transactions, unknown, future, old, backfilled, on_time = session.execute(text(
        QUALITY_CTE.format(predicate=predicate) + QUALITY_SELECT
    ), params).one()

    return QualityCounts(
        transactions=int(transactions or 0),
        on_time=int(on_time or 0),
        backfill=int(backfilled or 0),
        suspect_future=int(future or 0),
        suspect_old=int(old or 0),
        unknown=int(unknown or 0),
    )


def data_span(session: Session, start: datetime, end: datetime,
              store_id: str | None = None,
              stores: list[str] | None = None) -> tuple[datetime | None, datetime | None]:
    """``(earliest, latest)`` ``effective_at`` with data, or ``(None, None)``.

    The console clamps a request that reaches outside the stored data to this and
    says so, instead of drawing an empty chart. ``stores`` narrows to a comparison
    set; without either argument the span covers the whole system.
    """
    params = _time_parameters(start, end)
    if stores is not None:
        predicate, filter_params = _list_predicate("t.store_id", stores)
        params.update(filter_params)
    else:
        predicate, filter_params = _store_filter(store_id)
        params.update(filter_params)
    earliest, latest = session.execute(text(f"""
        SELECT MIN(t.effective_at), MAX(t.effective_at)
        FROM dbo.pos_transaction AS t
        JOIN dbo.transaction_item AS ti ON ti.txn_id = t.txn_id
        WHERE t.effective_at >= CAST(:start AS datetime2)
          AND t.effective_at < CAST(:end AS datetime2)
          {predicate}
    """), params).one()
    return (_as_optional_datetime(earliest), _as_optional_datetime(latest))


# --- store lookups --------------------------------------------------------


def store_scope(session: Session) -> list[tuple[str, str, str, bool]]:
    """Every store as ``(store_id, name, region_id, is_active)``, ordered by id.

    A closed store is kept on purpose: an Admin still needs the history of a store
    that closed, and this endpoint is the only one that shows it.
    """
    rows = session.execute(text("""
        SELECT store_id, name, region_id, is_active
        FROM dbo.store
        ORDER BY store_id
    """)).all()
    return [(str(store_id), str(name), str(region_id), bool(is_active))
            for store_id, name, region_id, is_active in rows]


def store_details(session: Session, store_ids: list[str]) -> dict[str, tuple[str, str]]:
    """``store_id`` to ``(name, region_id)`` for the given ids, in one query."""
    if not store_ids:
        return {}
    rows = session.execute(
        text("""
            SELECT store_id, name, region_id
            FROM dbo.store
            WHERE store_id IN
                  (SELECT CAST(value AS varchar(10))
                   FROM STRING_SPLIT(CAST(:stores AS nvarchar(4000)), ','))
        """),
        {"stores": ",".join(store_ids)},
    ).all()
    return {str(store_id): (str(name), str(region_id)) for store_id, name, region_id in rows}


def known_store_ids(session: Session, store_ids: list[str]) -> set[str]:
    """The given ids that exist in this database."""
    if not store_ids:
        return set()
    rows = session.execute(
        text("""
            SELECT store_id
            FROM dbo.store
            WHERE store_id IN
                  (SELECT CAST(value AS varchar(10))
                   FROM STRING_SPLIT(CAST(:stores AS nvarchar(4000)), ','))
        """),
        {"stores": ",".join(store_ids)},
    ).all()
    return {str(store_id) for (store_id,) in rows}


def all_store_ids(session: Session) -> list[str]:
    """Every store id, the caller's authorized scope for the comparison set."""
    return [str(store_id) for (store_id,) in session.execute(text("""
        SELECT store_id FROM dbo.store ORDER BY store_id
    """))]
