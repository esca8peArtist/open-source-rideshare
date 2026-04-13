"""Transparent supply/demand-aware pricing for cooperative rideshare.

Unlike opaque surge pricing used by Uber/Lyft, this system:
- Shows riders exactly why their fare is higher (demand count, driver count, multiplier)
- Enforces a hard cap set by the cooperative (default 1.5x)
- Uses geohash grid cells to track local supply/demand in real time
- Allows cooperatives to disable demand pricing entirely (multiplier always 1.0)

Architecture:
- Demand is tracked as ride-request counts per geohash cell in Redis (sliding window).
- Supply is counted from available drivers in the matching engine's geo set.
- The ratio drives a linear multiplier between 1.0 and the configured cap.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import redis.asyncio as redis

from app.config import settings

# Redis key patterns
_DEMAND_KEY_PREFIX = "openride:demand:"  # + geohash
_DEMAND_WINDOW_SECONDS = 300  # 5-minute sliding window


@dataclass(frozen=True)
class DemandInfo:
    """Transparent demand pricing info returned to riders."""

    geohash: str
    demand_count: int
    supply_count: int
    multiplier: float
    multiplier_cap: float
    is_elevated: bool
    explanation: str


def encode_geohash(lat: float, lng: float, precision: int = 5) -> str:
    """Encode lat/lng into a geohash string.

    Precision 5 gives ~4.9km x 4.9km cells — good granularity for
    urban demand zones without being too fine-grained.
    """
    base32 = "0123456789bcdefghjkmnpqrstuvwxyz"
    lat_range = (-90.0, 90.0)
    lng_range = (-180.0, 180.0)
    bits = [16, 8, 4, 2, 1]
    result = []
    bit = 0
    ch = 0
    is_lng = True

    while len(result) < precision:
        if is_lng:
            mid = (lng_range[0] + lng_range[1]) / 2
            if lng >= mid:
                ch |= bits[bit]
                lng_range = (mid, lng_range[1])
            else:
                lng_range = (lng_range[0], mid)
        else:
            mid = (lat_range[0] + lat_range[1]) / 2
            if lat >= mid:
                ch |= bits[bit]
                lat_range = (mid, lat_range[1])
            else:
                lat_range = (lat_range[0], mid)
        is_lng = not is_lng
        bit += 1
        if bit == 5:
            result.append(base32[ch])
            bit = 0
            ch = 0

    return "".join(result)


def geohash_neighbors(gh: str) -> list[str]:
    """Return the 8 neighboring geohash cells plus the cell itself.

    Used to count supply in the surrounding area, not just the exact cell.
    This prevents edge effects where a rider at a cell boundary sees
    no supply even though drivers are 100m away in the adjacent cell.
    """
    # Decode geohash center, then offset by cell dimensions
    # For simplicity, use the adjacent geohash calculation
    lat, lng = _decode_geohash_center(gh)
    precision = len(gh)
    lat_err, lng_err = _geohash_dimensions(precision)

    neighbors = []
    for dlat in (-lat_err, 0, lat_err):
        for dlng in (-lng_err, 0, lng_err):
            n = encode_geohash(lat + dlat, lng + dlng, precision)
            if n not in neighbors:
                neighbors.append(n)
    return neighbors


def _decode_geohash_center(gh: str) -> tuple[float, float]:
    """Decode a geohash to its center lat/lng."""
    base32 = "0123456789bcdefghjkmnpqrstuvwxyz"
    lat_range = [-90.0, 90.0]
    lng_range = [-180.0, 180.0]
    is_lng = True

    for c in gh:
        val = base32.index(c)
        for bit in [16, 8, 4, 2, 1]:
            if is_lng:
                mid = (lng_range[0] + lng_range[1]) / 2
                if val & bit:
                    lng_range[0] = mid
                else:
                    lng_range[1] = mid
            else:
                mid = (lat_range[0] + lat_range[1]) / 2
                if val & bit:
                    lat_range[0] = mid
                else:
                    lat_range[1] = mid
            is_lng = not is_lng

    return (lat_range[0] + lat_range[1]) / 2, (lng_range[0] + lng_range[1]) / 2


def _geohash_dimensions(precision: int) -> tuple[float, float]:
    """Return approximate (lat_delta, lng_delta) for a geohash cell at the given precision."""
    # Each precision level halves the range alternating between lng and lat
    lat_bits = 0
    lng_bits = 0
    for i in range(precision * 5):
        if i % 2 == 0:
            lng_bits += 1
        else:
            lat_bits += 1
    lat_delta = 180.0 / (2 ** lat_bits)
    lng_delta = 360.0 / (2 ** lng_bits)
    return lat_delta * 2, lng_delta * 2  # *2 to step to neighbor center


async def record_demand(
    redis_client: redis.Redis,
    lat: float,
    lng: float,
) -> str:
    """Record a ride request for demand tracking. Returns the geohash cell."""
    gh = encode_geohash(lat, lng)
    key = f"{_DEMAND_KEY_PREFIX}{gh}"
    async with redis_client.pipeline() as pipe:
        pipe.incr(key)
        pipe.expire(key, _DEMAND_WINDOW_SECONDS)
        await pipe.execute()
    return gh


async def get_demand_count(redis_client: redis.Redis, geohash: str) -> int:
    """Get current demand count for a geohash cell."""
    key = f"{_DEMAND_KEY_PREFIX}{geohash}"
    val = await redis_client.get(key)
    return int(val) if val else 0


async def get_area_demand(redis_client: redis.Redis, lat: float, lng: float) -> int:
    """Get total demand across the cell and its neighbors."""
    gh = encode_geohash(lat, lng)
    neighbors = geohash_neighbors(gh)
    total = 0
    for n in neighbors:
        total += await get_demand_count(redis_client, n)
    return total


async def get_area_supply(
    redis_client: redis.Redis,
    lat: float,
    lng: float,
    radius_km: float | None = None,
) -> int:
    """Count available drivers near a location.

    Uses the matching engine's existing geo set to avoid duplication.
    """
    from app.services.matching import REDIS_DRIVER_GEO_KEY, REDIS_DRIVER_STATUS_PREFIX

    if radius_km is None:
        radius_km = settings.driver_search_radius_km

    results = await redis_client.geosearch(
        REDIS_DRIVER_GEO_KEY,
        longitude=lng,
        latitude=lat,
        radius=radius_km,
        unit="km",
        sort="ASC",
        count=50,
    )

    available = 0
    for member in results:
        user_id = member if isinstance(member, str) else member[0] if isinstance(member, (list, tuple)) else str(member)
        status = await redis_client.get(f"{REDIS_DRIVER_STATUS_PREFIX}{user_id}")
        if status in (b"available", "available"):
            available += 1
    return available


def calculate_demand_multiplier(
    demand: int,
    supply: int,
    demand_threshold: float | None = None,
    max_multiplier: float | None = None,
    scale_factor: float | None = None,
) -> float:
    """Calculate the demand multiplier from supply/demand counts.

    The multiplier is 1.0 when demand/supply ratio is at or below the threshold,
    and scales linearly up to max_multiplier as the ratio increases.

    Args:
        demand: Number of ride requests in the area (sliding window).
        supply: Number of available drivers in the area.
        demand_threshold: Demand/supply ratio below which no multiplier applies.
        max_multiplier: Hard cap on the multiplier (cooperative policy).
        scale_factor: How quickly the multiplier rises per unit of ratio above threshold.
    """
    if demand_threshold is None:
        demand_threshold = settings.demand_pricing_threshold
    if max_multiplier is None:
        max_multiplier = settings.demand_pricing_max_multiplier
    if scale_factor is None:
        scale_factor = settings.demand_pricing_scale_factor

    if not settings.demand_pricing_enabled:
        return 1.0

    if max_multiplier <= 1.0:
        return 1.0

    effective_supply = max(supply, 1)
    ratio = demand / effective_supply

    if ratio <= demand_threshold:
        return 1.0

    excess = ratio - demand_threshold
    multiplier = 1.0 + excess * scale_factor
    return min(round(multiplier, 2), max_multiplier)


async def get_demand_info(
    redis_client: redis.Redis,
    lat: float,
    lng: float,
) -> DemandInfo:
    """Get full transparent demand pricing info for a location.

    This is what gets shown to the rider before they confirm a ride.
    """
    gh = encode_geohash(lat, lng)
    demand = await get_area_demand(redis_client, lat, lng)
    supply = await get_area_supply(redis_client, lat, lng)
    multiplier = calculate_demand_multiplier(demand, supply)
    max_mult = settings.demand_pricing_max_multiplier

    is_elevated = multiplier > 1.0

    if not settings.demand_pricing_enabled:
        explanation = "Standard pricing — demand-based adjustments are disabled."
    elif not is_elevated:
        explanation = "Standard pricing — driver availability is good in your area."
    else:
        pct = round((multiplier - 1.0) * 100)
        explanation = (
            f"Fares are {pct}% higher due to high demand in your area. "
            f"{demand} ride requests vs {supply} available driver{'s' if supply != 1 else ''} nearby. "
            f"Maximum increase is capped at {round((max_mult - 1.0) * 100)}%."
        )

    return DemandInfo(
        geohash=gh,
        demand_count=demand,
        supply_count=supply,
        multiplier=multiplier,
        multiplier_cap=max_mult,
        is_elevated=is_elevated,
        explanation=explanation,
    )
