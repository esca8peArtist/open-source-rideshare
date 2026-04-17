"""Fare preview API endpoint — transparent pre-ride pricing.

Public endpoint (no authentication required):
  GET /pricing/fare-preview    — full surge-transparent fare estimate

This endpoint is intentionally unauthenticated so riders can check pricing
before they log in. It exposes both admin surge zone and real-time demand
pricing separately, which is our cooperative differentiator vs Uber/Lyft.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.schemas.fare_preview import (
    DemandPricingInfo,
    FareComponentsResponse,
    FarePreviewResponse,
    SurgeZoneInfo,
)
from app.services.fare_preview import get_fare_preview

router = APIRouter(prefix="/pricing", tags=["pricing"])


@router.get("/fare-preview", response_model=FarePreviewResponse)
async def fare_preview(
    origin_lat: float = Query(..., ge=-90.0, le=90.0, description="Pickup latitude"),
    origin_lon: float = Query(..., ge=-180.0, le=180.0, description="Pickup longitude"),
    dest_lat: float = Query(..., ge=-90.0, le=90.0, description="Dropoff latitude"),
    dest_lon: float = Query(..., ge=-180.0, le=180.0, description="Dropoff longitude"),
    db: AsyncSession = Depends(get_db),
):
    """Return a full transparent fare estimate before the rider confirms a trip.

    No authentication required — pricing is public information.

    Shows separately:
    - **surge_zone**: Admin-defined surge zones (airports, stadiums, events).
      Based on geography and time-of-day rules configured by the cooperative.
    - **demand_pricing**: Real-time supply/demand. Set by the actual ratio of
      ride requests to available drivers in a ~5 km area. Capped by cooperative
      policy (default 1.5×).
    - **time_of_day_multiplier**: Optional operator-scheduled adjustments (e.g.
      late-night premium). Set by the cooperative, not algorithmic.

    The ``pricing_summary`` field explains any elevation in plain English
    including the percentage increase, demand count, and driver count.

    Falls back gracefully when OSRM or Redis are unavailable:
    - Route: Haversine straight-line distance + 30 km/h urban estimate.
    - Demand pricing: 1.0× (no adjustment) with explanation in ``demand_pricing``.
    """
    try:
        from app.services.matching import get_redis

        redis_client = await get_redis()
    except Exception:
        redis_client = None

    result = await get_fare_preview(
        origin_lat=origin_lat,
        origin_lon=origin_lon,
        dest_lat=dest_lat,
        dest_lon=dest_lon,
        db=db,
        redis_client=redis_client,
    )

    return FarePreviewResponse(
        origin_lat=result.origin_lat,
        origin_lon=result.origin_lon,
        dest_lat=result.dest_lat,
        dest_lon=result.dest_lon,
        distance_km=result.distance_km,
        duration_min=result.duration_min,
        route_source=result.route_source,
        surge_zone=SurgeZoneInfo(
            multiplier=result.surge_zone_multiplier,
            zone_name=result.surge_zone_name,
            zone_description=result.surge_zone_description,
        ),
        demand_pricing=DemandPricingInfo(
            multiplier=result.demand_multiplier,
            multiplier_cap=result.demand_multiplier_cap,
            demand_count=result.demand_count,
            supply_count=result.supply_count,
            is_elevated=result.is_demand_elevated,
            explanation=result.demand_explanation,
        ),
        time_of_day_multiplier=result.breakdown.multiplier,
        time_of_day_label=result.breakdown.multiplier_label,
        components=FareComponentsResponse(
            base=result.breakdown.base,
            distance=result.breakdown.distance,
            time=result.breakdown.time,
        ),
        combined_multiplier=result.combined_multiplier,
        subtotal=result.breakdown.subtotal,
        platform_fee=result.breakdown.platform_fee,
        estimated_fare=result.breakdown.total,
        pricing_summary=result.pricing_summary,
        is_surge_active=result.is_surge_active,
    )
