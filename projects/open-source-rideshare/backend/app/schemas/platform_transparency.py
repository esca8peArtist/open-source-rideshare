"""Pydantic schemas for the platform transparency report endpoint.

GET /platform/transparency-report

A public, unauthenticated endpoint that publishes aggregate platform
economics — ride volumes, driver earnings, rider savings, and service
quality — for the requested time period.

This report is something Uber and Lyft would never voluntarily publish.
OpenRide does so as a matter of cooperative principle.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class PlatformModel(BaseModel):
    """Static description of OpenRide's economic model."""

    commission_rate_pct: float = Field(
        ...,
        description="Platform commission rate as a percentage. Always 0.0 on OpenRide.",
    )
    commission_note: str = Field(
        ...,
        description="Human-readable explanation of the zero-commission model.",
    )
    ownership_model: str = Field(
        ...,
        description="Describes the ownership structure (e.g. 'cooperative').",
    )
    cooperative_description: str = Field(
        ...,
        description=(
            "Explanation of how the cooperative model works and how surplus "
            "revenue is returned to driver-owners."
        ),
    )


class RideVolume(BaseModel):
    """Aggregate ride counts for the report period."""

    total_rides_completed: int = Field(
        ...,
        description="Total rides completed across all time on the platform.",
    )
    total_rides_period: int = Field(
        ...,
        description="Rides completed within the requested report period.",
    )
    period_label: str = Field(
        ...,
        description="Human-readable label for the period (e.g. 'Last 30 days').",
    )


class EarningsSummary(BaseModel):
    """Aggregate driver earnings and competitor comparison for the period."""

    total_driver_earnings_usd: float = Field(
        ...,
        description=(
            "Sum of all driver payouts for completed rides in the period. "
            "On OpenRide, drivers keep 100% of base fares."
        ),
    )
    avg_driver_earnings_per_ride_usd: float = Field(
        ...,
        description="Average driver payout per completed ride in the period.",
    )
    avg_driver_payout_pct: float = Field(
        ...,
        description=(
            "Average percentage of each fare that went to the driver. "
            "Always 100.0 on OpenRide — no platform commission is deducted."
        ),
    )
    uber_equivalent_driver_earnings_usd: float = Field(
        ...,
        description=(
            "Estimated driver earnings had the same rides been completed on Uber "
            "(UberX), applying the 2025 national average 75% driver take rate."
        ),
    )
    lyft_equivalent_driver_earnings_usd: float = Field(
        ...,
        description=(
            "Estimated driver earnings had the same rides been completed on Lyft "
            "(Standard), applying the 2025 national average 75% driver take rate."
        ),
    )
    driver_savings_vs_uber_usd: float = Field(
        ...,
        description=(
            "Total additional earnings drivers received on OpenRide vs. the "
            "estimated Uber equivalent. Positive = drivers kept more on OpenRide."
        ),
    )
    driver_savings_vs_lyft_usd: float = Field(
        ...,
        description=(
            "Total additional earnings drivers received on OpenRide vs. the "
            "estimated Lyft equivalent. Positive = drivers kept more on OpenRide."
        ),
    )


class RiderSummary(BaseModel):
    """Aggregate rider metrics and competitor fare comparison for the period."""

    unique_riders_period: int = Field(
        ...,
        description="Number of distinct riders who completed at least one ride in the period.",
    )
    avg_fare_usd: float = Field(
        ...,
        description="Average fare paid by riders per completed ride in the period.",
    )
    avg_uber_equivalent_fare_usd: float = Field(
        ...,
        description=(
            "Estimated average fare riders would have paid on Uber (UberX), "
            "calculated from recorded distance and duration using 2025 rate cards. "
            "Higher than OpenRide because Uber extracts a platform commission."
        ),
    )
    avg_lyft_equivalent_fare_usd: float = Field(
        ...,
        description=(
            "Estimated average fare riders would have paid on Lyft (Standard), "
            "calculated from recorded distance and duration using 2025 rate cards."
        ),
    )
    avg_rider_savings_vs_uber_usd: float = Field(
        ...,
        description=(
            "Average per-ride saving for riders vs. the Uber equivalent. "
            "Positive = riders paid less on OpenRide."
        ),
    )
    avg_rider_savings_vs_lyft_usd: float = Field(
        ...,
        description=(
            "Average per-ride saving for riders vs. the Lyft equivalent. "
            "Positive = riders paid less on OpenRide."
        ),
    )


class ServiceQuality(BaseModel):
    """Aggregate service quality metrics for the period."""

    avg_driver_rating: float = Field(
        ...,
        description="Average driver rating (1-5 scale) across rated rides in the period.",
    )
    avg_rider_rating: float = Field(
        ...,
        description="Average rider rating (1-5 scale) across rated rides in the period.",
    )
    rides_completed_pct: float = Field(
        ...,
        description=(
            "Ride completion rate as a percentage: "
            "(completed rides / (completed + cancelled rides)) * 100."
        ),
    )


class PlatformTransparencyReport(BaseModel):
    """Full platform transparency report.

    Published publicly by OpenRide to demonstrate cooperative accountability.
    Contains aggregate platform economics across the requested period,
    including driver earnings, rider savings, and service quality metrics.
    """

    generated_at: datetime = Field(
        ...,
        description="UTC timestamp at which this report was generated.",
    )
    report_period: str = Field(
        ...,
        description=(
            "The period key used to generate this report: "
            "'last_7_days', 'last_30_days', or 'all_time'."
        ),
    )
    data_available: bool = Field(
        ...,
        description=(
            "True when the platform has ride data to report. False when the "
            "database contains no completed rides (e.g. a fresh installation). "
            "All numeric fields are set to zero when data_available is False."
        ),
    )
    platform_model: PlatformModel = Field(
        ...,
        description="Static description of OpenRide's cooperative economic model.",
    )
    ride_volume: RideVolume = Field(
        ...,
        description="Aggregate ride counts for the period.",
    )
    earnings_summary: EarningsSummary = Field(
        ...,
        description="Driver earnings and competitor comparison for the period.",
    )
    rider_summary: RiderSummary = Field(
        ...,
        description="Rider fare metrics and competitor comparison for the period.",
    )
    service_quality: ServiceQuality = Field(
        ...,
        description="Aggregate service quality metrics for the period.",
    )
    methodology_note: str = Field(
        ...,
        description=(
            "Full disclosure of how competitor estimates are calculated, "
            "data sources used, and limitations of the comparison."
        ),
    )
    transparency_note: str = Field(
        ...,
        description=(
            "Statement of intent: why OpenRide publishes this report publicly "
            "when competitors do not."
        ),
    )
