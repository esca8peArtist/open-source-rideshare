"""Pydantic schemas for driver revenue projection and earnings comparison endpoints.

Provides:
- RevenueProjectionDetail  — the core projection numbers
- HistoricalBasis          — the ride history the projection is derived from
- RevenueProjectionResponse — full response for GET /drivers/me/revenue-projections
- DriverPeriodStats        — a single side of the earnings comparison
- PlatformPeriodStats      — platform average side of the earnings comparison
- PercentileRanks          — percentile breakdown across all active drivers
- EarningsComparisonResponse — full response for GET /drivers/me/earnings-comparison
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class RevenueProjectionDetail(BaseModel):
    """Projected earnings numbers for the requested period and scenario."""

    estimated_rides: int = Field(..., description="Estimated number of rides completed")
    estimated_gross_earnings: float = Field(
        ..., description="Estimated gross fare earnings in dollars"
    )
    estimated_net_earnings: float = Field(
        ..., description="Estimated net earnings after platform fee deduction"
    )
    estimated_tips: float = Field(..., description="Estimated tip income in dollars")
    platform_fees_deducted: float = Field(
        ..., description="Estimated platform fees deducted in dollars"
    )
    avg_hourly_rate: float = Field(
        ..., description="Estimated net earnings per hour of driving"
    )


class HistoricalBasis(BaseModel):
    """Summary of the historical data used to build the projection."""

    historical_rides: int = Field(
        ..., description="Number of completed rides in the history window"
    )
    historical_days: int = Field(
        ..., description="Number of calendar days in the history window"
    )
    avg_daily_rides: float = Field(
        ..., description="Average rides completed per calendar day"
    )
    avg_earnings_per_ride: float = Field(
        ..., description="Average gross fare per ride in dollars"
    )


class RevenueProjectionResponse(BaseModel):
    """Response for GET /drivers/me/revenue-projections.

    When the driver has fewer than 5 completed rides, ``is_new_driver_estimate``
    is ``true`` and the projection is derived from platform-wide averages rather
    than the driver's personal history.
    """

    driver_id: int
    period: str = Field(..., description="Requested period: week | month | quarter")
    scenario: str = Field(
        ..., description="Requested scenario: conservative | moderate | optimistic"
    )
    projection: RevenueProjectionDetail
    based_on: HistoricalBasis
    scenario_multipliers: dict[str, float] = Field(
        ...,
        description="Multipliers applied for each scenario relative to moderate baseline",
    )
    is_new_driver_estimate: bool = Field(
        ...,
        description=(
            "True when the driver has < 5 rides and projection uses platform averages"
        ),
    )
    notes: str = Field(..., description="Human-readable explanation of the projection")


# ---------------------------------------------------------------------------
# Earnings comparison schemas
# ---------------------------------------------------------------------------


class DriverPeriodStats(BaseModel):
    """This driver's aggregate stats for the comparison period."""

    total_rides: int
    gross_earnings: float
    avg_per_ride: float
    tips: float
    completion_rate: float = Field(
        ..., description="Completed rides / (completed + cancelled) for the period"
    )


class PlatformPeriodStats(BaseModel):
    """Platform-wide average stats across all active drivers for the period."""

    total_rides: float
    gross_earnings: float
    avg_per_ride: float
    tips: float
    completion_rate: float


class PercentileRanks(BaseModel):
    """Percentile rank (0–100) of this driver vs. all active drivers in the period."""

    rides: int = Field(..., ge=0, le=100)
    earnings: int = Field(..., ge=0, le=100)
    tips: int = Field(..., ge=0, le=100)
    completion_rate: int = Field(..., ge=0, le=100)


class EarningsComparisonResponse(BaseModel):
    """Response for GET /drivers/me/earnings-comparison."""

    period: str = Field(..., description="Requested period: week | month | quarter")
    driver: DriverPeriodStats
    platform_average: PlatformPeriodStats
    percentile: PercentileRanks
