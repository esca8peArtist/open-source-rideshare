"""Pydantic schemas for the driver income stability report endpoint.

GET /drivers/me/income-stability-report

Gig platforms like Uber and Lyft are structurally indifferent to driver income
instability — their business model thrives on flexible labor supply regardless
of driver financial outcomes.  A driver-owned cooperative has an obligation to
quantify and address income volatility, because unpredictable earnings harm
members' financial wellbeing.  This endpoint surfaces a 12-week retrospective
of a driver's earnings variance to help them understand their income stability
and plan accordingly.  It also acknowledges when the platform's earnings
guarantee (if active) helped smooth income.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from pydantic import BaseModel, Field


class WeeklyEarningsEntry(BaseModel):
    """Earnings summary for a single ISO calendar week."""

    week_start: date = Field(
        ...,
        description="Monday of this ISO week (inclusive).",
    )
    week_end: date = Field(
        ...,
        description="Sunday of this ISO week (inclusive).",
    )
    earnings_usd: float = Field(
        ...,
        description="Gross fares plus tips received during this week.",
    )
    ride_count: int = Field(
        ...,
        description="Number of completed rides during this week.",
    )
    had_guarantee_payout: bool = Field(
        ...,
        description=(
            "True when the cooperative's earnings guarantee triggered a top-up "
            "payment for this week, cushioning a shortfall."
        ),
    )


class DriverIncomeStabilityReport(BaseModel):
    """12-week retrospective income stability report for the authenticated driver.

    Quantifies earnings variance so drivers can understand their income
    stability and plan personal finances accordingly.  A cooperative platform
    owes its member-drivers this visibility.
    """

    period_weeks: int = Field(
        12,
        description="Total calendar weeks covered by this report (always 12).",
    )
    weeks_analyzed: int = Field(
        ...,
        description=(
            "Weeks within the 12-week window that had at least one completed ride.  "
            "May be less than 12 for newer or recently inactive drivers."
        ),
    )
    weeks_inactive: int = Field(
        ...,
        description="Weeks within the 12-week window with zero earnings.",
    )
    mean_weekly_earnings_usd: Optional[float] = Field(
        None,
        description=(
            "Average weekly earnings across active weeks.  "
            "None when weeks_analyzed is 0."
        ),
    )
    std_dev_weekly_earnings_usd: Optional[float] = Field(
        None,
        description=(
            "Population standard deviation of weekly earnings across active weeks.  "
            "None when fewer than 2 active weeks exist."
        ),
    )
    coefficient_of_variation: Optional[float] = Field(
        None,
        description=(
            "Ratio of std_dev to mean (dimensionless volatility measure).  "
            "None when mean is 0 or fewer than 2 active weeks exist."
        ),
    )
    stability_tier: str = Field(
        ...,
        description=(
            "Categorical income stability level derived from the coefficient of "
            "variation: 'high' (CV < 0.2), 'moderate' (0.2–0.4), 'low' (CV > 0.4), "
            "'insufficient_data' (fewer than 2 active weeks)."
        ),
    )
    trend_direction: str = Field(
        ...,
        description=(
            "Earnings trend over the 12-week window: 'improving' (last-4-week average "
            "exceeds first-4-week average by more than 10%), 'declining' (more than 10% "
            "drop), 'stable' (within ±10%), or 'insufficient_data' (fewer than 8 active "
            "weeks across the two comparison windows)."
        ),
    )
    best_week_earnings_usd: Optional[float] = Field(
        None,
        description=(
            "Highest single-week gross earnings in the 12-week window.  "
            "None when no active weeks exist."
        ),
    )
    worst_nonzero_week_earnings_usd: Optional[float] = Field(
        None,
        description=(
            "Lowest weekly gross earnings among active (non-zero) weeks.  "
            "Inactive weeks are excluded so the metric reflects true earning "
            "volatility rather than time off.  None when no active weeks exist."
        ),
    )
    guarantee_activations: int = Field(
        ...,
        description=(
            "Count of weeks within the window where the cooperative's earnings "
            "guarantee issued a top-up payout.  0 when no guarantee records exist."
        ),
    )
    weekly_breakdown: list[WeeklyEarningsEntry] = Field(
        ...,
        description=(
            "Per-week earnings entries for all 12 weeks, sorted newest-first.  "
            "Weeks with no rides have earnings_usd=0 and ride_count=0."
        ),
    )
    stability_note: str = Field(
        ...,
        description=(
            "Human-readable sentence summarising the driver's income stability "
            "tier and trend direction.  Suitable for display as a dashboard card."
        ),
    )
