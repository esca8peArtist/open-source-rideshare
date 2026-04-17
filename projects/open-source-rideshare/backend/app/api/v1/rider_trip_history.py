"""Rider trip history endpoint.

GET /riders/me/trip-history
  Returns a paginated, filtered list of past trips for the authenticated rider.

Query parameters
----------------
status      : "all" | "completed" | "cancelled"  (default: "all")
from_date   : YYYY-MM-DD  (optional, inclusive)
to_date     : YYYY-MM-DD  (optional, inclusive)
limit       : int 1–100   (default: 20)
offset      : int ≥ 0     (default: 0)
"""

from __future__ import annotations

from datetime import date
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi import status as http_status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.database import get_db
from app.models.user import User
from app.schemas.rider_trip_history import RiderTripHistory
from app.services.rider_trip_history import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    get_rider_trip_history,
)

router = APIRouter(prefix="/riders", tags=["riders"])


@router.get("/me/trip-history", response_model=RiderTripHistory)
async def get_trip_history(
    status: Literal["all", "completed", "cancelled"] = Query(
        default="all",
        description="Filter by ride status.  'all' returns every trip.",
    ),
    from_date: Optional[date] = Query(
        default=None,
        description="Inclusive start date (YYYY-MM-DD).  Filters on requested_at.",
    ),
    to_date: Optional[date] = Query(
        default=None,
        description="Inclusive end date (YYYY-MM-DD).  Filters on requested_at.",
    ),
    limit: int = Query(
        default=DEFAULT_LIMIT,
        ge=1,
        le=MAX_LIMIT,
        description=f"Max trips per page (1–{MAX_LIMIT}).",
    ),
    offset: int = Query(
        default=0,
        ge=0,
        description="Pagination offset.",
    ),
    rider: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RiderTripHistory:
    """Return a paginated, filtered trip history for the authenticated rider."""
    if from_date is not None and to_date is not None and from_date > to_date:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="from_date must not be after to_date.",
        )
    return await get_rider_trip_history(
        db=db,
        rider_id=rider.id,
        status=status,
        from_date=from_date,
        to_date=to_date,
        limit=limit,
        offset=offset,
    )
