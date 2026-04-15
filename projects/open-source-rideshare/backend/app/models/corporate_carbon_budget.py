"""Corporate Carbon Budget model.

Enterprise ESG feature: corporate accounts set a monthly CO2 budget and track
their environmental footprint across all employee rides.  Finance and
sustainability teams can view per-month trend data, per-employee breakdowns,
and a comprehensive ESG report.

This is a genuine cooperative differentiator — Uber for Business offers no
environmental accountability or carbon budgeting tools.

Tables:
  corporate_carbon_budgets — one row per corporate account; upsert-on-read.

The budget is expressed in kilograms of CO2 per month (nullable = no budget
configured). Tracking is always on by default so accounts accumulate data
before they decide to set a budget.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class CorporateCarbonBudget(Base):
    """Monthly CO2 budget configuration for a corporate account.

    One row per account (unique constraint on account_id). Created lazily on
    first GET request (upsert-on-read pattern — same as billing settings).

    Attributes:
        account_id: Corporate account this budget belongs to.
        monthly_budget_co2_kg: Target CO2 ceiling in kg/month. None = no cap.
        offset_budget_usd: Optional USD budget reserved for carbon offsets.
        tracking_enabled: When False, no carbon queries are surfaced to members.
        alert_threshold_pct: Send alert when budget utilisation crosses this %.
        notes: Free-text field for sustainability team notes.
        updated_by_id: Last admin to update this record (audit trail).
    """

    __tablename__ = "corporate_carbon_budgets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    account_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Budget ceiling in kg CO2/month; null = no budget configured
    monthly_budget_co2_kg: Mapped[float | None] = mapped_column(
        Numeric(10, 2), nullable=True
    )

    # Optional dedicated offset spend budget in USD
    offset_budget_usd: Mapped[float | None] = mapped_column(
        Numeric(10, 2), nullable=True
    )

    # When False, carbon endpoints still work for admins but are hidden from members
    tracking_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )

    # Alert when utilisation (co2_used / monthly_budget_co2_kg × 100) reaches this %
    alert_threshold_pct: Mapped[int] = mapped_column(
        Integer, nullable=False, default=80
    )

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    updated_by_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
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

    # Relationships
    account = relationship(
        "BusinessAccount", foreign_keys=[account_id], lazy="raise"
    )
    updated_by = relationship(
        "User", foreign_keys=[updated_by_id], lazy="raise"
    )

    __table_args__ = (
        UniqueConstraint("account_id", name="uq_corporate_carbon_budgets_account"),
    )
