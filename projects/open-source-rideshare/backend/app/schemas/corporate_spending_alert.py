"""Pydantic schemas for corporate spending limit alerts."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.models.corporate_spending_alert import AlertType


class SpendingAlertOut(BaseModel):
    """A single spending alert record returned to callers."""

    id: int
    account_id: int
    member_id: int | None
    alert_type: AlertType
    threshold_pct: int
    current_spend_usd: Decimal
    limit_usd: Decimal
    period_year: int
    period_month: int
    created_at: datetime

    model_config = {"from_attributes": True}


class SpendingAlertsListResponse(BaseModel):
    """Response wrapper for a list of spending alerts."""

    alerts: list[SpendingAlertOut]
    total: int


class MemberSpendStatus(BaseModel):
    """Spend status for a single member used within the summary response."""

    member_id: int
    current_spend_usd: Decimal
    limit_usd: Decimal
    pct_used: float = Field(description="Percentage of limit consumed (0-100+).")
    highest_alert: AlertType | None = Field(
        None, description="Most severe alert fired this period, or None."
    )


class SpendingAlertsSummary(BaseModel):
    """Summary of current-month spending alerts for an account.

    Attributes:
        account_id: The corporate account.
        period_year: Calendar year of the summary.
        period_month: Calendar month of the summary (1-12).
        account_spend_usd: Total account spend this period.
        account_limit_usd: Account-level monthly limit, or None if unlimited.
        account_pct_used: Account spend as percentage of limit, or None if no limit.
        account_alert: Most severe account-level alert fired, or None.
        members_near_limit: Members at 75-89 % of their individual limit.
        members_at_limit: Members at 90 %+ of their individual limit.
        members_over_limit: Members whose spend exceeds their limit.
    """

    account_id: int
    period_year: int
    period_month: int
    account_spend_usd: Decimal
    account_limit_usd: Decimal | None
    account_pct_used: float | None
    account_alert: AlertType | None
    members_near_limit: list[MemberSpendStatus]
    members_at_limit: list[MemberSpendStatus]
    members_over_limit: list[MemberSpendStatus]
