"""Schemas for the rider fare transparency endpoint.

Shows riders the exact breakdown of what they paid: how much went to the
driver, how much was the platform fee, and taxes — then compares OpenRide's
take rate to Uber/Lyft so riders can see the difference in where their money
goes.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class CompetitorFeeComparison(BaseModel):
    """Estimated platform fees a rider would have paid on a competitor platform."""

    platform_name: str
    platform_fee_rate: float = Field(
        description="Competitor's platform fee as a fraction of total fare (0.0–1.0)"
    )
    estimated_platform_fee_usd: float = Field(
        description="Estimated platform fee the rider would have paid on this platform, USD"
    )
    estimated_driver_payout_usd: float = Field(
        description="Estimated driver payout on this platform for the same fare, USD"
    )
    source_note: str = Field(
        description="Rate source and applicable geography/date range"
    )


class FareBreakdownResponse(BaseModel):
    """Per-ride fare breakdown showing exactly where the rider's money goes.

    All amounts are in USD.
    """

    # -----------------------------------------------------------------------
    # Identifiers
    # -----------------------------------------------------------------------
    ride_id: int

    # -----------------------------------------------------------------------
    # Fare components
    # -----------------------------------------------------------------------
    total_fare_usd: float = Field(
        description="Total amount charged to the rider, USD"
    )
    driver_payout_usd: float = Field(
        description="Amount received by the driver, USD"
    )
    driver_payout_pct: float = Field(
        description="Driver payout as a percentage of total fare (0–100)"
    )
    platform_fee_usd: float = Field(
        description="OpenRide platform fee, USD"
    )
    platform_fee_pct: float = Field(
        description="Platform fee as a percentage of total fare (0–100)"
    )
    tip_usd: float = Field(
        description=(
            "Tip included in total fare, USD. "
            "Tips go 100% to the driver and are excluded from platform fee calculation."
        )
    )
    taxes_usd: float = Field(
        description=(
            "Tax component, USD. Currently 0.00 — OpenRide passes no tax surcharge "
            "to riders beyond the base fare. Included for future transparency if tax "
            "tracking is added."
        )
    )
    taxes_pct: float = Field(
        description="Taxes as a percentage of total fare (0–100)"
    )

    # -----------------------------------------------------------------------
    # Data source flag
    # -----------------------------------------------------------------------
    platform_fee_is_estimated: bool = Field(
        description=(
            "True when the platform fee was derived from the standard rate constant "
            "rather than a stored per-ride Payment record. This occurs for cash rides "
            "or legacy records created before platform_fee tracking was introduced."
        )
    )
    openride_platform_fee_rate_used: float = Field(
        description=(
            "The OpenRide platform fee rate applied in this breakdown (0.0–1.0). "
            "Sourced from the Payment record when available; otherwise the documented "
            "standard rate constant."
        )
    )

    # -----------------------------------------------------------------------
    # Competitor comparison
    # -----------------------------------------------------------------------
    uber_comparison: CompetitorFeeComparison
    lyft_comparison: CompetitorFeeComparison

    # -----------------------------------------------------------------------
    # OpenRide advantage
    # -----------------------------------------------------------------------
    driver_received_more_than_uber_usd: float = Field(
        description=(
            "Extra USD the driver received vs. estimated Uber payout for the same fare. "
            "Positive = driver got more on OpenRide."
        )
    )
    driver_received_more_than_lyft_usd: float = Field(
        description=(
            "Extra USD the driver received vs. estimated Lyft payout for the same fare. "
            "Positive = driver got more on OpenRide."
        )
    )

    # -----------------------------------------------------------------------
    # Human-readable context
    # -----------------------------------------------------------------------
    transparency_note: str = Field(
        description=(
            "Readable explanation of this fare breakdown for display in the rider app."
        )
    )
    methodology_note: str = Field(
        description=(
            "Competitor fee estimates are based on published 2025 US national average "
            "platform take rates. Actual competitor rates vary by city, promotion, and "
            "surge conditions."
        )
    )
