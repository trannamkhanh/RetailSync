"""Dashboard revenue API against real SQL Server (plan B8).

Three groups:

* The pure parts of the service (interval validation, bucket alignment, zero
  fill) run without a database.
* The response contract is checked on the serialized body, because money must be
  a JSON number and a timestamp must end in ``Z``.
* The numbers, scopes and roles run against ``RTS_DB_TEST`` through the real app.

Every row belongs to a ``TEST-`` store created by this module, and ``db_session``
rolls the outer transaction back, so nothing outlives a test.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas.dashboard import (
    DashboardBucket,
    DashboardCategoryRevenue,
    DashboardRevenue,
    DashboardScope,
    DashboardTimePolicy,
    DashboardTimeQuality,
)
from app.core.config import settings
from app.core.errors import ApiError
from app.core.security import create_token
from app.domain.models import PosTerminal, PosTransaction, Product, StaffUser, Store, TransactionItem
from app.services import dashboard as service
from app.services.dashboard import bucket_starts, parse_interval, zero_fill
from app.repositories.dashboard import BucketRow

URL_STORES = "/api/v1/dashboard/stores"
URL_REVENUE = "/api/v1/dashboard/revenue"
URL_CATEGORY = "/api/v1/dashboard/revenue-by-category"
URL_BY_STORE = "/api/v1/dashboard/revenue-by-store"

# The business offset the tests assume; the settings default is UTC+7.
OFFSET = 7


@pytest.fixture(autouse=True)
def jwt_secret(monkeypatch):
    """Tokens are built here, so the secret must not depend on the local .env."""
    monkeypatch.setattr(settings, "jwt_secret",
                        SecretStr("dashboard-test-secret-with-enough-length"))


# --- pure parts, no database ----------------------------------------------


def test_pb49_interval_is_half_open_and_rejects_an_empty_or_backwards_range() -> None:
    start, end = datetime(2026, 11, 1), datetime(2026, 12, 1)

    assert parse_interval(start, end) == (start, end)
    with pytest.raises(ApiError) as same:
        parse_interval(end, end)
    assert same.value.status == 422
    with pytest.raises(ApiError) as backwards:
        parse_interval(end, start)
    assert backwards.value.code == "VALIDATION_ERROR"


def test_pb49_interval_rejects_an_unbounded_span() -> None:
    with pytest.raises(ApiError) as failure:
        parse_interval(datetime(2000, 1, 1), datetime(2026, 11, 1))

    assert failure.value.code == "VALIDATION_ERROR"


def test_pb49_interval_converts_an_offset_to_utc() -> None:
    start = datetime(2026, 11, 1, 0, 0, tzinfo=timezone(timedelta(hours=7)))

    naive, _ = parse_interval(start, datetime(2026, 11, 2))

    assert naive == datetime(2026, 10, 31, 17, 0)


def test_pb49_a_day_bucket_starts_at_local_midnight() -> None:
    """16:59:59Z is still the previous local day in UTC+7; 17:00:00Z starts a new one."""
    before = bucket_starts(datetime(2026, 11, 16, 16, 59, 59),
                           datetime(2026, 11, 17, 0, 0), "day", OFFSET)
    after = bucket_starts(datetime(2026, 11, 16, 17, 0, 0),
                          datetime(2026, 11, 17, 0, 0), "day", OFFSET)

    assert before[0][0] == datetime(2026, 11, 15, 17, 0)
    assert after[0][0] == datetime(2026, 11, 16, 17, 0)
    assert before[0][0] != after[0][0]


def test_pb49_week_buckets_start_on_monday() -> None:
    # 2026-11-17 is a Tuesday; its local week starts on Monday 2026-11-16.
    windows = bucket_starts(datetime(2026, 11, 17, 3, 0), datetime(2026, 11, 24, 3, 0),
                            "week", OFFSET)

    assert windows[0][0] == datetime(2026, 11, 15, 17, 0)


def test_pb49_month_buckets_advance_calendar_months() -> None:
    windows = bucket_starts(datetime(2026, 11, 1), datetime(2027, 1, 1), "month", OFFSET)

    # Each month starts at local midnight, which is 17:00 UTC the day before.
    assert [start for start, _ in windows] == [
        datetime(2026, 10, 31, 17, 0),
        datetime(2026, 11, 30, 17, 0),
        datetime(2026, 12, 31, 17, 0),
    ]
    # The last bucket is clamped to the requested end, not left running.
    assert windows[-1][1] == datetime(2027, 1, 1)


def test_pb49_zero_fill_adds_the_buckets_with_no_sales() -> None:
    start, end = datetime(2026, 11, 16, 17, 0), datetime(2026, 11, 19, 17, 0)
    rows = [BucketRow(start=start + timedelta(days=1), revenue=Decimal("12.50"), transactions=2)]

    filled = zero_fill(start, end, "day", OFFSET, rows)

    assert [row.start for row in filled] == [
        start, start + timedelta(days=1), start + timedelta(days=2),
    ]
    assert [row.revenue for row in filled] == [Decimal("0.00"), Decimal("12.50"), Decimal("0.00")]
    assert [row.transactions for row in filled] == [0, 2, 0]


def test_pb49_the_last_bucket_is_clamped_to_the_interval() -> None:
    start, end = datetime(2026, 11, 16, 17, 0), datetime(2026, 11, 17, 12, 0)

    windows = bucket_starts(start, end, "day", OFFSET)

    assert windows == [(start, end)]


# --- the response contract ------------------------------------------------


def test_pb49_money_is_a_json_number_and_times_end_with_z() -> None:
    body = DashboardRevenue(
        scope=DashboardScope(store_id=None, is_system_wide=True),
        time_policy=DashboardTimePolicy(max_future_skew_seconds=300, max_backfill_days=30),
        data_from=datetime(2026, 11, 16, 17, 0),
        data_to=None,
        has_data=True,
        total_revenue=Decimal("1234.50"),
        transactions=3,
        quality=DashboardTimeQuality(on_time=3, backfill=0, suspect_future=0,
                                     suspect_old=0, unknown=0),
        buckets=[DashboardBucket(from_time=datetime(2026, 11, 16, 17, 0),
                                 to_time=datetime(2026, 11, 17, 17, 0),
                                 revenue=Decimal("1234.50"), transactions=3)],
    ).model_dump(by_alias=True, mode="json")

    assert body["total_revenue"] == 1234.5
    assert isinstance(body["total_revenue"], float)
    assert body["data_from"] == "2026-11-16T17:00:00Z"
    assert body["data_to"] is None
    assert body["buckets"][0]["revenue"] == 1234.5
    assert body["buckets"][0]["from"] == "2026-11-16T17:00:00Z"
    assert body["buckets"][0]["to"] == "2026-11-17T17:00:00Z"


def test_pb49_a_negative_total_stays_a_number() -> None:
    body = DashboardCategoryRevenue(
        scope=DashboardScope(store_id="TEST-1", is_system_wide=False),
        time_policy=DashboardTimePolicy(max_future_skew_seconds=300, max_backfill_days=30),
        total_revenue=Decimal("-10.00"),
        transactions=1,
        quality=DashboardTimeQuality(on_time=0, backfill=0, suspect_future=0,
                                     suspect_old=0, unknown=0),
        categories=[],
    ).model_dump(mode="json")

    assert body["total_revenue"] == -10.0
    assert isinstance(body["total_revenue"], float)


# --- the database ---------------------------------------------------------


class World:
    """One test store with a terminal, products and named accounts."""

    def __init__(self, store_id: str, pos_id: str, skus: list[str],
                 tokens: dict[str, str]) -> None:
        self.store_id = store_id
        self.pos_id = pos_id
        self.skus = skus
        self.tokens = tokens


def _unique(prefix: str, length: int = 5) -> str:
    from uuid import uuid4

    return f"{prefix}{uuid4().hex[:length].upper()}"


def seed_world(session: Session, *, categories: tuple[str, ...] = ("Dairy",)) -> World:
    """A store, a terminal, one product per category and the three roles."""
    from tests.pos_test_support import add_stock

    store_id, pos_id = _unique("TD"), _unique("TEST-POS-")
    skus = [_unique("TEST-SKU-", 6) for _ in categories]
    session.add(Store(store_id=store_id, name="Dashboard store", latitude=Decimal("16.0"),
                      longitude=Decimal("108.0"), region_id="TEST"))
    session.flush()
    for sku, category in zip(skus, categories):
        session.add(Product(sku=sku, barcode=sku, name=f"Product {sku}",
                            category=category, unit_price=Decimal("10.00")))
    session.flush()
    session.add(PosTerminal(pos_id=pos_id, store_id=store_id, status="ACTIVE"))
    tokens = {}
    for role, db_role in (("Admin", "ADMIN"), ("Auditor", "AUDITOR"), ("Manager", "STORE_MANAGER")):
        username = _unique("TEST-U-")
        session.add(StaffUser(username=username, full_name="Dashboard user", role=db_role,
                              store_id=None if role != "Manager" else store_id))
        tokens[role] = create_token(username, role,
                                    store_id=None if role != "Manager" else store_id)
    for sku in skus:
        add_stock(session, store_id, sku, 1000)
    session.flush()
    return World(store_id, pos_id, skus, tokens)


def add_transaction(session: Session, world: World, *, key: str, occurred_at: datetime | None,
                    created_at: datetime, sku: str, quantity: int = 1,
                    txn_type: str = "SALE", unit_price: Decimal = Decimal("10.00"),
                    ref_txn_id: str | None = None, status: str = "OK") -> str:
    txn_id = f"TEST-{key}"
    session.add(PosTransaction(
        txn_id=txn_id, store_id=world.store_id, pos_id=world.pos_id, txn_type=txn_type,
        ref_txn_id=ref_txn_id, status=status, payload_hash="0" * 64,
        occurred_at=occurred_at, created_at=created_at,
    ))
    session.add(TransactionItem(txn_id=txn_id, sku=sku, qty=quantity, unit_price=unit_price))
    session.flush()
    return txn_id


def headers(world: World, role: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {world.tokens[role]}"}


def params(start: datetime, end: datetime, **extra) -> dict:
    values = {"from": start.isoformat(), "to": end.isoformat()}
    values.update(extra)
    return values


@pytest.fixture
def world(db_session: Session) -> World:
    return seed_world(db_session, categories=("Dairy", "Bakery"))


# [from, to)


def test_pb49_from_is_included_and_to_is_excluded(client, db_session, world) -> None:
    day = datetime(2026, 11, 10, 0, 0)
    inside = add_transaction(db_session, world, key="D-INSIDE", occurred_at=day,
                             created_at=day, sku=world.skus[0], quantity=2)
    add_transaction(db_session, world, key="D-AT-FROM", occurred_at=day + timedelta(days=1),
                    created_at=day + timedelta(days=1), sku=world.skus[0], quantity=3)
    add_transaction(db_session, world, key="D-AT-TO", occurred_at=day + timedelta(days=2),
                    created_at=day + timedelta(days=2), sku=world.skus[0], quantity=4)

    response = client.get(URL_REVENUE, params=params(day + timedelta(days=1),
                                                     day + timedelta(days=2),
                                                     store_id=world.store_id),
                          headers=headers(world, "Admin"))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total_revenue"] == 30.0   # 3 x 10.00, only the row at `from`
    assert body["transactions"] == 1
    assert body["has_data"] is True
    assert inside != ""


def test_pb49_a_cancellation_nets_the_sale_to_zero(client, db_session, world) -> None:
    day = datetime(2026, 11, 10, 3, 0)
    sale = add_transaction(db_session, world, key="D-SALE", occurred_at=day, created_at=day,
                           sku=world.skus[0], quantity=4)
    # The CANCELLATION copies the sale's items, as pos_cancellation does.
    add_transaction(db_session, world, key="D-CANCEL", occurred_at=day, created_at=day,
                    sku=world.skus[0], quantity=4, txn_type="CANCELLATION", ref_txn_id=sale)
    db_session.flush()
    db_session.execute(
        PosTransaction.__table__.update()
        .where(PosTransaction.txn_id == sale)
        .values(status="CANCELLED"))

    response = client.get(URL_REVENUE, params=params(day - timedelta(hours=1),
                                                     day + timedelta(hours=1),
                                                     store_id=world.store_id),
                          headers=headers(world, "Admin"))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total_revenue"] == 0.0
    assert body["transactions"] == 2


def test_pb49_a_return_reduces_the_revenue(client, db_session, world) -> None:
    day = datetime(2026, 11, 10, 3, 0)
    sale = add_transaction(db_session, world, key="D-S2", occurred_at=day, created_at=day,
                           sku=world.skus[0], quantity=5)
    add_transaction(db_session, world, key="D-R2", occurred_at=day, created_at=day,
                    sku=world.skus[0], quantity=2, txn_type="RETURN", ref_txn_id=sale)

    body = client.get(URL_REVENUE, params=params(day - timedelta(hours=1),
                                                 day + timedelta(hours=1),
                                                 store_id=world.store_id),
                      headers=headers(world, "Admin")).json()

    assert body["total_revenue"] == 30.0   # 5 x 10 - 2 x 10


def test_pb49_include_suspect_false_leaves_the_money_but_keeps_the_quality(
        client, db_session, world) -> None:
    day = datetime(2026, 11, 10, 3, 0)
    add_transaction(db_session, world, key="D-OK", occurred_at=day, created_at=day,
                    sku=world.skus[0], quantity=1)
    # A terminal clock one day ahead: SUSPECT_FUTURE.
    add_transaction(db_session, world, key="D-FUTURE", occurred_at=day + timedelta(days=1),
                    created_at=day, sku=world.skus[0], quantity=1)
    # Sent 40 days late: SUSPECT_OLD, while its declared moment is still inside
    # the window, so only the quality filter can remove it.
    add_transaction(db_session, world, key="D-OLD", occurred_at=day,
                    created_at=day + timedelta(days=40), sku=world.skus[0], quantity=1)

    window = params(datetime(2026, 11, 9), datetime(2026, 11, 12),
                    store_id=world.store_id)
    everything = client.get(URL_REVENUE, params=window, headers=headers(world, "Admin")).json()
    clean = client.get(URL_REVENUE, params={**window, "include_suspect": "false"},
                       headers=headers(world, "Admin")).json()

    assert everything["total_revenue"] == 30.0
    assert everything["quality"]["suspect_future"] == 1
    assert everything["quality"]["suspect_old"] == 1
    # The money drops the two suspects, the quality still counts them.
    assert clean["total_revenue"] == 10.0
    assert clean["transactions"] == 1
    assert clean["quality"] == everything["quality"]


def test_pb49_quality_counts_a_row_without_occurred_at_as_unknown(
        client, db_session, world) -> None:
    day = datetime(2026, 11, 10, 3, 0)
    add_transaction(db_session, world, key="D-NULL", occurred_at=None, created_at=day,
                    sku=world.skus[0], quantity=1)

    body = client.get(URL_REVENUE, params=params(day - timedelta(hours=1),
                                                 day + timedelta(hours=1),
                                                 store_id=world.store_id),
                      headers=headers(world, "Admin")).json()

    assert body["total_revenue"] == 10.0
    assert body["quality"]["unknown"] == 1
    assert body["quality"]["on_time"] == 0


def test_pb49_empty_buckets_are_zero_filled(client, db_session, world) -> None:
    day = datetime(2026, 11, 10, 12, 0)
    add_transaction(db_session, world, key="D-ONE", occurred_at=day, created_at=day,
                    sku=world.skus[0], quantity=1)
    start, end = datetime(2026, 11, 10, 0, 0), datetime(2026, 11, 13, 0, 0)

    body = client.get(URL_REVENUE, params=params(start, end, bucket="day",
                                                 store_id=world.store_id),
                      headers=headers(world, "Admin")).json()

    assert len(body["buckets"]) >= 3
    assert sum(1 for bucket in body["buckets"] if bucket["transactions"] == 0) >= 2
    assert sum(bucket["revenue"] for bucket in body["buckets"]) == body["total_revenue"]


def test_pb49_the_categories_share_the_total(client, db_session, world) -> None:
    day = datetime(2026, 11, 10, 12, 0)
    add_transaction(db_session, world, key="D-CAT1", occurred_at=day, created_at=day,
                    sku=world.skus[0], quantity=3)
    add_transaction(db_session, world, key="D-CAT2", occurred_at=day, created_at=day,
                    sku=world.skus[1], quantity=1)

    body = client.get(URL_CATEGORY, params=params(day - timedelta(hours=1),
                                                  day + timedelta(hours=1),
                                                  store_id=world.store_id),
                      headers=headers(world, "Admin")).json()

    assert body["total_revenue"] == 40.0
    assert {category["category"]: category["revenue"] for category in body["categories"]} == {
        "Bakery": 10.0, "Dairy": 30.0,
    }
    assert round(sum(category["share"] for category in body["categories"]), 6) == 1


def test_pb49_the_system_total_equals_the_sum_of_the_stores(client, db_session, world) -> None:
    day = datetime(2026, 11, 10, 12, 0)
    add_transaction(db_session, world, key="D-SUM1", occurred_at=day, created_at=day,
                    sku=world.skus[0], quantity=3)

    window = params(day - timedelta(hours=1), day + timedelta(hours=1))
    system = client.get(URL_REVENUE, params=window, headers=headers(world, "Admin")).json()
    compared = client.get(URL_BY_STORE, params=window, headers=headers(world, "Admin")).json()

    assert compared["total_revenue"] == system["total_revenue"]
    assert sum(store["revenue"] for store in compared["stores"]) == system["total_revenue"]


def test_pb49_a_store_with_no_revenue_keeps_its_column(client, db_session, world) -> None:
    day = datetime(2026, 11, 10, 12, 0)
    add_transaction(db_session, world, key="D-COL", occurred_at=day, created_at=day,
                    sku=world.skus[0], quantity=1)

    body = client.get(URL_BY_STORE, params=params(day - timedelta(hours=1),
                                                  day + timedelta(hours=1)),
                      headers=headers(world, "Admin")).json()

    ids = {store["store_id"] for store in body["stores"]}
    assert world.store_id in ids
    assert len([store for store in body["stores"] if store["store_id"] == world.store_id]) == 1


# --- scopes and roles -----------------------------------------------------


def test_pb49_a_second_store_appears_for_admin_and_not_for_manager(
        client, db_session, world) -> None:
    other = seed_world(db_session)
    db_session.flush()

    admin = client.get(URL_STORES, headers=headers(world, "Admin")).json()
    manager = client.get(URL_STORES, headers=headers(world, "Manager")).json()

    admin_ids = {store["store_id"] for store in admin["stores"]}
    assert {world.store_id, other.store_id} <= admin_ids
    assert [store["store_id"] for store in manager["stores"]] == [world.store_id]


def test_pb49_a_manager_reading_another_store_gets_403(client, db_session, world) -> None:
    other = seed_world(db_session)
    db_session.flush()

    response = client.get(URL_REVENUE,
                          params=params(datetime(2026, 11, 1), datetime(2026, 11, 2),
                                        store_id=other.store_id),
                          headers=headers(world, "Manager"))

    assert response.status_code == 403, response.text
    assert response.json()["code"] == "FORBIDDEN"


def test_pb49_an_unknown_store_for_admin_gets_422(client, world) -> None:
    # An id the column accepts (varchar(10)) and the route's pattern accepts, but
    # no store carries, so the answer comes from the store lookup and not from a
    # length/pattern violation.
    response = client.get(URL_REVENUE,
                          params=params(datetime(2026, 11, 1), datetime(2026, 11, 2),
                                        store_id="TEST-NOSE"),
                          headers=headers(world, "Admin"))

    assert response.status_code == 422, response.text
    assert response.json()["code"] == "INVALID_STORE"


def test_pb49_a_manager_comparing_another_store_gets_403(client, db_session, world) -> None:
    other = seed_world(db_session)
    db_session.flush()

    response = client.get(URL_BY_STORE,
                          params=params(datetime(2026, 11, 1), datetime(2026, 11, 2),
                                        **{"compare_store_ids": [other.store_id]}),
                          headers=headers(world, "Manager"))

    assert response.status_code == 403, response.text
    assert response.json()["code"] == "FORBIDDEN"


def test_pb49_an_unknown_compare_store_gets_422(client, world) -> None:
    """A well-formed id for a store that does not exist answers INVALID_STORE.

    The id must fit the column (varchar(10)) and the shared pattern; an over-long one
    is rejected earlier as VALIDATION_ERROR, which is covered separately.
    """
    response = client.get(URL_BY_STORE,
                          params=params(datetime(2026, 11, 1), datetime(2026, 11, 2),
                                        **{"compare_store_ids": ["TEST-NOSU"]}),
                          headers=headers(world, "Admin"))

    assert response.status_code == 422, response.text
    assert response.json()["code"] == "INVALID_STORE"


def test_pb49_the_comparison_syntax_repeats_the_parameter(client, db_session, world) -> None:
    other = seed_world(db_session)
    db_session.flush()

    response = client.get(
        URL_BY_STORE,
        params=[("from", "2026-11-01T00:00:00"), ("to", "2026-11-02T00:00:00"),
                ("compare_store_ids", world.store_id),
                ("compare_store_ids", other.store_id)],
        headers=headers(world, "Admin"),
    )

    assert response.status_code == 200, response.text
    assert {store["store_id"] for store in response.json()["stores"]} == {
        world.store_id, other.store_id,
    }


def test_pb49_a_closed_store_is_listed_with_its_flag(client, db_session, world) -> None:
    closed = seed_world(db_session)
    db_session.execute(
        Store.__table__.update().where(Store.store_id == closed.store_id).values(is_active=False))
    db_session.flush()

    body = client.get(URL_STORES, headers=headers(world, "Admin")).json()

    entry = next(store for store in body["stores"] if store["store_id"] == closed.store_id)
    assert entry["is_active"] is False


def test_pb49_an_invalid_bucket_gets_422(client, world) -> None:
    response = client.get(URL_REVENUE,
                          params=params(datetime(2026, 11, 1), datetime(2026, 11, 2),
                                        bucket="fortnight"),
                          headers=headers(world, "Admin"))

    assert response.status_code == 422, response.text
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_pb49_a_missing_interval_gets_422(client, world) -> None:
    response = client.get(URL_REVENUE, params={"from": "2026-11-01T00:00:00"},
                          headers=headers(world, "Admin"))

    assert response.status_code == 422, response.text
    assert response.json()["code"] == "VALIDATION_ERROR"


# --- the service's own scope rules ---------------------------------------


def test_pb49_scope_filters_the_row_set_for_a_manager(db_session, world) -> None:
    other = seed_world(db_session)
    query = service.build_query(
        db_session, _principal(db_session, world, "Manager"),
        store_id=None, compare_store_ids=None,
        start=datetime(2026, 11, 1), end=datetime(2026, 11, 2),
    )

    assert query.store_id == world.store_id
    assert query.compare_store_ids == (world.store_id,)

    with pytest.raises(Exception) as failure:
        service.resolve_scope(db_session, _principal(db_session, world, "Manager"),
                              other.store_id)
    assert failure.value.status == 403


def _principal(session: Session, world: World, role: str):
    """The Principal the security layer would build for that role."""
    from app.core.security import Principal

    username = session.scalar(
        select(StaffUser.username).where(StaffUser.store_id == world.store_id))
    store_id = world.store_id if role == "Manager" else None
    return Principal(sub=username, role=role, store_id=store_id, pos_id=None)


# --- the datetime limits (Dashboard_Review 2) ------------------------------


@pytest.mark.parametrize("start,end", [
    (datetime.min.replace(tzinfo=timezone(timedelta(hours=7))),
     datetime(2026, 11, 2, tzinfo=timezone.utc)),
    (datetime(2026, 11, 1, tzinfo=timezone.utc),
     datetime.max.replace(microsecond=0, tzinfo=timezone(timedelta(hours=-7)))),
])
def test_pb49_a_bound_at_the_datetime_limit_is_a_bad_request(start, end) -> None:
    """A bound whose UTC conversion overflows is the caller's mistake, so 422, not 503."""
    with pytest.raises(ApiError) as failure:
        parse_interval(start, end)

    assert failure.value.status == 422


# --- include_suspect and rows without occurred_at (Dashboard_Review 2) -----


def test_pb49_include_suspect_false_keeps_a_row_without_occurred_at(client, db_session, world) -> None:
    """A pre-migration row has real revenue; the filter must not drop it.

    Both suspect comparisons are NULL for such a row, and ``NOT NULL`` is still NULL,
    so a bare ``NOT (...)`` predicate would hide its money while the badge still
    counted it. The row belongs to no suspect group, so it is kept.
    """
    day = datetime(2026, 11, 10, 3, 0)
    add_transaction(db_session, world, key="PB49-NULL", occurred_at=None,
                    created_at=day, sku=world.skus[0], quantity=2)

    response = client.get(URL_REVENUE, params=params(day, day + timedelta(days=1),
                                                    store_id=world.store_id,
                                                    include_suspect="false"),
                          headers=headers(world, "Admin"))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total_revenue"] == 20.0
    assert body["quality"]["unknown"] == 1
    assert body["transactions"] == 1


# --- categories count a basket once (Dashboard_Review 4) -------------------


def test_pb49_a_basket_with_two_categories_counts_one_transaction(client, db_session, world) -> None:
    """One sale across two categories must not double-count the transaction."""
    day = datetime(2026, 11, 10, 3, 0)
    txn = f"TEST-PB49-MULTI"
    db_session.add(PosTransaction(
        txn_id=txn, store_id=world.store_id, pos_id=world.pos_id, txn_type="SALE",
        ref_txn_id=None, status="OK", payload_hash="0" * 64,
        occurred_at=day, created_at=day,
    ))
    db_session.add(TransactionItem(txn_id=txn, sku=world.skus[0], qty=1,
                                   unit_price=Decimal("10.00")))
    db_session.add(TransactionItem(txn_id=txn, sku=world.skus[1], qty=1,
                                   unit_price=Decimal("10.00")))
    db_session.flush()

    response = client.get(URL_CATEGORY, params=params(day, day + timedelta(days=1),
                                                      store_id=world.store_id),
                          headers=headers(world, "Admin"))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["transactions"] == 1
    assert len(body["categories"]) == 2
    assert body["total_revenue"] == 20.0


# --- the comparison set (Dashboard_Review 3) -------------------------------


def test_pb49_duplicate_compare_ids_give_one_column_each(client, world) -> None:
    response = client.get(URL_BY_STORE, params=params(
        datetime(2026, 11, 1), datetime(2026, 11, 2),
        **{"compare_store_ids": [world.store_id, world.store_id]}),
        headers=headers(world, "Admin"))

    assert response.status_code == 200, response.text
    ids = [store["store_id"] for store in response.json()["stores"]]
    assert ids == [world.store_id]


def test_pb49_an_over_long_compare_id_is_rejected_not_truncated(client, world) -> None:
    """A 16-char id must answer 422, not silently query a truncated 10-char store."""
    response = client.get(URL_BY_STORE, params=params(
        datetime(2026, 11, 1), datetime(2026, 11, 2),
        **{"compare_store_ids": ["TEST-NOT-A-STORE"]}),
        headers=headers(world, "Admin"))

    assert response.status_code == 422, response.text
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_pb49_a_manager_probing_an_unknown_store_gets_403_not_422(client, db_session, world) -> None:
    """Existence must not leak: outside and unknown answer the same for a Manager.

    The two requests run in separate tests below, because a 403 makes ``get_db``
    roll the fixture's transaction back, so a second request in the same test would
    no longer find the accounts it needs.
    """
    unknown = client.get(URL_BY_STORE, params=params(
        datetime(2026, 11, 1), datetime(2026, 11, 2),
        **{"compare_store_ids": ["TEST-NOSU"]}),
        headers=headers(world, "Manager"))

    # 403, not 422: the store does not exist, but a Manager is not told that.
    assert unknown.status_code == 403, unknown.text
    assert unknown.json()["code"] == "FORBIDDEN"


# --- the hourly span (Dashboard_Review 7) ----------------------------------


def test_pb49_an_hour_bucket_over_too_long_a_span_is_a_bad_request(client, world) -> None:
    response = client.get(URL_REVENUE, params=params(
        datetime(2026, 1, 1), datetime(2026, 12, 1), bucket="hour"),
        headers=headers(world, "Admin"))

    assert response.status_code == 422, response.text
    assert response.json()["code"] == "VALIDATION_ERROR"


# --- the bucket axis at the datetime limits (Dashboard_Review 2) -----------


@pytest.mark.parametrize("bucket", ["hour", "day", "week", "month"])
def test_pb49_the_bucket_axis_survives_year_1_and_year_9999(bucket) -> None:
    """The axis must not raise: SQL anchors on datetime2, Python clamps the shift.

    A bare `0` anchor is a `datetime` in SQL Server, whose range starts in 1753, so a
    year-1 instant used to raise "datetime2 to datetime out of range" and answer 503.
    """
    windows = bucket_starts(datetime(1, 1, 1), datetime(1, 1, 3), bucket, 7)

    assert windows
    assert windows[0][0] == datetime(1, 1, 1)


@pytest.mark.parametrize("bucket", ["day", "week", "month"])
def test_pb49_the_bucket_axis_ends_at_the_ceiling(bucket) -> None:
    """A span reaching year 9999 ends the axis instead of raising."""
    windows = bucket_starts(datetime(9999, 12, 1), datetime.max.replace(microsecond=0),
                            bucket, 7)

    assert windows
    assert windows[-1][1] == datetime.max.replace(microsecond=0)


def test_pb49_an_hourly_window_back_to_year_1_is_answered(client, world) -> None:
    """The endpoint itself answers 200 over that window, not 503."""
    response = client.get(URL_REVENUE, params={
        "from": "0001-01-01T00:00:00Z", "to": "0001-01-03T00:00:00Z",
        "bucket": "day", "store_id": world.store_id,
    }, headers=headers(world, "Admin"))

    assert response.status_code == 200, response.text
    assert response.json()["buckets"]


# --- a stored instant at the ceiling (review round 2, point 1) -------------


def test_pb49_a_transaction_near_year_9999_is_answered_not_503(client, db_session, world) -> None:
    """A row stored at the top of the type must not break the whole request.

    `DATEADD(HOUR, +offset, moment)` in the bucket expression overflowed for an
    `occurred_at` at or beyond 9999-12-31T17:00Z, so every /dashboard/revenue call
    whose interval covered it answered 503. The POS clamp can also store
    9999-12-31T23:59:59, so a `to` with fractional seconds reached the same edge.
    """
    near_max = datetime(9999, 12, 31, 23, 0, 0)
    add_transaction(db_session, world, key="PB49-CEILING", occurred_at=near_max,
                    created_at=near_max, sku=world.skus[0], quantity=1)

    response = client.get(URL_REVENUE, params={
        "from": "9999-12-01T00:00:00Z",
        "to": "9999-12-31T23:59:59.999999Z",
        "bucket": "day",
        "store_id": world.store_id,
    }, headers=headers(world, "Admin"))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["transactions"] == 1
    assert body["total_revenue"] == 10.0


@pytest.mark.parametrize("bucket", ["hour", "day", "week", "month"])
def test_pb49_the_api_answers_at_the_ceiling_for_every_bucket(client, db_session, world, bucket) -> None:
    near_max = datetime(9999, 12, 31, 22, 30, 0)
    add_transaction(db_session, world, key=f"PB49-CEIL-{bucket}", occurred_at=near_max,
                    created_at=near_max, sku=world.skus[0], quantity=1)

    response = client.get(URL_REVENUE, params={
        "from": "9999-12-31T00:00:00Z",
        "to": "9999-12-31T23:59:59Z",
        "bucket": bucket,
        "store_id": world.store_id,
    }, headers=headers(world, "Admin"))

    assert response.status_code == 200, response.text
