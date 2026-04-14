"""Trip heatmap API — admin analytics endpoint.

Admin endpoints:
  GET /admin/analytics/trip-heatmap  — geographic heatmap of pickup/dropoff activity
"""
from __future__ import annotations

import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin
from app.db.database import get_db
from app.models.user import User
from app.models.ride import RideStatus
from app.schemas.trip_heatmap import HeatmapResponse
from app.services.trip_heatmap import get_trip_heatmap

logger = logging.getLogger(__name__)
router = APIRouter(tags=["admin-analytics"])

_VALID_STATUSES = {s.value for s in RideStatus}


@router.get(
    "/admin/analytics/trip-heatmap",
    response_model=HeatmapResponse,
    summary="Get geographic trip heatmap",
    description=(
        "Returns aggregated pickup and dropoff activity grouped into geographic grid cells. "
        "Each cell represents a latitude/longitude square whose size is controlled by the "
        "`precision` parameter (2 decimal places ≈ 1 km, 3 ≈ 110 m, 4 ≈ 11 m). "
        "Defaults to completed rides only. Cells are sorted by total_activity descending "
        "(hottest zones first). Useful for informing surge zone boundaries and service area planning."
    ),
)
async def get_heatmap(
    start_date: date | None = Query(
        None, description="Inclusive start date filter (YYYY-MM-DD) on ride requested_at"
    ),
    end_date: date | None = Query(
        None, description="Inclusive end date filter (YYYY-MM-DD) on ride requested_at"
    ),
    precision: int = Query(
        2, ge=1, le=4, description="Coordinate rounding precision (1-4 decimal places)"
    ),
    status: str | None = Query(
        None,
        description="Ride status to include (default: completed). One of: "
        + ", ".join(sorted(_VALID_STATUSES)),
    ),
    min_activity: int = Query(
        1, ge=1, description="Minimum total_activity (pickup + dropoff) to include a cell"
    ),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> HeatmapResponse:
    """Admin-only heatmap of geographic trip activity."""
    # Validate date order
    if start_date is not None and end_date is not None and end_date < start_date:
        raise HTTPException(
            status_code=422,
            detail="end_date must be on or after start_date",
        )

    # Validate status value if provided
    if status is not None and status not in _VALID_STATUSES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid status '{status}'. Must be one of: {', '.join(sorted(_VALID_STATUSES))}",
        )

    return await get_trip_heatmap(
        db,
        start_date=start_date,
        end_date=end_date,
        precision=precision,
        status=status,
        min_activity=min_activity,
    )
