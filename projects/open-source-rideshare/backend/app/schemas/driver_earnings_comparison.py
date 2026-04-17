"""Schemas for the driver earnings comparison endpoint.

Compares a driver's actual OpenRide payouts to estimated Uber/Lyft payouts
for the same trips, using published platform rate cards.
"""
from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class PlatformRateCard(BaseModel):
    """Published rate card for a competing rideshare platform."""

    platform_name: str
    base_fare_usd: float = Field(description="Per-ride base fare, USD")
    per_minute_usd: float = Field(description="Per-minute in-ride rate, USD")
    per_mile_usd: float = Field(description="Per-mile rate, USD")
    driver_take_rate: float = Field(
        description="Fraction of the computed fare paid to the driver (0.0–1.0)"
    )
    source_note: str = Field(
        description="Rate source and applicable geography/date range"
    )


class EarningsComparisonRequest(BaseModel):
    """Optional date-range filter for the comparison endpoint."""

    start_date: date | None = Field(
        None, description="Inclusive start date; defaults to first day of current month"
    )
    end_date: date | None = Field(
        None, description="Inclusive end date; defaults to today"
    )


class EarningsComparisonResponse(BaseModel):
    """Comparison of OpenRide actual earnings vs. estimated competitor payouts."""

    # -----------------------------------------------------------------------
    # Query window
    # -----------------------------------------------------------------------
    period_start: date
    period_end: date

    # -----------------------------------------------------------------------
    # Ride counts
    # -----------------------------------------------------------------------
    rides_analyzed: int = Field(
        description="Rides with complete distance + duration data used in comparison"
    )
    rides_excluded: int = Field(
        description="Completed rides skipped because distance or duration data is missing"
    )

    # -----------------------------------------------------------------------
    # Trip totals
    # -----------------------------------------------------------------------
    total_distance_km: float
    total_distance_miles: float
    total_duration_min: float

    # -----------------------------------------------------------------------
    # OpenRide actuals
    # -----------------------------------------------------------------------
    openride_total_payout: float = Field(
        description="Actual amount paid to the driver by OpenRide (from Payment records)"
    )
    openride_total_tips: float = Field(
        description="Tips included in the OpenRide payout total"
    )
    openride_avg_payout_per_ride: float
    openride_avg_payout_per_mile: float
    openride_avg_payout_per_hour: float

    # -----------------------------------------------------------------------
    # Competitor estimates
    # -----------------------------------------------------------------------
    uber_estimated_total_payout: float = Field(
        description="Estimated driver earnings on Uber for the same trips"
    )
    lyft_estimated_total_payout: float = Field(
        description="Estimated driver earnings on Lyft for the same trips"
    )

    # -----------------------------------------------------------------------
    # Advantage deltas (positive = OpenRide paid more)
    # -----------------------------------------------------------------------
    openride_vs_uber_delta: float = Field(
        description="Extra earnings on OpenRide vs. Uber (USD). Positive = OpenRide advantage."
    )
    openride_vs_lyft_delta: float = Field(
        description="Extra earnings on OpenRide vs. Lyft (USD). Positive = OpenRide advantage."
    )
    openride_vs_uber_pct: float = Field(
        description="Percentage more (+) or less (-) earned on OpenRide vs. Uber"
    )
    openride_vs_lyft_pct: float = Field(
        description="Percentage more (+) or less (-) earned on OpenRide vs. Lyft"
    )

    # -----------------------------------------------------------------------
    # Rate card reference
    # -----------------------------------------------------------------------
    uber_rate_card: PlatformRateCard
    lyft_rate_card: PlatformRateCard
    methodology_note: str = Field(
        description=(
            "Competitor earnings are estimates based on published national average "
            "rate cards. Actual competitor rates vary by city, time, and surge "
            "conditions. Tips are included in OpenRide totals but not modelled for "
            "competitor estimates."
        )
    )
