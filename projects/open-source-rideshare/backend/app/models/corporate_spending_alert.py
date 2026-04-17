"""Corporate spending limit alert model.

Tracks when a member or account has crossed a spend threshold within a calendar
month.  One row is written per (account, member_or_null, alert_type, period)
combination — duplicate detection uses the UniqueConstraint below.

CorporateSpendingAlert  — one alert event per threshold/period
"""
from __future__ import annotations

import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Integer,
    Numeric,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class AlertType(str, enum.Enum):
    WARNING_75PCT = "warning_75pct"
    WARNING_90PCT = "warning_90pct"
    LIMIT_REACHED = "limit_reached"


class CorporateSpendingAlert(Base):
    """A single spend-threshold crossing event.

    Attributes:
        account_id: FK to corporate_accounts_v2.
        member_id: FK to corporate_account_members — NULL for account-level alerts.
        alert_type: Which threshold was crossed.
        threshold_pct: Exact percentage stored for reference (e.g. 75, 90, 100).
        current_spend_usd: Spend amount at the time the alert was created.
        limit_usd: The applicable limit at the time the alert was created.
        period_year: Calendar year of the billing period (e.g. 2026).
        period_month: Calendar month of the billing period (1-12).
        created_at: When this alert record was inserted.

    The combination (account_id, member_id, alert_type, period_year, period_month)
    is unique so the same threshold is not alerted more than once per period.
    """

    __tablename__ = "corporate_spending_alerts"
    __table_args__ = (
        UniqueConstraint(
            "account_id",
            "member_id",
            "alert_type",
            "period_year",
            "period_month",
            name="uq_corp_spend_alert_period",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    account_id: Mapped[int] = mapped_column(
        ForeignKey("corporate_accounts_v2.id"), nullable=False, index=True
    )
    member_id: Mapped[int | None] = mapped_column(
        ForeignKey("corporate_account_members.id"), nullable=True, index=True
    )

    alert_type: Mapped[AlertType] = mapped_column(
        SAEnum(AlertType), nullable=False
    )
    threshold_pct: Mapped[int] = mapped_column(Integer, nullable=False)

    current_spend_usd: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False
    )
    limit_usd: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)

    period_year: Mapped[int] = mapped_column(Integer, nullable=False)
    period_month: Mapped[int] = mapped_column(Integer, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
