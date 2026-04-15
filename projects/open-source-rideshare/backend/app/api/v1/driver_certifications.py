"""Driver Certification Badge endpoints.

Public endpoints:
  GET  /drivers/{driver_id}/badges        — view any driver's active badges

Authenticated driver endpoints:
  GET  /drivers/me/badges                 — view own badges (including revoked)

Admin endpoints:
  POST   /admin/drivers/{driver_id}/badges                      — award badge
  DELETE /admin/drivers/{driver_id}/badges/{badge_type}         — revoke badge
  POST   /admin/drivers/{driver_id}/badges/check-eligibility    — auto-award eligible
  GET    /admin/badge-stats                                      — platform statistics

Cooperative differentiator: transparent peer recognition that Uber/Lyft have
never provided — riders can see driver achievements, drivers are rewarded for
community contribution.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_admin
from app.db.database import get_db
from app.models.driver_certification import BadgeType
from app.models.user import User
from app.schemas.driver_certification import (
    AwardBadgeRequest,
    BadgeEligibilityReport,
    BadgeStats,
    BadgeDriverSummary,
    DriverBadgeListResponse,
    DriverBadgeResponse,
    RevokeBadgeRequest,
)
from app.services.driver_certification import (
    auto_award_eligible_badges,
    award_badge,
    check_badge_eligibility,
    get_badge_stats,
    get_driver_badges,
    revoke_badge,
)

router = APIRouter(tags=["driver-certifications"])


# ---------------------------------------------------------------------------
# Public: any driver's active badges
# ---------------------------------------------------------------------------


@router.get(
    "/drivers/{driver_id}/badges",
    response_model=DriverBadgeListResponse,
    summary="List a driver's active certification badges",
)
async def list_driver_badges(
    driver_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Return all active badges for a driver.

    Intended for the rider app — shown during ride matching to give riders
    confidence in their driver's qualifications and community standing.
    """
    badges = await get_driver_badges(db, driver_id, active_only=True)
    responses = [DriverBadgeResponse.model_validate(b) for b in badges]
    return DriverBadgeListResponse(
        badges=responses,
        total=len(responses),
        active_count=len(responses),
    )


# ---------------------------------------------------------------------------
# Driver: own badges (including revoked history)
# ---------------------------------------------------------------------------


@router.get(
    "/drivers/me/badges",
    response_model=DriverBadgeListResponse,
    summary="View your own certification badges",
)
async def my_badges(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all badges for the authenticated driver, including revoked ones.

    Drivers can review their badge history and understand what was revoked and
    when, promoting accountability and transparency.
    """
    badges = await get_driver_badges(db, user.id, active_only=False)
    responses = [DriverBadgeResponse.model_validate(b) for b in badges]
    active_count = sum(1 for b in badges if b.is_active)
    return DriverBadgeListResponse(
        badges=responses,
        total=len(responses),
        active_count=active_count,
    )


# ---------------------------------------------------------------------------
# Admin: award badge
# ---------------------------------------------------------------------------


@router.post(
    "/admin/drivers/{driver_id}/badges",
    response_model=DriverBadgeResponse,
    status_code=status.HTTP_200_OK,
    summary="Award a certification badge to a driver",
    dependencies=[Depends(require_admin)],
)
async def admin_award_badge(
    driver_id: int,
    body: AwardBadgeRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Admin: award a certification badge to a driver.

    Returns 409 if the driver already holds an active badge of that type.
    If the driver previously held the badge and it was revoked, this re-activates
    it rather than creating a duplicate record.
    """
    cert = await award_badge(
        db,
        driver_id=driver_id,
        badge_type=body.badge_type,
        awarded_by=user.id,
        notes=body.notes,
    )
    return DriverBadgeResponse.model_validate(cert)


# ---------------------------------------------------------------------------
# Admin: revoke badge
# ---------------------------------------------------------------------------


@router.delete(
    "/admin/drivers/{driver_id}/badges/{badge_type}",
    response_model=DriverBadgeResponse,
    summary="Revoke a certification badge from a driver",
    dependencies=[Depends(require_admin)],
)
async def admin_revoke_badge(
    driver_id: int,
    badge_type: BadgeType,
    body: RevokeBadgeRequest = Depends(),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Admin: revoke an active certification badge.

    Returns 404 if the driver does not hold an active badge of that type.
    The revocation is recorded with timestamp and admin ID for audit purposes.
    """
    cert = await revoke_badge(
        db,
        driver_id=driver_id,
        badge_type=badge_type,
        revoked_by=user.id,
        notes=body.notes,
    )
    return DriverBadgeResponse.model_validate(cert)


# ---------------------------------------------------------------------------
# Admin: check eligibility and auto-award
# ---------------------------------------------------------------------------


@router.post(
    "/admin/drivers/{driver_id}/badges/check-eligibility",
    response_model=BadgeEligibilityReport,
    summary="Check badge eligibility and auto-award eligible badges",
    dependencies=[Depends(require_admin)],
)
async def admin_check_eligibility(
    driver_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Admin: evaluate a driver's eligibility for all badge types and award any
    eligible badges they don't yet hold.

    Returns the full eligibility report and a list of newly awarded badge types.
    Safe to call repeatedly — already-active badges are never duplicated.
    """
    results = await check_badge_eligibility(db, driver_id)
    newly_awarded = await auto_award_eligible_badges(db, driver_id)
    return BadgeEligibilityReport(
        driver_id=driver_id,
        results=results,
        newly_awarded=newly_awarded,
    )


# ---------------------------------------------------------------------------
# Admin: platform-wide statistics
# ---------------------------------------------------------------------------


@router.get(
    "/admin/badge-stats",
    response_model=BadgeStats,
    summary="Platform-wide driver badge statistics",
    dependencies=[Depends(require_admin)],
)
async def admin_badge_stats(
    db: AsyncSession = Depends(get_db),
):
    """Admin: platform-wide badge statistics.

    Includes total active badges, breakdown by badge type, and the top 10
    most-badged drivers — useful for cooperative governance reporting.
    """
    stats = await get_badge_stats(db)
    top_drivers = [BadgeDriverSummary(**d) for d in stats["top_drivers"]]
    return BadgeStats(
        total_active=stats["total_active"],
        by_type=stats["by_type"],
        top_drivers=top_drivers,
    )
