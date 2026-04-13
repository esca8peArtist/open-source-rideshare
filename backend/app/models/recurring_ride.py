"""Recurring ride model.

Allows riders to set up repeating ride schedules (e.g., daily commute).
The dispatch scheduler generates individual SCHEDULED rides from active
recurring templates ahead of time.
"""

import enum
from datetime import datetime, time

from geoalchemy2 import Geometry
from sqlalchemy import DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, INTEGER
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class RecurringRideStatus(str, enum.Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    CANCELLED = "cancelled"


class RecurringRide(Base):
    __tablename__ = "recurring_rides"

    id: Mapped[int] = mapped_column(primary_key=True)
    rider_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)

    # Route
    pickup_location: Mapped[bytes] = mapped_column(
        Geometry(geometry_type="POINT", srid=4326)
    )
    dropoff_location: Mapped[bytes] = mapped_column(
        Geometry(geometry_type="POINT", srid=4326)
    )
    pickup_address: Mapped[str] = mapped_column(String(500))
    dropoff_address: Mapped[str] = mapped_column(String(500))

    # Optional saved location references
    pickup_saved_location_id: Mapped[int | None] = mapped_column(nullable=True)
    dropoff_saved_location_id: Mapped[int | None] = mapped_column(nullable=True)

    # Schedule: days of week as integer array (0=Monday .. 6=Sunday, ISO 8601)
    days_of_week: Mapped[list[int]] = mapped_column(ARRAY(INTEGER))
    # Time of day for pickup (in rider's local timezone)
    pickup_time: Mapped[time] = mapped_column()
    # IANA timezone string (e.g. "America/New_York")
    timezone: Mapped[str] = mapped_column(String(50), default="UTC")

    accessibility_required: Mapped[bool] = mapped_column(default=False)

    # Status
    status: Mapped[RecurringRideStatus] = mapped_column(
        Enum(RecurringRideStatus), default=RecurringRideStatus.ACTIVE
    )

    # Label for rider convenience (e.g. "Morning commute", "Gym pickup")
    label: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Tracking: the date up to which rides have been generated
    # (prevents duplicate generation)
    last_generated_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    rider = relationship("User", foreign_keys=[rider_id], backref="recurring_rides")
