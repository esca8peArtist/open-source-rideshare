"""Surge pricing event log.

Records every fare preview where surge pricing was active (zone or demand).
Used by the admin surge analytics endpoints to report on when/where surge fired,
at what multiplier, and with what supply/demand conditions.

Events are written fire-and-forget from get_fare_preview() — never block riders.
"""

import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class SurgeEventType(str, enum.Enum):
    ZONE_ONLY = "zone_only"
    DEMAND_ONLY = "demand_only"
    COMBINED = "combined"


class SurgePricingEvent(Base):
    __tablename__ = "surge_pricing_events"

    id: Mapped[int] = mapped_column(primary_key=True)

    event_type: Mapped[SurgeEventType] = mapped_column(
        Enum(SurgeEventType), nullable=False, index=True
    )

    # Origin point of the fare preview
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lon: Mapped[float] = mapped_column(Float, nullable=False)
    geohash: Mapped[str] = mapped_column(String(12), nullable=False, index=True)

    # Admin surge zone (nullable — absent when event_type == DEMAND_ONLY)
    surge_zone_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    surge_zone_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    zone_multiplier: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)

    # Real-time demand pricing
    demand_multiplier: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    demand_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    supply_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Combined effective multiplier
    combined_multiplier: Mapped[float] = mapped_column(Float, nullable=False)

    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
