"""Demand-by-hour analytics API — admin endpoint.

Admin endpoints:
  GET /admin/analytics/demand-by-hour  — hourly ride demand breakdown (24 slots)
"""
from __future__ import annotations

import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin
from app.db.database import get_db
from app.models.user import User
from app.schemas.demand_heatmap import DemandByHourResponse
from app.services.demand_heatmap import get_demand_by_hour

logger = logging.getLogger(__name__)
router = APIRouter(tags=["admin-analytics"])

_DOW_NAMES = {
    0: "Sunday",
    1: "Monday",
    2: "Tuesday",
    3: "Wednesday",
    4: "Thursday",
    5: "Friday",
    6: "Saturday",
}


@router.get(
    "/admin/analytics/demand-by-hour",
    response_model=DemandByHourResponse,
    summary="Get hourly ride demand breakdown",
    description=(
        "Returns 24 slots — one per hour of day (UTC) — showing how many rides were "
        "requested in each hour, split into completed vs cancelled, with average fare "
        "and average wait time (requested → matched). "
        "Use `day_of_week` (0=Sunday … 6=Saturday) to isolate a single day type, e.g. "
        "Friday nights vs Monday mornings. Useful for driver incentive scheduling and "
        "surge zone activation windows."
    ),
)
async def get_demand_heatmap(
    start_date: date | None = Query(
        None, description="Inclusive start date filter (YYYY-MM-DD) on ride requested_at"
    ),
    end_date: date | None = Query(
        None, description="Inclusive end date filter (YYYY-MM-DD) on ride requested_at"
    ),
    day_of_week: int | None = Query(
        None,
        ge=0,
        le=6,
        description=(
            "PostgreSQL day-of-week (0=Sunday, 1=Monday, …, 6=Saturday). "
            "Omit to include all days."
        ),
    ),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> DemandByHourResponse:
    """Admin-only hourly demand analytics across all 24 hours of the day."""
    if start_date is not None and end_date is not None and end_date < start_date:
        raise HTTPException(
            status_code=422,
            detail="end_date must be on or after start_date",
        )

    return await get_demand_by_hour(
        db,
        start_date=start_date,
        end_date=end_date,
        day_of_week=day_of_week,
    )
