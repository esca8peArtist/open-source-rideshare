"""Pydantic v2 schemas for the Corporate Spending Analytics feature.

Corporate account admins can request spending trend data, per-employee
breakdowns, and ride pattern analytics over arbitrary date ranges.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Spending overview
# ---------------------------------------------------------------------------


class SpendingOverviewResponse(BaseModel):
    """High-level spend summary for a corporate account.

    Covers current calendar month, year-to-date, and all-time totals.
    """

    account_id: int
    current_month: str = Field(
        ..., description="Current billing month in YYYY-MM format"
    )
    current_month_rides: int
    current_month_spend: Decimal
    ytd_rides: int
    ytd_spend: Decimal
    all_time_rides: int
    all_time_spend: Decimal
    monthly_budget_limit: Decimal | None = Field(
        None, description="Monthly budget cap set on the account (NULL = unlimited)"
    )
    current_month_budget_utilization_pct: float | None = Field(
        None,
        description=(
            "Percentage of monthly budget consumed this month. "
            "NULL when no budget limit is configured."
        ),
    )


# ---------------------------------------------------------------------------
# Monthly spend trend
# ---------------------------------------------------------------------------


class MonthlySpendPoint(BaseModel):
    """Spend data for one calendar month."""

    month: str = Field(..., description="Month in YYYY-MM format")
    total_rides: int
    total_spend: Decimal
    avg_fare: Decimal | None = Field(
        None,
        description="Average fare per ride. NULL when total_rides is 0.",
    )


class MonthlySpendTrendResponse(BaseModel):
    """Monthly spend trend for the last N months (newest first)."""

    account_id: int
    months_requested: int
    data: list[MonthlySpendPoint]


# ---------------------------------------------------------------------------
# Employee spend breakdown
# ---------------------------------------------------------------------------


class EmployeeSpendItem(BaseModel):
    """Ride spend statistics for one employee within a date range."""

    user_id: int
    user_email: str | None = None
    user_name: str | None = None
    total_rides: int
    total_spend: Decimal
    avg_fare: Decimal | None = Field(
        None,
        description="Average fare per ride. NULL when total_rides is 0.",
    )


class EmployeeSpendBreakdownResponse(BaseModel):
    """Top employee spenders for a given billing period."""

    account_id: int
    period_start: date
    period_end: date
    limit: int
    top_spenders: list[EmployeeSpendItem]


# ---------------------------------------------------------------------------
# Ride pattern analytics
# ---------------------------------------------------------------------------


class HourBucket(BaseModel):
    """Ride count for a single hour-of-day bucket."""

    hour: int = Field(..., ge=0, le=23, description="Hour of day (0–23, UTC)")
    ride_count: int


class DayBucket(BaseModel):
    """Ride count for a single day-of-week bucket."""

    day_of_week: int = Field(
        ..., ge=0, le=6, description="0 = Sunday, 1 = Monday … 6 = Saturday (ISO-style)"
    )
    day_name: str
    ride_count: int


class RidePatternResponse(BaseModel):
    """Ride distribution by hour-of-day and day-of-week for a billing period."""

    account_id: int
    period_start: date
    period_end: date
    total_rides: int
    by_hour: list[HourBucket]
    by_day_of_week: list[DayBucket]
