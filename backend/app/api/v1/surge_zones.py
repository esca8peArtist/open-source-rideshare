"""Surge pricing zone API endpoints.

Admin endpoints (require admin auth):
  POST   /admin/surge-zones          — create zone
  GET    /admin/surge-zones          — list all zones
  GET    /admin/surge-zones/{id}     — get single zone
  PUT    /admin/surge-zones/{id}     — update zone
  DELETE /admin/surge-zones/{id}     — hard-delete zone
  POST   /admin/surge-zones/{id}/activate  — toggle active state

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
    SurgeZoneCreate,
    SurgeZoneListResponse,
    SurgeZonePublicListResponse,
    SurgeZonePublicResponse,
    SurgeZoneResponse,
    SurgeZoneUpdate,
    ToggleActiveRequest,
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
