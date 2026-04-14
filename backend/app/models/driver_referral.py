import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class ReferralStatus(str, enum.Enum):
    PENDING = "pending"
    QUALIFIED = "qualified"
    BONUS_PAID = "bonus_paid"


class DriverReferralCode(Base):
    """One referral code per driver.  Generated on first request."""

    __tablename__ = "driver_referral_codes"

    id: Mapped[int] = mapped_column(primary_key=True)
    driver_profile_id: Mapped[int] = mapped_column(
        ForeignKey("driver_profiles.id"), unique=True, index=True
    )
    code: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class DriverReferral(Base):
    """Tracks a single referral relationship between two drivers.

    A driver can only be referred once (referred_profile_id is unique).
    The referrer earns a bonus once the referred driver completes
    QUALIFICATION_RIDES rides.
    """

    __tablename__ = "driver_referrals"

    id: Mapped[int] = mapped_column(primary_key=True)
    referrer_profile_id: Mapped[int] = mapped_column(
        ForeignKey("driver_profiles.id"), index=True
    )
    referred_profile_id: Mapped[int] = mapped_column(
        ForeignKey("driver_profiles.id"), unique=True, index=True
    )
    code_used: Mapped[str] = mapped_column(String(16))
    status: Mapped[ReferralStatus] = mapped_column(
        Enum(ReferralStatus), default=ReferralStatus.PENDING
    )
    rides_completed: Mapped[int] = mapped_column(Integer, default=0)
    bonus_amount: Mapped[float] = mapped_column(default=0.0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    qualified_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
