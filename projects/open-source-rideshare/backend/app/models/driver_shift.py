"""Driver shift and hours-tracking model.

Drivers clock in (start a shift) and clock out (end a shift). The platform
records total hours worked per day and per week so that:

  1. Cooperative governance: the platform can surface fatigue warnings and
     enforce configurable safety limits (default: 12 h/day, 60 h/week).
  2. Transparency: drivers see their own hours history at any time.
  3. Admin visibility: operators can identify drivers approaching or exceeding
     safe-driving limits before an incident occurs.

This is a deliberate cooperative differentiator — Uber and Lyft impose no
such protections and have faced regulatory scrutiny for driver fatigue.

Shift lifecycle
---------------
  active      — shift started, no end time yet
  completed   — driver ended the shift normally
  auto_ended  — admin or system force-ended the shift (e.g. exceeded limit)
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum as SAEnum, Float, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class ShiftStatus(str, enum.Enum):
    active = "active"
    completed = "completed"
    auto_ended = "auto_ended"


class DriverShift(Base):
    """One contiguous on-shift window for a driver."""

    __tablename__ = "driver_shifts"

    id: Mapped[int] = mapped_column(primary_key=True)

    driver_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    status: Mapped[ShiftStatus] = mapped_column(
        SAEnum(ShiftStatus, name="shiftstatusenum"),
        nullable=False,
        default=ShiftStatus.active,
    )

    # Rides dispatched / accepted during this shift (updated by the ride engine).
    rides_completed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Total shift length in minutes, computed when the shift ends.
    total_minutes: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Optional note recorded when an admin force-ends a shift.
    admin_note: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Who force-ended the shift (admin user id).
    ended_by_admin_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    driver = relationship("User", foreign_keys=[driver_id], backref="driver_shifts")
    ended_by_admin = relationship("User", foreign_keys=[ended_by_admin_id])
