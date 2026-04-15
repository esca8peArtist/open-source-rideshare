"""Rider referral program models.

Each rider gets a unique referral code.  When a new rider applies a code
and completes their first ride, the referrer earns a ride credit and the
referred rider receives a first-ride discount.
"""

import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class RiderReferralStatus(str, enum.Enum):
    PENDING = "pending"          # code applied; referred user hasn't completed first ride
    QUALIFIED = "qualified"      # referred user completed first ride; reward pending
    REWARDED = "rewarded"        # referrer reward credited


class RiderReferralCode(Base):
    """One referral code per rider.  Generated on first request."""

    __tablename__ = "rider_referral_codes"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), unique=True, index=True
    )
    code: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class RiderReferral(Base):
    """Tracks a single referral relationship between two riders.

    A rider can only be referred once (referred_user_id is unique).
    The referrer earns REFERRER_REWARD_USD once the referred rider completes
    their first ride.  The referred rider is eligible for REFERRED_DISCOUNT_USD
    off their first ride via the promo system.
    """

    __tablename__ = "rider_referrals"

    id: Mapped[int] = mapped_column(primary_key=True)
    referrer_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), index=True
    )
    referred_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), unique=True, index=True
    )
    code_used: Mapped[str] = mapped_column(String(16))
    status: Mapped[RiderReferralStatus] = mapped_column(
        Enum(RiderReferralStatus), default=RiderReferralStatus.PENDING
    )
    first_ride_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("rides.id"), nullable=True
    )
    referrer_reward_amount: Mapped[float] = mapped_column(Float, default=0.0)
    referred_discount_amount: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    qualified_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
