"""Rider-facing busy hours indicator.

Exposes historical demand patterns to authenticated users so they can
anticipate surge pricing and longer wait times before requesting a ride.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.database import get_db
from app.models.user import User
from app.schemas.busy_hours import BusyHoursResponse
from app.services.busy_hours import get_busy_hours

router = APIRouter(prefix="/rides", tags=["busy-hours"])


@router.get(
    "/busy-hours",
    response_model=BusyHoursResponse,
    summary="Get busy hours indicator",
    description=(
        "Returns hourly demand levels (low / medium / high / peak) based on "
        "historical ride data. Riders can use this to anticipate surge pricing "
        "and longer wait times. Optionally filter by day of week to see typical "
        "patterns for a specific day (e.g. Friday nights vs. Monday mornings)."
    ),
)
async def busy_hours(
    day_of_week: int | None = Query(
        None,
        ge=0,
        le=6,
        description="Filter by day of week (0=Sunday, 1=Monday, …, 6=Saturday). "
        "Omit to aggregate across all days.",
    ),
    _current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BusyHoursResponse:
    return await get_busy_hours(db, day_of_week=day_of_week)
