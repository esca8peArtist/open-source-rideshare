"""Driver Certification Badge service layer.

Public functions:
  award_badge                — award a badge to a driver (or re-activate revoked one)
  revoke_badge               — revoke an active badge from a driver
  get_driver_badges          — list a driver's badges (active only or all)
  check_badge_eligibility    — check eligibility for all badge types
  auto_award_eligible_badges — award all eligible badges not already active
  get_badge_stats            — platform-wide badge statistics
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.driver_certification import BadgeType, DriverCertification
from app.schemas.driver_certification import BadgeEligibilityResult


# ---------------------------------------------------------------------------
# Award / revoke
# ---------------------------------------------------------------------------


async def award_badge(
    db: AsyncSession,
    driver_id: int,
    badge_type: BadgeType,
    awarded_by: Optional[int] = None,
    notes: Optional[str] = None,
) -> DriverCertification:
    """Award a badge to a driver.

    If the badge already exists and is active, raises 409.
    If it exists but was revoked, re-activates it instead of inserting a new row.
    """
    result = await db.execute(
        select(DriverCertification).where(
            DriverCertification.driver_id == driver_id,
            DriverCertification.badge_type == badge_type,
        )
    )
    cert = result.scalar_one_or_none()

    if cert is not None:
        if cert.is_active:
            raise HTTPException(status_code=409, detail="Badge already active for this driver")
        # Re-activate a previously revoked badge
        cert.is_active = True
        cert.awarded_at = datetime.now(tz=timezone.utc)
        cert.awarded_by = awarded_by
        cert.revoked_at = None
        cert.revoked_by = None
        cert.notes = notes
    else:
        cert = DriverCertification(
            driver_id=driver_id,
            badge_type=badge_type,
            is_active=True,
            awarded_by=awarded_by,
            notes=notes,
        )
        db.add(cert)

    await db.flush()
    return cert


async def revoke_badge(
    db: AsyncSession,
    driver_id: int,
    badge_type: BadgeType,
    revoked_by: int,
    notes: Optional[str] = None,
) -> DriverCertification:
    """Revoke an active badge.

    Raises 404 if no active badge of that type exists for the driver.
    """
    result = await db.execute(
        select(DriverCertification).where(
            DriverCertification.driver_id == driver_id,
            DriverCertification.badge_type == badge_type,
            DriverCertification.is_active.is_(True),
        )
    )
    cert = result.scalar_one_or_none()

    if cert is None:
        raise HTTPException(
            status_code=404,
            detail="No active badge of that type found for this driver",
        )

    cert.is_active = False
    cert.revoked_at = datetime.now(tz=timezone.utc)
    cert.revoked_by = revoked_by
    if notes is not None:
        cert.notes = notes

    await db.flush()
    return cert


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------


async def get_driver_badges(
    db: AsyncSession,
    driver_id: int,
    active_only: bool = True,
) -> list[DriverCertification]:
    """Return a driver's badges, ordered newest first."""
    stmt = select(DriverCertification).where(
        DriverCertification.driver_id == driver_id
    )
    if active_only:
        stmt = stmt.where(DriverCertification.is_active.is_(True))
    stmt = stmt.order_by(DriverCertification.awarded_at.desc())

    result = await db.execute(stmt)
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Eligibility checks
# ---------------------------------------------------------------------------


async def check_badge_eligibility(
    db: AsyncSession,
    driver_id: int,
) -> list[BadgeEligibilityResult]:
    """Check eligibility for all badge types for a given driver.

    Each check queries the database independently.  Missing data (no profile,
    no rides, etc.) is treated as not eligible.
    """
    results: list[BadgeEligibilityResult] = []

    # --- safe_driver ---
    # 0 driver incident records AND avg rider_rating >= 4.5
    try:
        from app.models.driver_incident import DriverIncidentReport
        from app.models.rider_rating import RiderRating

        incident_count_row = await db.execute(
            select(func.count()).where(DriverIncidentReport.driver_id == driver_id)
        )
        incident_count = incident_count_row.scalar() or 0

        avg_rating_row = await db.execute(
            select(func.avg(RiderRating.rating)).where(RiderRating.driver_id == driver_id)
        )
        avg_rating = avg_rating_row.scalar()

        if incident_count == 0 and avg_rating is not None and avg_rating >= 4.5:
            results.append(BadgeEligibilityResult(
                badge_type=BadgeType.SAFE_DRIVER,
                is_eligible=True,
                reason=f"No incidents and average rating {avg_rating:.2f} >= 4.5",
            ))
        else:
            reason = []
            if incident_count > 0:
                reason.append(f"{incident_count} incident(s) on record")
            if avg_rating is None:
                reason.append("no ratings yet")
            elif avg_rating < 4.5:
                reason.append(f"average rating {avg_rating:.2f} < 4.5")
            results.append(BadgeEligibilityResult(
                badge_type=BadgeType.SAFE_DRIVER,
                is_eligible=False,
                reason="; ".join(reason) or "not eligible",
            ))
    except Exception:
        results.append(BadgeEligibilityResult(
            badge_type=BadgeType.SAFE_DRIVER,
            is_eligible=False,
            reason="Unable to retrieve eligibility data",
        ))

    # --- five_star ---
    # avg rider_rating >= 4.8 AND at least 50 completed rides
    try:
        from app.models.ride import Ride, RideStatus
        from app.models.rider_rating import RiderRating

        avg_rating_row = await db.execute(
            select(func.avg(RiderRating.rating)).where(RiderRating.driver_id == driver_id)
        )
        avg_rating = avg_rating_row.scalar()

        ride_count_row = await db.execute(
            select(func.count()).where(
                Ride.driver_id == driver_id,
                Ride.status == RideStatus.COMPLETED,
            )
        )
        ride_count = ride_count_row.scalar() or 0

        if avg_rating is not None and avg_rating >= 4.8 and ride_count >= 50:
            results.append(BadgeEligibilityResult(
                badge_type=BadgeType.FIVE_STAR,
                is_eligible=True,
                reason=f"Rating {avg_rating:.2f} >= 4.8 and {ride_count} completed rides >= 50",
            ))
        else:
            reason = []
            if avg_rating is None:
                reason.append("no ratings yet")
            elif avg_rating < 4.8:
                reason.append(f"average rating {avg_rating:.2f} < 4.8")
            if ride_count < 50:
                reason.append(f"only {ride_count} completed rides (need 50+)")
            results.append(BadgeEligibilityResult(
                badge_type=BadgeType.FIVE_STAR,
                is_eligible=False,
                reason="; ".join(reason) or "not eligible",
            ))
    except Exception:
        results.append(BadgeEligibilityResult(
            badge_type=BadgeType.FIVE_STAR,
            is_eligible=False,
            reason="Unable to retrieve eligibility data",
        ))

    # --- accessibility_specialist ---
    # driver has an active vehicle with service_category = WAV
    try:
        from app.models.driver import DriverProfile
        from app.models.vehicle import Vehicle, VehicleServiceCategory

        wav_count_row = await db.execute(
            select(func.count()).select_from(Vehicle).join(
                DriverProfile, Vehicle.driver_profile_id == DriverProfile.id
            ).where(
                DriverProfile.user_id == driver_id,
                Vehicle.service_category == VehicleServiceCategory.WAV,
                Vehicle.is_active.is_(True),
            )
        )
        wav_count = wav_count_row.scalar() or 0

        if wav_count > 0:
            results.append(BadgeEligibilityResult(
                badge_type=BadgeType.ACCESSIBILITY_SPECIALIST,
                is_eligible=True,
                reason="Active WAV-category vehicle registered",
            ))
        else:
            results.append(BadgeEligibilityResult(
                badge_type=BadgeType.ACCESSIBILITY_SPECIALIST,
                is_eligible=False,
                reason="No active WAV-category vehicle found",
            ))
    except Exception:
        results.append(BadgeEligibilityResult(
            badge_type=BadgeType.ACCESSIBILITY_SPECIALIST,
            is_eligible=False,
            reason="Unable to retrieve eligibility data",
        ))

    # --- pet_friendly ---
    # driver's ride_preference has pets_allowed=True
    # Note: ride_preferences table is for riders; drivers use driver profile.
    # We check if the driver opted in by looking for a driver ride_preference row.
    try:
        from app.models.ride_preference import RidePreference

        pref_row = await db.execute(
            select(RidePreference).where(RidePreference.user_id == driver_id)
        )
        pref = pref_row.scalar_one_or_none()

        if pref is not None and pref.pet_friendly:
            results.append(BadgeEligibilityResult(
                badge_type=BadgeType.PET_FRIENDLY,
                is_eligible=True,
                reason="Driver has opted in to allow pets",
            ))
        else:
            results.append(BadgeEligibilityResult(
                badge_type=BadgeType.PET_FRIENDLY,
                is_eligible=False,
                reason="Driver has not opted in to allow pets",
            ))
    except Exception:
        results.append(BadgeEligibilityResult(
            badge_type=BadgeType.PET_FRIENDLY,
            is_eligible=False,
            reason="Unable to retrieve eligibility data",
        ))

    # --- long_distance_expert ---
    # count of completed rides where distance_km > 30 >= 10
    try:
        from app.models.ride import Ride, RideStatus

        long_ride_count_row = await db.execute(
            select(func.count()).where(
                Ride.driver_id == driver_id,
                Ride.status == RideStatus.COMPLETED,
                Ride.distance_km > 30,
            )
        )
        long_ride_count = long_ride_count_row.scalar() or 0

        if long_ride_count >= 10:
            results.append(BadgeEligibilityResult(
                badge_type=BadgeType.LONG_DISTANCE_EXPERT,
                is_eligible=True,
                reason=f"{long_ride_count} long-distance rides (30+ km) completed",
            ))
        else:
            results.append(BadgeEligibilityResult(
                badge_type=BadgeType.LONG_DISTANCE_EXPERT,
                is_eligible=False,
                reason=f"Only {long_ride_count} long-distance rides (need 10+)",
            ))
    except Exception:
        results.append(BadgeEligibilityResult(
            badge_type=BadgeType.LONG_DISTANCE_EXPERT,
            is_eligible=False,
            reason="Unable to retrieve eligibility data",
        ))

    # --- mentor ---
    # driver has at least one active mentorship record as mentor
    try:
        from app.models.driver_mentorship import DriverMentorship, MentorshipStatus

        mentorship_count_row = await db.execute(
            select(func.count()).where(
                DriverMentorship.mentor_id == driver_id,
                DriverMentorship.status == MentorshipStatus.active,
            )
        )
        mentorship_count = mentorship_count_row.scalar() or 0

        if mentorship_count > 0:
            results.append(BadgeEligibilityResult(
                badge_type=BadgeType.MENTOR,
                is_eligible=True,
                reason=f"Active mentor in {mentorship_count} mentorship(s)",
            ))
        else:
            results.append(BadgeEligibilityResult(
                badge_type=BadgeType.MENTOR,
                is_eligible=False,
                reason="No active mentorship records as mentor",
            ))
    except Exception:
        results.append(BadgeEligibilityResult(
            badge_type=BadgeType.MENTOR,
            is_eligible=False,
            reason="Unable to retrieve eligibility data",
        ))

    # --- eco_driver ---
    # driver has a vehicle registered under the eco service category, or
    # if the platform has a fuel_type field, driver's vehicle is electric/hybrid.
    # We query for active vehicles; if the model has a fuel_type column we filter
    # on it, otherwise we fall back to checking vehicle_type annotation.
    try:
        from app.models.driver import DriverProfile
        from app.models.vehicle import Vehicle

        stmt = (
            select(func.count())
            .select_from(Vehicle)
            .join(DriverProfile, Vehicle.driver_profile_id == DriverProfile.id)
            .where(
                DriverProfile.user_id == driver_id,
                Vehicle.is_active.is_(True),
            )
        )

        # Add fuel_type filter only if the column exists on the model.
        if hasattr(Vehicle, "fuel_type"):
            stmt = stmt.where(Vehicle.fuel_type.in_(["electric", "hybrid"]))

        eco_count_row = await db.execute(stmt)
        eco_count = eco_count_row.scalar() or 0

        if hasattr(Vehicle, "fuel_type") and eco_count > 0:
            results.append(BadgeEligibilityResult(
                badge_type=BadgeType.ECO_DRIVER,
                is_eligible=True,
                reason="Active electric or hybrid vehicle registered",
            ))
        elif not hasattr(Vehicle, "fuel_type"):
            # Platform does not yet track fuel type — badge not awardable via auto-check
            results.append(BadgeEligibilityResult(
                badge_type=BadgeType.ECO_DRIVER,
                is_eligible=False,
                reason="Fuel type data not available; award manually",
            ))
        else:
            results.append(BadgeEligibilityResult(
                badge_type=BadgeType.ECO_DRIVER,
                is_eligible=False,
                reason="No active electric or hybrid vehicle found",
            ))
    except Exception:
        results.append(BadgeEligibilityResult(
            badge_type=BadgeType.ECO_DRIVER,
            is_eligible=False,
            reason="Unable to retrieve eligibility data",
        ))

    # --- veteran ---
    # driver account created > 365 days ago AND completed rides >= 500
    try:
        from app.models.ride import Ride, RideStatus
        from app.models.user import User

        user_row = await db.execute(
            select(User.created_at).where(User.id == driver_id)
        )
        user_created_at = user_row.scalar_one_or_none()

        ride_count_row = await db.execute(
            select(func.count()).where(
                Ride.driver_id == driver_id,
                Ride.status == RideStatus.COMPLETED,
            )
        )
        ride_count = ride_count_row.scalar() or 0

        now = datetime.now(tz=timezone.utc)
        account_age_days = 0
        if user_created_at is not None:
            created = user_created_at if user_created_at.tzinfo else user_created_at.replace(tzinfo=timezone.utc)
            account_age_days = (now - created).days

        if account_age_days >= 365 and ride_count >= 500:
            results.append(BadgeEligibilityResult(
                badge_type=BadgeType.VETERAN,
                is_eligible=True,
                reason=f"{account_age_days} days on platform and {ride_count} completed rides",
            ))
        else:
            reason = []
            if account_age_days < 365:
                reason.append(f"account only {account_age_days} days old (need 365+)")
            if ride_count < 500:
                reason.append(f"only {ride_count} completed rides (need 500+)")
            results.append(BadgeEligibilityResult(
                badge_type=BadgeType.VETERAN,
                is_eligible=False,
                reason="; ".join(reason) or "not eligible",
            ))
    except Exception:
        results.append(BadgeEligibilityResult(
            badge_type=BadgeType.VETERAN,
            is_eligible=False,
            reason="Unable to retrieve eligibility data",
        ))

    return results


# ---------------------------------------------------------------------------
# Auto-award
# ---------------------------------------------------------------------------


async def auto_award_eligible_badges(
    db: AsyncSession,
    driver_id: int,
) -> list[BadgeType]:
    """Award all eligible badges that the driver doesn't already hold.

    Returns the list of newly awarded badge types.
    """
    eligibility = await check_badge_eligibility(db, driver_id)

    # Fetch currently active badge types to avoid duplicates
    active_result = await db.execute(
        select(DriverCertification.badge_type).where(
            DriverCertification.driver_id == driver_id,
            DriverCertification.is_active.is_(True),
        )
    )
    already_active = set(active_result.scalars().all())

    newly_awarded: list[BadgeType] = []
    for result in eligibility:
        if result.is_eligible and result.badge_type not in already_active:
            await award_badge(db, driver_id, result.badge_type, awarded_by=None)
            newly_awarded.append(result.badge_type)

    return newly_awarded


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------


async def get_badge_stats(db: AsyncSession) -> dict:
    """Return platform-wide badge statistics for the admin dashboard."""
    # Total active certifications
    total_row = await db.execute(
        select(func.count()).where(DriverCertification.is_active.is_(True))
    )
    total_active = total_row.scalar() or 0

    # Count by badge type
    by_type_rows = await db.execute(
        select(DriverCertification.badge_type, func.count().label("cnt"))
        .where(DriverCertification.is_active.is_(True))
        .group_by(DriverCertification.badge_type)
    )
    by_type = {row.badge_type.value: row.cnt for row in by_type_rows}

    # Top 10 drivers by active badge count
    top_rows = await db.execute(
        select(DriverCertification.driver_id, func.count().label("badge_count"))
        .where(DriverCertification.is_active.is_(True))
        .group_by(DriverCertification.driver_id)
        .order_by(func.count().desc())
        .limit(10)
    )
    top_drivers = [
        {"driver_id": row.driver_id, "badge_count": row.badge_count}
        for row in top_rows
    ]

    return {
        "total_active": total_active,
        "by_type": by_type,
        "top_drivers": top_drivers,
    }
