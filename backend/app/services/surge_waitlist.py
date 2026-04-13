"""Surge waitlist service.

Handles creation, cancellation, and polling of surge waitlist entries.
Riders join the waitlist when surge pricing is active; when the multiplier
drops to their threshold the system notifies them via their chosen channels.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.surge import SurgePricingZone
from app.models.surge_waitlist import SurgeWaitlistEntry
from app.services.notifications import (
    Notification,
    NotificationChannel,
    NotificationType,
    send_notification,
)
from app.services.surge_zones import (
    _point_in_zone,
    is_zone_active_now,
)

logger = logging.getLogger(__name__)

# How long waitlist entries remain active before auto-expiring
_ENTRY_TTL_HOURS = 2


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _validate_multiplier(max_multiplier: float) -> None:
    if max_multiplier < 1.0 or max_multiplier > 5.0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="max_multiplier must be between 1.0 and 5.0",
        )


def _validate_coordinates(
    lat: float,
    lon: float,
    field_prefix: str = "origin",
) -> None:
    if not (-90.0 <= lat <= 90.0):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{field_prefix}_lat must be between -90 and 90",
        )
    if not (-180.0 <= lon <= 180.0):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{field_prefix}_lon must be between -180 and 180",
        )


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


async def create_waitlist_entry(
    db: AsyncSession,
    rider_id: int,
    origin_lat: float,
    origin_lon: float,
    dest_lat: float | None = None,
    dest_lon: float | None = None,
    max_multiplier: float = 1.5,
    vehicle_pref: str | None = None,
    notify_push: bool = True,
    notify_sms: bool = False,
) -> SurgeWaitlistEntry:
    """Create and persist a surge waitlist entry for a rider.

    Validates coordinates and multiplier range before persisting. The entry
    expires automatically two hours after creation.
    """
    _validate_multiplier(max_multiplier)
    _validate_coordinates(origin_lat, origin_lon, "origin")
    if dest_lat is not None:
        _validate_coordinates(dest_lat, dest_lon or 0.0, "destination")

    now = datetime.now(timezone.utc)
    entry = SurgeWaitlistEntry(
        rider_id=rider_id,
        origin_lat=origin_lat,
        origin_lon=origin_lon,
        destination_lat=dest_lat,
        destination_lon=dest_lon,
        max_multiplier=max_multiplier,
        vehicle_preference=vehicle_pref,
        status="active",
        notify_via_push=notify_push,
        notify_via_sms=notify_sms,
        expires_at=now + timedelta(hours=_ENTRY_TTL_HOURS),
    )
    db.add(entry)
    await db.flush()
    await db.refresh(entry)
    return entry


async def cancel_waitlist_entry(
    db: AsyncSession,
    entry_id: uuid.UUID,
    rider_id: int,
) -> SurgeWaitlistEntry:
    """Cancel an active waitlist entry owned by the given rider.

    Raises:
        404 if entry not found.
        403 if the entry belongs to a different rider.
        400 if the entry is not in 'active' status.
    """
    result = await db.execute(
        select(SurgeWaitlistEntry).where(SurgeWaitlistEntry.id == entry_id)
    )
    entry = result.scalar_one_or_none()

    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Waitlist entry not found",
        )

    if entry.rider_id != rider_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not own this waitlist entry",
        )

    if entry.status != "active":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot cancel entry with status '{entry.status}'",
        )

    entry.status = "cancelled"
    await db.flush()
    return entry


async def get_my_waitlist_entries(
    db: AsyncSession,
    rider_id: int,
    include_expired: bool = False,
) -> list[SurgeWaitlistEntry]:
    """Return all waitlist entries belonging to rider_id.

    When include_expired is False (default), only 'active' and 'notified'
    entries are returned. When True, all entries including 'expired' and
    'cancelled' are included.
    """
    query = select(SurgeWaitlistEntry).where(
        SurgeWaitlistEntry.rider_id == rider_id
    )
    if not include_expired:
        query = query.where(
            SurgeWaitlistEntry.status.in_(["active", "notified"])
        )
    query = query.order_by(SurgeWaitlistEntry.created_at.desc())
    result = await db.execute(query)
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Geo-enhanced surge lookup (returns zone name alongside multiplier)
# ---------------------------------------------------------------------------


async def get_current_surge_for_location(
    db: AsyncSession,
    lat: float,
    lon: float,
) -> dict:
    """Return the current surge multiplier and matching zone name for a location.

    Returns a dict with keys:
      - multiplier (float): highest applicable multiplier, 1.0 if none
      - zone_name (str | None): name of the matching zone, or None
      - has_surge (bool): True when multiplier > 1.0
    """
    result = await db.execute(
        select(SurgePricingZone).where(SurgePricingZone.is_active.is_(True))
    )
    zones = list(result.scalars().all())

    best_multiplier = 1.0
    best_zone_name: str | None = None

    for zone in zones:
        if not is_zone_active_now(zone):
            continue
        if _point_in_zone(lat, lon, zone):
            if zone.multiplier > best_multiplier:
                best_multiplier = zone.multiplier
                best_zone_name = zone.name

    return {
        "multiplier": best_multiplier,
        "zone_name": best_zone_name,
        "has_surge": best_multiplier > 1.0,
    }


# ---------------------------------------------------------------------------
# Core polling function
# ---------------------------------------------------------------------------


async def check_and_notify_waitlist(db: AsyncSession) -> dict:
    """Check all active waitlist entries and notify riders whose threshold is met.

    For each active entry:
      - If expires_at is in the past → mark as 'expired'
      - If the current surge multiplier at the origin is ≤ max_multiplier → notify

    Returns a summary dict with counts: {notified, expired, still_active}.
    """
    now = datetime.now(timezone.utc)

    result = await db.execute(
        select(SurgeWaitlistEntry).where(SurgeWaitlistEntry.status == "active")
    )
    active_entries = list(result.scalars().all())

    # Fetch all active zones once and reuse for all entries
    zone_result = await db.execute(
        select(SurgePricingZone).where(SurgePricingZone.is_active.is_(True))
    )
    zones = list(zone_result.scalars().all())

    notified_count = 0
    expired_count = 0
    still_active_count = 0

    for entry in active_entries:
        # Check expiry first
        if entry.expires_at < now:
            entry.status = "expired"
            expired_count += 1
            continue

        # Calculate current multiplier for origin coordinates
        best = 1.0
        for zone in zones:
            if not is_zone_active_now(zone, now):
                continue
            if _point_in_zone(entry.origin_lat, entry.origin_lon, zone):
                if zone.multiplier > best:
                    best = zone.multiplier

        if best <= entry.max_multiplier:
            # Surge has dropped to/below threshold — notify rider
            entry.status = "notified"
            entry.notified_at = now

            channels = []
            if entry.notify_via_push:
                channels.append(NotificationChannel.PUSH)
            if entry.notify_via_sms:
                channels.append(NotificationChannel.SMS)
            if not channels:
                channels = [NotificationChannel.PUSH]

            notification = Notification(
                user_id=entry.rider_id,
                type=NotificationType.RIDE_MATCHED,  # reuse closest existing type
                title="Surge pricing has dropped!",
                body=(
                    f"The surge multiplier at your pickup location is now {best:.1f}x "
                    f"(your threshold: {entry.max_multiplier:.1f}x). "
                    "Book your ride now!"
                ),
                channels=channels,
                data={"entry_id": str(entry.id), "current_multiplier": best},
            )

            try:
                await send_notification(notification, db=db)
            except Exception:
                logger.exception(
                    "Failed to send surge waitlist notification for entry %s", entry.id
                )

            notified_count += 1
        else:
            still_active_count += 1

    await db.flush()

    return {
        "notified": notified_count,
        "expired": expired_count,
        "still_active": still_active_count,
    }
