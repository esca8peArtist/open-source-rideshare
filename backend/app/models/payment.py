import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class PaymentStatus(str, enum.Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    REFUNDED = "refunded"


class PaymentType(str, enum.Enum):
    RIDE_FARE = "ride_fare"
    CANCELLATION_FEE = "cancellation_fee"


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = (
        UniqueConstraint("ride_id", "payment_type", name="uq_payment_ride_type"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    ride_id: Mapped[int] = mapped_column(ForeignKey("rides.id"), index=True)
    payment_type: Mapped[PaymentType] = mapped_column(
        Enum(PaymentType), default=PaymentType.RIDE_FARE,
    )
    stripe_payment_intent_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    amount: Mapped[float]
    platform_fee: Mapped[float]
    driver_payout: Mapped[float]
    status: Mapped[PaymentStatus] = mapped_column(Enum(PaymentStatus), default=PaymentStatus.PENDING)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    tip_amount: Mapped[float] = mapped_column(default=0.0)
    tip_stripe_payment_intent_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    ride = relationship("Ride", backref="payment")
