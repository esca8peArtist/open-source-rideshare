"""Jurisdiction model — immutable per-city TNC regulatory configuration.

Each row represents one regulatory jurisdiction (city/state) where the
cooperative is licensed to operate.  Records are seeded at deploy time via
the Alembic migration and are *not* modified at runtime — changes require a
new migration so that config drift is tracked in version control.
"""

from sqlalchemy import Boolean, Float, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class Jurisdiction(Base):
    """Regulatory configuration for a single TNC operating jurisdiction.

    Fields mirror the config structure described in the Phase 3 sprint
    roadmap (Sprint 1, item 5).  The ``id`` is a human-readable slug
    (e.g. ``portland_or``) so it can be referenced in environment config
    and admin tools without needing to look up a numeric key.
    """

    __tablename__ = "jurisdictions"

    # Human-readable slug: "portland_or", "atlanta_ga"
    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    name: Mapped[str] = mapped_column(String(150))

    # Background check requirements
    background_check_type: Mapped[str] = mapped_column(
        String(100), default="motor_vehicle_record + criminal"
    )

    # Per-trip surcharge collected on behalf of the city (in dollars, e.g. 0.50)
    per_trip_surcharge: Mapped[float] = mapped_column(Float, default=0.0)
    per_trip_surcharge_description: Mapped[str] = mapped_column(String(200), default="")

    # Licensing & insurance prose (for admin reference and driver onboarding copy)
    license_requirement: Mapped[str] = mapped_column(Text, default="")
    insurance_requirement: Mapped[str] = mapped_column(Text, default="")

    # WAV (wheelchair accessible vehicle) mandate
    wav_mandate: Mapped[bool] = mapped_column(Boolean, default=False)
    # Minimum % of fleet that must be WAV-capable (0.0 if not mandated)
    wav_percentage: Mapped[float] = mapped_column(Float, default=0.0)

    # Grace periods (days) before compliance hold is triggered after expiry
    license_grace_days: Mapped[int] = mapped_column(default=14)
    background_check_grace_days: Mapped[int] = mapped_column(default=30)

    # Whether this jurisdiction is currently active for new driver registration
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
