"""Driver onboarding status model.

Tracks the overall onboarding state for a driver:
  incomplete      — one or more required documents/steps not yet submitted
  pending_review  — all items submitted; awaiting admin approval
  approved        — all requirements met; driver cleared to go online
  suspended       — driver manually suspended by admin

This model stores the current resolved status plus an optional
suspension reason.  The checklist details are computed on-the-fly
by the service layer from the underlying document/profile tables.
"""

import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class OnboardingStatus(str, enum.Enum):
    INCOMPLETE = "incomplete"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    SUSPENDED = "suspended"


class DriverOnboarding(Base):
    """Persisted onboarding state for a driver profile."""

    __tablename__ = "driver_onboarding"

    id: Mapped[int] = mapped_column(primary_key=True)
    driver_profile_id: Mapped[int] = mapped_column(
        ForeignKey("driver_profiles.id"), unique=True, index=True, nullable=False
    )

    status: Mapped[OnboardingStatus] = mapped_column(
        Enum(OnboardingStatus),
        default=OnboardingStatus.INCOMPLETE,
        nullable=False,
        index=True,
    )

    # Populated when an admin suspends the driver
    suspension_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    suspended_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    suspended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Populated when an admin activates the driver
    activated_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    activated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    driver_profile = relationship("DriverProfile", backref="onboarding")
    suspending_admin = relationship("User", foreign_keys=[suspended_by])
    activating_admin = relationship("User", foreign_keys=[activated_by])
