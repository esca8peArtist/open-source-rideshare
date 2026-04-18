"""Service layer for driver accessibility capability flags.

Provides get and upsert operations for hearing_impairment_capable and
sign_language_capable on the driver_profiles table.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.driver import DriverProfile
from app.schemas.driver_accessibility import DriverAccessibilityUpdate

logger = logging.getLogger(__name__)


async def get_accessibility(
    db: AsyncSession,
    user_id: int,
) -> DriverProfile | None:
    """Return the driver's profile row, or None if no profile exists yet."""
    result = await db.execute(
        select(DriverProfile).where(DriverProfile.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def update_accessibility(
    db: AsyncSession,
    user_id: int,
    updates: DriverAccessibilityUpdate,
) -> DriverProfile:
    """Update accessibility capability flags for a driver.

    Only fields provided (non-None) in *updates* are written; existing values
    are preserved for omitted fields.

    Raises ValueError if the driver profile does not exist.
    """
    profile = await get_accessibility(db, user_id)
    if profile is None:
        raise ValueError(f"Driver profile not found for user_id={user_id}")

    changed = False
    for field, value in updates.model_dump(exclude_none=True).items():
        if getattr(profile, field) != value:
            setattr(profile, field, value)
            changed = True

    if changed:
        await db.flush()
        logger.info(
            "Updated accessibility capabilities for driver user_id=%d", user_id
        )

    return profile
