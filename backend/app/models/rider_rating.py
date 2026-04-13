"""RiderRating model — driver-submitted rating for a rider after a completed ride.

Each ride may have at most one rider rating from the driver (enforced by
UniqueConstraint on ride_id + driver_id). Ratings use a 1-5 integer scale.
"""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class RiderRating(Base):
    """A rating submitted by a driver for the rider on a completed ride.

    Stores the raw 1-5 star value and an optional free-text comment.
    Aggregate stats are computed on demand by the service layer.
    """

    __tablename__ = "rider_ratings"
    __table_args__ = (
        UniqueConstraint("ride_id", "driver_id", name="uq_rider_rating_ride_driver"),
        CheckConstraint("rating >= 1 AND rating <= 5", name="ck_rider_rating_range"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    ride_id: Mapped[int] = mapped_column(ForeignKey("rides.id"), index=True)
    driver_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    rider_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)

    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    ride = relationship("Ride", foreign_keys=[ride_id])
    driver = relationship("User", foreign_keys=[driver_id])
    rider = relationship("User", foreign_keys=[rider_id])
