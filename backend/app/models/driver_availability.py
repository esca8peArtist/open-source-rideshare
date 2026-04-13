"""Driver availability models.

Two tables:
  driver_schedules      — recurring weekly availability slots per driver
  driver_online_status  — current real-time online/offline state per driver

day_of_week uses Python's datetime.weekday() convention: 0=Monday, 6=Sunday.

Break management: drivers can take short breaks (is_on_break=True) while
remaining "online" in intent.  Break status excludes them from dispatch
without requiring a full offline toggle.
"""

from datetime import datetime, time

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Time, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class DriverSchedule(Base):
    """Recurring weekly availability slot for a driver.

    A driver may have multiple non-overlapping slots per day.  The unique
    constraint on (driver_id, day_of_week, start_time) means a slot can be
    upserted by identifying it with those three fields.

    Columns
    -------
    driver_id     FK to driver_profiles.id
    day_of_week   0=Monday … 6=Sunday (datetime.weekday() convention)
    start_time    Wall-clock start of availability window
    end_time      Wall-clock end of availability window (must be > start_time)
    is_active     Soft-disable without deleting the slot
    """

    __tablename__ = "driver_schedules"

    __table_args__ = (
        UniqueConstraint(
            "driver_id",
            "day_of_week",
            "start_time",
            name="uq_driver_schedule_day_start",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    driver_id: Mapped[int] = mapped_column(
        ForeignKey("driver_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    day_of_week: Mapped[int] = mapped_column(Integer, nullable=False)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    driver = relationship("DriverProfile", backref="schedules")


class DriverOnlineStatus(Base):
    """Current online/offline/break state for a driver.

    One row per driver (driver_id is unique).  Created on first toggle;
    upserted on subsequent changes.

    Columns
    -------
    driver_id        FK to driver_profiles.id (unique — one row per driver)
    is_online        Whether the driver is currently accepting rides
    is_on_break      Whether the driver has paused to take a break.
                     A driver on break is online (intends to return) but is
                     excluded from dispatch until break ends.
    went_online_at   Timestamp of the most recent transition to online
    break_started_at Timestamp when the current break began (None if not on break)
    last_heartbeat   Timestamp of the most recent keep-alive ping
    """

    __tablename__ = "driver_online_status"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    driver_id: Mapped[int] = mapped_column(
        ForeignKey("driver_profiles.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    is_online: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_on_break: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    went_online_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    break_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_heartbeat: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    driver = relationship("DriverProfile", backref="online_status")
