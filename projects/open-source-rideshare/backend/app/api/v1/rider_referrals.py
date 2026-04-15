"""Rider referral program API endpoints.

Rider-facing:
  GET  /riders/me/referral-code     — get (or create) referral code + summary
  GET  /riders/me/referrals         — paginated list of referrals I've made
  POST /riders/referral/apply       — apply a friend's referral code

Admin-facing:
  GET  /admin/referrals/rider/stats — platform-wide aggregate stats
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_admin
from app.db.database import get_db
from app.models.user import User
from app.schemas.rider_referral import (
    AdminRiderReferralStats,
    ApplyRiderReferralRequest,
    ApplyRiderReferralResponse,
    RiderReferralCodeResponse,
    RiderReferralListResponse,
)
from app.services.rider_referrals import (
    apply_referral_code,
    get_admin_stats,
    get_my_referrals,
    get_referral_summary,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["rider-referrals"])

_MAX_LIMIT = 100


# ---------------------------------------------------------------------------
# Rider endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/riders/me/referral-code",
    response_model=RiderReferralCodeResponse,
    summary="Get my referral code and referral summary",
)
async def get_my_referral_code(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RiderReferralCodeResponse:
    """Return this rider's unique referral code along with aggregate stats.

    Creates a code on first call; subsequent calls are idempotent.
    """
    return await get_referral_summary(db, user.id)


@router.get(
    "/riders/me/referrals",
    response_model=RiderReferralListResponse,
    summary="List people I've referred",
)
async def list_my_referrals(
    limit: int = Query(default=50, ge=1, le=_MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RiderReferralListResponse:
    """Paginated list of referrals this rider has made."""
    return await get_my_referrals(db, user.id, limit=limit, offset=offset)


@router.post(
    "/riders/referral/apply",
    response_model=ApplyRiderReferralResponse,
    summary="Apply a referral code",
)
async def apply_my_referral_code(
    body: ApplyRiderReferralRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApplyRiderReferralResponse:
    """Apply a friend's referral code.

    - Returns `success: false` (not a 4xx) for soft failures such as invalid
      codes, self-referral, or duplicate application — the client should
      display `message` to the rider.
    - A 200 with `success: true` means the referral was recorded; the referred
      rider's first-ride discount will be honoured by the platform.
    """
    result = await apply_referral_code(db, user.id, body.code)
    await db.commit()
    return result


# ---------------------------------------------------------------------------
# Admin endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/admin/referrals/rider/stats",
    response_model=AdminRiderReferralStats,
    summary="Platform-wide rider referral statistics (admin)",
    dependencies=[Depends(require_admin)],
)
async def admin_rider_referral_stats(
    db: AsyncSession = Depends(get_db),
) -> AdminRiderReferralStats:
    """Return aggregate counts and reward totals for the rider referral programme."""
    return await get_admin_stats(db)
