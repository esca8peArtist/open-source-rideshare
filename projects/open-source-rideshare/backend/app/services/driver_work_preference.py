"""Service layer for driver work preferences.

Provides get-or-create and upsert operations.  Preferences give drivers
agency over their workload — a cooperative differentiator vs Uber/Lyft where
algorithmic dispatch ignores driver preferences entirely.

Public functions:
  get_preferences    — return or create a driver's preference row
  update_preferences — partial update (upsert) of preferences
  reset_preferences  — reset all preferences to platform defaults
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.driver_work_preference import DriverWorkPreference
from app.schemas.driver_work_preference import DriverWorkPreferenceUpdate

logger = logging.getLogger(__name__)

# Platform defaults — permissive so new drivers aren't inadvertently filtered out
_DEFAULTS: dict = {
    "accept_pool_rides": True,
    "accept_pet_riders": True,
    "accept_extra_luggage": True,
    "min_trip_distance_km": None,
    "max_trip_distance_km": None,
    "prefer_long_distance": False,
    "prefer_language_matched": False,
    "notes": None,
}


async def get_preferences(
    db: AsyncSession,
    driver_id: int,
) -> DriverWorkPreference:
    """Return the driver's work preferences row, creating one with defaults if absent."""
    result = await db.execute(
        select(DriverWorkPreference).where(
            DriverWorkPreference.driver_id == driver_id
        )
    )
    prefs = result.scalar_one_or_none()

    if prefs is None:
        prefs = DriverWorkPreference(driver_id=driver_id, **_DEFAULTS)
        db.add(prefs)
        await db.flush()
        logger.info("Created default work preferences for driver %d", driver_id)

    return prefs


async def update_preferences(
    db: AsyncSession,
    driver_id: int,
    updates: DriverWorkPreferenceUpdate,
) -> DriverWorkPreference:
    """Upsert work preferences for a driver.

    Only fields provided (non-None) in *updates* are written; existing values
    are preserved for omitted fields.  Distance range validation is enforced
    against the *resulting* combined state (existing + updates).
    """
    prefs = await get_preferences(db, driver_id)

    for field, value in updates.model_dump(exclude_none=True).items():
        setattr(prefs, field, value)

    await db.flush()
    logger.info("Updated work preferences for driver %d", driver_id)
    return prefs


async def reset_preferences(
    db: AsyncSession,
    driver_id: int,
) -> DriverWorkPreference:
    """Reset a driver's work preferences to platform defaults.

    Returns the updated (now-default) preference row.
    """
    prefs = await get_preferences(db, driver_id)

    for field, value in _DEFAULTS.items():
        setattr(prefs, field, value)

    await db.flush()
    logger.info("Reset work preferences to defaults for driver %d", driver_id)
    return prefs
