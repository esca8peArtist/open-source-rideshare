"""Surge pricing zone API endpoints.

Admin endpoints (require admin auth):
  POST   /admin/surge-zones                    — create zone
  GET    /admin/surge-zones                    — list all zones
  GET    /admin/surge-zones/auto-tune          — preview multiplier recommendations
  POST   /admin/surge-zones/auto-tune/apply    — apply multiplier recommendations
  GET    /admin/surge-zones/suggestions        — propose new zone boundaries from heatmap clusters
  GET    /admin/surge-zones/{id}               — get single zone
  PUT    /admin/surge-zones/{id}               — update zone
  DELETE /admin/surge-zones/{id}               — hard-delete zone
  POST   /admin/surge-zones/{id}/activate      — toggle active state

Public endpoint (no auth required):
  GET /pricing/surge-zones/active    — currently active zones for map display
"""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
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
from app.schemas.surge_zone_autotune import (
    AutoTuneApplyRequest,
    AutoTuneApplyResponse,
    AutoTunePreviewResponse,
)
from app.schemas.surge_zone_suggestions import ZoneSuggestionsResponse
from app.services.surge_zone_autotune import (
    apply_auto_tune_recommendations,
    compute_auto_tune_recommendations,
)
from app.services.surge_zone_suggestions import get_zone_boundary_suggestions
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


# ---------------------------------------------------------------------------
# Auto-tune endpoints
# NOTE: These literal-path routes must appear before the /{zone_id} parameter
# route so FastAPI resolves "auto-tune" as a path literal, not a UUID.
# ---------------------------------------------------------------------------


@admin_router.get("/auto-tune", response_model=AutoTunePreviewResponse)
async def preview_auto_tune(
    lookback_days: int = 30,
    min_sample_size: int = 10,
    db: AsyncSession = Depends(get_db),
):
    """Preview surge zone multiplier recommendations based on historical demand.

    Analyses the last ``lookback_days`` days of hourly ride volume and
    computes a suggested multiplier for each active zone. This is a read-only
    preview — no changes are written to the database.

    Zones with fewer than ``min_sample_size`` rides during their active window
    receive an ``insufficient_data`` recommendation and are left unchanged.
    """
    return await compute_auto_tune_recommendations(
        db, lookback_days=lookback_days, min_sample_size=min_sample_size
    )


@admin_router.post("/auto-tune/apply", response_model=AutoTuneApplyResponse)
async def apply_auto_tune(
    body: AutoTuneApplyRequest,
    lookback_days: int = 30,
    min_sample_size: int = 10,
    db: AsyncSession = Depends(get_db),
):
    """Apply auto-tune multiplier recommendations to active surge zones.

    Recomputes the same recommendations as the preview endpoint and then
    writes the ``increase`` / ``decrease`` changes to the database.

    Pass a list of ``zone_ids`` in the request body to selectively apply
    recommendations. Omit ``zone_ids`` (or pass ``null``) to apply all
    actionable recommendations.

    Zones with ``no_change`` or ``insufficient_data`` recommendations are
    always skipped, even if their IDs appear in ``zone_ids``.
    """
    return await apply_auto_tune_recommendations(
        db,
        zone_ids=body.zone_ids,
        lookback_days=lookback_days,
        min_sample_size=min_sample_size,
    )


@admin_router.get("/suggestions", response_model=ZoneSuggestionsResponse)
async def get_zone_suggestions(
    start_date: date | None = Query(
        None, description="Inclusive start date filter (YYYY-MM-DD) on ride requested_at"
    ),
    end_date: date | None = Query(
        None, description="Inclusive end date filter (YYYY-MM-DD) on ride requested_at"
    ),
    min_activity: int = Query(
        5, ge=1, description="Minimum total activity (pickups + dropoffs) for a heatmap cell to be clustered"
    ),
    precision: int = Query(
        2, ge=1, le=4, description="Heatmap grid precision (1–4 decimal places; default 2 ≈ 1.1 km cells)"
    ),
    cluster_radius_km: float = Query(
        2.0, gt=0.0, description="Maximum km between two cells to be considered neighbours in the same cluster"
    ),
    min_cells: int = Query(
        2, ge=1, description="Minimum heatmap cells a cluster must have to produce a suggestion"
    ),
    max_suggestions: int = Query(
        10, ge=1, le=50, description="Maximum number of zone suggestions to return"
    ),
    db: AsyncSession = Depends(get_db),
) -> ZoneSuggestionsResponse:
    """Propose new surge zone boundaries derived from heatmap demand clusters.

    Analyses trip heatmap data to identify geographic clusters of high
    pickup/dropoff activity and suggests circle-shaped zone boundaries that
    an admin can review and apply via the zone creation endpoint.

    Each suggestion includes:
    - Activity-weighted centroid (center_lat / center_lon)
    - Suggested radius that covers all cluster cells
    - Suggested starting multiplier scaled by demand density
    - Confidence score relative to the busiest cluster
    - Overlap flag if the centroid falls inside an existing active zone

    This is a read-only preview — no zones are created or modified.
    """
    if start_date is not None and end_date is not None and end_date < start_date:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="end_date must be on or after start_date",
        )
    return await get_zone_boundary_suggestions(
        db,
        start_date=start_date,
        end_date=end_date,
        min_activity=min_activity,
        precision=precision,
        cluster_radius_km=cluster_radius_km,
        min_cells=min_cells,
        max_suggestions=max_suggestions,
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
