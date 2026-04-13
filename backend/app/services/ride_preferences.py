"""Service layer for rider ride preferences.

Provides get_or_create and upsert operations.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ride_preference import RidePreference, TemperaturePreference
from app.schemas.ride_preference import RidePreferenceUpdate

logger = logging.getLogger(__name__)

# Sensible defaults for a new preference row
_DEFAULTS = {
    "quiet_ride": False,
    "music_off": False,
    "temperature_preference": TemperaturePreference.NO_PREFERENCE,
    "pet_friendly": False,
    "extra_luggage": False,
    "accessibility_vehicle_needed": False,
    "notes": None,
}


async def get_preferences(
    db: AsyncSession,
    user_id: int,
) -> RidePreference:
    """Return the rider's preferences row, creating one with defaults if absent."""
    result = await db.execute(
        select(RidePreference).where(RidePreference.user_id == user_id)
    )
    prefs = result.scalar_one_or_none()

    if prefs is None:
        prefs = RidePreference(user_id=user_id, **_DEFAULTS)
        db.add(prefs)
        await db.flush()
        logger.info("Created default ride preferences for user %d", user_id)

    return prefs


async def update_preferences(
    db: AsyncSession,
    user_id: int,
    updates: RidePreferenceUpdate,
) -> RidePreference:
    """Upsert ride preferences for a rider.

    Only fields provided (non-None) in *updates* are written; existing values
    are preserved for omitted fields.
    """
    prefs = await get_preferences(db, user_id)

    changed = False
    for field, value in updates.model_dump(exclude_none=True).items():
        if getattr(prefs, field) != value:
            setattr(prefs, field, value)
            changed = True

    if changed:
        await db.flush()
        logger.info("Updated ride preferences for user %d", user_id)

    return prefs


async def get_preferences_for_ride(
    db: AsyncSession,
    rider_user_id: int,
) -> RidePreference | None:
    """Return a rider's preferences to show a matched driver.

    Returns None if no preferences have ever been saved (driver should treat
    all fields as default/no-preference).
    """
    result = await db.execute(
        select(RidePreference).where(RidePreference.user_id == rider_user_id)
    )
    return result.scalar_one_or_none()
