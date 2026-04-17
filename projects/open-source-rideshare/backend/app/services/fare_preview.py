"""Fare preview service — transparent pre-ride pricing for riders.

Combines two independent pricing signals into a single honest breakdown:
  1. Admin-defined surge zones (geographic, time-of-day)
  2. Real-time demand pricing (supply/demand ratio via Redis)

Both signals are always shown separately so riders understand *why* their
fare is elevated. This is the core cooperative differentiator vs Uber/Lyft:
no hidden multipliers, no opaque "surge" buttons.

Key functions:
  - get_fare_preview()       — main async entry point
  - build_pricing_summary()  — pure: produces human-readable summary
  - _haversine_km()          — pure: great-circle distance fallback
  - _estimate_duration_min() — pure: duration estimate from distance
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.demand_pricing import DemandInfo, get_demand_info
from app.services.pricing import FareBreakdown, calculate_fare_breakdown
from app.services.surge_zones import _point_in_zone, is_zone_active_now, list_zones


# ---------------------------------------------------------------------------
# Pure helpers — no I/O, fully unit-testable
# ---------------------------------------------------------------------------


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return the great-circle distance in kilometres between two points.

    Used as a fallback when OSRM is unavailable, and for direct-line estimates.
    Accurate to within ~0.5% for typical urban trip distances.
    """
    earth_radius_km = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    return earth_radius_km * 2 * math.asin(math.sqrt(a))


def _estimate_duration_min(distance_km: float, avg_speed_kmh: float = 30.0) -> float:
    """Estimate trip duration from distance assuming average urban speed.

    Default 30 km/h reflects mixed urban/suburban driving with stops.
    Callers can override avg_speed_kmh for highway-heavy routes.
    """
    if avg_speed_kmh <= 0:
        raise ValueError("avg_speed_kmh must be positive")
    return (distance_km / avg_speed_kmh) * 60.0


def build_pricing_summary(
    surge_zone_multiplier: float,
    surge_zone_name: str | None,
    demand_multiplier: float,
    demand_count: int,
    supply_count: int,
    combined_multiplier: float,
    demand_pricing_enabled: bool = True,
) -> str:
    """Build a single human-readable pricing summary for riders.

    Pure function — testable without any I/O.

    Args:
        surge_zone_multiplier: Multiplier from admin-defined surge zone (1.0 = none).
        surge_zone_name: Name of the matching zone, or None.
        demand_multiplier: Multiplier from real-time supply/demand (1.0 = none).
        demand_count: Ride requests seen in the area in the last 5 minutes.
        supply_count: Available drivers in the area.
        combined_multiplier: Product of all multipliers (rounded).
        demand_pricing_enabled: Whether real-time demand pricing is on.

    Returns:
        A plain-English string suitable for display in the rider app.
    """
    parts: list[str] = []

    if surge_zone_multiplier > 1.0 and surge_zone_name:
        pct = round((surge_zone_multiplier - 1.0) * 100)
        parts.append(f"{surge_zone_name} zone (+{pct}%)")

    if demand_pricing_enabled and demand_multiplier > 1.0:
        pct = round((demand_multiplier - 1.0) * 100)
        driver_word = "driver" if supply_count == 1 else "drivers"
        parts.append(
            f"high demand (+{pct}%): {demand_count} requests, "
            f"{supply_count} available {driver_word}"
        )

    if not parts:
        return "Standard pricing — no surge active in your area."

    total_pct = round((combined_multiplier - 1.0) * 100)
    reasons = "; ".join(parts)
    return (
        f"Fares are {total_pct}% higher than normal. Reasons: {reasons}. "
        f"This is the cooperative maximum — no additional hidden fees."
    )


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FarePreviewResult:
    """Full transparent fare preview returned to riders before they confirm."""

    # Route
    origin_lat: float
    origin_lon: float
    dest_lat: float
    dest_lon: float
    distance_km: float
    duration_min: float
    route_source: Literal["osrm", "estimate"]

    # Surge zone (admin-defined)
    surge_zone_multiplier: float
    surge_zone_name: str | None
    surge_zone_description: str | None

    # Demand pricing (real-time)
    demand_multiplier: float
    demand_multiplier_cap: float
    demand_count: int
    supply_count: int
    demand_explanation: str
    is_demand_elevated: bool

    # Fare breakdown
    breakdown: FareBreakdown

    # Transparency summary
    combined_multiplier: float
    pricing_summary: str
    is_surge_active: bool


# ---------------------------------------------------------------------------
# Main async entry point
# ---------------------------------------------------------------------------


async def get_fare_preview(
    origin_lat: float,
    origin_lon: float,
    dest_lat: float,
    dest_lon: float,
    db: AsyncSession,
    redis_client,  # redis.asyncio.Redis — typed loosely to avoid hard import
) -> FarePreviewResult:
    """Build a transparent fare preview for the given origin → destination.

    Steps:
    1. Route distance/duration (OSRM with Haversine fallback).
    2. Surge zone multiplier from admin-defined zones.
    3. Real-time demand pricing via Redis.
    4. Fare breakdown with all multipliers applied.
    5. Human-readable summary.

    Never raises — falls back gracefully if OSRM or Redis are unavailable.
    """
    # --- Step 1: Routing ---
    route_source: Literal["osrm", "estimate"] = "estimate"
    distance_km: float
    duration_min: float

    try:
        from app.services.routing import get_route

        route = await get_route(origin_lat, origin_lon, dest_lat, dest_lon)
        distance_km = route["distance_km"]
        duration_min = route["duration_min"]
        route_source = "osrm"
    except Exception:
        distance_km = _haversine_km(origin_lat, origin_lon, dest_lat, dest_lon)
        duration_min = _estimate_duration_min(distance_km)

    # --- Step 2: Surge zone ---
    surge_zone_multiplier = 1.0
    surge_zone_name: str | None = None
    surge_zone_description: str | None = None

    try:
        all_zones = await list_zones(db, active_only=True)
        best_multiplier = 1.0
        for zone in all_zones:
            if not is_zone_active_now(zone):
                continue
            if _point_in_zone(origin_lat, origin_lon, zone):
                if zone.multiplier > best_multiplier:
                    best_multiplier = zone.multiplier
                    surge_zone_name = zone.name
                    surge_zone_description = zone.description
        surge_zone_multiplier = best_multiplier
    except Exception:
        pass

    # --- Step 3: Demand pricing ---
    from app.config import settings

    demand_multiplier = 1.0
    demand_cap = getattr(settings, "demand_pricing_max_multiplier", 1.5)
    demand_count = 0
    supply_count = 0
    demand_explanation = "Standard pricing — demand data unavailable."
    is_demand_elevated = False

    try:
        di: DemandInfo = await get_demand_info(redis_client, origin_lat, origin_lon)
        demand_multiplier = di.multiplier
        demand_cap = di.multiplier_cap
        demand_count = di.demand_count
        supply_count = di.supply_count
        demand_explanation = di.explanation
        is_demand_elevated = di.is_elevated
    except Exception:
        pass

    # --- Step 4: Fare breakdown ---
    surge_label = surge_zone_name if surge_zone_multiplier > 1.0 else None
    demand_label = demand_explanation if is_demand_elevated else None

    breakdown = calculate_fare_breakdown(
        distance_km=distance_km,
        duration_min=duration_min,
        demand_multiplier=demand_multiplier,
        demand_label=demand_label,
        surge_multiplier=surge_zone_multiplier,
        surge_label=surge_label,
    )

    # Combined effective multiplier (time-of-day × demand × zone)
    combined_multiplier = round(
        breakdown.multiplier * demand_multiplier * surge_zone_multiplier, 3
    )

    # --- Step 5: Transparency summary ---
    demand_pricing_enabled = getattr(settings, "demand_pricing_enabled", True)
    pricing_summary = build_pricing_summary(
        surge_zone_multiplier=surge_zone_multiplier,
        surge_zone_name=surge_zone_name,
        demand_multiplier=demand_multiplier,
        demand_count=demand_count,
        supply_count=supply_count,
        combined_multiplier=combined_multiplier,
        demand_pricing_enabled=demand_pricing_enabled,
    )

    is_surge_active = surge_zone_multiplier > 1.0 or is_demand_elevated

    # Emit a surge event for admin analytics — fire-and-forget, never blocks the rider
    if is_surge_active:
        try:
            from app.services.demand_pricing import encode_geohash
            from app.services.surge_analytics import record_surge_event

            gh = encode_geohash(origin_lat, origin_lon)
            await record_surge_event(
                db,
                lat=origin_lat,
                lon=origin_lon,
                geohash=gh,
                surge_zone_id=None,  # zone id not surfaced through current lookup path
                surge_zone_name=surge_zone_name,
                zone_multiplier=surge_zone_multiplier,
                demand_multiplier=demand_multiplier,
                demand_count=demand_count,
                supply_count=supply_count,
                combined_multiplier=combined_multiplier,
            )
        except Exception:
            pass

    return FarePreviewResult(
        origin_lat=origin_lat,
        origin_lon=origin_lon,
        dest_lat=dest_lat,
        dest_lon=dest_lon,
        distance_km=round(distance_km, 2),
        duration_min=round(duration_min, 1),
        route_source=route_source,
        surge_zone_multiplier=surge_zone_multiplier,
        surge_zone_name=surge_zone_name,
        surge_zone_description=surge_zone_description,
        demand_multiplier=demand_multiplier,
        demand_multiplier_cap=demand_cap,
        demand_count=demand_count,
        supply_count=supply_count,
        demand_explanation=demand_explanation,
        is_demand_elevated=is_demand_elevated,
        breakdown=breakdown,
        combined_multiplier=combined_multiplier,
        pricing_summary=pricing_summary,
        is_surge_active=is_surge_active,
    )
