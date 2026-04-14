"""Service layer for the driver referral program.

Constants
---------
QUALIFICATION_RIDES  Number of rides a referred driver must complete to qualify.
BONUS_AMOUNT         USD bonus credited to the referrer on qualification.

Public API
----------
get_or_create_referral_code   Return (or create) this driver's unique referral code.
apply_referral_code           Record a new driver's use of a referral code.
record_ride_completion        Update referral progress when a driver finishes a ride.
get_referral_summary          Code + aggregate stats for the referrer.
get_my_referrals              Paginated list of referrals made by this driver.
get_admin_stats               Platform-wide aggregate statistics.
"""

from __future__ import annotations

import logging
import random
import string
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import func, select

from app.models.driver_referral import DriverReferral, DriverReferralCode, ReferralStatus
from app.schemas.driver_referral import (
    AdminReferralStats,
    ApplyReferralResponse,
    ReferralCodeResponse,
    ReferralItem,
    ReferralListResponse,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

QUALIFICATION_RIDES: int = 10
BONUS_AMOUNT: float = 50.0
_CODE_CHARS = string.ascii_uppercase + string.digits
_CODE_LENGTH = 8


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _make_code() -> str:
    """Generate a random 8-character alphanumeric code (upper-case)."""
    return "".join(random.choices(_CODE_CHARS, k=_CODE_LENGTH))


async def _unique_code(db: AsyncSession) -> str:
    """Keep generating until we find a code not already in the DB."""
    for _ in range(20):
        candidate = _make_code()
        existing = await db.execute(
            select(DriverReferralCode).where(DriverReferralCode.code == candidate)
        )
        if existing.scalar_one_or_none() is None:
            return candidate
    raise RuntimeError("Failed to generate a unique referral code after 20 attempts")


# ---------------------------------------------------------------------------
# Public service functions
# ---------------------------------------------------------------------------


async def get_or_create_referral_code(
    db: AsyncSession,
    driver_profile_id: int,
) -> DriverReferralCode:
    """Return the driver's existing code or create a new one."""
    result = await db.execute(
        select(DriverReferralCode).where(
            DriverReferralCode.driver_profile_id == driver_profile_id
        )
    )
    record = result.scalar_one_or_none()
    if record is not None:
        return record

    code = await _unique_code(db)
    record = DriverReferralCode(driver_profile_id=driver_profile_id, code=code)
    db.add(record)
    await db.flush()
    return record


async def apply_referral_code(
    db: AsyncSession,
    new_driver_profile_id: int,
    code: str,
) -> ApplyReferralResponse:
    """Record a new driver's use of a referral code.

    Failure cases (returned as success=False, not raised):
    - Code does not exist.
    - Driver is trying to use their own code.
    - Driver has already been referred by someone.
    """
    # Check the new driver has not already used a code.
    already = await db.execute(
        select(DriverReferral).where(
            DriverReferral.referred_profile_id == new_driver_profile_id
        )
    )
    if already.scalar_one_or_none() is not None:
        return ApplyReferralResponse(
            success=False,
            message="You have already applied a referral code.",
        )

    # Resolve the code to a referrer.
    code_result = await db.execute(
        select(DriverReferralCode).where(DriverReferralCode.code == code)
    )
    code_record = code_result.scalar_one_or_none()
    if code_record is None:
        return ApplyReferralResponse(
            success=False,
            message="Invalid referral code.",
        )

    if code_record.driver_profile_id == new_driver_profile_id:
        return ApplyReferralResponse(
            success=False,
            message="You cannot use your own referral code.",
        )

    referral = DriverReferral(
        referrer_profile_id=code_record.driver_profile_id,
        referred_profile_id=new_driver_profile_id,
        code_used=code,
        status=ReferralStatus.PENDING,
        rides_completed=0,
        bonus_amount=BONUS_AMOUNT,
    )
    db.add(referral)
    await db.flush()

    return ApplyReferralResponse(
        success=True,
        message=(
            f"Referral code applied. Complete {QUALIFICATION_RIDES} rides "
            f"to unlock a ${BONUS_AMOUNT:.0f} bonus for the driver who referred you."
        ),
        referrer_driver_profile_id=code_record.driver_profile_id,
    )


async def record_ride_completion(
    db: AsyncSession,
    driver_profile_id: int,
) -> None:
    """Increment rides_completed for any pending referral where this driver was referred.

    Called whenever a driver completes a ride.  If the threshold is reached,
    the referral transitions from PENDING → QUALIFIED.
    """
    result = await db.execute(
        select(DriverReferral).where(
            DriverReferral.referred_profile_id == driver_profile_id,
            DriverReferral.status == ReferralStatus.PENDING,
        )
    )
    referral = result.scalar_one_or_none()
    if referral is None:
        return

    referral.rides_completed += 1
    if referral.rides_completed >= QUALIFICATION_RIDES:
        referral.status = ReferralStatus.QUALIFIED
        referral.qualified_at = datetime.now(timezone.utc)

    await db.flush()


async def get_referral_summary(
    db: AsyncSession,
    driver_profile_id: int,
) -> ReferralCodeResponse:
    """Return the driver's code with aggregate referral stats."""
    code_record = await get_or_create_referral_code(db, driver_profile_id)

    referrals_result = await db.execute(
        select(DriverReferral).where(
            DriverReferral.referrer_profile_id == driver_profile_id
        )
    )
    referrals = list(referrals_result.scalars().all())

    pending_count = sum(1 for r in referrals if r.status == ReferralStatus.PENDING)
    qualified_count = sum(1 for r in referrals if r.status == ReferralStatus.QUALIFIED)
    bonus_paid_count = sum(1 for r in referrals if r.status == ReferralStatus.BONUS_PAID)
    total_bonus = sum(r.bonus_amount for r in referrals if r.status == ReferralStatus.BONUS_PAID)

    return ReferralCodeResponse(
        code=code_record.code,
        driver_profile_id=driver_profile_id,
        total_referrals=len(referrals),
        pending_count=pending_count,
        qualified_count=qualified_count,
        bonus_paid_count=bonus_paid_count,
        total_bonus_earned=total_bonus,
        created_at=code_record.created_at,
    )


async def get_my_referrals(
    db: AsyncSession,
    driver_profile_id: int,
    limit: int = 50,
    offset: int = 0,
) -> ReferralListResponse:
    """Return a paginated list of referrals made by this driver."""
    code_record = await get_or_create_referral_code(db, driver_profile_id)

    total_result = await db.execute(
        select(func.count()).select_from(DriverReferral).where(
            DriverReferral.referrer_profile_id == driver_profile_id
        )
    )
    total = total_result.scalar_one()

    referrals_result = await db.execute(
        select(DriverReferral)
        .where(DriverReferral.referrer_profile_id == driver_profile_id)
        .order_by(DriverReferral.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    referrals = list(referrals_result.scalars().all())

    items = [
        ReferralItem(
            referral_id=r.id,
            referred_driver_profile_id=r.referred_profile_id,
            status=r.status.value,
            rides_completed=r.rides_completed,
            rides_needed=QUALIFICATION_RIDES,
            bonus_amount=r.bonus_amount,
            created_at=r.created_at,
            qualified_at=r.qualified_at,
        )
        for r in referrals
    ]

    return ReferralListResponse(
        code=code_record.code,
        referrals=items,
        total=total,
    )


async def get_admin_stats(db: AsyncSession) -> AdminReferralStats:
    """Return platform-wide referral aggregate statistics."""
    total_codes_result = await db.execute(
        select(func.count()).select_from(DriverReferralCode)
    )
    total_codes = total_codes_result.scalar_one()

    total_ref_result = await db.execute(
        select(func.count()).select_from(DriverReferral)
    )
    total_referrals = total_ref_result.scalar_one()

    pending_result = await db.execute(
        select(func.count()).select_from(DriverReferral).where(
            DriverReferral.status == ReferralStatus.PENDING
        )
    )
    pending = pending_result.scalar_one()

    qualified_result = await db.execute(
        select(func.count()).select_from(DriverReferral).where(
            DriverReferral.status == ReferralStatus.QUALIFIED
        )
    )
    qualified = qualified_result.scalar_one()

    paid_result = await db.execute(
        select(func.count()).select_from(DriverReferral).where(
            DriverReferral.status == ReferralStatus.BONUS_PAID
        )
    )
    bonus_paid = paid_result.scalar_one()

    bonus_sum_result = await db.execute(
        select(func.coalesce(func.sum(DriverReferral.bonus_amount), 0.0)).where(
            DriverReferral.status == ReferralStatus.BONUS_PAID
        )
    )
    total_bonus_paid = float(bonus_sum_result.scalar_one())

    return AdminReferralStats(
        total_codes_issued=total_codes,
        total_referrals=total_referrals,
        pending_count=pending,
        qualified_count=qualified,
        bonus_paid_count=bonus_paid,
        total_bonus_paid_amount=total_bonus_paid,
    )
