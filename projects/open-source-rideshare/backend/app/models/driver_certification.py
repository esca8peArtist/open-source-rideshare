"""Driver Certification Badges model.

Cooperative recognition badges awarded to drivers for quality, safety, and
community contribution. Unlike Uber/Lyft, this platform gives drivers and
riders transparent peer recognition — visible when a rider is matched with
a driver.
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class BadgeType(str, enum.Enum):
    SAFE_DRIVER = "safe_driver"                          # 0 safety incidents, high safety score
    FIVE_STAR = "five_star"                              # sustained 4.8+ average rating
    ACCESSIBILITY_SPECIALIST = "accessibility_specialist"  # WAV certified + training
    PET_FRIENDLY = "pet_friendly"                        # opted in to allow pets
    LONG_DISTANCE_EXPERT = "long_distance_expert"        # 10+ airport/long-distance rides
    MENTOR = "mentor"                                    # active mentorship participation
    ECO_DRIVER = "eco_driver"                           # hybrid/electric vehicle
    VETERAN = "veteran"                                  # 1+ year on platform, 500+ rides completed


class DriverCertification(Base):
    """A badge awarded to a driver for meeting platform or community criteria."""

    __tablename__ = "driver_certifications"
    __table_args__ = (
        UniqueConstraint("driver_id", "badge_type", name="uq_driver_certification"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    driver_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    badge_type: Mapped[BadgeType] = mapped_column(Enum(BadgeType))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    awarded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    awarded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    driver = relationship("User", foreign_keys=[driver_id], backref="certifications")
    awarder = relationship("User", foreign_keys=[awarded_by])
    revoker = relationship("User", foreign_keys=[revoked_by])
