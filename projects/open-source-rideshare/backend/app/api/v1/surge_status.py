"""Lightweight surge status endpoint — rider-facing pickup location check.

Public endpoint (no authentication required):
  GET /surge/current    — is surge active at this location right now?

Cheaper than fare-preview: no routing, no fare math. Just checks whether
the rider's pickup point is currently in a surge zone or experiencing
elevated demand. Used by the rider app to show a "SURGE PRICING IN EFFECT"
banner before the rider enters a destination.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.services.demand_pricing import get_demand_info
from app.services.surge_zones import _point_in_zone, is_zone_active_now, list_zones

router = APIRouter(prefix="/surge", tags=["pricing"])


class SurgeStatusResponse(BaseModel):
    is_surge_active: bool
    zone_multiplier: float
    demand_multiplier: float
    combined_multiplier: float
    zone_name: str | None
    message: str


async def _get_zone_multiplier(db: AsyncSession, lat: float, lon: float) -> tuple[float, str | None]:
    """Return (best_multiplier, zone_name) for the given point, or (1.0, None)."""
    try:
        zones = await list_zones(db, active_only=True)
        best = 1.0
        best_name: str | None = None
        for zone in zones:
            if not is_zone_active_now(zone):
                continue
            if _point_in_zone(lat, lon, zone):
                if zone.multiplier > best:
                    best = zone.multiplier
                    best_name = zone.name
        return best, best_name
    except Exception:
        return 1.0, None


@router.get("/current", response_model=SurgeStatusResponse)
async def surge_current_status(
    lat: float = Query(..., ge=-90.0, le=90.0, description="Pickup latitude"),
    lng: float = Query(..., ge=-180.0, le=180.0, description="Pickup longitude"),
    db: AsyncSession = Depends(get_db),
):
    """Check whether surge pricing is active at a pickup location.

    No authentication required — riders check this before entering a destination.

    Returns a lightweight status object: active/inactive flag, the zone and
    demand multipliers independently, and a short plain-English message.

    Falls back gracefully: if the DB or Redis are unavailable, returns
    standard pricing (multiplier 1.0) rather than erroring.
    """
    try:
        from app.services.matching import get_redis
        redis_client = await get_redis()
    except Exception:
        redis_client = None

    zone_multiplier, zone_name = await _get_zone_multiplier(db, lat, lng)

    demand_multiplier = 1.0
    is_demand_elevated = False
    if redis_client is not None:
        try:
            di = await get_demand_info(redis_client, lat, lng)
            demand_multiplier = di.multiplier
            is_demand_elevated = di.is_elevated
        except Exception:
            pass

    combined = round(zone_multiplier * demand_multiplier, 3)
    is_active = zone_multiplier > 1.0 or is_demand_elevated

    if not is_active:
        message = "Standard pricing — no surge active at your pickup location."
    else:
        parts: list[str] = []
        if zone_multiplier > 1.0 and zone_name:
            pct = round((zone_multiplier - 1.0) * 100)
            parts.append(f"{zone_name} zone (+{pct}%)")
        if is_demand_elevated:
            pct = round((demand_multiplier - 1.0) * 100)
            parts.append(f"high demand (+{pct}%)")
        total_pct = round((combined - 1.0) * 100)
        message = f"Surge pricing active: {total_pct}% above standard. Reasons: {'; '.join(parts)}."

    return SurgeStatusResponse(
        is_surge_active=is_active,
        zone_multiplier=zone_multiplier,
        demand_multiplier=demand_multiplier,
        combined_multiplier=combined,
        zone_name=zone_name,
        message=message,
    )
