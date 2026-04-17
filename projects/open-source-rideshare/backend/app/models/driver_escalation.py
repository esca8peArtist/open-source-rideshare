"""Driver accountability escalation model.

Tracks the progressive warning/suspension state for a driver based on
repeated performance alerts (high no-show rate, low score, etc.).

Escalation levels
-----------------
- none         — no outstanding warnings
- warning      — 1st offence: driver notified, coaching encouraged
- final_warning — 2nd offence: driver told one more will result in suspension
- suspended    — 3rd offence: driver auto-suspended; admin must review before reinstatement

The warning count resets to 1 (not 0) when a new alert fires more than
RESET_WINDOW_DAYS after the previous warning — a long clean stretch earns
a fresh start but the new offence is still counted.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base

# Days of clean operation before the warning counter resets
RESET_WINDOW_DAYS = 28


class DriverEscalation(Base):
    """Persisted escalation state for a driver.

    One row per driver.  The row is created on the first alert and updated
    on every subsequent escalation event.  ``warning_count`` is incremented
    each time an escalation-triggering alert fires (subject to the reset
    window); ``escalation_level`` is set to the corresponding severity.
    """

    __tablename__ = "driver_escalations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    driver_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, unique=True, index=True
    )

    # Cumulative warning count for the current streak (resets after RESET_WINDOW_DAYS clean)
    warning_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Current escalation level: none | warning | final_warning | suspended
    escalation_level: Mapped[str] = mapped_column(
        String(20), default="none", nullable=False
    )

    # The alert type that most recently triggered an escalation event
    last_trigger_type: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # When the most recent warning/escalation was issued
    last_warning_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # When an auto-suspension was triggered (None if not yet auto-suspended)
    auto_suspended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Optional note added when an admin resets the escalation
    admin_reset_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reset_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    last_reset_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    driver = relationship("User", foreign_keys=[driver_id])
    resetting_admin = relationship("User", foreign_keys=[reset_by])

    __table_args__ = (
        Index("ix_driver_escalation_driver_id", "driver_id"),
        Index("ix_driver_escalation_level", "escalation_level"),
    )
