"""Rider favourite driver model.

Riders can save up to 20 driver profiles as favourites.  Matching prefers
favourite drivers when they are nearby, and riders can review their history
with known drivers before requesting a ride.
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base

_MAX_FAVORITES = 20


class RiderFavoriteDriver(Base):
    __tablename__ = "rider_favorite_drivers"
    __table_args__ = (
        UniqueConstraint("rider_id", "driver_profile_id", name="uq_rider_favorite_driver"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    rider_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    driver_profile_id: Mapped[int] = mapped_column(
        ForeignKey("driver_profiles.id"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    rider = relationship("User", foreign_keys=[rider_id])
    driver_profile = relationship("DriverProfile", foreign_keys=[driver_profile_id])
