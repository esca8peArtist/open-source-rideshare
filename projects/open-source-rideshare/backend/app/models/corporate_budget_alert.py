"""Corporate Budget Alert model.

Admins configure percentage-based alert thresholds on cost centers or the
overall corporate account.  When spend for a billing cycle crosses the
configured threshold, an alert record transitions to ``triggered`` and is
surfaced via the API.

CorporateBudgetAlert — table corporate_budget_alerts
"""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Date,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class BudgetAlertScope(str, enum.Enum):
    """Whether the alert monitors a specific cost center or the whole account."""

    cost_center = "cost_center"
    account = "account"


class BudgetAlertStatus(str, enum.Enum):
    """Lifecycle state of a budget alert."""

    active = "active"               # threshold not yet crossed
    triggered = "triggered"         # threshold crossed, not yet acknowledged
    acknowledged = "acknowledged"   # admin has acknowledged the alert


class CorporateBudgetAlert(Base):
    """A percentage-based budget alert threshold for a corporate account.

    Attributes:
        id: UUID primary key.
        corporate_account_id: FK to corporate_accounts_v2.
        scope: Whether this monitors a cost center or the whole account.
        cost_center_id: Required when scope=cost_center; FK to
            corporate_cost_centers.  NULL when scope=account.
        threshold_pct: Integer 1–100.  Alert triggers when spend reaches
            this percentage of the configured budget.
        label: Optional admin-friendly name (e.g. "Engineering 80% warning").
        status: Current lifecycle state.
        triggered_at: When the alert was triggered, if applicable.
        acknowledged_at: When the alert was acknowledged, if applicable.
        acknowledged_by_id: FK to users — who acknowledged the alert.
        billing_month: The first day of the month for which this trigger applies.
        spend_at_trigger_usd: Actual spend recorded at trigger time.
        budget_at_trigger_usd: Configured budget recorded at trigger time.
        created_at: Row creation timestamp.
        updated_at: Row last-modification timestamp.
    """

    __tablename__ = "corporate_budget_alerts"
    __table_args__ = (
        UniqueConstraint(
            "corporate_account_id",
            "scope",
            "cost_center_id",
            "threshold_pct",
            name="uq_budget_alert_account_scope_cc_pct",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    corporate_account_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_accounts_v2.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    scope: Mapped[BudgetAlertScope] = mapped_column(
        SAEnum(BudgetAlertScope),
        nullable=False,
    )

    cost_center_id: Mapped[int | None] = mapped_column(
        ForeignKey("corporate_cost_centers.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    threshold_pct: Mapped[int] = mapped_column(Integer, nullable=False)

    label: Mapped[str | None] = mapped_column(String(200), nullable=True)

    status: Mapped[BudgetAlertStatus] = mapped_column(
        SAEnum(BudgetAlertStatus),
        nullable=False,
        default=BudgetAlertStatus.active,
    )

    triggered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    acknowledged_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )

    billing_month: Mapped[date | None] = mapped_column(Date, nullable=True)

    spend_at_trigger_usd: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2), nullable=True
    )
    budget_at_trigger_usd: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2), nullable=True
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
    cost_center = relationship(
        "CorporateCostCenter", foreign_keys=[cost_center_id]
    )
    acknowledged_by = relationship("User", foreign_keys=[acknowledged_by_id])
