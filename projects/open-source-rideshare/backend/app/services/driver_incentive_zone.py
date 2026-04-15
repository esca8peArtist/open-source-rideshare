"""Driver Incentive Zone service layer.

Public functions:
  create_zone              — admin: create a new incentive zone
  update_zone              — admin: update zone fields
  deactivate_zone          — admin: end a zone early
  get_zone                 — fetch a single zone by id
  get_active_zones         — list zones currently in their active window
  get_all_zones            — admin: all zones paginated
  record_zone_completion   — idempotent: award a zone bonus for a ride
  get_driver_completions   — driver's bonus history across all zones
  get_driver_zone_summary  — aggregate bonus stats for a driver
  get_zone_stats           — admin: performance stats for a single zone
  check_ride_qualifies     — pure helper: does a ride fall inside a zone?
"""

from __future__ import annotations

import math
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.driver_incentive_zone import (
    DriverIncentiveZone,
    DriverZoneCompletion,
    IncentiveBonusType,
)
from app.schemas.driver_incentive_zone import (
    CreateIncentiveZoneRequest,
    DriverZoneEarningsSummary,
    UpdateIncentiveZoneRequest,
    ZoneStatsResponse,
)


# ---------------------------------------------------------------------------
# Custom exception
# ---------------------------------------------------------------------------


class IncentiveZoneError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


# ---------------------------------------------------------------------------
# Geography helpers (pure)
# ---------------------------------------------------------------------------


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return the great-circle distance in kilometres between two points."""
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _ray_cast_in_polygon(lat: float, lon: float, polygon: list[dict[str, Any]]) -> bool:
    """Return True if (lat, lon) is inside the polygon using ray casting."""
    n = len(polygon)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]["lon"], polygon[i]["lat"]
        xj, yj = polygon[j]["lon"], polygon[j]["lat"]
        if ((yi > lat) != (yj > lat)) and (lon < (xj - xi) * (lat - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def check_ride_qualifies(
    zone: DriverIncentiveZone,
    pickup_lat: float,
    pickup_lon: float,
    ride_completed_at: datetime,
) -> bool:
    """Return True if a ride qualifies for a zone bonus.

    Criteria:
    1. Pickup location is inside the zone boundary.
    2. Ride was completed within the zone's active time window.
    3. Zone is still marked active.
    """
    if not zone.is_active:
        return False
    if not (zone.starts_at <= ride_completed_at <= zone.ends_at):
        return False

    if zone.polygon:
        return _ray_cast_in_polygon(pickup_lat, pickup_lon, zone.polygon)

    if zone.center_lat is not None and zone.center_lon is not None and zone.radius_km is not None:
        dist = _haversine_km(zone.center_lat, zone.center_lon, pickup_lat, pickup_lon)
        return dist <= zone.radius_km

    return False


# ---------------------------------------------------------------------------
# CRUD operations
# ---------------------------------------------------------------------------


async def create_zone(
    db: AsyncSession, body: CreateIncentiveZoneRequest
) -> DriverIncentiveZone:
    """Create and persist a new incentive zone."""
    zone = DriverIncentiveZone(
        name=body.name,
        description=body.description,
        reason=body.reason,
        polygon=body.polygon,
        center_lat=body.center_lat,
        center_lon=body.center_lon,
        radius_km=float(body.radius_km) if body.radius_km is not None else None,
        bonus_type=body.bonus_type,
        bonus_multiplier=float(body.bonus_multiplier) if body.bonus_multiplier is not None else None,
        bonus_flat_cents=body.bonus_flat_cents,
        starts_at=body.starts_at,
        ends_at=body.ends_at,
        max_total_completions=body.max_total_completions,
        max_completions_per_driver=body.max_completions_per_driver,
        min_driver_rating=float(body.min_driver_rating) if body.min_driver_rating is not None else None,
        is_active=True,
    )
    db.add(zone)
    await db.commit()
    await db.refresh(zone)
    return zone


async def update_zone(
    db: AsyncSession, zone_id: uuid.UUID, body: UpdateIncentiveZoneRequest
) -> DriverIncentiveZone:
    """Apply partial updates to an existing zone."""
    result = await db.execute(
        select(DriverIncentiveZone).where(DriverIncentiveZone.id == zone_id)
    )
    zone = result.scalar_one_or_none()
    if zone is None:
        raise IncentiveZoneError("Incentive zone not found", status_code=404)

    update_fields = body.model_dump(exclude_unset=True)
    for field, value in update_fields.items():
        setattr(zone, field, value)

    await db.commit()
    await db.refresh(zone)
    return zone


async def deactivate_zone(db: AsyncSession, zone_id: uuid.UUID) -> DriverIncentiveZone:
    """Mark a zone as inactive (ends it early)."""
    result = await db.execute(
        select(DriverIncentiveZone).where(DriverIncentiveZone.id == zone_id)
    )
    zone = result.scalar_one_or_none()
    if zone is None:
        raise IncentiveZoneError("Incentive zone not found", status_code=404)
    if not zone.is_active:
        raise IncentiveZoneError("Zone is already inactive", status_code=409)

    zone.is_active = False
    await db.commit()
    await db.refresh(zone)
    return zone


async def get_zone(db: AsyncSession, zone_id: uuid.UUID) -> DriverIncentiveZone | None:
    """Return a zone by id, or None."""
    result = await db.execute(
        select(DriverIncentiveZone).where(DriverIncentiveZone.id == zone_id)
    )
    return result.scalar_one_or_none()


async def get_active_zones(db: AsyncSession) -> list[DriverIncentiveZone]:
    """Return all zones whose time window includes right now and is_active=True."""
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(DriverIncentiveZone).where(
            DriverIncentiveZone.is_active.is_(True),
            DriverIncentiveZone.starts_at <= now,
            DriverIncentiveZone.ends_at >= now,
        )
    )
    return list(result.scalars().all())


async def get_all_zones(
    db: AsyncSession, skip: int = 0, limit: int = 50
) -> list[DriverIncentiveZone]:
    """Return all zones, newest first (admin use)."""
    result = await db.execute(
        select(DriverIncentiveZone)
        .order_by(DriverIncentiveZone.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Bonus award
# ---------------------------------------------------------------------------


async def record_zone_completion(
    db: AsyncSession,
    zone_id: uuid.UUID,
    driver_profile_id: int,
    ride_id: int,
    bonus_amount_cents: int,
) -> DriverZoneCompletion:
    """Award a zone bonus for a completed ride.

    Idempotent: if a completion already exists for (zone_id, ride_id) the
    existing record is returned without modification.

    Raises IncentiveZoneError(404) if the zone does not exist.
    Raises IncentiveZoneError(409) if the zone's total cap has been reached.
    """
    result = await db.execute(
        select(DriverIncentiveZone).where(DriverIncentiveZone.id == zone_id)
    )
    zone = result.scalar_one_or_none()
    if zone is None:
        raise IncentiveZoneError("Incentive zone not found", status_code=404)

    # Idempotency check.
    existing_result = await db.execute(
        select(DriverZoneCompletion).where(
            DriverZoneCompletion.zone_id == zone_id,
            DriverZoneCompletion.ride_id == ride_id,
        )
    )
    existing = existing_result.scalar_one_or_none()
    if existing is not None:
        return existing

    # Total cap check.
    if zone.max_total_completions is not None:
        count_result = await db.execute(
            select(func.count()).where(DriverZoneCompletion.zone_id == zone_id)
        )
        total = count_result.scalar_one()
        if total >= zone.max_total_completions:
            raise IncentiveZoneError(
                "Incentive zone has reached its maximum completion cap", status_code=409
            )

    # Per-driver cap check.
    if zone.max_completions_per_driver is not None:
        driver_count_result = await db.execute(
            select(func.count()).where(
                DriverZoneCompletion.zone_id == zone_id,
                DriverZoneCompletion.driver_profile_id == driver_profile_id,
            )
        )
        driver_total = driver_count_result.scalar_one()
        if driver_total >= zone.max_completions_per_driver:
            raise IncentiveZoneError(
                "Driver has reached the per-driver cap for this zone", status_code=409
            )

    completion = DriverZoneCompletion(
        zone_id=zone_id,
        driver_profile_id=driver_profile_id,
        ride_id=ride_id,
        bonus_amount_cents=bonus_amount_cents,
        bonus_type=zone.bonus_type,
    )
    db.add(completion)
    await db.commit()
    await db.refresh(completion)
    return completion


# ---------------------------------------------------------------------------
# Driver history / stats
# ---------------------------------------------------------------------------


async def get_driver_completions(
    db: AsyncSession, driver_profile_id: int, skip: int = 0, limit: int = 50
) -> list[DriverZoneCompletion]:
    """Return a driver's zone bonus history, newest first."""
    result = await db.execute(
        select(DriverZoneCompletion)
        .where(DriverZoneCompletion.driver_profile_id == driver_profile_id)
        .order_by(DriverZoneCompletion.completed_at.desc())
        .offset(skip)
        .limit(limit)
    )
    return list(result.scalars().all())


async def get_driver_zone_summary(
    db: AsyncSession, driver_profile_id: int
) -> DriverZoneEarningsSummary:
    """Return aggregate incentive zone earnings for a driver."""
    result = await db.execute(
        select(DriverZoneCompletion).where(
            DriverZoneCompletion.driver_profile_id == driver_profile_id
        )
    )
    completions = result.scalars().all()

    total_cents = sum(c.bonus_amount_cents for c in completions)
    unique_zones = len({c.zone_id for c in completions})

    return DriverZoneEarningsSummary(
        driver_profile_id=driver_profile_id,
        total_completions=len(completions),
        total_bonus_cents=total_cents,
        total_bonus_dollars=round(total_cents / 100, 2),
        zones_participated=unique_zones,
    )


# ---------------------------------------------------------------------------
# Admin stats
# ---------------------------------------------------------------------------


async def get_zone_stats(
    db: AsyncSession, zone_id: uuid.UUID
) -> ZoneStatsResponse:
    """Return performance stats for a single zone (admin)."""
    result = await db.execute(
        select(DriverIncentiveZone).where(DriverIncentiveZone.id == zone_id)
    )
    zone = result.scalar_one_or_none()
    if zone is None:
        raise IncentiveZoneError("Incentive zone not found", status_code=404)

    comp_result = await db.execute(
        select(DriverZoneCompletion).where(DriverZoneCompletion.zone_id == zone_id)
    )
    completions = comp_result.scalars().all()

    total_paid = sum(c.bonus_amount_cents for c in completions)
    unique_drivers = len({c.driver_profile_id for c in completions})
    remaining = (
        zone.max_total_completions - len(completions)
        if zone.max_total_completions is not None
        else None
    )

    return ZoneStatsResponse(
        zone_id=zone.id,
        zone_name=zone.name,
        total_completions=len(completions),
        total_paid_cents=total_paid,
        total_paid_dollars=round(total_paid / 100, 2),
        unique_drivers=unique_drivers,
        is_active=zone.is_active,
        starts_at=zone.starts_at,
        ends_at=zone.ends_at,
        max_total_completions=zone.max_total_completions,
        remaining_budget=remaining,
    )
