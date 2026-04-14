"""Surge price lock model.

A rider can lock the current demand multiplier for their pickup location for a
short window (LOCK_DURATION_MINUTES).  If they complete a ride booking within
that window, the locked multiplier is used instead of recalculating from the
current demand level.

This prevents the "I checked the price, got distracted for 2 minutes, and now
it's higher" frustration without meaningfully gaming surge pricing — the window
is short, the lock is single-use, and only one lock is active at a time.
"""

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class SurgePriceLock(Base):
    __tablename__ = "surge_price_locks"

    id: Mapped[int] = mapped_column(primary_key=True)

    # The rider who created the lock.
    rider_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)

    # Pickup location captured at lock time (for informational display; we do
    # not enforce proximity at booking time — that would add friction).
    pickup_lat: Mapped[float] = mapped_column(Float)
    pickup_lon: Mapped[float] = mapped_column(Float)
    pickup_address: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # The multiplier that was active at lock creation.
    locked_multiplier: Mapped[float] = mapped_column(Float)

    # Lifecycle timestamps.
    locked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    # Set when the rider books a ride while the lock is active.
    used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # The ride that consumed this lock.
    ride_id: Mapped[int | None] = mapped_column(
        ForeignKey("rides.id"), nullable=True, index=True
    )

    # Set when the rider explicitly cancels before using the lock.
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    rider = relationship("User", foreign_keys=[rider_id], backref="surge_price_locks")
