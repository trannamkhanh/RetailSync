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
from app.core.security import Principal, require_role
from app.services import dashboard as service


router = APIRouter(prefix="/dashboard", tags=["Dashboard"])

# Every Dashboard route allows the same three roles and nothing else.
DASHBOARD_ROLES = ("Admin", "Auditor", "Manager")


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
    compare_store_ids: list[str] | None = Query(default=None),
    include_suspect: bool = Query(default=True),
    session: Session = Depends(get_db),
    principal: Principal = Depends(require_role(*DASHBOARD_ROLES)),
) -> DashboardStoreRevenueResponse:
    """Net revenue per store of the comparison set, sorted by revenue descending."""
    query = service.build_query(
        session, principal, store_id=None, compare_store_ids=compare_store_ids,
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