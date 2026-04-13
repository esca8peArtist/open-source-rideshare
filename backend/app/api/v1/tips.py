"""Tips API — rider-to-driver tip endpoints.

POST /rides/{ride_id}/tip          — rider submits a tip for a completed ride
GET  /rides/{ride_id}/tip          — rider or driver fetches tip for a ride
GET  /drivers/me/tips              — driver views their tip history (paginated)
GET  /drivers/me/tips/summary      — driver tip earnings summary by period
GET  /admin/tips                   — admin lists all tips with optional filters
GET  /admin/tips/stats             — admin platform-wide tip analytics
"""

import logging
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_admin
from app.db.database import get_db
from app.models.ride import Ride
from app.models.tip import TipRecord, TipStatus
from app.models.user import User, UserRole
from app.schemas.tip import AdminTipStatsResponse, TipRequest, TipResponse, TipStatusBreakdown, TipSummaryResponse
from app.services.analytics import get_admin_tip_stats, get_driver_tip_summary
from app.services.tips import TipError, submit_tip

logger = logging.getLogger(__name__)
router = APIRouter(tags=["tips"])


@router.post("/rides/{ride_id}/tip", response_model=TipResponse, status_code=201)
async def create_tip(
    ride_id: int,
    req: TipRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Submit a tip for a completed ride.

    Only the rider who took the ride may submit a tip, and only within
    48 hours of completion. Each ride allows at most one tip.
    """
    try:
        tip = await submit_tip(
            db,
            ride_id=ride_id,
            rider_user=user,
            amount_cents=req.amount_cents,
            message=req.thank_you_message,
        )
    except TipError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))

    return tip


@router.get("/rides/{ride_id}/tip", response_model=TipResponse)
async def get_ride_tip(
    ride_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Fetch the tip for a specific ride.

    Accessible by the rider or driver for that ride, and by admins.
    """
    # Load ride to authorise access
    ride_result = await db.execute(select(Ride).where(Ride.id == ride_id))
    ride = ride_result.scalar_one_or_none()

    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")

    is_admin = user.role == UserRole.ADMIN
    is_rider = ride.rider_id == user.id
    is_driver = ride.driver_id == user.id

    if not (is_admin or is_rider or is_driver):
        raise HTTPException(status_code=403, detail="Not authorised to view this tip")

    tip_result = await db.execute(
        select(TipRecord).where(TipRecord.ride_id == ride_id)
    )
    tip = tip_result.scalar_one_or_none()

    if not tip:
        raise HTTPException(status_code=404, detail="No tip found for this ride")

    return tip


@router.get("/drivers/me/tips", response_model=list[TipResponse])
async def list_my_tips(
    limit: int = Query(20, ge=1, le=100, description="Page size"),
    offset: int = Query(0, ge=0, description="Page offset"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List tips received by the authenticated driver, newest first.

    Requires driver role. Supports pagination via limit/offset.
    """
    if user.role != UserRole.DRIVER:
        raise HTTPException(status_code=403, detail="Driver access required")

    result = await db.execute(
        select(TipRecord)
        .where(TipRecord.driver_id == user.id)
        .order_by(TipRecord.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return result.scalars().all()


@router.get("/drivers/me/tips/summary", response_model=TipSummaryResponse)
async def get_my_tip_summary(
    period: Literal["week", "month", "year", "all"] = Query("month", description="Aggregation period"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return tip earnings summary for the authenticated driver.

    Requires driver role.

    Returns aggregated totals for the selected period:
    - total_cents / total_dollars: sum of all tip amounts
    - tip_count: number of tips received
    - avg_tip_cents / avg_tip_dollars: mean tip value
    - status_breakdown: counts by tip status (completed/pending/failed/refunded)
    """
    if user.role != UserRole.DRIVER:
        raise HTTPException(status_code=403, detail="Driver access required")

    summary = await get_driver_tip_summary(db, driver_id=user.id, period=period)
    return TipSummaryResponse(
        period=summary["period"],
        total_cents=summary["total_cents"],
        total_dollars=summary["total_dollars"],
        tip_count=summary["tip_count"],
        avg_tip_cents=summary["avg_tip_cents"],
        avg_tip_dollars=summary["avg_tip_dollars"],
        status_breakdown=TipStatusBreakdown(**summary["status_breakdown"]),
    )


@router.get("/admin/tips/stats", response_model=AdminTipStatsResponse)
async def admin_tip_stats(
    period: Literal["week", "month", "year", "all"] = Query("month", description="Aggregation period"),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Platform-wide tip analytics for the given period.

    Admin only.

    Returns:
    - total_cents / total_dollars: platform tip revenue
    - tip_count: number of tips in period
    - avg_tip_cents / avg_tip_dollars: platform mean tip
    - unique_drivers_tipped: how many distinct drivers received tips
    - unique_riders_who_tipped: how many distinct riders sent tips
    - top_tipped_drivers: up to 10 drivers ranked by total tip income
    """
    stats = await get_admin_tip_stats(db, period=period)
    from app.schemas.tip import TopTippedDriver
    return AdminTipStatsResponse(
        period=stats["period"],
        total_cents=stats["total_cents"],
        total_dollars=stats["total_dollars"],
        tip_count=stats["tip_count"],
        avg_tip_cents=stats["avg_tip_cents"],
        avg_tip_dollars=stats["avg_tip_dollars"],
        unique_drivers_tipped=stats["unique_drivers_tipped"],
        unique_riders_who_tipped=stats["unique_riders_who_tipped"],
        top_tipped_drivers=[TopTippedDriver(**d) for d in stats["top_tipped_drivers"]],
    )


@router.get("/admin/tips", response_model=list[TipResponse])
async def admin_list_tips(
    status_filter: TipStatus | None = Query(None, alias="status"),
    driver_id: int | None = Query(None, description="Filter by driver"),
    date_from: date | None = Query(None, description="Start date (inclusive)"),
    date_to: date | None = Query(None, description="End date (inclusive)"),
    limit: int = Query(50, ge=1, le=200, description="Page size"),
    offset: int = Query(0, ge=0, description="Page offset"),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Admin endpoint: list all tips with optional filters.

    Filters:
    - status: pending | completed | failed | refunded
    - driver_id: restrict to a specific driver
    - date_from / date_to: filter by created_at date (inclusive)
    """
    filters = []

    if status_filter is not None:
        filters.append(TipRecord.status == status_filter)
    if driver_id is not None:
        filters.append(TipRecord.driver_id == driver_id)
    if date_from is not None:
        from sqlalchemy import func as sqlfunc
        filters.append(sqlfunc.date(TipRecord.created_at) >= date_from)
    if date_to is not None:
        from sqlalchemy import func as sqlfunc
        filters.append(sqlfunc.date(TipRecord.created_at) <= date_to)

    query = select(TipRecord).order_by(TipRecord.created_at.desc()).limit(limit).offset(offset)
    if filters:
        query = query.where(and_(*filters))

    result = await db.execute(query)
    return result.scalars().all()
