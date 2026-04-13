"""Surge pricing zone model.

Admin-defined geographic zones with surge multipliers that layer on top
of the existing demand-based pricing. Zones can be circular (center + radius)
or polygonal (list of lat/lng points). Time-of-day and day-of-week restrictions
are supported for recurring surge patterns such as rush hours.
"""

import uuid
from datetime import datetime, time

from sqlalchemy import Boolean, DateTime, Float, JSON, String, Text, Time, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class SurgePricingZone(Base):
    __tablename__ = "surge_pricing_zones"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Geographic definition — either polygon or circle (or both; polygon takes precedence)
    polygon: Mapped[list | None] = mapped_column(
        JSON, nullable=True,
        comment="List of {lat, lon} dicts defining the zone boundary (ray-cast check)."
    )
    center_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    center_lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    radius_km: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Multiplier applied on top of demand-based pricing
    multiplier: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Optional time-of-day restriction (naive local times — cooperative sets the schedule)
    start_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    end_time: Mapped[time | None] = mapped_column(Time, nullable=True)

    # Optional day-of-week restriction: list of ints 0=Mon … 6=Sun
    days_of_week: Mapped[list | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
