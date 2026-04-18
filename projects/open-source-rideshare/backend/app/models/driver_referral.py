import enum
import secrets
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class DriverReferralStatus(str, enum.Enum):
    PENDING = "pending"   # milestone not yet reached
    AWARDED = "awarded"   # milestone hit; bonus not yet paid out
    PAID = "paid"         # included in a driver payout


def generate_driver_referral_code() -> str:
    """Generate a unique 9-character driver referral code prefixed with 'D'."""
    return "D" + secrets.token_urlsafe(6)[:8].upper()


class DriverReferral(Base):
    """Tracks one driver-to-driver referral relationship.

    Created when a referred driver applies the referrer's code.
    Bonus is awarded when the referee completes `milestone_rides` trips.
    """

    __tablename__ = "driver_referrals"
    __table_args__ = (
        UniqueConstraint("referrer_driver_id", "referee_driver_id", name="uq_driver_referral_pair"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    referrer_driver_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    referee_driver_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)

    milestone_rides: Mapped[int] = mapped_column(default=10)
    bonus_amount: Mapped[float] = mapped_column(default=50.0)

    status: Mapped[DriverReferralStatus] = mapped_column(
        Enum(DriverReferralStatus), default=DriverReferralStatus.PENDING
    )
    awarded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    paid_on_payout_id: Mapped[int | None] = mapped_column(
        ForeignKey("driver_payouts.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    referrer = relationship("User", foreign_keys=[referrer_driver_id])
    referee = relationship("User", foreign_keys=[referee_driver_id])
