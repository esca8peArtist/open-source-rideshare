"""Driver-to-driver referral service.

When a driver refers another driver (using their unique referral code), the
referee applies that code to create a DriverReferral record.  Once the referee
completes `milestone_rides` trips, the referrer earns `bonus_amount` (default
$50).  The bonus is surfaced in the payout flow.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.driver import DriverProfile
from app.models.driver_referral import DriverReferral, DriverReferralStatus, generate_driver_referral_code

logger = logging.getLogger(__name__)

DRIVER_REFERRAL_MILESTONE = 10   # rides the referee must complete
DRIVER_REFERRAL_BONUS = 50.0     # dollars awarded to referrer


async def create_or_get_driver_referral_code(
    driver_user_id: int,
    db: AsyncSession,
) -> str:
    """Return the driver's referral code, generating one if none exists.

    Idempotent — repeated calls return the same code.
    """
    result = await db.execute(
        select(DriverProfile).where(DriverProfile.user_id == driver_user_id)
    )
    profile = result.scalar_one_or_none()
    if profile is None:
        raise ValueError(f"No driver profile found for user {driver_user_id}")

    if profile.driver_referral_code:
        return profile.driver_referral_code

    # Generate a unique code (retry on collision)
    for _ in range(5):
        candidate = generate_driver_referral_code()
        collision = await db.execute(
            select(DriverProfile).where(DriverProfile.driver_referral_code == candidate)
        )
        if not collision.scalar_one_or_none():
            break

    profile.driver_referral_code = candidate
    await db.flush()
    logger.info("Driver referral code %s created for user %d", candidate, driver_user_id)
    return candidate


async def apply_driver_referral_code(
    code: str,
    referee_user_id: int,
    db: AsyncSession,
) -> DriverReferral:
    """Link a referee driver to the referrer who owns `code`.

    Raises:
        ValueError: code not found, self-referral, or already applied a code.
    """
    code = code.strip().upper()

    # Find the referrer's profile by code
    result = await db.execute(
        select(DriverProfile).where(DriverProfile.driver_referral_code == code)
    )
    referrer_profile = result.scalar_one_or_none()
    if referrer_profile is None:
        raise ValueError("Referral code not found")

    referrer_user_id = referrer_profile.user_id

    if referrer_user_id == referee_user_id:
        raise ValueError("Cannot apply your own referral code")

    # Check that the referee hasn't already applied any code
    existing = await db.execute(
        select(DriverReferral).where(DriverReferral.referee_driver_id == referee_user_id)
    )
    if existing.scalar_one_or_none():
        raise ValueError("You have already applied a driver referral code")

    referral = DriverReferral(
        referrer_driver_id=referrer_user_id,
        referee_driver_id=referee_user_id,
        milestone_rides=DRIVER_REFERRAL_MILESTONE,
        bonus_amount=DRIVER_REFERRAL_BONUS,
        status=DriverReferralStatus.PENDING,
    )
    db.add(referral)
    await db.flush()
    logger.info(
        "Driver referral applied: referrer=%d, referee=%d, milestone=%d",
        referrer_user_id, referee_user_id, DRIVER_REFERRAL_MILESTONE,
    )
    return referral


async def check_and_award_driver_referral_bonus(
    referee_user_id: int,
    completed_trips: int,
    db: AsyncSession,
) -> DriverReferral | None:
    """Award the referrer's bonus if the referee has just hit the milestone.

    Called inside complete_ride after total_trips is incremented.
    Idempotent — won't award twice for the same referral.

    Returns the updated DriverReferral if a bonus was just awarded, else None.
    """
    result = await db.execute(
        select(DriverReferral).where(
            DriverReferral.referee_driver_id == referee_user_id,
            DriverReferral.status == DriverReferralStatus.PENDING,
        )
    )
    referral = result.scalar_one_or_none()
    if referral is None:
        return None

    if completed_trips >= referral.milestone_rides:
        referral.status = DriverReferralStatus.AWARDED
        referral.awarded_at = datetime.now(timezone.utc)
        await db.flush()
        logger.info(
            "Driver referral bonus $%.2f awarded: referrer=%d after referee=%d completed %d trips",
            referral.bonus_amount, referral.referrer_driver_id,
            referee_user_id, completed_trips,
        )
        return referral

    return None


async def get_driver_referral_stats(
    referrer_user_id: int,
    db: AsyncSession,
) -> dict:
    """Return stats for a referrer: count, pending bonus, total paid."""
    result = await db.execute(
        select(DriverReferral).where(DriverReferral.referrer_driver_id == referrer_user_id)
    )
    referrals = result.scalars().all()

    total_referrals = len(referrals)
    pending_bonus = sum(r.bonus_amount for r in referrals if r.status == DriverReferralStatus.AWARDED)
    total_paid = sum(r.bonus_amount for r in referrals if r.status == DriverReferralStatus.PAID)
    return {
        "total_referrals": total_referrals,
        "pending_bonus": round(pending_bonus, 2),
        "total_paid": round(total_paid, 2),
    }


async def get_driver_referral_bonuses(
    referrer_user_id: int,
    db: AsyncSession,
) -> list[DriverReferral]:
    """Return all referral records for a referrer, newest-first."""
    result = await db.execute(
        select(DriverReferral)
        .where(DriverReferral.referrer_driver_id == referrer_user_id)
        .order_by(DriverReferral.created_at.desc())
    )
    return list(result.scalars().all())


async def mark_driver_referral_bonuses_paid(
    referrer_user_id: int,
    payout_id: int,
    db: AsyncSession,
) -> float:
    """Mark all AWARDED bonuses as PAID for a given payout.

    Returns the total amount marked paid (for inclusion in payout totals).
    """
    result = await db.execute(
        select(DriverReferral).where(
            DriverReferral.referrer_driver_id == referrer_user_id,
            DriverReferral.status == DriverReferralStatus.AWARDED,
        )
    )
    bonuses = result.scalars().all()
    total = 0.0
    now = datetime.now(timezone.utc)
    for bonus in bonuses:
        bonus.status = DriverReferralStatus.PAID
        bonus.paid_at = now
        bonus.paid_on_payout_id = payout_id
        total += bonus.bonus_amount
    await db.flush()
    return round(total, 2)
