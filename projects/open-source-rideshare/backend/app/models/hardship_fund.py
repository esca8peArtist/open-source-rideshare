"""Driver Emergency Assistance Fund models.

Mutual-aid cooperative feature — drivers and the platform contribute to a
shared fund; drivers apply for emergency disbursements.

Tables:
  driver_hardship_fund     — singleton balance record for the fund
  hardship_contributions   — every deposit (driver, platform, donation)
  hardship_applications    — one row per driver emergency application

Application lifecycle:
  pending → under_review → approved → disbursed
  pending | under_review → denied
  pending → withdrawn    (driver self-cancels)
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Integer,
    Numeric,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ContributionSource(str, enum.Enum):
    driver = "driver"
    platform = "platform"
    donation = "donation"
    other = "other"


class ApplicationType(str, enum.Enum):
    medical = "medical"
    vehicle_repair = "vehicle_repair"
    natural_disaster = "natural_disaster"
    housing = "housing"
    bereavement = "bereavement"
    other = "other"


class ApplicationStatus(str, enum.Enum):
    pending = "pending"
    under_review = "under_review"
    approved = "approved"
    denied = "denied"
    disbursed = "disbursed"
    withdrawn = "withdrawn"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class DriverHardshipFund(Base):
    """Singleton balance record for the Driver Emergency Assistance Fund.

    Only one row should exist.  The service layer enforces this by
    using get_or_create semantics rather than blind inserts.
    """

    __tablename__ = "driver_hardship_fund"

    id: Mapped[int] = mapped_column(primary_key=True)

    total_balance_usd: Mapped[float] = mapped_column(
        Numeric(12, 2), default=0, nullable=False
    )
    total_contributed_usd: Mapped[float] = mapped_column(
        Numeric(12, 2), default=0, nullable=False
    )
    total_disbursed_usd: Mapped[float] = mapped_column(
        Numeric(12, 2), default=0, nullable=False
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


class HardshipContribution(Base):
    """Records every deposit into the Driver Emergency Assistance Fund."""

    __tablename__ = "hardship_contributions"

    id: Mapped[int] = mapped_column(primary_key=True)

    source: Mapped[ContributionSource] = mapped_column(
        SAEnum(ContributionSource), nullable=False, index=True
    )

    # Null for platform/donation contributions; set when a driver contributes.
    driver_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("users.id"),
        nullable=True,
        index=True,
    )

    amount_usd: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)

    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    driver = relationship("User", foreign_keys=[driver_id])


class HardshipApplication(Base):
    """An emergency assistance application submitted by a driver."""

    __tablename__ = "hardship_applications"

    id: Mapped[int] = mapped_column(primary_key=True)

    driver_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )

    application_type: Mapped[ApplicationType] = mapped_column(
        SAEnum(ApplicationType), nullable=False, index=True
    )

    description: Mapped[str] = mapped_column(Text, nullable=False)

    amount_requested_usd: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)

    status: Mapped[ApplicationStatus] = mapped_column(
        SAEnum(ApplicationStatus),
        default=ApplicationStatus.pending,
        nullable=False,
        index=True,
    )

    # Set when admin approves — may be less than amount_requested_usd.
    approved_amount_usd: Mapped[float | None] = mapped_column(
        Numeric(10, 2), nullable=True
    )

    admin_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    reviewed_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )

    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    disbursed_at: Mapped[datetime | None] = mapped_column(
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

    driver = relationship("User", foreign_keys=[driver_id])
    reviewed_by = relationship("User", foreign_keys=[reviewed_by_id])
