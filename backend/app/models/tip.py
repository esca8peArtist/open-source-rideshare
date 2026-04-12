"""TipRecord model — standalone tip transaction attached to a completed ride.

Tips use integer cents throughout to avoid floating-point rounding errors.
Each ride may have at most one tip (enforced by UniqueConstraint on ride_id).
"""

import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class TipStatus(str, enum.Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    REFUNDED = "refunded"


class TipRecord(Base):
    """A tip paid by a rider to a driver after a completed ride.

    amount_cents is stored as an integer (e.g. 500 = $5.00) to prevent
    floating-point rounding errors in financial calculations.
    """

    __tablename__ = "tip_records"
    __table_args__ = (
        UniqueConstraint("ride_id", name="uq_tip_ride"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    ride_id: Mapped[int] = mapped_column(ForeignKey("rides.id"), index=True)
    driver_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    rider_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)

    amount_cents: Mapped[int] = mapped_column(Integer)
    stripe_payment_intent_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    status: Mapped[TipStatus] = mapped_column(Enum(TipStatus), default=TipStatus.PENDING)

    thank_you_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    ride = relationship("Ride", foreign_keys=[ride_id])
    driver = relationship("User", foreign_keys=[driver_id])
    rider = relationship("User", foreign_keys=[rider_id])
