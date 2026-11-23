"""Dashboard revenue endpoints (PB-49, plan B5). Read-only: they never commit.

Four routes, each guarded by ``require_role("Admin", "Auditor", "Manager")``.
The two view-scope routes accept ``store_id``; the comparison route accepts
``compare_store_ids``; the store list accepts neither, because it is limited by
the caller's role alone and must not become a way to probe whether a store
exists.

The parameters are passed to the service, which validates the interval, resolves
both scopes against the caller's authority and runs the queries. The route only
maps the service's result to the response model.
"""

from datetime import datetime
import re

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.schemas.dashboard import (
    DashboardBucket,
    DashboardCategory,
    DashboardCategoryRevenue,
    DashboardRevenue,
    DashboardScope,
    DashboardStore,
    DashboardStoreList,
    DashboardStoreRevenue,
    DashboardStoreRevenueResponse,
    DashboardTimePolicy,
    DashboardTimeQuality,
)
from app.api.schemas.registry import ID_PATTERN
from app.core.db import get_db
from app.core.errors import ApiError
from app.core.security import Principal, require_role
from app.services import dashboard as service


router = APIRouter(prefix="/dashboard", tags=["Dashboard"])

# Every Dashboard route allows the same three roles and nothing else.
DASHBOARD_ROLES = ("Admin", "Auditor", "Manager")

# A comparison set is a handful of stores; the cap keeps one request from asking the
# repository for an unbounded list, which would also overflow its nvarchar concat.
MAX_COMPARE_STORES = 100


def _validated_compare(ids: list[str] | None) -> list[str] | None:
    """Each id must be one the store column could hold and the shared pattern allows.

    FastAPI validates the list length but not the shape of its items, so a 16-character
    id would pass here and then be silently truncated by the repository's
    ``CAST(value AS varchar(10))``, answering about a different store. Rejecting it is
    both safer and more honest than truncating.

    Raises:
        ApiError(422, "VALIDATION_ERROR"): an item is empty, too long, or off-pattern.
    """
    if not ids:
        return ids
    for value in ids:
        if not 1 <= len(value) <= 10 or not re.fullmatch(ID_PATTERN, value):
            raise ApiError(
                422, "VALIDATION_ERROR",
                f"Invalid field 'compare_store_ids': '{value}' must be 1-10 characters "
                f"matching {ID_PATTERN}.")
    return ids


def _scope_response(query: service.DashboardQuery) -> DashboardScope:
    return DashboardScope(store_id=query.store_id, is_system_wide=query.store_id is None)


def _policy(query: service.DashboardQuery) -> DashboardTimePolicy:
    return DashboardTimePolicy(
        max_future_skew_seconds=query.skew_seconds,
        max_backfill_days=query.backfill_days,
    )


def _quality(result) -> DashboardTimeQuality:
    return DashboardTimeQuality(**result.quality.as_dict())


@router.get("/stores", response_model=DashboardStoreList)
def list_dashboard_stores(
    session: Session = Depends(get_db),
    principal: Principal = Depends(require_role(*DASHBOARD_ROLES)),
) -> DashboardStoreList:
    """The stores of the caller's scope, closed ones included.

    The role alone decides the answer; there is no ``store_id`` parameter, so this
    route cannot be used to ask about someone else's store.
    """
    return DashboardStoreList(stores=[
        DashboardStore(store_id=store_id, name=name, region_id=region_id,
                       is_active=is_active)
        for store_id, name, region_id, is_active in service.stores_for(session, principal)
    ])


@router.get("/revenue", response_model=DashboardRevenue)
def get_dashboard_revenue(
    from_time: datetime = Query(alias="from"),
    to: datetime = Query(),
    store_id: str | None = Query(default=None, min_length=1, max_length=10, pattern=ID_PATTERN),
    bucket: str = Query(default="day"),
    include_suspect: bool = Query(default=True),
    session: Session = Depends(get_db),
    principal: Principal = Depends(require_role(*DASHBOARD_ROLES)),
) -> DashboardRevenue:
    """Net revenue per bucket of the half-open interval ``[from, to)``."""
    query = service.build_query(
        session, principal, store_id=store_id, compare_store_ids=None,
        start=from_time, end=to, bucket=bucket, include_suspect=include_suspect,
    )
    result = service.revenue_series(session, query)
    return DashboardRevenue(
        scope=_scope_response(query),
        time_policy=_policy(query),
        data_from=result.data_from,
        data_to=result.data_to,
        has_data=result.has_data,
        total_revenue=result.total_revenue,
        transactions=result.transactions,
        quality=_quality(result),
        buckets=[
            DashboardBucket(from_time=point.start, to_time=point.end,
                            revenue=point.revenue, transactions=point.transactions)
            for point in result.points
        ],
    )


@router.get("/revenue-by-category", response_model=DashboardCategoryRevenue)
def get_dashboard_revenue_by_category(
    from_time: datetime = Query(alias="from"),
    to: datetime = Query(),
    store_id: str | None = Query(default=None, min_length=1, max_length=10, pattern=ID_PATTERN),
    include_suspect: bool = Query(default=True),
    session: Session = Depends(get_db),
    principal: Principal = Depends(require_role(*DASHBOARD_ROLES)),
) -> DashboardCategoryRevenue:
    """Net revenue per product category of the half-open interval ``[from, to)``."""
    query = service.build_query(
        session, principal, store_id=store_id, compare_store_ids=None,
        start=from_time, end=to, include_suspect=include_suspect,
    )
    result = service.category_breakdown(session, query)
    return DashboardCategoryRevenue(
        scope=_scope_response(query),
        time_policy=_policy(query),
        total_revenue=result.total_revenue,
        transactions=result.transactions,
        quality=_quality(result),
        categories=[
            DashboardCategory(category=category.category, revenue=category.revenue,
                              share=category.share)
            for category in result.categories
        ],
    )


@router.get("/revenue-by-store", response_model=DashboardStoreRevenueResponse)
def get_dashboard_revenue_by_store(
    from_time: datetime = Query(alias="from"),
    to: datetime = Query(),
    compare_store_ids: list[str] | None = Query(
        default=None,
        # The list length is capped, so one request cannot ask the repository for an
        # unbounded set; each id is validated below against the same rules as
        # store_id, because a longer value would be silently truncated by the CAST
        # inside the repository rather than rejected.
        max_length=MAX_COMPARE_STORES,
        description=f"At most {MAX_COMPARE_STORES} store ids; the key repeats.",
    ),
    include_suspect: bool = Query(default=True),
    session: Session = Depends(get_db),
    principal: Principal = Depends(require_role(*DASHBOARD_ROLES)),
) -> DashboardStoreRevenueResponse:
    """Net revenue per store of the comparison set, sorted by revenue descending."""
    query = service.build_query(
        session, principal, store_id=None,
        compare_store_ids=_validated_compare(compare_store_ids),
        start=from_time, end=to, include_suspect=include_suspect,
    )
    result = service.store_comparison(session, query)
    return DashboardStoreRevenueResponse(
        scope=_scope_response(query),
        time_policy=_policy(query),
        data_from=result.data_from,
        data_to=result.data_to,
        has_data=result.has_data,
        total_revenue=result.total_revenue,
        transactions=result.transactions,
        quality=_quality(result),
        stores=[
            DashboardStoreRevenue(store_id=column.store_id, name=column.name,
                                  region_id=column.region_id, revenue=column.revenue,
                                  share=column.share)
            for column in result.stores
        ],
    )
