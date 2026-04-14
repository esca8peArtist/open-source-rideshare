"""Pydantic schemas for the driver earnings P&L summary endpoint.

Provides:
- IncomeBreakdown         — aggregate ride income for the period
- ExpenseSummary          — aggregate expense totals for the period (mirrors CategoryBreakdown)
- PeriodBreakdown         — income + expenses + net for one sub-period (weekly/monthly)
- EarningsSummaryResponse — top-level response for GET /drivers/me/earnings-summary
"""
from __future__ import annotations

from datetime import date
from enum import Enum

from pydantic import BaseModel, Field

from app.models.driver_expense import ExpenseCategory


class BreakdownInterval(str, Enum):
    """Granularity for the optional period breakdown in the earnings summary."""

    NONE = "none"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class ExpenseCategoryBreakdown(BaseModel):
    """Per-category expense totals within the summary period."""

    category: ExpenseCategory
    total_amount: float = Field(..., description="Sum of amounts in this category")
    count: int = Field(..., description="Number of expense records in this category")


class IncomeBreakdown(BaseModel):
    """Aggregate ride income for the summary period.

    gross_fares: sum of actual_fare (falling back to estimated_fare) for all
        completed rides in the period.
    platform_fees: sum of platform fees deducted from each ride's payment.
    tips: sum of completed tip payouts to the driver.
    net_ride_earnings: gross_fares - platform_fees + tips.
    rides_completed: count of completed rides in the period.
    """

    gross_fares: float = Field(..., description="Sum of gross fares (before platform fees)")
    platform_fees: float = Field(..., description="Total platform fees deducted")
    tips: float = Field(..., description="Total tips received")
    net_ride_earnings: float = Field(
        ..., description="gross_fares - platform_fees + tips"
    )
    rides_completed: int = Field(..., description="Number of completed rides in the period")


class ExpenseSummary(BaseModel):
    """Aggregate expense totals for the summary period."""

    total_expenses: float = Field(..., description="Sum of all expense amounts")
    deductible_total: float = Field(
        ..., description="Sum of expenses where is_deductible=True"
    )
    categories: list[ExpenseCategoryBreakdown] = Field(
        default_factory=list,
        description="Per-category breakdown of expenses",
    )


class PeriodBreakdown(BaseModel):
    """Income and expense summary for a single sub-period (weekly or monthly)."""

    period_label: str = Field(..., description="Human-readable period label, e.g. '2026-04-01 – 2026-04-07'")
    period_start: date = Field(..., description="Inclusive start of the sub-period")
    period_end: date = Field(..., description="Inclusive end of the sub-period")
    gross_fares: float
    platform_fees: float
    tips: float
    net_ride_earnings: float
    rides_completed: int
    total_expenses: float
    net_profit: float = Field(..., description="net_ride_earnings - total_expenses")


class EarningsSummaryResponse(BaseModel):
    """Response for GET /drivers/me/earnings-summary.

    Combines actual ride earnings with logged expenses to show the driver's
    true profit/loss for the requested period.
    """

    driver_id: int
    period_start: date = Field(..., description="Inclusive start of the summary period")
    period_end: date = Field(..., description="Inclusive end of the summary period")
    breakdown: BreakdownInterval = Field(
        ...,
        description="Granularity of the optional period breakdown",
    )
    income: IncomeBreakdown
    expenses: ExpenseSummary
    net_profit: float = Field(..., description="income.net_ride_earnings - expenses.total_expenses")
    periods: list[PeriodBreakdown] = Field(
        default_factory=list,
        description=(
            "Sub-period breakdowns. Populated only when breakdown=weekly or monthly. "
            "Ordered chronologically oldest-to-newest."
        ),
    )
