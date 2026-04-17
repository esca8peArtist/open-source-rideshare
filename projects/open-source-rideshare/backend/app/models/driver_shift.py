"""Driver shift model.

Tracks shift sessions for drivers — when they are actively working on the
platform. Used for fatigue monitoring and welfare summaries.
"""

import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class ShiftStatus(str, enum.Enum):
    active = "active"
    completed = "completed"
    auto_ended = "auto_ended"


class DriverShift(Base):
    """A single work session for a driver."""

    __tablename__ = "driver_shifts"

    id: Mapped[int] = mapped_column(primary_key=True)
    driver_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    status: Mapped[ShiftStatus] = mapped_column(
        Enum(ShiftStatus), nullable=False, default=ShiftStatus.active
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Pre-computed duration in minutes (populated when shift ends)
    total_minutes: Mapped[float | None] = mapped_column(Float, nullable=True)
    rides_completed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    driver = relationship("User", foreign_keys=[driver_id])
