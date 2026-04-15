"""DriverRatingAppeal model — drivers contest unfair ride_feedback ratings.

A driver may submit one appeal per feedback record. Admins review appeals and
may approve (nullifying the rating from score calculations) or reject them.

Design notes:
- One appeal per feedback record enforced by unique constraint on feedback_id.
- When an appeal is approved, rating_nullified is set to True. The underlying
  RideFeedback row is preserved for audit; the service layer excludes nullified
  ratings when computing driver averages.
- The appeal reason is driver-supplied free text; admin_notes is admin-supplied.
"""

import enum
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class AppealStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"   # rating nullified from driver average
    REJECTED = "rejected"   # rating stands


class DriverRatingAppeal(Base):
    __tablename__ = "driver_rating_appeals"
    __table_args__ = (
        # Each feedback record can only have one appeal
        UniqueConstraint("feedback_id", name="uq_appeal_per_feedback"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    driver_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    feedback_id: Mapped[int] = mapped_column(ForeignKey("ride_feedback.id"), unique=True, index=True)

    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[AppealStatus] = mapped_column(
        Enum(AppealStatus), default=AppealStatus.PENDING, index=True
    )
    admin_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    rating_nullified: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    driver = relationship("User", foreign_keys=[driver_id])
    feedback = relationship("RideFeedback", foreign_keys=[feedback_id])
    reviewer = relationship("User", foreign_keys=[reviewed_by])
