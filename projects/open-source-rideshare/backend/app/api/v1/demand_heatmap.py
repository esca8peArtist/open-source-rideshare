"""Trip demand heatmap API.

Driver endpoint (authenticated driver):
  GET /drivers/demand-heatmap   — pickup hotspot map for positioning guidance

Admin endpoint (requires admin auth):
  GET /admin/analytics/demand-heatmap   — full heatmap with fare aggregates and filters
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_admin, require_driver
from app.db.database import get_db
from app.models.user import User
from app.schemas.demand_heatmap import (
    AdminDemandHeatmapResponse,
    DriverDemandHeatmapResponse,
    FiltersApplied,
    HeatmapCell,
    HeatmapCellWithFare,
    HeatmapResolution,
)
from app.services.demand_heatmap import MAX_LIMIT_ADMIN, MAX_LIMIT_DRIVER, get_demand_heatmap

logger = logging.getLogger(__name__)
router = APIRouter(tags=["demand-heatmap"])

_ISO_DOW_MAP = {0: 1, 1: 2, 2: 3, 3: 4, 4: 5, 5: 6, 6: 7}  # 0=Mon→1, …, 6=Sun→7


def _today_utc() -> date:
    return datetime.now(timezone.utc).date()


# ---------------------------------------------------------------------------
# Driver endpoint
# ---------------------------------------------------------------------------


@router.get(
    "/drivers/demand-heatmap",
    response_model=DriverDemandHeatmapResponse,
    summary="Get trip demand heatmap for driver positioning",
    description=(
        "Returns a geographic heatmap of ride request pickup locations for the "
        "last *days* days. Cells are returned sorted by request count descending — "
        "high-demand cells are shown first. Use this to identify where to position "
        "yourself to maximise ride opportunities. No fare data is included. "
        "``resolution`` controls cell size: low≈11km, medium≈1.1km, high≈110m."
    ),
)
async def driver_demand_heatmap(
    days: int = Query(7, ge=1, le=30, description="Lookback window in days (1–30)"),
    resolution: HeatmapResolution = Query(
        HeatmapResolution.MEDIUM, description="Grid cell size: low, medium, or high"
    ),
    limit: int = Query(
        100, ge=1, le=MAX_LIMIT_DRIVER, description=f"Max cells to return (1–{MAX_LIMIT_DRIVER})"
    ),
    _driver: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    """Pickup hotspot map for the authenticated driver."""
    end_date = _today_utc()
    start_date = end_date - timedelta(days=days - 1)

    data = await get_demand_heatmap(
        db,
        start_date=start_date,
        end_date=end_date,
        resolution=resolution.value,
        limit=limit,
        include_fare=False,
    )

    return DriverDemandHeatmapResponse(
        period_start=data["period_start"],
        period_end=data["period_end"],
        resolution=HeatmapResolution(data["resolution"]),
        resolution_degrees=data["resolution_degrees"],
        total_requests=data["total_requests"],
        total_cells=data["total_cells"],
        cells=[HeatmapCell(**c) for c in data["cells"]],
    )


# ---------------------------------------------------------------------------
# Admin endpoint
# ---------------------------------------------------------------------------


@router.get(
    "/admin/analytics/demand-heatmap",
    response_model=AdminDemandHeatmapResponse,
    summary="Get trip demand heatmap with fare aggregates (admin)",
    description=(
        "Returns a geographic heatmap of ride request pickup locations. "
        "Each cell includes request count, completed count, average fare, and total fare. "
        "Supports filtering by explicit date range, time of day, and day of week. "
        "``day_of_week``: 0=Monday, 1=Tuesday, …, 6=Sunday. "
        "``resolution`` cell sizes: low≈11km, medium≈1.1km (default), high≈110m."
    ),
)
async def admin_demand_heatmap(
    days: int = Query(
        7,
        ge=1,
        le=90,
        description="Lookback window in days (1–90). Ignored if start_date/end_date are set.",
    ),
    start_date: date | None = Query(None, description="Explicit window start (YYYY-MM-DD)"),
    end_date: date | None = Query(None, description="Explicit window end (YYYY-MM-DD)"),
    resolution: HeatmapResolution = Query(
        HeatmapResolution.MEDIUM, description="Grid cell size: low, medium, or high"
    ),
    hour_start: int | None = Query(
        None, ge=0, le=23, description="Filter: only rides requested at or after this UTC hour"
    ),
    hour_end: int | None = Query(
        None, ge=0, le=23, description="Filter: only rides requested at or before this UTC hour"
    ),
    day_of_week: int | None = Query(
        None, ge=0, le=6, description="Filter by day of week: 0=Monday … 6=Sunday"
    ),
    limit: int = Query(
        200, ge=1, le=MAX_LIMIT_ADMIN, description=f"Max cells to return (1–{MAX_LIMIT_ADMIN})"
    ),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Full demand heatmap with fare aggregates for admin analytics."""
    # Resolve date window
    if start_date is not None or end_date is not None:
        if start_date is None or end_date is None:
            raise HTTPException(
                status_code=422,
                detail="Both start_date and end_date must be provided together.",
            )
        if start_date > end_date:
            raise HTTPException(
                status_code=422,
                detail="start_date must be on or before end_date.",
            )
    else:
        end_date = _today_utc()
        start_date = end_date - timedelta(days=days - 1)

    # Validate hour range
    if hour_start is not None and hour_end is not None and hour_start > hour_end:
        raise HTTPException(
            status_code=422,
            detail="hour_start must be <= hour_end.",
        )

    # Map 0-based day_of_week to PostgreSQL ISODOW (1=Mon … 7=Sun)
    iso_dow = _ISO_DOW_MAP[day_of_week] if day_of_week is not None else None

    data = await get_demand_heatmap(
        db,
        start_date=start_date,
        end_date=end_date,
        resolution=resolution.value,
        hour_start=hour_start,
        hour_end=hour_end,
        day_of_week=iso_dow,
        limit=limit,
        include_fare=True,
    )

    filters = FiltersApplied(
        period_start=start_date,
        period_end=end_date,
        resolution=HeatmapResolution(data["resolution"]),
        hour_start=hour_start,
        hour_end=hour_end,
        day_of_week=day_of_week,
        limit=limit,
    )

    return AdminDemandHeatmapResponse(
        period_start=data["period_start"],
        period_end=data["period_end"],
        resolution=HeatmapResolution(data["resolution"]),
        resolution_degrees=data["resolution_degrees"],
        total_requests=data["total_requests"],
        total_cells=data["total_cells"],
        filters_applied=filters,
        cells=[HeatmapCellWithFare(**c) for c in data["cells"]],
    )
