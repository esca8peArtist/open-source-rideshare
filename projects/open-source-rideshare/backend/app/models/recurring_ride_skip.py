"""Tracks skipped occurrences for a recurring ride template."""

from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class RecurringRideSkip(Base):
    __tablename__ = "recurring_ride_skips"
    __table_args__ = (
        UniqueConstraint("recurring_ride_id", "skip_date", name="uq_recurring_ride_skip"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    recurring_ride_id: Mapped[int] = mapped_column(
        ForeignKey("recurring_rides.id"), index=True
    )
    # Date to skip, expressed in the rider's local timezone (same frame as days_of_week)
    skip_date: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    recurring_ride = relationship("RecurringRide", back_populates="skips")
