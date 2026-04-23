"""Pool fare ladder service — show riders how much they save at each pool size.

Returns a tier table (1–3 riders) with fare, discount %, and savings for a
given route so riders can make an informed decision before booking a pool ride.
"""

from __future__ import annotations

from app.schemas.pool_fare_ladder import FareTier, PoolFareLadderResponse
from app.services.fare_preview import _estimate_duration_min, _haversine_km
from app.services.pool_matching import (
    DISCOUNT_BY_RIDERS,
    MAX_POOL_WAIT_SECONDS,
    calculate_pool_fare,
)


def _build_recommendation(tiers: list[FareTier]) -> str:
    solo = next((t for t in tiers if t.is_solo), None)
    pool_tiers = [t for t in tiers if not t.is_solo]

    if not solo or not pool_tiers:
        return "Pool fare data unavailable."

    min_pool = min(pool_tiers, key=lambda t: t.riders)
    max_pool = max(pool_tiers, key=lambda t: t.savings)

    if solo.fare < 8.0:
        return (
            f"Short trip — pool savings top out at ${max_pool.savings:.2f} "
            f"({max_pool.discount_percent:.0f}% off) with {max_pool.riders} riders."
        )

    if len(pool_tiers) == 1:
        return (
            f"Pooling with one co-rider saves ${min_pool.savings:.2f} "
            f"({min_pool.discount_percent:.0f}% off) and you wait at most "
            f"{MAX_POOL_WAIT_SECONDS // 60} minutes."
        )

    return (
        f"Pooling with one co-rider saves ${min_pool.savings:.2f} "
        f"({min_pool.discount_percent:.0f}%). With {max_pool.riders} riders, "
        f"you save up to ${max_pool.savings:.2f} ({max_pool.discount_percent:.0f}%)."
    )


def get_pool_fare_ladder(
    pickup_lat: float,
    pickup_lng: float,
    dropoff_lat: float,
    dropoff_lng: float,
) -> PoolFareLadderResponse:
    """Build a fare ladder for a given route across all pool sizes."""
    distance_km = _haversine_km(pickup_lat, pickup_lng, dropoff_lat, dropoff_lng)
    duration_min = _estimate_duration_min(distance_km)

    tiers: list[FareTier] = []
    for riders, discount in sorted(DISCOUNT_BY_RIDERS.items()):
        solo_fare, pool_fare, savings = calculate_pool_fare(distance_km, duration_min, discount)
        tiers.append(FareTier(
            riders=riders,
            label="Solo" if riders == 1 else f"{riders} riders",
            fare=solo_fare if riders == 1 else pool_fare,
            discount_percent=discount,
            savings=savings,
            is_solo=(riders == 1),
        ))

    # Recommend the smallest pool (least wait, still saves money)
    recommended_tier = next(
        (t.riders for t in tiers if not t.is_solo and t.savings > 0),
        1,
    )

    return PoolFareLadderResponse(
        pickup_lat=pickup_lat,
        pickup_lng=pickup_lng,
        dropoff_lat=dropoff_lat,
        dropoff_lng=dropoff_lng,
        distance_km=round(distance_km, 2),
        estimated_duration_min=round(duration_min, 1),
        tiers=tiers,
        recommended_tier=recommended_tier,
        recommendation=_build_recommendation(tiers),
        max_pool_wait_minutes=MAX_POOL_WAIT_SECONDS // 60,
    )
