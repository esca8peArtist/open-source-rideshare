"""Service layer for GET /drivers/{driver_id}/public-profile."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.driver import DriverProfile
from app.schemas.driver_public_profile import DriverPublicProfile


async def get_driver_public_profile(
    db: AsyncSession,
    driver_id: int,
) -> DriverPublicProfile | None:
    """Return a driver's public profile by DriverProfile.id.

    Returns None when no driver with that id exists, allowing the API layer
    to raise a 404.  Only approved drivers are returned — unapproved drivers
    are not visible to riders.
    """
    stmt = select(DriverProfile).where(
        DriverProfile.id == driver_id,
        DriverProfile.is_approved.is_(True),
    )
    result = await db.execute(stmt)
    profile: DriverProfile | None = result.scalar_one_or_none()

    if profile is None:
        return None

    return DriverPublicProfile(
        driver_id=profile.id,
        vehicle_type=profile.vehicle_type,
        vehicle_make=profile.vehicle_make,
        vehicle_model=profile.vehicle_model,
        vehicle_year=profile.vehicle_year,
        vehicle_color=profile.vehicle_color,
        rating_avg=profile.rating_avg,
        total_trips=profile.total_trips,
        is_approved=profile.is_approved,
        member_since=profile.created_at,
    )
