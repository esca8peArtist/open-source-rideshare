import enum
import secrets
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class PromoType(str, enum.Enum):
    FLAT = "flat"          # Fixed dollar amount off
    PERCENT = "percent"    # Percentage discount


class PromoCode(Base):
    __tablename__ = "promo_codes"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    description: Mapped[str] = mapped_column(String(500), default="")
    promo_type: Mapped[PromoType] = mapped_column(Enum(PromoType))
    value: Mapped[float]  # Dollar amount for FLAT, percentage (0-100) for PERCENT
    max_discount: Mapped[float | None] = mapped_column(nullable=True)  # Cap for PERCENT codes
    minimum_fare: Mapped[float] = mapped_column(default=0.0)  # Minimum fare to apply

    max_uses: Mapped[int | None] = mapped_column(nullable=True)  # Total uses across all users
    max_uses_per_user: Mapped[int] = mapped_column(default=1)   # Uses per individual user
    total_uses: Mapped[int] = mapped_column(default=0)

    is_active: Mapped[bool] = mapped_column(default=True)
    first_ride_only: Mapped[bool] = mapped_column(default=False)  # Only for users with 0 completed rides
    is_referral: Mapped[bool] = mapped_column(default=False)  # Auto-generated referral code

    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    redemptions = relationship("PromoRedemption", back_populates="promo_code")


class PromoRedemption(Base):
    __tablename__ = "promo_redemptions"
    __table_args__ = (
        UniqueConstraint("promo_code_id", "ride_id", name="uq_promo_ride"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    promo_code_id: Mapped[int] = mapped_column(ForeignKey("promo_codes.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    ride_id: Mapped[int | None] = mapped_column(ForeignKey("rides.id"), nullable=True, index=True)
    discount_amount: Mapped[float]  # Actual discount applied
    redeemed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    promo_code = relationship("PromoCode", back_populates="redemptions")
    user = relationship("User")
    ride = relationship("Ride")


def generate_referral_code() -> str:
    """Generate a unique 8-character referral code."""
    return secrets.token_urlsafe(6)[:8].upper()
