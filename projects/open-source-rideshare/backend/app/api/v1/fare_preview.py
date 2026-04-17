"""Pre-booking fare transparency API.

Public endpoint — no authentication required.

  GET /pricing/fare-preview
      Returns a full fare breakdown for a hypothetical trip given distance and
      duration, including OpenRide driver payout and platform fee (zero), plus
      estimated competitor (Uber/Lyft) fares and driver payouts for the same trip.

      Designed to be called from the booking flow or onboarding screens so riders
      and drivers can see the cooperative advantage before committing to a ride.

Query parameters
----------------
  distance_km      float  required  Trip distance in kilometres (0 < x ≤ 500)
  duration_min     float  required  Estimated duration in minutes  (0 < x ≤ 600)
  surge_multiplier float  optional  Surge multiplier at pickup location (default 1.0)
                                    Pass the value from GET /pricing/surge-check.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.schemas.fare_preview import FarePreviewResponse
from app.services.fare_preview import get_fare_preview

router = APIRouter(
    prefix="/pricing",
    tags=["pricing"],
)


@router.get(
    "/fare-preview",
    response_model=FarePreviewResponse,
    summary="Pre-booking fare transparency",
    description=(
        "Returns an estimated fare breakdown for a trip of given distance and duration. "
        "Shows how the fare is split between the driver and the platform on OpenRide "
        "(zero platform commission) alongside estimated competitor fares and driver "
        "payouts for the same trip. No authentication required."
    ),
)
async def fare_preview(
    distance_km: float = Query(
        ...,
        gt=0.0,
        le=500.0,
        description="Trip distance in kilometres",
    ),
    duration_min: float = Query(
        ...,
        gt=0.0,
        le=600.0,
        description="Estimated trip duration in minutes",
    ),
    surge_multiplier: float = Query(
        1.0,
        ge=1.0,
        le=10.0,
        description=(
            "Surge zone multiplier in effect at the pickup location (default 1.0 = no surge). "
            "Use the value returned by GET /pricing/surge-check."
        ),
    ),
) -> FarePreviewResponse:
    return get_fare_preview(
        distance_km=distance_km,
        duration_min=duration_min,
        surge_multiplier=surge_multiplier,
    )
