"""Corporate Service Zone endpoints.

Corporate admins define named circular geographic zones that gate or restrict
employee ride bookings.  Zone types:
  - allowed           — explicitly permitted area
  - restricted        — bookings blocked when pickup/dropoff falls inside
  - approval_required — booking requires admin approval when inside the zone

Member endpoints (any active member):
  GET  /corporate/accounts/me/service-zones                         — list zones
  GET  /corporate/accounts/me/service-zones/summary                 — coverage summary
  GET  /corporate/accounts/me/service-zones/{zone_id}               — get zone
  POST /corporate/accounts/me/service-zones/check                   — check ride coords

Admin endpoints (account admins only):
  POST   /corporate/accounts/me/service-zones                       — create zone
  PATCH  /corporate/accounts/me/service-zones/{zone_id}             — update zone
  POST   /corporate/accounts/me/service-zones/{zone_id}/deactivate
  POST   /corporate/accounts/me/service-zones/{zone_id}/reactivate
  DELETE /corporate/accounts/me/service-zones/{zone_id}             — delete zone

Platform-admin endpoints:
  GET /platform/corporate/service-zones                             — all zones
  GET /platform/corporate/accounts/{account_id}/service-zones       — account zones
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.models.corporate_service_zone import ZoneType
from app.models.user import User
from app.schemas.corporate_service_zone import (
    ServiceZoneCreate,
    ServiceZoneListResponse,
    ServiceZoneResponse,
    ServiceZoneUpdate,
    ZoneCheckRequest,
    ZoneCheckResponse,
    ZoneCoverageSummary,
)
from app.services.corporate_account_mgmt import get_user_account
from app.services.corporate_service_zone import (
    check_ride_zones,
    create_service_zone,
    deactivate_service_zone,
    delete_service_zone,
    get_service_zone,
    get_zone_coverage_summary,
    list_all_platform,
    list_service_zones,
    reactivate_service_zone,
    update_service_zone,
)
from app.services.corporate_trip_purpose import _require_account_admin

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Corporate Service Zones"])


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------


async def _resolve_account_id(db: AsyncSession, user_id: int) -> int:
    """Return the account_id for the authenticated user.

    Raises HTTP 404 if the user is not a member of any corporate account.
    """
    account = await get_user_account(db, user_id)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="You are not a member of any corporate account.",
        )
    return account.id


# ---------------------------------------------------------------------------
# Member: list zones
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/service-zones",
    response_model=ServiceZoneListResponse,
    summary="List corporate service zones for own account",
)
async def list_my_service_zones(
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    zone_type: Optional[ZoneType] = Query(
        None, description="Filter by zone type: allowed / restricted / approval_required"
    ),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all corporate service zones for the authenticated user's account.

    Optionally filter by active status and/or zone type.  Any active member
    may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    return await list_service_zones(
        db, account_id, is_active=is_active, zone_type=zone_type
    )


# ---------------------------------------------------------------------------
# Member: coverage summary (must appear before /{zone_id} to avoid conflict)
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/service-zones/summary",
    response_model=ZoneCoverageSummary,
    summary="Get service zone coverage summary for own account",
)
async def get_my_zone_coverage_summary(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a count breakdown of active zones by type and applies_to.

    Any active member may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    return await get_zone_coverage_summary(db, account_id)


# ---------------------------------------------------------------------------
# Member: get zone
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/service-zones/{zone_id}",
    response_model=ServiceZoneResponse,
    summary="Get a corporate service zone",
)
async def get_my_service_zone(
    zone_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a single service zone by ID.

    Any active member may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    return await get_service_zone(db, zone_id, account_id)


# ---------------------------------------------------------------------------
# Member: check ride coordinates against zones
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/accounts/me/service-zones/check",
    response_model=ZoneCheckResponse,
    summary="Check whether ride pickup/dropoff fall within any service zones",
)
async def check_my_ride_zones(
    data: ZoneCheckRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Evaluate pickup and dropoff coordinates against all active service zones.

    Returns matched zones per endpoint, plus ``is_restricted`` and
    ``requires_approval`` flags.  Any active member may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    return await check_ride_zones(db, account_id, data)


# ---------------------------------------------------------------------------
# Admin: create zone
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/accounts/me/service-zones",
    response_model=ServiceZoneResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a corporate service zone (admin only)",
)
async def create_my_service_zone(
    data: ServiceZoneCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new service zone for the account.

    Returns 409 if a zone with the same name already exists.
    Only account admins may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    return await create_service_zone(
        db, account_id, created_by_id=user.id, data=data
    )


# ---------------------------------------------------------------------------
# Admin: update zone
# ---------------------------------------------------------------------------


@router.patch(
    "/corporate/accounts/me/service-zones/{zone_id}",
    response_model=ServiceZoneResponse,
    summary="Update a corporate service zone (admin only)",
)
async def update_my_service_zone(
    zone_id: int,
    data: ServiceZoneUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Partially update a service zone.

    Only supplied fields are written; unset fields are left unchanged.
    Returns 409 if the new name collides with an existing zone.
    Only account admins may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    return await update_service_zone(db, zone_id, account_id, data)


# ---------------------------------------------------------------------------
# Admin: deactivate zone
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/accounts/me/service-zones/{zone_id}/deactivate",
    response_model=ServiceZoneResponse,
    summary="Deactivate a corporate service zone (admin only)",
)
async def deactivate_my_service_zone(
    zone_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Soft-deactivate a service zone.

    Returns 409 if the zone is already inactive.
    Only account admins may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    return await deactivate_service_zone(db, zone_id, account_id)


# ---------------------------------------------------------------------------
# Admin: reactivate zone
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/accounts/me/service-zones/{zone_id}/reactivate",
    response_model=ServiceZoneResponse,
    summary="Reactivate a corporate service zone (admin only)",
)
async def reactivate_my_service_zone(
    zone_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Reactivate a previously deactivated service zone.

    Returns 409 if the zone is already active.
    Only account admins may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    return await reactivate_service_zone(db, zone_id, account_id)


# ---------------------------------------------------------------------------
# Admin: delete zone
# ---------------------------------------------------------------------------


@router.delete(
    "/corporate/accounts/me/service-zones/{zone_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a corporate service zone (admin only)",
)
async def delete_my_service_zone(
    zone_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Hard-delete a service zone.

    Returns 404 if the zone does not exist.
    Only account admins may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    await delete_service_zone(db, zone_id, account_id)


# ---------------------------------------------------------------------------
# Platform-admin: list all zones
# ---------------------------------------------------------------------------


@router.get(
    "/platform/corporate/service-zones",
    response_model=ServiceZoneListResponse,
    summary="Admin: list all corporate service zones",
)
async def admin_list_all_service_zones(
    account_id: Optional[int] = Query(None, description="Filter by account ID"),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return all corporate service zones across all accounts.

    Optionally filter by account_id.  Platform admin only.
    """
    return await list_all_platform(db, account_id=account_id)


# ---------------------------------------------------------------------------
# Platform-admin: list zones for a specific account
# ---------------------------------------------------------------------------


@router.get(
    "/platform/corporate/accounts/{account_id}/service-zones",
    response_model=ServiceZoneListResponse,
    summary="Admin: list corporate service zones for a specific account",
)
async def admin_list_account_service_zones(
    account_id: int,
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    zone_type: Optional[ZoneType] = Query(
        None, description="Filter by zone type"
    ),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return all corporate service zones for any account.

    Platform admin only.
    """
    return await list_service_zones(
        db, account_id, is_active=is_active, zone_type=zone_type
    )
