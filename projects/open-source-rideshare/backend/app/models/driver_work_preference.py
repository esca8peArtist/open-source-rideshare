"""Driver Work Preferences model.

One row per driver (driver_id is unique).  Created on first get; upserted on
subsequent changes.  Preferences let drivers express what kinds of rides they
are willing to accept, giving them meaningful agency over their workload — a
core cooperative value that Uber/Lyft's algorithmic dispatch ignores.

Columns
-------
driver_id               FK to users.id (unique — one row per driver)
accept_pool_rides       True → driver willing to accept pooled/shared rides
accept_pet_riders       True → driver willing to transport riders with pets
accept_extra_luggage    True → driver willing to assist with extra luggage
min_trip_distance_km    Minimum preferred trip distance in km; null = no preference
max_trip_distance_km    Maximum preferred trip distance in km; null = no preference
prefer_long_distance    True → driver prefers long-distance/airport/highway trips
prefer_language_matched True → prefer matches where a shared language is available
notes                   Free-text notes for dispatch (max 200 chars)
created_at / updated_at
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class DriverWorkPreference(Base):
    """Per-driver work preferences surfaced to the matching and dispatch engine."""

    __tablename__ = "driver_work_preferences"

    id: Mapped[int] = mapped_column(primary_key=True)
    driver_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    # Ride-type acceptance
    accept_pool_rides: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )
    accept_pet_riders: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )
    accept_extra_luggage: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )

    # Trip distance range (km); null means no preference for that bound
    min_trip_distance_km: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_trip_distance_km: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Route/style preferences
    prefer_long_distance: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    prefer_language_matched: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )

    notes: Mapped[str | None] = mapped_column(String(200), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    driver = relationship(
        "User", foreign_keys=[driver_id], backref="work_preferences"
    )
