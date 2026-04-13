"""Rider ride preference model.

One row per rider (user_id is unique).  Created on first save; upserted on
subsequent changes.  Preferences are hints to drivers — not hard requirements
unless accessibility_vehicle_needed is True.

Columns
-------
user_id                    FK to users.id (unique — one row per rider)
quiet_ride                 True → rider prefers minimal conversation
music_off                  True → rider prefers no music
temperature_preference     Enum: no_preference | warm | cool
pet_friendly               True → rider is traveling with a pet
extra_luggage              True → rider has more than normal luggage
accessibility_vehicle_needed  True → rider requires a wheelchair-accessible vehicle
notes                      Free-text notes for driver (max 200 chars)
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class TemperaturePreference(str, enum.Enum):
    NO_PREFERENCE = "no_preference"
    WARM = "warm"
    COOL = "cool"


class RidePreference(Base):
    """Per-rider preferences shown to matched drivers."""

    __tablename__ = "ride_preferences"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    quiet_ride: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    music_off: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    temperature_preference: Mapped[TemperaturePreference] = mapped_column(
        Enum(TemperaturePreference),
        default=TemperaturePreference.NO_PREFERENCE,
        nullable=False,
    )
    pet_friendly: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    extra_luggage: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    accessibility_vehicle_needed: Mapped[bool] = mapped_column(
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

    user = relationship("User", backref="ride_preference")
