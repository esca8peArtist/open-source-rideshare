"""Fare forecast API endpoint — show riders cheapest booking windows.

Public endpoint (no authentication required):
  GET /pricing/fare-forecast   — fare estimates at 6 future time slots

This is a cooperative transparency feature: riders can see how pricing
changes over the next 1–12 hours and pick the cheapest window to book.
Uber and Lyft do not offer this. All demand multipliers are heuristic
(time-of-day rules) and are clearly labelled as such in the response.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.schemas.fare_forecast import FareForecastResponse
from app.services.fare_forecast import get_fare_forecast

router = APIRouter(prefix="/pricing", tags=["pricing"])


@router.get("/fare-forecast", response_model=FareForecastResponse)
async def fare_forecast(
    origin_lat: float = Query(..., ge=-90.0, le=90.0, description="Pickup latitude"),
    origin_lon: float = Query(..., ge=-180.0, le=180.0, description="Pickup longitude"),
    dest_lat: float = Query(..., ge=-90.0, le=90.0, description="Dropoff latitude"),
    dest_lon: float = Query(..., ge=-180.0, le=180.0, description="Dropoff longitude"),
    lookahead_hours: int = Query(
        default=4,
        ge=1,
        le=12,
        description="How many hours ahead to forecast (1–12, default 4)",
    ),
    db: AsyncSession = Depends(get_db),
) -> FareForecastResponse:
    """Return fare estimates at 6 evenly-spaced future time slots.

    No authentication required — future pricing is public information.

    Slots are spaced at 0%, 20%, 40%, 60%, 80%, and 100% of the lookahead
    window. With the default ``lookahead_hours=4`` this gives estimates at
    now, +48 min, +96 min, +144 min, +192 min, and +240 min.

    Each slot shows:
    - **surge_multiplier**: Live zone multiplier from admin-defined zones.
      Evaluated for the slot's future datetime using time/day constraints.
    - **demand_multiplier**: Heuristic time-of-day estimate (morning rush,
      evening rush, bar close, off-peak). Not live Redis data.
    - **combined_multiplier**: Product of the above two multipliers.
    - **estimated_fare**: Total fare estimate for that departure time.
    - **is_cheapest**: Exactly one slot is flagged as the cheapest option.

    The ``recommendation`` field provides plain-English booking guidance,
    e.g. "Cheapest fare in 80 minutes. Current fare is 35% higher."

    ``demand_is_heuristic`` is always ``true`` — remind riders that demand
    estimates are approximations, not real-time data.
    """
    return await get_fare_forecast(
        db=db,
        origin_lat=origin_lat,
        origin_lon=origin_lon,
        dest_lat=dest_lat,
        dest_lon=dest_lon,
        lookahead_hours=lookahead_hours,
    )
