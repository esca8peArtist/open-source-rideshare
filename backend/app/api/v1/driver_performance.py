"""Driver Performance Scoring API.

Driver endpoints (authenticated driver):
  GET /drivers/me/performance           — current scorecard
  GET /drivers/me/performance/history   — last 12 weekly snapshots

Admin endpoints:
  GET  /admin/drivers/performance                        — paginated list with filters
  GET  /admin/drivers/{driver_id}/performance            — full snapshot for one driver
  GET  /admin/drivers/{driver_id}/performance/history    — snapshot history
  GET  /admin/drivers/{driver_id}/performance/alerts     — active alerts
  POST /admin/performance/recalculate                    — bulk recalculate all drivers
"""

from __future__ import annotations

import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_admin, require_driver
from app.db.database import get_db
from app.models.driver_performance import DriverPerformanceAlert, DriverPerformanceSnapshot
from app.models.user import User
from app.schemas.driver_performance import (
    AdminPerformanceListItem,
    AdminPerformanceListResponse,
    AdminRecalculateResponse,
    DriverPerformanceAlertResponse,
    DriverPerformanceSnapshotResponse,
    DriverScorecardResponse,
)
from app.services.driver_performance import (
    bulk_recalculate_all_drivers,
    get_current_snapshot,
    get_snapshot_history,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["driver-performance"])

# ---------------------------------------------------------------------------
# Driver self-view endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/drivers/me/performance",
    response_model=DriverScorecardResponse,
    summary="Get current driver scorecard",
)
async def get_my_performance(
    user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    """Return the authenticated driver's most recent performance scorecard.

    Returns 404 if no snapshot has been calculated for this driver yet.
    """
    snapshot = await get_current_snapshot(db, driver_id=user.id)
    if snapshot is None:
        raise HTTPException(
            status_code=404,
            detail="No performance snapshot found. Snapshots are calculated weekly.",
        )
    return snapshot


@router.get(
    "/drivers/me/performance/history",
    response_model=list[DriverScorecardResponse],
    summary="Get driver scorecard history",
)
async def get_my_performance_history(
    limit: int = Query(12, ge=1, le=52, description="Number of snapshots to return"),
    user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    """Return up to the last 52 weekly performance snapshots for the authenticated driver."""
    snapshots = await get_snapshot_history(db, driver_id=user.id, limit=limit)
    return snapshots


# ---------------------------------------------------------------------------
# Admin endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/admin/drivers/performance",
    response_model=AdminPerformanceListResponse,
    summary="List all driver performance snapshots (admin)",
)
async def admin_list_driver_performance(
    tier: str | None = Query(None, description="Filter by tier: bronze/silver/gold/platinum"),
    min_score: float | None = Query(None, ge=0, le=100, description="Minimum composite score"),
    max_score: float | None = Query(None, ge=0, le=100, description="Maximum composite score"),
    sort_by: str = Query(
        "score",
        description="Sort field: score | acceptance_rate | avg_rating | cancellation_rate",
    ),
    limit: int = Query(50, ge=1, le=200, description="Page size"),
    offset: int = Query(0, ge=0, description="Page offset"),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Paginated list of the most-recent performance snapshot per driver.

    Supports filtering by tier and score range, and sorting by score,
    acceptance_rate, avg_rating, or cancellation_rate.
    """
    # Sub-query: latest snapshot id per driver
    latest_subq = (
        select(
            DriverPerformanceSnapshot.driver_id,
            func.max(DriverPerformanceSnapshot.period_start).label("max_period"),
        )
        .group_by(DriverPerformanceSnapshot.driver_id)
        .subquery()
    )

    stmt = (
        select(DriverPerformanceSnapshot, User.name.label("driver_name"))
        .join(
            latest_subq,
            (DriverPerformanceSnapshot.driver_id == latest_subq.c.driver_id)
            & (DriverPerformanceSnapshot.period_start == latest_subq.c.max_period),
        )
        .join(User, User.id == DriverPerformanceSnapshot.driver_id)
    )

    if tier:
        stmt = stmt.where(DriverPerformanceSnapshot.score_tier == tier)
    if min_score is not None:
        stmt = stmt.where(DriverPerformanceSnapshot.performance_score >= min_score)
    if max_score is not None:
        stmt = stmt.where(DriverPerformanceSnapshot.performance_score <= max_score)

    # Sorting
    sort_map = {
        "score": DriverPerformanceSnapshot.performance_score.desc(),
        "acceptance_rate": DriverPerformanceSnapshot.acceptance_rate.desc(),
        "avg_rating": DriverPerformanceSnapshot.average_rider_rating.desc(),
        "cancellation_rate": DriverPerformanceSnapshot.cancellation_rate.asc(),
    }
    order_col = sort_map.get(sort_by, DriverPerformanceSnapshot.performance_score.desc())
    stmt = stmt.order_by(order_col)

    # Count
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total_result = await db.execute(count_stmt)
    total = total_result.scalar_one()

    # Page
    stmt = stmt.limit(limit).offset(offset)
    rows = await db.execute(stmt)

    items: list[AdminPerformanceListItem] = []
    for row in rows:
        snap: DriverPerformanceSnapshot = row[0]
        driver_name: str | None = row[1]
        items.append(
            AdminPerformanceListItem(
                driver_id=snap.driver_id,
                driver_name=driver_name,
                performance_score=snap.performance_score,
                score_tier=snap.score_tier,
                acceptance_rate=snap.acceptance_rate,
                cancellation_rate=snap.cancellation_rate,
                completion_rate=snap.completion_rate,
                average_rider_rating=snap.average_rider_rating,
                total_rides_completed=snap.total_rides_completed,
                period_start=snap.period_start,
                period_end=snap.period_end,
            )
        )

    return AdminPerformanceListResponse(total=total, limit=limit, offset=offset, items=items)


@router.get(
    "/admin/drivers/{driver_id}/performance",
    response_model=DriverPerformanceSnapshotResponse,
    summary="Get full performance snapshot for a specific driver (admin)",
)
async def admin_get_driver_performance(
    driver_id: int,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return the most recent full performance snapshot for the specified driver."""
    snapshot = await get_current_snapshot(db, driver_id=driver_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="No performance snapshot found for this driver")
    return snapshot


@router.get(
    "/admin/drivers/{driver_id}/performance/history",
    response_model=list[DriverPerformanceSnapshotResponse],
    summary="Get snapshot history for a specific driver (admin)",
)
async def admin_get_driver_performance_history(
    driver_id: int,
    limit: int = Query(12, ge=1, le=52),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return up to 52 performance snapshots for the specified driver, newest first."""
    snapshots = await get_snapshot_history(db, driver_id=driver_id, limit=limit)
    return snapshots


@router.get(
    "/admin/drivers/{driver_id}/performance/alerts",
    response_model=list[DriverPerformanceAlertResponse],
    summary="Get active performance alerts for a specific driver (admin)",
)
async def admin_get_driver_alerts(
    driver_id: int,
    include_resolved: bool = Query(False, description="Include resolved alerts"),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return performance alerts for the specified driver.

    By default only unresolved alerts are returned. Pass include_resolved=true
    to see the full history.
    """
    stmt = select(DriverPerformanceAlert).where(
        DriverPerformanceAlert.driver_id == driver_id
    )
    if not include_resolved:
        stmt = stmt.where(DriverPerformanceAlert.is_resolved == False)  # noqa: E712
    stmt = stmt.order_by(DriverPerformanceAlert.created_at.desc())

    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.post(
    "/admin/performance/recalculate",
    response_model=AdminRecalculateResponse,
    summary="Bulk recalculate performance snapshots for all active drivers (admin)",
)
async def admin_recalculate_all(
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Trigger an immediate recalculation of the current-period snapshot for every
    active driver. Normally this runs automatically on a weekly schedule.

    Returns the count of successful recalculations and any errors.
    """
    result = await bulk_recalculate_all_drivers(db)
    await db.commit()
    return AdminRecalculateResponse(**result)
