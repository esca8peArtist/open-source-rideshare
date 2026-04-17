"""Surge pricing zone API endpoints.

Admin endpoints (require admin auth):
  POST   /admin/surge-zones          — create zone
  GET    /admin/surge-zones          — list all zones
  GET    /admin/surge-zones/{id}     — get single zone
  PUT    /admin/surge-zones/{id}     — update zone
  DELETE /admin/surge-zones/{id}     — hard-delete zone
  POST   /admin/surge-zones/{id}/activate  — toggle active state

Admin analytics endpoints (require admin auth):
  GET /admin/surge-analytics/summary        — platform-level surge stats
  GET /admin/surge-analytics/zones          — per-zone breakdown
  GET /admin/surge-analytics/demand-heatmap — geohash surge frequency heatmap

Public endpoint (no auth required):
  GET /pricing/surge-zones/active    — currently active zones for map display
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin
from app.db.database import get_db
from app.schemas.surge_zone import (
    DemandHeatmapCellResponse,
    DemandHeatmapResponse,
    SurgeSummaryResponse,
    SurgeZoneCreate,
    SurgeZoneListResponse,
    SurgeZonePublicListResponse,
    SurgeZonePublicResponse,
    SurgeZoneResponse,
    SurgeZoneUpdate,
    ToggleActiveRequest,
    ZoneAnalyticsResponse,
    ZoneBreakdownResponse,
)
from app.services.surge_analytics import (
    get_demand_heatmap,
    get_surge_summary,
    get_zone_breakdown,
)
from app.services.surge_zones import (
    create_zone,
    delete_zone,
    get_zone,
    list_zones,
    is_zone_active_now,
    toggle_zone_active,
    update_zone,
)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

admin_router = APIRouter(
    prefix="/admin/surge-zones",
    tags=["admin", "surge-zones"],
    dependencies=[Depends(require_admin)],
)

admin_analytics_router = APIRouter(
    prefix="/admin/surge-analytics",
    tags=["admin", "surge-analytics"],
    dependencies=[Depends(require_admin)],
)

public_router = APIRouter(
    prefix="/pricing",
    tags=["pricing"],
)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _zone_to_response(zone) -> SurgeZoneResponse:
    return SurgeZoneResponse(
        id=zone.id,
        name=zone.name,
        description=zone.description,
        polygon=zone.polygon,
        center_lat=zone.center_lat,
        center_lon=zone.center_lon,
        radius_km=zone.radius_km,
        multiplier=zone.multiplier,
        is_active=zone.is_active,
        start_time=zone.start_time,
        end_time=zone.end_time,
        days_of_week=zone.days_of_week,
        created_at=zone.created_at,
        updated_at=zone.updated_at,
    )


# ---------------------------------------------------------------------------
# Admin CRUD
# ---------------------------------------------------------------------------


@admin_router.post("", response_model=SurgeZoneResponse, status_code=status.HTTP_201_CREATED)
async def create_surge_zone(
    body: SurgeZoneCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a new surge pricing zone.

    A zone must define at least one geographic constraint: either a polygon
    (list of lat/lon points) or a center + radius_km for a circular zone.
    """
    if body.polygon is None and (
        body.center_lat is None or body.center_lon is None or body.radius_km is None
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A zone must define either polygon or center_lat/center_lon/radius_km.",
        )
    zone = await create_zone(
        db=db,
        name=body.name,
        description=body.description,
        polygon=body.polygon,
        center_lat=body.center_lat,
        center_lon=body.center_lon,
        radius_km=body.radius_km,
        multiplier=body.multiplier,
        is_active=body.is_active,
        start_time=body.start_time,
        end_time=body.end_time,
        days_of_week=body.days_of_week,
    )
    return _zone_to_response(zone)


@admin_router.get("", response_model=SurgeZoneListResponse)
async def list_surge_zones(
    active_only: bool = False,
    db: AsyncSession = Depends(get_db),
):
    """List all surge pricing zones. Pass ``active_only=true`` to filter."""
    zones = await list_zones(db, active_only=active_only)
    return SurgeZoneListResponse(
        zones=[_zone_to_response(z) for z in zones],
        total=len(zones),
    )


@admin_router.get("/{zone_id}", response_model=SurgeZoneResponse)
async def get_surge_zone(
    zone_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get a single surge pricing zone by ID."""
    zone = await get_zone(db, zone_id)
    if zone is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Surge zone not found")
    return _zone_to_response(zone)


@admin_router.put("/{zone_id}", response_model=SurgeZoneResponse)
async def update_surge_zone(
    zone_id: uuid.UUID,
    body: SurgeZoneUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update an existing surge pricing zone. Only supplied fields are changed."""
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    zone = await update_zone(db, zone_id, **updates)
    if zone is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Surge zone not found")
    return _zone_to_response(zone)


@admin_router.delete("/{zone_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_surge_zone(
    zone_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Hard-delete a surge pricing zone."""
    deleted = await delete_zone(db, zone_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Surge zone not found")


@admin_router.post("/{zone_id}/activate", response_model=SurgeZoneResponse)
async def activate_surge_zone(
    zone_id: uuid.UUID,
    body: ToggleActiveRequest,
    db: AsyncSession = Depends(get_db),
):
    """Activate or deactivate a surge pricing zone."""
    zone = await toggle_zone_active(db, zone_id, body.is_active)
    if zone is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Surge zone not found")
    return _zone_to_response(zone)


# ---------------------------------------------------------------------------
# Admin analytics endpoints
# ---------------------------------------------------------------------------


@admin_analytics_router.get("/summary", response_model=SurgeSummaryResponse)
async def surge_analytics_summary(
    days: int = 7,
    db: AsyncSession = Depends(get_db),
):
    """Platform-level surge pricing statistics for the last N days.

    Returns total event counts by type (zone-only, demand-only, combined),
    average combined multiplier, peak surge hour (UTC), and top zone by volume.
    """
    if days < 1 or days > 365:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="days must be between 1 and 365",
        )
    summary = await get_surge_summary(db, days=days)
    return SurgeSummaryResponse(
        period_days=summary.period_days,
        total_surge_events=summary.total_surge_events,
        zone_surge_events=summary.zone_surge_events,
        demand_surge_events=summary.demand_surge_events,
        combined_surge_events=summary.combined_surge_events,
        avg_combined_multiplier=summary.avg_combined_multiplier,
        peak_hour=summary.peak_hour,
        top_zone_name=summary.top_zone_name,
        top_zone_event_count=summary.top_zone_event_count,
    )


@admin_analytics_router.get("/zones", response_model=ZoneBreakdownResponse)
async def surge_analytics_zones(
    days: int = 30,
    db: AsyncSession = Depends(get_db),
):
    """Per-zone surge analytics for the last N days.

    Shows event count, average zone multiplier, and average supply/demand
    per zone — ordered by event count descending. Useful for identifying
    which zones generate the most surge activity.
    """
    if days < 1 or days > 365:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="days must be between 1 and 365",
        )
    zones = await get_zone_breakdown(db, days=days)
    return ZoneBreakdownResponse(
        period_days=days,
        zones=[
            ZoneAnalyticsResponse(
                zone_id=z.zone_id,
                zone_name=z.zone_name,
                event_count=z.event_count,
                avg_multiplier=z.avg_multiplier,
                avg_demand_count=z.avg_demand_count,
                avg_supply_count=z.avg_supply_count,
            )
            for z in zones
        ],
        total_zones=len(zones),
    )


@admin_analytics_router.get("/demand-heatmap", response_model=DemandHeatmapResponse)
async def surge_analytics_demand_heatmap(
    days: int = 7,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    """Geohash cells ranked by surge event frequency for the last N days.

    Each cell is a ~4.9km × 4.9km area. High-event cells are the geographic
    hotspots where demand pricing most often fires. Useful for deciding where
    to create or expand admin surge zones.
    """
    if days < 1 or days > 365:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="days must be between 1 and 365",
        )
    if limit < 1 or limit > 200:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="limit must be between 1 and 200",
        )
    cells = await get_demand_heatmap(db, days=days, limit=limit)
    return DemandHeatmapResponse(
        period_days=days,
        cells=[
            DemandHeatmapCellResponse(
                geohash=c.geohash,
                event_count=c.event_count,
                avg_combined_multiplier=c.avg_combined_multiplier,
            )
            for c in cells
        ],
        total_cells=len(cells),
    )


# ---------------------------------------------------------------------------
# Public endpoint
# ---------------------------------------------------------------------------


@public_router.get("/surge-zones/active", response_model=SurgeZonePublicListResponse)
async def get_active_surge_zones(db: AsyncSession = Depends(get_db)):
    """Return all currently active surge zones for map display.

    No authentication required — this is public information shown to riders
    before they request a ride so they can make informed decisions.
    """
    zones = await list_zones(db, active_only=True)
    active_now = [z for z in zones if is_zone_active_now(z)]
    return SurgeZonePublicListResponse(
        zones=[
            SurgeZonePublicResponse(
                id=z.id,
                name=z.name,
                description=z.description,
                polygon=z.polygon,
                center_lat=z.center_lat,
                center_lon=z.center_lon,
                radius_km=z.radius_km,
                multiplier=z.multiplier,
            )
            for z in active_now
        ],
        total=len(active_now),
    )
