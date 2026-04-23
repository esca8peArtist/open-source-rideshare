"""Pool fare ladder endpoint — pre-booking pool pricing transparency."""

from fastapi import APIRouter, Query

from app.schemas.pool_fare_ladder import PoolFareLadderResponse
from app.services.pool_fare_ladder import get_pool_fare_ladder

router = APIRouter(prefix="/pricing", tags=["pricing"])


@router.get("/pool-fare-ladder", response_model=PoolFareLadderResponse)
async def pool_fare_ladder(
    pickup_lat: float = Query(..., ge=-90, le=90, description="Pickup latitude"),
    pickup_lng: float = Query(..., ge=-180, le=180, description="Pickup longitude"),
    dropoff_lat: float = Query(..., ge=-90, le=90, description="Dropoff latitude"),
    dropoff_lng: float = Query(..., ge=-180, le=180, description="Dropoff longitude"),
) -> PoolFareLadderResponse:
    """Show estimated fares for each pool size (1–3 riders).

    Public endpoint — no authentication required. Returns a fare table
    showing the solo fare alongside pool fares at 2 and 3 riders, with
    discount percentages, savings amounts, and a plain-English recommendation.

    Use this to help riders decide whether to book solo or pool before they
    commit to a pool request.
    """
    return get_pool_fare_ladder(pickup_lat, pickup_lng, dropoff_lat, dropoff_lng)
