"""Service layer for the rider referral program.

Constants
---------
REFERRER_REWARD_USD     Ride credit earned by the referrer when their referred
                        rider completes a first ride.
REFERRED_DISCOUNT_USD   First-ride discount applied to the referred rider
                        (tracked here; actual discount applied via promo system).

Public API
----------
get_or_create_referral_code   Return (or create) this rider's unique referral code.
apply_referral_code           Record a new rider's use of a referral code.
record_first_ride_completion  Called after a rider's first ride; qualifies the referral.
get_referral_summary          Code + aggregate stats for the referrer.
get_my_referrals              Paginated list of referrals made by this rider.
get_admin_stats               Platform-wide aggregate statistics.
"""

from __future__ import annotations

import logging
import random
import string
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import func, select

from app.models.rider_referral import (
    RiderReferral,
    RiderReferralCode,
    RiderReferralStatus,
)
from app.schemas.rider_referral import (
    AdminRiderReferralStats,
    ApplyRiderReferralResponse,
    RiderReferralCodeResponse,
    RiderReferralItem,
    RiderReferralListResponse,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

REFERRER_REWARD_USD: float = 10.00
REFERRED_DISCOUNT_USD: float = 5.00
_CODE_CHARS = string.ascii_uppercase + string.digits
_CODE_LENGTH = 8


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _make_code() -> str:
    return "".join(random.choices(_CODE_CHARS, k=_CODE_LENGTH))


async def _unique_code(db: AsyncSession) -> str:
    for _ in range(20):
        candidate = _make_code()
        existing = await db.execute(
            select(RiderReferralCode).where(RiderReferralCode.code == candidate)
        )
        if existing.scalar_one_or_none() is None:
            return candidate
    raise RuntimeError("Failed to generate a unique rider referral code after 20 attempts")


# ---------------------------------------------------------------------------
# Public service functions
# ---------------------------------------------------------------------------


async def get_or_create_referral_code(
    db: AsyncSession,
    user_id: int,
) -> RiderReferralCode:
    """Return the rider's existing code or create a new one."""
    result = await db.execute(
        select(RiderReferralCode).where(RiderReferralCode.user_id == user_id)
    )
    record = result.scalar_one_or_none()
    if record is not None:
        return record

    code = await _unique_code(db)
    record = RiderReferralCode(user_id=user_id, code=code)
    db.add(record)
    await db.flush()
    return record


async def apply_referral_code(
    db: AsyncSession,
    new_user_id: int,
    code: str,
) -> ApplyRiderReferralResponse:
    """Record a new rider's use of a referral code.

    Failure cases (returned as success=False, not raised):
    - Code does not exist.
    - Rider is trying to use their own code.
    - Rider has already been referred by someone.
    """
    # Guard: rider has not already used a code
    already = await db.execute(
        select(RiderReferral).where(RiderReferral.referred_user_id == new_user_id)
    )
    if already.scalar_one_or_none() is not None:
        return ApplyRiderReferralResponse(
            success=False,
            message="You have already applied a referral code.",
        )

    # Resolve code → referrer
    code_result = await db.execute(
        select(RiderReferralCode).where(RiderReferralCode.code == code.upper())
    )
    code_record = code_result.scalar_one_or_none()
    if code_record is None:
        return ApplyRiderReferralResponse(
            success=False,
            message="Invalid referral code.",
        )

    if code_record.user_id == new_user_id:
        return ApplyRiderReferralResponse(
            success=False,
            message="You cannot use your own referral code.",
        )

    referral = RiderReferral(
        referrer_user_id=code_record.user_id,
        referred_user_id=new_user_id,
        code_used=code.upper(),
        status=RiderReferralStatus.PENDING,
        referrer_reward_amount=REFERRER_REWARD_USD,
        referred_discount_amount=REFERRED_DISCOUNT_USD,
    )
    db.add(referral)
    await db.flush()

    return ApplyRiderReferralResponse(
        success=True,
        message=(
            f"Referral code applied! You'll receive ${REFERRED_DISCOUNT_USD:.0f} off "
            f"your first ride. Your friend will earn ${REFERRER_REWARD_USD:.0f} after "
            "you complete it."
        ),
        referrer_user_id=code_record.user_id,
    )


async def record_first_ride_completion(
    db: AsyncSession,
    user_id: int,
    ride_id: int,
) -> None:
    """Qualify the referral when the referred rider completes their first ride.

    Idempotent — does nothing if no pending referral exists or if the referral
    has already progressed past PENDING.
    """
    result = await db.execute(
        select(RiderReferral).where(
            RiderReferral.referred_user_id == user_id,
            RiderReferral.status == RiderReferralStatus.PENDING,
        )
    )
    referral = result.scalar_one_or_none()
    if referral is None:
        return

    referral.status = RiderReferralStatus.QUALIFIED
    referral.first_ride_id = ride_id
    referral.qualified_at = datetime.now(timezone.utc)
    await db.flush()


async def get_referral_summary(
    db: AsyncSession,
    user_id: int,
) -> RiderReferralCodeResponse:
    """Return the rider's code with aggregate referral stats."""
    code_record = await get_or_create_referral_code(db, user_id)

    referrals_result = await db.execute(
        select(RiderReferral).where(RiderReferral.referrer_user_id == user_id)
    )
    referrals = list(referrals_result.scalars().all())

    pending_count = sum(1 for r in referrals if r.status == RiderReferralStatus.PENDING)
    qualified_count = sum(1 for r in referrals if r.status == RiderReferralStatus.QUALIFIED)
    rewarded_count = sum(1 for r in referrals if r.status == RiderReferralStatus.REWARDED)
    total_reward = sum(
        r.referrer_reward_amount
        for r in referrals
        if r.status == RiderReferralStatus.REWARDED
    )

    return RiderReferralCodeResponse(
        code=code_record.code,
        user_id=user_id,
        total_referrals=len(referrals),
        pending_count=pending_count,
        qualified_count=qualified_count,
        rewarded_count=rewarded_count,
        total_reward_earned=total_reward,
        created_at=code_record.created_at,
    )


async def get_my_referrals(
    db: AsyncSession,
    user_id: int,
    limit: int = 50,
    offset: int = 0,
) -> RiderReferralListResponse:
    """Return a paginated list of referrals made by this rider."""
    code_record = await get_or_create_referral_code(db, user_id)

    total_result = await db.execute(
        select(func.count()).select_from(RiderReferral).where(
            RiderReferral.referrer_user_id == user_id
        )
    )
    total = total_result.scalar_one()

    referrals_result = await db.execute(
        select(RiderReferral)
        .where(RiderReferral.referrer_user_id == user_id)
        .order_by(RiderReferral.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    referrals = list(referrals_result.scalars().all())

    items = [
        RiderReferralItem(
            referral_id=r.id,
            referred_user_id=r.referred_user_id,
            status=r.status.value,
            first_ride_id=r.first_ride_id,
            referrer_reward_amount=r.referrer_reward_amount,
            referred_discount_amount=r.referred_discount_amount,
            created_at=r.created_at,
            qualified_at=r.qualified_at,
        )
        for r in referrals
    ]

    return RiderReferralListResponse(
        code=code_record.code,
        referrals=items,
        total=total,
    )


async def get_admin_stats(db: AsyncSession) -> AdminRiderReferralStats:
    """Return platform-wide rider referral aggregate statistics."""
    total_codes_result = await db.execute(
        select(func.count()).select_from(RiderReferralCode)
    )
    total_codes = total_codes_result.scalar_one()

    total_ref_result = await db.execute(
        select(func.count()).select_from(RiderReferral)
    )
    total_referrals = total_ref_result.scalar_one()

    pending_result = await db.execute(
        select(func.count()).select_from(RiderReferral).where(
            RiderReferral.status == RiderReferralStatus.PENDING
        )
    )
    pending = pending_result.scalar_one()

    qualified_result = await db.execute(
        select(func.count()).select_from(RiderReferral).where(
            RiderReferral.status == RiderReferralStatus.QUALIFIED
        )
    )
    qualified = qualified_result.scalar_one()

    rewarded_result = await db.execute(
        select(func.count()).select_from(RiderReferral).where(
            RiderReferral.status == RiderReferralStatus.REWARDED
        )
    )
    rewarded = rewarded_result.scalar_one()

    reward_sum_result = await db.execute(
        select(func.coalesce(func.sum(RiderReferral.referrer_reward_amount), 0.0)).where(
            RiderReferral.status == RiderReferralStatus.REWARDED
        )
    )
    total_reward_paid = float(reward_sum_result.scalar_one())

    return AdminRiderReferralStats(
        total_codes_issued=total_codes,
        total_referrals=total_referrals,
        pending_count=pending,
        qualified_count=qualified,
        rewarded_count=rewarded,
        total_reward_paid_amount=total_reward_paid,
    )
