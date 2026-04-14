"""Driver career tier API endpoints.

Driver-facing:
  GET  /drivers/me/tier          — own tier, benefits, and progress to next tier
  POST /drivers/me/tier/refresh  — recalculate own tier from current stats

Admin-facing:
  GET  /admin/drivers/tier-distribution          — aggregate counts per tier
  POST /admin/drivers/{driver_id}/tier/refresh   — manually refresh a driver's tier
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_admin, require_driver
from app.models.driver import DriverProfile
from app.models.user import User
from app.schemas.driver_tier import AdminTierDistributionResponse, DriverCareerTierResponse
from app.services.driver_tiers import (
    get_driver_career_tier,
    get_next_tier_progress,
    get_tier_benefits,
    get_tier_distribution,
    refresh_driver_tier,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["driver-tiers"])


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


async def _require_driver_profile(db: AsyncSession, user: User) -> DriverProfile:
    """Fetch the DriverProfile for the authenticated user or raise 404."""
    result = await db.execute(
        select(DriverProfile).where(DriverProfile.user_id == user.id)
    )
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Driver profile not found.",
        )
    return profile


def _build_tier_response(row, profile_id: int) -> DriverCareerTierResponse:
    """Assemble a DriverCareerTierResponse from a DriverCareerTier row."""
    benefits = get_tier_benefits(row.current_tier)
    progress = get_next_tier_progress(
        rides=row.snapshot_rides,
        rating=row.snapshot_rating,
        acceptance_rate=row.snapshot_acceptance_rate,
        current_tier=row.current_tier,
    )
    return DriverCareerTierResponse(
        driver_id=profile_id,
        current_tier=row.current_tier,
        previous_tier=row.previous_tier,
        tier_since=row.tier_since,
        evaluated_at=row.evaluated_at,
        snapshot_rides=row.snapshot_rides,
        snapshot_rating=row.snapshot_rating,
        snapshot_acceptance_rate=row.snapshot_acceptance_rate,
        benefits=benefits,
        next_tier_progress=progress,
    )


# ---------------------------------------------------------------------------
# Driver endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/drivers/me/tier",
    response_model=DriverCareerTierResponse,
    summary="Get own career tier, benefits, and next-tier progress",
)
async def get_my_tier(
    user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    """Return the authenticated driver's career tier record.

    If the driver has no tier record yet (first request), a BRONZE record is
    created automatically.  The response also includes the benefit package for
    the current tier and a breakdown of what is needed to reach the next tier.
    """
    profile = await _require_driver_profile(db, user)
    row = await get_driver_career_tier(db, profile.id)
    return _build_tier_response(row, profile.id)


@router.post(
    "/drivers/me/tier/refresh",
    response_model=DriverCareerTierResponse,
    summary="Recalculate own career tier from current stats",
)
async def refresh_my_tier(
    user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    """Trigger a recalculation of the driver's career tier.

    Pulls the latest ``total_trips`` and ``rating_avg`` from DriverProfile and
    the most recent acceptance rate from DriverPerformanceSnapshot, then
    updates the tier if the driver has crossed a threshold.

    Returns the updated tier record (whether or not the tier changed).
    """
    profile = await _require_driver_profile(db, user)
    row, _ = await refresh_driver_tier(db, profile.id)
    return _build_tier_response(row, profile.id)


# ---------------------------------------------------------------------------
# Admin endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/admin/drivers/tier-distribution",
    response_model=AdminTierDistributionResponse,
    summary="Aggregate driver count per career tier (admin only)",
)
async def admin_tier_distribution(
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return a breakdown of how many drivers are at each career tier level."""
    return await get_tier_distribution(db)


@router.post(
    "/admin/drivers/{driver_id}/tier/refresh",
    response_model=DriverCareerTierResponse,
    summary="Manually recalculate a driver's career tier (admin only)",
)
async def admin_refresh_driver_tier(
    driver_id: int,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Force a tier recalculation for a specific driver.

    Useful after manually adjusting a driver's stats or correcting data
    quality issues.  Returns the updated tier record.
    """
    try:
        row, _ = await refresh_driver_tier(db, driver_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )
    return _build_tier_response(row, driver_id)
