"""Ride carbon footprint models.

Green Rides cooperative differentiator: track per-ride CO2 emissions and
allow riders to pay an optional carbon-offset fee. Uber/Lyft offer no
environmental accountability — a cooperative that cares about its community
should.

Tables:
  ride_carbon_records — one row per ride: emission class, distance, CO2 grams,
                        optional offset payment

Emission classes and rates (grams CO2 per km):
  petrol   → 120 g/km  (EU passenger car average)
  diesel   → 130 g/km  (slightly higher tailpipe)
  hybrid   →  70 g/km  (parallel hybrid average)
  electric →  50 g/km  (well-to-wheel, mixed grid)
  unknown  → 120 g/km  (fallback = petrol rate)

Offset pricing: $1 per 10 kg CO2 = 10 cents per 1,000 g CO2.
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum as SAEnum,
    Float,
    ForeignKey,
    Integer,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class VehicleEmissionClass(str, enum.Enum):
    petrol = "petrol"
    diesel = "diesel"
    hybrid = "hybrid"
    electric = "electric"
    unknown = "unknown"


# Grams of CO2 per km for each emission class
EMISSION_RATES_G_PER_KM: dict[str, int] = {
    VehicleEmissionClass.petrol: 120,
    VehicleEmissionClass.diesel: 130,
    VehicleEmissionClass.hybrid: 70,
    VehicleEmissionClass.electric: 50,
    VehicleEmissionClass.unknown: 120,
}

# Offset cost: 10 cents per 1,000 g CO2 ($1/10 kg)
OFFSET_CENTS_PER_KG: int = 10


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


class RideCarbonRecord(Base):
    """Per-ride carbon footprint record.

    Created when a ride completes and its distance + vehicle type are known.
    ``offset_paid`` flips to True when the rider pays the voluntary offset fee.
    """

    __tablename__ = "ride_carbon_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    # One record per ride — enforced by unique constraint
    ride_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("rides.id"), unique=True, nullable=False, index=True
    )

    emission_class: Mapped[VehicleEmissionClass] = mapped_column(
        SAEnum(VehicleEmissionClass, name="vehicleemissionclass", create_type=True),
        nullable=False,
        default=VehicleEmissionClass.unknown,
    )

    # Distance driven for this ride in kilometres
    distance_km: Mapped[float] = mapped_column(Float, nullable=False)

    # Computed at record creation time: EMISSION_RATES * distance_km
    co2_grams: Mapped[int] = mapped_column(Integer, nullable=False)

    # Suggested offset cost in US cents (stored for display, even if not paid)
    offset_cost_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Whether the rider chose to pay the offset
    offset_paid: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Actual amount paid (may equal offset_cost_cents, or 0 if not paid)
    offset_amount_cents: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    offset_paid_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
