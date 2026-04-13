from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.promo import PromoCode, PromoRedemption, PromoType
from app.models.ride import Ride, RideStatus

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PromoValidation:
    valid: bool
    reason: str
    discount: float = 0.0  # Calculated discount amount for the given fare
    promo_code_id: int | None = None


async def validate_promo(
    code: str,
    user_id: int,
    fare: float,
    db: AsyncSession,
) -> PromoValidation:
    """Validate a promo code for a specific user and fare amount.

    Returns a PromoValidation with the calculated discount if valid.
    """
    result = await db.execute(
        select(PromoCode).where(PromoCode.code == code.upper().strip())
    )
    promo = result.scalar_one_or_none()

    if not promo:
        return PromoValidation(valid=False, reason="Invalid promo code")

    if not promo.is_active:
        return PromoValidation(valid=False, reason="This promo code is no longer active")

    now = datetime.now(timezone.utc)
    if promo.expires_at and promo.expires_at < now:
        return PromoValidation(valid=False, reason="This promo code has expired")

    if promo.max_uses is not None and promo.total_uses >= promo.max_uses:
        return PromoValidation(valid=False, reason="This promo code has reached its usage limit")

    # Check per-user usage limit
    user_uses_result = await db.execute(
        select(func.count(PromoRedemption.id)).where(
            PromoRedemption.promo_code_id == promo.id,
            PromoRedemption.user_id == user_id,
        )
    )
    user_uses = user_uses_result.scalar() or 0
    if user_uses >= promo.max_uses_per_user:
        return PromoValidation(valid=False, reason="You have already used this promo code")

    if fare < promo.minimum_fare:
        return PromoValidation(
            valid=False,
            reason=f"Minimum fare of ${promo.minimum_fare:.2f} required for this promo",
        )

    # First-ride-only check
    if promo.first_ride_only:
        completed_rides = await db.execute(
            select(func.count(Ride.id)).where(
                Ride.rider_id == user_id,
                Ride.status == RideStatus.COMPLETED,
            )
        )
        if (completed_rides.scalar() or 0) > 0:
            return PromoValidation(valid=False, reason="This promo code is for first rides only")

    # Calculate discount
    discount = _calculate_discount(promo, fare)

    return PromoValidation(
        valid=True,
        reason="Promo code applied",
        discount=round(discount, 2),
        promo_code_id=promo.id,
    )


def _calculate_discount(promo: PromoCode, fare: float) -> float:
    """Calculate the discount amount for a promo code and fare."""
    if promo.promo_type == PromoType.FLAT:
        discount = min(promo.value, fare)  # Can't discount more than the fare
    else:  # PERCENT
        discount = fare * (promo.value / 100.0)
        if promo.max_discount is not None:
            discount = min(discount, promo.max_discount)
        discount = min(discount, fare)

    return discount


async def redeem_promo(
    promo_code_id: int,
    user_id: int,
    ride_id: int,
    discount_amount: float,
    db: AsyncSession,
) -> PromoRedemption:
    """Record a promo code redemption and increment the usage counter."""
    redemption = PromoRedemption(
        promo_code_id=promo_code_id,
        user_id=user_id,
        ride_id=ride_id,
        discount_amount=discount_amount,
    )
    db.add(redemption)

    # Increment total_uses on the promo code
    result = await db.execute(
        select(PromoCode).where(PromoCode.id == promo_code_id)
    )
    promo = result.scalar_one()
    promo.total_uses += 1

    await db.flush()
    logger.info(
        "Promo code %d redeemed by user %d on ride %d: -$%.2f",
        promo_code_id, user_id, ride_id, discount_amount,
    )
    return redemption


async def get_referral_promo_for_user(
    referrer_user_id: int,
    db: AsyncSession,
) -> PromoCode | None:
    """Get the referral promo code for a user, if one exists."""
    result = await db.execute(
        select(PromoCode).where(
            PromoCode.is_referral == True,  # noqa: E712
            PromoCode.description.contains(f"referrer:{referrer_user_id}"),
        )
    )
    return result.scalar_one_or_none()


async def create_referral_promo(
    referrer_user_id: int,
    referral_code: str,
    db: AsyncSession,
) -> PromoCode:
    """Create a referral promo code for a user.

    Referral promos: $5 off, first ride only, unlimited total uses (one per referee).
    """
    promo = PromoCode(
        code=referral_code,
        description=f"Referral code — referrer:{referrer_user_id}",
        promo_type=PromoType.FLAT,
        value=5.00,
        max_uses=None,  # Unlimited total
        max_uses_per_user=1,
        first_ride_only=True,
        is_referral=True,
        is_active=True,
    )
    db.add(promo)
    await db.flush()
    logger.info("Referral promo code %s created for user %d", referral_code, referrer_user_id)
    return promo
