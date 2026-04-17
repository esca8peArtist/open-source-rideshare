"""Pydantic schemas for the rider savings summary endpoint.

GET /riders/me/savings-summary

Shows a rider the cumulative fare savings compared to Uber and Lyft across
their completed ride history.  Only rides with distance and duration data
contribute to the competitor comparison; rides without that data are counted
in total_openride_spend_usd but excluded from the savings calculation.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from pydantic import BaseModel, Field


class RiderSavingsSummary(BaseModel):
    """Cumulative savings summary for an authenticated rider."""

    # -----------------------------------------------------------------------
    # Ride counts
    # -----------------------------------------------------------------------
    total_completed_rides: int = Field(
        ...,
        description=(
            "Total number of completed rides in the requested period."
        ),
    )
    rides_included_in_comparison: int = Field(
        ...,
        description=(
            "Number of rides where both distance and duration data were available "
            "for competitor fare estimation.  Rides without distance/duration data "
            "are counted in total_openride_spend_usd but excluded from the savings "
            "comparison."
        ),
    )

    # -----------------------------------------------------------------------
    # Spend totals
    # -----------------------------------------------------------------------
    total_openride_spend_usd: float = Field(
        ...,
        description=(
            "Total amount paid to OpenRide for all completed rides in the period "
            "(sum of actual_fare, excluding tips)."
        ),
    )
    total_tips_usd: float = Field(
        ...,
        description=(
            "Total tips paid across completed rides.  Tips go 100%% to drivers on "
            "all platforms; they are reported here separately and are not included "
            "in the competitor savings comparison."
        ),
    )

    # -----------------------------------------------------------------------
    # Competitor estimates (only for rides with distance/duration data)
    # -----------------------------------------------------------------------
    total_estimated_uber_spend_usd: float = Field(
        ...,
        description=(
            "Estimated total rider spend for the same trips on Uber (UberX), "
            "based on 2025 US national average rate cards applied to each "
            "ride's recorded distance and duration.  Only includes rides with "
            "distance and duration data."
        ),
    )
    total_estimated_lyft_spend_usd: float = Field(
        ...,
        description=(
            "Estimated total rider spend for the same trips on Lyft (Standard), "
            "based on 2025 US national average rate cards applied to each "
            "ride's recorded distance and duration.  Only includes rides with "
            "distance and duration data."
        ),
    )

    # -----------------------------------------------------------------------
    # Savings
    # -----------------------------------------------------------------------
    total_saved_vs_uber_usd: float = Field(
        ...,
        description=(
            "Estimated total savings vs. Uber over the period.  Positive values "
            "mean OpenRide was cheaper; negative values mean OpenRide was more "
            "expensive for the comparable trips."
        ),
    )
    total_saved_vs_lyft_usd: float = Field(
        ...,
        description=(
            "Estimated total savings vs. Lyft over the period.  Positive values "
            "mean OpenRide was cheaper; negative values mean OpenRide was more "
            "expensive for the comparable trips."
        ),
    )
    avg_saved_per_ride_vs_uber_usd: float = Field(
        ...,
        description=(
            "Average per-ride savings vs. Uber for rides included in the comparison."
        ),
    )
    avg_saved_per_ride_vs_lyft_usd: float = Field(
        ...,
        description=(
            "Average per-ride savings vs. Lyft for rides included in the comparison."
        ),
    )

    # -----------------------------------------------------------------------
    # Period bounds
    # -----------------------------------------------------------------------
    period_start: Optional[date] = Field(
        None,
        description="Inclusive start date applied to the query, if provided.",
    )
    period_end: Optional[date] = Field(
        None,
        description="Inclusive end date applied to the query, if provided.",
    )

    # -----------------------------------------------------------------------
    # Disclosure
    # -----------------------------------------------------------------------
    methodology_note: str = Field(
        ...,
        description=(
            "Disclosure of the estimation method and its limitations.  Always "
            "present — surface this in the rider-facing UI alongside the figures."
        ),
    )
    transparency_note: str = Field(
        ...,
        description=(
            "Human-readable summary sentence suitable for display in the rider app."
        ),
    )
