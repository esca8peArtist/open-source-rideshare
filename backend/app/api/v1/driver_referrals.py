"""Driver referral program endpoints.

Driver endpoints (require driver auth):
  GET  /drivers/me/referral          — get my code + aggregate summary
  POST /drivers/me/referral/apply    — apply another driver's code (once)
  GET  /drivers/me/referral/referred — list drivers I referred (paginated)

Admin endpoints (require admin auth):
  GET  /admin/referrals/stats        — platform-wide referral statistics
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin, require_driver
from app.db.database import get_db
from app.models.driver import DriverProfile
from app.models.user import User
from app.schemas.driver_referral import (
    AdminReferralStats,
    ApplyReferralRequest,
    ApplyReferralResponse,
    ReferralCodeResponse,
    ReferralListResponse,
)
from app.services import driver_referrals as svc
from sqlalchemy import select

router = APIRouter(tags=["driver-referrals"])


async def _get_driver_profile_id(user: User, db: AsyncSession) -> int:
    result = await db.execute(
        select(DriverProfile).where(DriverProfile.user_id == user.id)
    )
    profile = result.scalar_one_or_none()
    if profile is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Driver profile not found")
    return profile.id


# ---------------------------------------------------------------------------
# Driver endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/drivers/me/referral",
    response_model=ReferralCodeResponse,
    summary="Get my referral code and summary",
)
async def get_my_referral_code(
    user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    """Return the calling driver's unique referral code and aggregate stats.

    If the driver has never requested a code before, one is created on the fly.
    """
    profile_id = await _get_driver_profile_id(user, db)
    return await svc.get_referral_summary(db, profile_id)


@router.post(
    "/drivers/me/referral/apply",
    response_model=ApplyReferralResponse,
    summary="Apply a referral code at onboarding",
)
async def apply_referral_code(
    req: ApplyReferralRequest,
    user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    """Apply another driver's referral code.

    A driver may only apply a code once.  Returns success=False (not 4xx) for
    business-logic failures (invalid code, already applied, own code).
    """
    profile_id = await _get_driver_profile_id(user, db)
    return await svc.apply_referral_code(db, profile_id, req.code)


@router.get(
    "/drivers/me/referral/referred",
    response_model=ReferralListResponse,
    summary="List drivers I referred",
)
async def list_my_referrals(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    """Return a paginated list of drivers this driver has referred, newest first."""
    profile_id = await _get_driver_profile_id(user, db)
    return await svc.get_my_referrals(db, profile_id, limit=limit, offset=offset)


# ---------------------------------------------------------------------------
# Admin endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/admin/referrals/stats",
    response_model=AdminReferralStats,
    summary="Platform-wide referral statistics",
)
async def admin_referral_stats(
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return aggregate referral counts and bonus totals across all drivers."""
    return await svc.get_admin_stats(db)
