"""Analytics API — rider spending and driver tax summary.

Rider endpoints (authenticated rider):
  GET /analytics/rider/spending         — spending summary with period filter
  GET /analytics/rider/spending/export  — CSV export of trip history
  GET /analytics/rider/stats            — lifetime stats summary

Driver endpoints (authenticated driver):
  GET /analytics/driver/tax-summary         — annual earnings summary for 1099 prep
  GET /analytics/driver/tax-summary/export  — CSV export of annual rides
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_driver
from app.db.database import get_db
from app.models.user import User
from app.schemas.ride import RiderStatsResponse
from app.services.analytics import (
    export_driver_tax_csv,
    export_rider_spending_csv,
    get_driver_tax_summary,
    get_rider_spending,
    get_rider_stats,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/analytics", tags=["analytics"])

_VALID_PERIODS = {"week", "month", "year", "all"}


# ---------------------------------------------------------------------------
# Rider endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/rider/spending",
    summary="Get rider spending analytics",
    description=(
        "Returns a spending summary for the authenticated rider's completed trips. "
        "The `period` parameter filters results to the current week, month, year, "
        "or all time. The `limit` parameter caps the number of individual trips "
        "returned in the `trips` list (aggregates are always over the full period). "
        "Monthly breakdown is included when period is `year` or `all`."
    ),
)
async def get_rider_spending_summary(
    period: str = Query("month", description="One of: week, month, year, all"),
    limit: int = Query(20, ge=1, le=200, description="Max trips to return in trips list"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Spending analytics for the authenticated rider."""
    if period not in _VALID_PERIODS:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=422,
            detail=f"Invalid period '{period}'. Must be one of: week, month, year, all",
        )
    return await get_rider_spending(db, rider_id=current_user.id, period=period, limit=limit)


@router.get(
    "/rider/spending/export",
    summary="Export rider trip history as CSV",
    description=(
        "Returns a CSV file containing all completed trips for the authenticated rider "
        "within the specified period. "
        "Columns: date, pickup_address, dropoff_address, fare, tip, "
        "promo_discount, total_charged, ride_id."
    ),
)
async def export_rider_spending(
    period: str = Query("month", description="One of: week, month, year, all"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """CSV export of rider trip history."""
    if period not in _VALID_PERIODS:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=422,
            detail=f"Invalid period '{period}'. Must be one of: week, month, year, all",
        )
    csv_content = await export_rider_spending_csv(db, rider_id=current_user.id, period=period)

    filename = f"trip_history_{period}_{datetime.now(tz=timezone.utc).strftime('%Y%m%d')}.csv"
    return StreamingResponse(
        iter([csv_content]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get(
    "/rider/stats",
    response_model=RiderStatsResponse,
    summary="Get rider lifetime stats",
    description=(
        "Returns lifetime ride statistics for the authenticated user. "
        "Includes total rides, completion rate, total spent, average fare, "
        "total distance, average rating given to drivers, and tip summary."
    ),
)
async def get_rider_stats_endpoint(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Lifetime stats summary for the authenticated rider."""
    stats = await get_rider_stats(db, rider_id=current_user.id, member_since=current_user.created_at)
    return RiderStatsResponse(**stats)


# ---------------------------------------------------------------------------
# Driver endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/driver/tax-summary",
    summary="Get driver annual tax summary (1099 prep)",
    description=(
        "Returns an annual earnings summary for the authenticated driver to assist "
        "with 1099 tax preparation. Includes gross fares, tips, incentive bonuses, "
        "platform fees, and a quarterly breakdown. "
        "DISCLAIMER: This is an estimate only and does not constitute tax advice."
    ),
)
async def get_driver_tax_summary_endpoint(
    year: int = Query(
        default=None,
        ge=2020,
        le=2100,
        description="Tax year (4-digit). Defaults to the current year.",
    ),
    current_user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    """Annual tax summary for the authenticated driver."""
    if year is None:
        year = datetime.now(tz=timezone.utc).year
    return await get_driver_tax_summary(db, driver_id=current_user.id, year=year)


@router.get(
    "/driver/tax-summary/export",
    summary="Export driver annual rides as CSV for tax purposes",
    description=(
        "Returns a CSV file of all completed rides driven in the given year. "
        "Columns: date, ride_id, fare_earned, tip, bonus, total, ride_duration_minutes. "
        "DISCLAIMER: This is an estimate only and does not constitute tax advice."
    ),
)
async def export_driver_tax_summary(
    year: int = Query(
        default=None,
        ge=2020,
        le=2100,
        description="Tax year (4-digit). Defaults to the current year.",
    ),
    current_user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    """CSV export of driver annual rides for tax purposes."""
    if year is None:
        year = datetime.now(tz=timezone.utc).year
    csv_content = await export_driver_tax_csv(db, driver_id=current_user.id, year=year)

    filename = f"tax_summary_{year}_{current_user.id}.csv"
    return StreamingResponse(
        iter([csv_content]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
