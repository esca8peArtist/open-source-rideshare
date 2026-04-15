"""Corporate Blackout Period model.

Admins define named date ranges when corporate bookings are restricted.
Supports one-time date ranges (e.g. a specific holiday), annually-recurring
windows (e.g. every Thanksgiving), and weekly recurring time blocks
(e.g. no corporate rides on weekends).

The check_booking_blackout service function evaluates whether a proposed
booking datetime falls within any active blackout period for the account.

CorporateBlackoutPeriod — table corporate_blackout_periods
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class BlackoutRecurrence(str, enum.Enum):
    """How often the blackout period repeats."""

    none = "none"      # one-time date range
    annual = "annual"  # repeats every calendar year (same month/day range)
    weekly = "weekly"  # repeats every week on specified days of the week


class CorporateBlackoutPeriod(Base):
    """A booking restriction window for a corporate account.

    Attributes:
        id: UUID primary key.
        corporate_account_id: FK to corporate_accounts_v2.
        name: Admin-friendly label (e.g. "Christmas 2026", "Weekend block").
        start_datetime: Inclusive start of the blackout window.
        end_datetime: Inclusive end of the blackout window.
        recurrence: Repeat pattern — none / annual / weekly.
        affected_days: For weekly recurrence, the weekday integers that are
            blocked (0=Monday … 6=Sunday).  The time-of-day window is taken
            from start_datetime.time() … end_datetime.time().  NULL → all days.
        override_allowed: Whether employees may request an exception.
        override_requires_approval: When True, an exception must go through the
            ride-approval workflow (only relevant when override_allowed=True).
        reason: Optional human-readable explanation for the restriction.
        is_active: Soft-disable without deletion.
        created_by_id: FK to the user who created this record.
        created_at / updated_at: Audit timestamps.
    """

    __tablename__ = "corporate_blackout_periods"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    corporate_account_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)

    start_datetime: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    end_datetime: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    recurrence: Mapped[BlackoutRecurrence] = mapped_column(
        SAEnum(BlackoutRecurrence),
        nullable=False,
        default=BlackoutRecurrence.none,
    )

    # Weekday integers (0–6) — used only for weekly recurrence.
    affected_days: Mapped[list[int] | None] = mapped_column(JSONB, nullable=True)

    # Override policy
    override_allowed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    override_requires_approval: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )

    reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, index=True
    )

    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
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

    account = relationship("BusinessAccount", foreign_keys=[corporate_account_id])
    created_by = relationship("User", foreign_keys=[created_by_id])
