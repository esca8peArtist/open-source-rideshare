"""Service layer for Corporate Service Zones.

Corporate accounts define named circular geographic zones that gate or restrict
ride bookings.  The service layer handles zone CRUD, the Haversine distance
check used to evaluate ride pickup/dropoff points against active zones, and
platform-admin helpers.

Public surface
--------------
create_service_zone(db, account_id, created_by_id, data) -> ServiceZoneResponse
get_service_zone(db, zone_id, account_id) -> ServiceZoneResponse
list_service_zones(db, account_id, is_active, zone_type) -> ServiceZoneListResponse
update_service_zone(db, zone_id, account_id, data) -> ServiceZoneResponse
deactivate_service_zone(db, zone_id, account_id) -> ServiceZoneResponse
reactivate_service_zone(db, zone_id, account_id) -> ServiceZoneResponse
delete_service_zone(db, zone_id, account_id) -> None
check_ride_zones(db, account_id, request, member_group_ids) -> ZoneCheckResponse
get_zone_coverage_summary(db, account_id) -> ZoneCoverageSummary
list_all_platform(db, account_id) -> ServiceZoneListResponse
"""

from __future__ import annotations

import math
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.corporate_service_zone import (
    CorporateServiceZone,
    ZoneAppliesTo,
    ZoneType,
)
from app.schemas.corporate_service_zone import (
    ServiceZoneCreate,
    ServiceZoneListResponse,
    ServiceZoneResponse,
    ServiceZoneUpdate,
    ZoneCheckRequest,
    ZoneCheckResponse,
    ZoneCoverageSummary,
    ZoneMatchDetail,
)


# ---------------------------------------------------------------------------
# Haversine helper
# ---------------------------------------------------------------------------


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return the great-circle distance in km between two lat/lng points."""
    R = 6371.0  # Earth's mean radius in km
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _to_response(zone: CorporateServiceZone) -> ServiceZoneResponse:
    """Convert a CorporateServiceZone ORM instance to ServiceZoneResponse."""
    return ServiceZoneResponse(
        id=zone.id,
        account_id=zone.account_id,
        created_by_id=zone.created_by_id,
        name=zone.name,
        description=zone.description,
        zone_type=zone.zone_type,
        center_latitude=float(zone.center_latitude),
        center_longitude=float(zone.center_longitude),
        radius_km=float(zone.radius_km),
        applies_to=zone.applies_to,
        group_ids=zone.group_ids,
        is_active=zone.is_active,
        created_at=zone.created_at,
        updated_at=zone.updated_at,
    )


async def _get_zone_or_404(
    db: AsyncSession, zone_id: int, account_id: int
) -> CorporateServiceZone:
    """Fetch a zone by ID scoped to the account; raise 404 if not found."""
    result = await db.execute(
        select(CorporateServiceZone).where(
            CorporateServiceZone.id == zone_id,
            CorporateServiceZone.account_id == account_id,
        )
    )
    zone = result.scalar_one_or_none()
    if zone is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Service zone not found.",
        )
    return zone


async def _check_name_conflict(
    db: AsyncSession,
    account_id: int,
    name: str,
    exclude_id: Optional[int] = None,
) -> None:
    """Raise 409 if another zone with the same name already exists in the account."""
    stmt = select(CorporateServiceZone).where(
        CorporateServiceZone.account_id == account_id,
        CorporateServiceZone.name == name,
    )
    if exclude_id is not None:
        stmt = stmt.where(CorporateServiceZone.id != exclude_id)
    result = await db.execute(stmt)
    if result.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A service zone named '{name}' already exists for this account.",
        )


def _zone_applies_to_member(
    zone: CorporateServiceZone,
    member_group_ids: Optional[list[int]],
) -> bool:
    """Return True if the zone applies to the member based on group_ids.

    If the zone has no group_ids restriction (NULL), it applies to everyone.
    If group_ids is set, the member must belong to at least one listed group.
    """
    if zone.group_ids is None:
        return True
    if not member_group_ids:
        return False
    return bool(set(zone.group_ids) & set(member_group_ids))


# ---------------------------------------------------------------------------
# Public service functions
# ---------------------------------------------------------------------------


async def create_service_zone(
    db: AsyncSession,
    account_id: int,
    created_by_id: Optional[int],
    data: ServiceZoneCreate,
) -> ServiceZoneResponse:
    """Create a new corporate service zone.

    Raises 409 if a zone with the same name already exists in the account.
    """
    await _check_name_conflict(db, account_id, data.name)

    zone = CorporateServiceZone(
        account_id=account_id,
        created_by_id=created_by_id,
        name=data.name,
        description=data.description,
        zone_type=data.zone_type,
        center_latitude=data.center_latitude,
        center_longitude=data.center_longitude,
        radius_km=data.radius_km,
        applies_to=data.applies_to,
        group_ids=data.group_ids,
        is_active=True,
    )
    db.add(zone)
    await db.commit()
    await db.refresh(zone)
    return _to_response(zone)


async def get_service_zone(
    db: AsyncSession,
    zone_id: int,
    account_id: int,
) -> ServiceZoneResponse:
    """Return a single service zone by ID, scoped to the account."""
    zone = await _get_zone_or_404(db, zone_id, account_id)
    return _to_response(zone)


async def list_service_zones(
    db: AsyncSession,
    account_id: int,
    is_active: Optional[bool] = None,
    zone_type: Optional[ZoneType] = None,
) -> ServiceZoneListResponse:
    """Return service zones for an account, optionally filtered by status/type."""
    stmt = select(CorporateServiceZone).where(
        CorporateServiceZone.account_id == account_id
    )
    if is_active is not None:
        stmt = stmt.where(CorporateServiceZone.is_active == is_active)
    if zone_type is not None:
        stmt = stmt.where(CorporateServiceZone.zone_type == zone_type)
    stmt = stmt.order_by(CorporateServiceZone.name)

    result = await db.execute(stmt)
    zones = result.scalars().all()
    return ServiceZoneListResponse(
        items=[_to_response(z) for z in zones],
        total=len(zones),
    )


async def update_service_zone(
    db: AsyncSession,
    zone_id: int,
    account_id: int,
    data: ServiceZoneUpdate,
) -> ServiceZoneResponse:
    """Partially update a service zone.

    Only fields explicitly supplied in the request body are written.
    Raises 409 on name collision with another zone in the same account.
    """
    zone = await _get_zone_or_404(db, zone_id, account_id)

    update_data = data.model_dump(exclude_unset=True)

    if "name" in update_data and update_data["name"] != zone.name:
        await _check_name_conflict(
            db, account_id, update_data["name"], exclude_id=zone_id
        )

    for field, value in update_data.items():
        setattr(zone, field, value)

    await db.commit()
    await db.refresh(zone)
    return _to_response(zone)


async def deactivate_service_zone(
    db: AsyncSession,
    zone_id: int,
    account_id: int,
) -> ServiceZoneResponse:
    """Soft-deactivate a service zone.

    Raises 409 if the zone is already inactive.
    """
    zone = await _get_zone_or_404(db, zone_id, account_id)
    if not zone.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Service zone is already inactive.",
        )
    zone.is_active = False
    await db.commit()
    await db.refresh(zone)
    return _to_response(zone)


async def reactivate_service_zone(
    db: AsyncSession,
    zone_id: int,
    account_id: int,
) -> ServiceZoneResponse:
    """Reactivate an inactive service zone.

    Raises 409 if the zone is already active.
    """
    zone = await _get_zone_or_404(db, zone_id, account_id)
    if zone.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Service zone is already active.",
        )
    zone.is_active = True
    await db.commit()
    await db.refresh(zone)
    return _to_response(zone)


async def delete_service_zone(
    db: AsyncSession,
    zone_id: int,
    account_id: int,
) -> None:
    """Hard-delete a service zone.

    Raises 404 if the zone does not exist in the account.
    """
    zone = await _get_zone_or_404(db, zone_id, account_id)
    await db.delete(zone)
    await db.commit()


async def check_ride_zones(
    db: AsyncSession,
    account_id: int,
    request: ZoneCheckRequest,
) -> ZoneCheckResponse:
    """Check whether a ride's pickup/dropoff points fall within any active zones.

    Loads all active zones for the account, filters by member group membership,
    then evaluates each zone against the pickup and dropoff coordinates using
    the Haversine formula.

    Returns a structured response with matched zones per endpoint, an
    ``is_restricted`` flag (any restricted zone applies), a ``requires_approval``
    flag (any approval_required zone applies and the ride is not already
    blocked), and human-readable ``denial_reasons``.
    """
    result = await db.execute(
        select(CorporateServiceZone).where(
            CorporateServiceZone.account_id == account_id,
            CorporateServiceZone.is_active == True,  # noqa: E712
        )
    )
    zones = result.scalars().all()

    pickup_lat = request.pickup_latitude
    pickup_lon = request.pickup_longitude
    dropoff_lat = request.dropoff_latitude
    dropoff_lon = request.dropoff_longitude
    member_groups = request.member_group_ids

    pickup_matches: list[ZoneMatchDetail] = []
    dropoff_matches: list[ZoneMatchDetail] = []

    for zone in zones:
        if not _zone_applies_to_member(zone, member_groups):
            continue

        clat = float(zone.center_latitude)
        clon = float(zone.center_longitude)
        radius = float(zone.radius_km)

        check_pickup = zone.applies_to in (ZoneAppliesTo.pickup, ZoneAppliesTo.both)
        check_dropoff = zone.applies_to in (ZoneAppliesTo.dropoff, ZoneAppliesTo.both)

        if check_pickup:
            dist = _haversine_km(pickup_lat, pickup_lon, clat, clon)
            if dist <= radius:
                pickup_matches.append(
                    ZoneMatchDetail(
                        zone_id=zone.id,
                        zone_name=zone.name,
                        zone_type=zone.zone_type,
                        applies_to=zone.applies_to,
                        distance_km=round(dist, 3),
                        radius_km=radius,
                    )
                )

        if check_dropoff:
            dist = _haversine_km(dropoff_lat, dropoff_lon, clat, clon)
            if dist <= radius:
                dropoff_matches.append(
                    ZoneMatchDetail(
                        zone_id=zone.id,
                        zone_name=zone.name,
                        zone_type=zone.zone_type,
                        applies_to=zone.applies_to,
                        distance_km=round(dist, 3),
                        radius_km=radius,
                    )
                )

    all_matches = pickup_matches + dropoff_matches
    is_restricted = any(m.zone_type == ZoneType.restricted for m in all_matches)
    requires_approval = (
        not is_restricted
        and any(m.zone_type == ZoneType.approval_required for m in all_matches)
    )

    denial_reasons: list[str] = []
    if is_restricted:
        restricted_names = sorted(
            {m.zone_name for m in all_matches if m.zone_type == ZoneType.restricted}
        )
        denial_reasons.append(
            f"Ride location falls within restricted zone(s): {', '.join(restricted_names)}."
        )

    return ZoneCheckResponse(
        pickup_matches=pickup_matches,
        dropoff_matches=dropoff_matches,
        is_restricted=is_restricted,
        requires_approval=requires_approval,
        denial_reasons=denial_reasons,
    )


async def get_zone_coverage_summary(
    db: AsyncSession,
    account_id: int,
) -> ZoneCoverageSummary:
    """Return a count breakdown of active zones by type and applies_to for the account."""
    result = await db.execute(
        select(CorporateServiceZone).where(
            CorporateServiceZone.account_id == account_id,
            CorporateServiceZone.is_active == True,  # noqa: E712
        )
    )
    zones = result.scalars().all()

    allowed_count = sum(1 for z in zones if z.zone_type == ZoneType.allowed)
    restricted_count = sum(1 for z in zones if z.zone_type == ZoneType.restricted)
    approval_required_count = sum(
        1 for z in zones if z.zone_type == ZoneType.approval_required
    )
    pickup_only_count = sum(1 for z in zones if z.applies_to == ZoneAppliesTo.pickup)
    dropoff_only_count = sum(
        1 for z in zones if z.applies_to == ZoneAppliesTo.dropoff
    )
    both_count = sum(1 for z in zones if z.applies_to == ZoneAppliesTo.both)

    return ZoneCoverageSummary(
        total_active_zones=len(zones),
        allowed_count=allowed_count,
        restricted_count=restricted_count,
        approval_required_count=approval_required_count,
        pickup_only_count=pickup_only_count,
        dropoff_only_count=dropoff_only_count,
        both_count=both_count,
    )


async def list_all_platform(
    db: AsyncSession,
    account_id: Optional[int] = None,
) -> ServiceZoneListResponse:
    """Platform-admin: list all service zones, optionally filtered by account."""
    stmt = select(CorporateServiceZone)
    if account_id is not None:
        stmt = stmt.where(CorporateServiceZone.account_id == account_id)
    stmt = stmt.order_by(
        CorporateServiceZone.account_id, CorporateServiceZone.name
    )
    result = await db.execute(stmt)
    zones = result.scalars().all()
    return ServiceZoneListResponse(
        items=[_to_response(z) for z in zones],
        total=len(zones),
    )
