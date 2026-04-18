"""Rider safety check-in timer model.

A rider starts a countdown timer.  If they do not confirm they are safe
before the timer expires, the platform notifies their trusted contacts.
"""

import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class CheckInTimerStatus(str, enum.Enum):
    ACTIVE = "active"
    CONFIRMED = "confirmed"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class RiderCheckInTimer(Base):
    __tablename__ = "rider_check_in_timers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rider_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[CheckInTimerStatus] = mapped_column(
        Enum(CheckInTimerStatus),
        default=CheckInTimerStatus.ACTIVE,
        nullable=False,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expired_notified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
