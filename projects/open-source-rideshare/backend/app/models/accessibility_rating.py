"""AccessibilityRating model — rider-submitted rating of accommodation quality.

One record is allowed per ride per rider (enforced by UniqueConstraint).
Ratings use a 1-5 integer scale. The accommodation_type field lets riders
indicate which specific need was (or wasn't) well served.
"""

import enum
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class AccommodationType(str, enum.Enum):
    HEARING_IMPAIRMENT = "hearing_impairment"
    VISUAL_IMPAIRMENT = "visual_impairment"
    SERVICE_ANIMAL = "service_animal"
    COMMUNICATION_PREFERENCE = "communication_preference"
    GENERAL = "general"


class AccessibilityRating(Base):
    """Rider's rating of how well their accessibility needs were accommodated.

    Submitted after a completed ride. One rating per ride per rider.
    """

    __tablename__ = "accessibility_ratings"
    __table_args__ = (
        UniqueConstraint("ride_id", "rider_id", name="uq_accessibility_rating_ride_rider"),
        CheckConstraint("rating >= 1 AND rating <= 5", name="ck_accessibility_rating_range"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    ride_id: Mapped[int] = mapped_column(ForeignKey("rides.id"), index=True)
    rider_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)

    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    accommodation_type: Mapped[AccommodationType | None] = mapped_column(
        Enum(AccommodationType), nullable=True
    )
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    ride = relationship("Ride", foreign_keys=[ride_id])
    rider = relationship("User", foreign_keys=[rider_id])
