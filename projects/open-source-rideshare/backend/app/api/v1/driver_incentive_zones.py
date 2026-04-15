"""Driver Incentive Zone endpoints.

Transparent "boost zones" — drivers see exactly where bonuses are available
and why.  Admins create and manage zones; drivers browse and track their
bonus earnings.

Driver endpoints:
  GET  /incentive-zones                        — list currently active zones
  GET  /incentive-zones/{zone_id}              — zone detail
  GET  /incentive-zones/my/completions         — driver's bonus history
  GET  /incentive-zones/my/summary             — driver's aggregate bonus stats

Admin endpoints:
  POST /incentive-zones/admin                  — create zone
  GET  /incentive-zones/admin/all              — list all zones (paginated)
  GET  /incentive-zones/admin/{zone_id}        — zone detail
  PUT  /incentive-zones/admin/{zone_id}        — update zone
  POST /incentive-zones/admin/{zone_id}/deactivate — end zone early
  POST /incentive-zones/admin/completions      — record zone completion bonus
  GET  /incentive-zones/admin/{zone_id}/stats  — zone performance stats
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.models.user import User
from app.schemas.driver_incentive_zone import (
    CreateIncentiveZoneRequest,
    DriverZoneEarningsSummary,
    IncentiveZoneResponse,
    RecordZoneCompletionRequest,
    UpdateIncentiveZoneRequest,
    ZoneCompletionResponse,
    ZoneStatsResponse,
)
from app.services import driver_incentive_zone as svc
from app.services.driver_incentive_zone import IncentiveZoneError

logger = logging.getLogger(__name__)

router = APIRouter(tags=["driver-incentive-zones"])


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _http(exc: IncentiveZoneError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.message)


# ---------------------------------------------------------------------------
# Driver routes
# ---------------------------------------------------------------------------


@router.get(
    "/incentive-zones",
    response_model=list[IncentiveZoneResponse],
    summary="List currently active incentive zones",
)
async def list_active_zones(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[IncentiveZoneResponse]:
    """Return all incentive zones currently within their active time window.

    Drivers use this to see where they should position for bonus earnings.
    The ``reason`` field explains the cooperative rationale for each zone —
    something Uber and Lyft never disclose.
    """
    zones = await svc.get_active_zones(db)
    return [IncentiveZoneResponse.from_zone(z) for z in zones]


@router.get(
    "/incentive-zones/my/completions",
    response_model=list[ZoneCompletionResponse],
    summary="Driver's incentive zone bonus history",
)
async def get_my_zone_completions(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ZoneCompletionResponse]:
    """Return the authenticated driver's earned zone bonuses, newest first."""
    from app.models.driver import DriverProfile

    from sqlalchemy import select as sa_select

    result = await db.execute(
        sa_select(DriverProfile).where(DriverProfile.user_id == current_user.id)
    )
    profile = result.scalar_one_or_none()
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Driver profile not found for this user",
        )
    completions = await svc.get_driver_completions(db, profile.id, skip=skip, limit=limit)
    return [ZoneCompletionResponse.from_completion(c) for c in completions]


@router.get(
    "/incentive-zones/my/summary",
    response_model=DriverZoneEarningsSummary,
    summary="Driver's aggregate incentive zone earnings",
)
async def get_my_zone_summary(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DriverZoneEarningsSummary:
    """Return lifetime incentive zone bonus totals for the authenticated driver."""
    from app.models.driver import DriverProfile

    from sqlalchemy import select as sa_select

    result = await db.execute(
        sa_select(DriverProfile).where(DriverProfile.user_id == current_user.id)
    )
    profile = result.scalar_one_or_none()
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Driver profile not found for this user",
        )
    return await svc.get_driver_zone_summary(db, profile.id)


@router.get(
    "/incentive-zones/{zone_id}",
    response_model=IncentiveZoneResponse,
    summary="Get incentive zone detail",
)
async def get_zone(
    zone_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> IncentiveZoneResponse:
    """Return details for a specific incentive zone."""
    zone = await svc.get_zone(db, zone_id)
    if zone is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Incentive zone not found",
        )
    return IncentiveZoneResponse.from_zone(zone)


# ---------------------------------------------------------------------------
# Admin routes
# ---------------------------------------------------------------------------


@router.post(
    "/incentive-zones/admin",
    response_model=IncentiveZoneResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create incentive zone (admin)",
)
async def admin_create_zone(
    body: CreateIncentiveZoneRequest,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> IncentiveZoneResponse:
    """Create a new driver incentive zone.

    Both polygon (≥3 {lat,lon} points) and circle (center_lat/lon + radius_km)
    geometries are supported.  The ``reason`` field is required — it's surfaced
    to drivers so they understand the cooperative's rationale.
    """
    zone = await svc.create_zone(db, body)
    return IncentiveZoneResponse.from_zone(zone)


@router.get(
    "/incentive-zones/admin/all",
    response_model=list[IncentiveZoneResponse],
    summary="List all incentive zones (admin)",
)
async def admin_list_all_zones(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> list[IncentiveZoneResponse]:
    """Return all incentive zones (active and expired), newest first."""
    zones = await svc.get_all_zones(db, skip=skip, limit=limit)
    return [IncentiveZoneResponse.from_zone(z) for z in zones]


@router.get(
    "/incentive-zones/admin/{zone_id}",
    response_model=IncentiveZoneResponse,
    summary="Get zone detail (admin)",
)
async def admin_get_zone(
    zone_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> IncentiveZoneResponse:
    """Return full zone detail including inactive zones."""
    zone = await svc.get_zone(db, zone_id)
    if zone is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Incentive zone not found",
        )
    return IncentiveZoneResponse.from_zone(zone)


@router.put(
    "/incentive-zones/admin/{zone_id}",
    response_model=IncentiveZoneResponse,
    summary="Update incentive zone (admin)",
)
async def admin_update_zone(
    zone_id: uuid.UUID,
    body: UpdateIncentiveZoneRequest,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> IncentiveZoneResponse:
    """Update zone fields.  Only supplied fields are changed."""
    try:
        zone = await svc.update_zone(db, zone_id, body)
    except IncentiveZoneError as exc:
        raise _http(exc)
    return IncentiveZoneResponse.from_zone(zone)


@router.post(
    "/incentive-zones/admin/{zone_id}/deactivate",
    response_model=IncentiveZoneResponse,
    summary="End an incentive zone early (admin)",
)
async def admin_deactivate_zone(
    zone_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> IncentiveZoneResponse:
    """Mark the zone as inactive immediately, stopping further bonus awards.

    Returns 404 if the zone doesn't exist.
    Returns 409 if already inactive.
    """
    try:
        zone = await svc.deactivate_zone(db, zone_id)
    except IncentiveZoneError as exc:
        raise _http(exc)
    return IncentiveZoneResponse.from_zone(zone)


@router.post(
    "/incentive-zones/admin/completions",
    response_model=ZoneCompletionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Record zone completion bonus (admin/internal)",
)
async def admin_record_completion(
    body: RecordZoneCompletionRequest,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> ZoneCompletionResponse:
    """Award an incentive zone bonus for a qualifying completed ride.

    Idempotent: calling twice for the same (zone_id, ride_id) returns the
    existing record without error.

    Returns 404 if the zone doesn't exist.
    Returns 409 if the zone has reached its total completion cap or the
    driver has hit their per-driver cap.
    """
    try:
        completion = await svc.record_zone_completion(
            db,
            zone_id=body.zone_id,
            driver_profile_id=body.driver_profile_id,
            ride_id=body.ride_id,
            bonus_amount_cents=body.bonus_amount_cents,
        )
    except IncentiveZoneError as exc:
        raise _http(exc)
    return ZoneCompletionResponse.from_completion(completion)


@router.get(
    "/incentive-zones/admin/{zone_id}/stats",
    response_model=ZoneStatsResponse,
    summary="Zone performance stats (admin)",
)
async def admin_zone_stats(
    zone_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> ZoneStatsResponse:
    """Return aggregate performance metrics for a single zone.

    Includes total completions, total bonus paid, unique drivers, and
    remaining capacity if a cap is configured.
    """
    try:
        return await svc.get_zone_stats(db, zone_id)
    except IncentiveZoneError as exc:
        raise _http(exc)
