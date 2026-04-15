"""CorporateScheduledReport model.

Enterprise admins configure automated periodic delivery of spending and usage
reports to a list of email recipients.  Reports can be scheduled daily, weekly
(specific day-of-week), or monthly (specific day-of-month).

The scheduler evaluates ``next_due_at`` to decide which reports to deliver;
after delivery it sets ``last_sent_at = now()`` and advances ``next_due_at``.

Tables:
  corporate_scheduled_reports — one row per configured report schedule.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.database import Base


class ReportFrequency(str, enum.Enum):
    """How often the report is sent."""

    daily = "daily"
    weekly = "weekly"
    monthly = "monthly"


class ScheduledReportType(str, enum.Enum):
    """Which report dataset to generate."""

    spending_overview = "spending_overview"
    monthly_trend = "monthly_trend"
    employee_breakdown = "employee_breakdown"
    ride_patterns = "ride_patterns"
    invoice_summary = "invoice_summary"
    expense_report_summary = "expense_report_summary"


class CorporateScheduledReport(Base):
    """Automated report schedule for a corporate account.

    Attributes:
        id: UUID primary key.
        account_id: FK → corporate_accounts_v2 (CASCADE delete).
        name: Human-readable label chosen by the admin.
        report_type: Which dataset to include (ScheduledReportType enum).
        frequency: Delivery cadence — daily, weekly, or monthly.
        day_of_week: 0–6 (Mon=0 … Sun=6).  Required when frequency=weekly.
        day_of_month: 1–28.  Required when frequency=monthly.
        recipients: JSONB list of email strings to deliver to.
        is_active: Soft-disable without deleting the schedule.
        last_sent_at: Timestamp of the most recent successful delivery.
        next_due_at: Pre-computed next fire time; NULL until first scheduled.
        created_by_id: FK → users (SET NULL on user delete).
        created_at / updated_at: Audit timestamps.
    """

    __tablename__ = "corporate_scheduled_reports"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    account_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    report_type: Mapped[ScheduledReportType] = mapped_column(
        Enum(ScheduledReportType, name="scheduledreporttype"),
        nullable=False,
    )
    frequency: Mapped[ReportFrequency] = mapped_column(
        Enum(ReportFrequency, name="reportfrequency"),
        nullable=False,
    )
    day_of_week: Mapped[int | None] = mapped_column(Integer, nullable=True)
    day_of_month: Mapped[int | None] = mapped_column(Integer, nullable=True)
    recipients: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    next_due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_by_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    account = relationship("BusinessAccount", foreign_keys=[account_id])
    created_by = relationship("User", foreign_keys=[created_by_id])
