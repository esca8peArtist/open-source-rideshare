"""Pydantic schemas for the driver welfare summary endpoint.

GET /drivers/me/welfare-summary

Returns a holistic welfare snapshot for the authenticated driver: shift hours
vs. recommended safety limits, earnings this week, insurance status, and
cooperative membership context.

This endpoint is a deliberate cooperative differentiator.  Uber and Lyft have
no equivalent — they benefit from drivers working unlimited hours and have no
structural incentive to surface burnout risk.  A cooperative is owned by its
drivers and is legally obligated to act in their collective interest.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field


class ShiftMetrics(BaseModel):
    """Hours-of-service summary for the last 7 calendar days."""

    hours_this_week: float = Field(
        ...,
        description=(
            "Total hours driven in the last 7 calendar days (rolling window ending "
            "at midnight today in UTC).  Computed from completed and active shifts."
        ),
    )
    hours_today: float = Field(
        ...,
        description="Total hours driven today (UTC calendar date).",
    )
    max_consecutive_hours: Optional[float] = Field(
        None,
        description=(
            "Duration in hours of the longest single completed shift in the last "
            "7 days.  None if no completed shifts exist."
        ),
    )
    active_shift_hours: Optional[float] = Field(
        None,
        description=(
            "Hours elapsed in the currently active shift, if any.  None when no "
            "shift is currently open."
        ),
    )
    fatigue_risk: str = Field(
        ...,
        description=(
            "Categorical fatigue risk level derived from hours this week: "
            "'low' (< 40 h), 'moderate' (40–50 h), 'high' (> 50 h).  "
            "The platform recommends against exceeding 50 h/week."
        ),
    )
    recommended_weekly_max_hours: float = Field(
        50.0,
        description="Platform-recommended maximum hours per rolling 7-day period.",
    )
    recommended_daily_max_hours: float = Field(
        10.0,
        description="Platform-recommended maximum hours per calendar day.",
    )


class EarningsMetrics(BaseModel):
    """Earnings snapshot for the last 7 calendar days."""

    earnings_this_week_usd: float = Field(
        ...,
        description=(
            "Gross ride earnings (sum of actual_fare) for completed rides in the "
            "last 7 calendar days, excluding tips."
        ),
    )
    tips_this_week_usd: float = Field(
        ...,
        description="Total tips received in the last 7 calendar days.",
    )
    rides_completed_this_week: int = Field(
        ...,
        description="Count of completed rides in the last 7 calendar days.",
    )
    estimated_hourly_rate_usd: Optional[float] = Field(
        None,
        description=(
            "Estimated gross hourly rate: earnings_this_week_usd divided by "
            "hours_this_week.  None when hours_this_week is 0."
        ),
    )
    earnings_goal_set: bool = Field(
        ...,
        description="Whether the driver has configured a self-set earnings goal.",
    )
    earnings_goal_target_usd: Optional[float] = Field(
        None,
        description="The driver's self-set earnings target (weekly or daily), in USD.",
    )
    earnings_goal_progress_pct: Optional[float] = Field(
        None,
        description=(
            "Progress toward the active earnings goal as a percentage (0–100+).  "
            "None when no goal is set."
        ),
    )


class InsuranceStatus(BaseModel):
    """Summary of the driver's on-file insurance documents."""

    status: str = Field(
        ...,
        description=(
            "Current insurance status: 'active' (at least one approved, non-expired "
            "document on file), 'expiring_soon' (active but expires within 30 days), "
            "'pending' (document submitted, awaiting review), "
            "'expired' (most recent document has expired), "
            "'not_on_file' (no insurance document submitted)."
        ),
    )
    expires_on: Optional[date] = Field(
        None,
        description=(
            "Expiry date of the most recently approved insurance document.  "
            "None when no approved document exists."
        ),
    )
    days_until_expiry: Optional[int] = Field(
        None,
        description=(
            "Calendar days until the active insurance policy expires.  "
            "Negative values indicate the policy has already expired.  "
            "None when no approved document exists."
        ),
    )


class CooperativeStatus(BaseModel):
    """Driver's standing in the OpenRide cooperative."""

    is_approved_member: bool = Field(
        ...,
        description=(
            "Whether the driver has been approved as an active platform member.  "
            "Approval is required before accepting rides."
        ),
    )
    total_trips_lifetime: int = Field(
        ...,
        description="Total completed trips since the driver joined the platform.",
    )
    average_rating: float = Field(
        ...,
        description="The driver's current average passenger rating (1.0–5.0).",
    )
    background_check_status: str = Field(
        ...,
        description=(
            "Current background check status: 'pending', 'approved', 'rejected', "
            "or 'expired'."
        ),
    )


class SupportResource(BaseModel):
    """A welfare or support resource available to the driver."""

    name: str
    description: str
    url: Optional[str] = None


class DriverWelfareSummary(BaseModel):
    """Holistic welfare snapshot for the authenticated driver.

    Surfaces hours-of-service risk, earnings context, insurance status,
    and cooperative membership in a single response designed for display
    in the driver app home screen or a dedicated welfare section.
    """

    as_of: datetime = Field(
        ...,
        description="UTC timestamp at which this snapshot was computed.",
    )
    shift_metrics: ShiftMetrics = Field(
        ...,
        description="Hours-of-service summary for the last 7 calendar days.",
    )
    earnings_metrics: EarningsMetrics = Field(
        ...,
        description="Earnings snapshot for the last 7 calendar days.",
    )
    insurance_status: InsuranceStatus = Field(
        ...,
        description="Summary of on-file insurance documents.",
    )
    cooperative_status: CooperativeStatus = Field(
        ...,
        description="Driver's standing in the OpenRide cooperative.",
    )
    welfare_note: str = Field(
        ...,
        description=(
            "Human-readable welfare message tailored to the driver's current state.  "
            "Surfaces the most important signal (e.g. fatigue risk, expiring insurance, "
            "earnings goal progress).  Suitable for display as a notification card."
        ),
    )
    support_resources: list[SupportResource] = Field(
        default_factory=list,
        description=(
            "Welfare and support resources available to this driver.  "
            "Always includes at minimum: driver safety guidelines and "
            "the cooperative hardship fund."
        ),
    )
