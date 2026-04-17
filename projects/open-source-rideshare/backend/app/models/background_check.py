"""Background check model for driver onboarding via Checkr API."""

from __future__ import annotations

import enum
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class BackgroundCheckStatus(str, enum.Enum):
    PENDING = "pending"
    CLEAR = "clear"
    CONSIDER = "consider"
    SUSPENDED = "suspended"
    DISPUTE = "dispute"
    CANCELLED = "cancelled"


class BackgroundCheckAlertType(str, enum.Enum):
    SIXTY_DAY = "60_day"
    THIRTY_DAY = "30_day"
    SEVEN_DAY = "7_day"
    EXPIRED = "expired"


class BackgroundCheck(Base):
    """Record of a background check ordered via Checkr for a driver."""

    __tablename__ = "background_checks"

    id: Mapped[int] = mapped_column(primary_key=True)
    driver_profile_id: Mapped[int] = mapped_column(
        ForeignKey("driver_profiles.id"), index=True
    )

    # Checkr-side identifiers
    checkr_candidate_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    checkr_check_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)

    # Which check package was ordered
    package: Mapped[str] = mapped_column(String(50), default="driver_pro")

    status: Mapped[BackgroundCheckStatus] = mapped_column(
        Enum(BackgroundCheckStatus), default=BackgroundCheckStatus.PENDING, index=True
    )

    # Checkr report URL (populated on completion)
    report_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Admin override fields
    admin_override_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    overridden_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    # Expiration tracking — populated when Checkr reports a clear result.
    # None means expiry is not yet known (check still pending or not applicable).
    expires_at: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)

    ordered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    driver_profile = relationship("DriverProfile", backref="background_checks")
    override_admin = relationship("User", foreign_keys=[overridden_by])
    alerts = relationship(
        "BackgroundCheckAlert", back_populates="background_check", cascade="all, delete-orphan"
    )


class BackgroundCheckAlert(Base):
    """Record of an expiry alert notification sent for a driver's background check."""

    __tablename__ = "background_check_alerts"

    id: Mapped[int] = mapped_column(primary_key=True)
    driver_profile_id: Mapped[int] = mapped_column(
        ForeignKey("driver_profiles.id"), index=True
    )
    background_check_id: Mapped[int] = mapped_column(
        ForeignKey("background_checks.id", ondelete="CASCADE"), index=True
    )
    alert_type: Mapped[BackgroundCheckAlertType] = mapped_column(
        Enum(BackgroundCheckAlertType, name="backgroundcheckalerttype"), nullable=False
    )
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    background_check = relationship("BackgroundCheck", back_populates="alerts")
