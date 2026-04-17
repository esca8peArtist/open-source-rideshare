"""Schemas for the pre-booking fare transparency preview endpoint.

GET /pricing/fare-preview returns a FarePreviewResponse showing:
  - OpenRide's estimated fare and driver payout (zero platform commission)
  - Estimated fares and driver payouts for Uber and Lyft for the same trip
  - Human-readable transparency and methodology notes

This lets riders see the cooperative advantage before they book, and
lets drivers understand what they'd earn compared to competitor platforms.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class FarePreviewCompetitor(BaseModel):
    """Estimated fare and driver earnings for one competitor platform."""

    platform_name: str = Field(description="Name of the competitor platform")
    estimated_fare_usd: float = Field(
        description="Estimated rider fare on this platform for the same trip"
    )
    estimated_driver_payout_usd: float = Field(
        description="Estimated driver earnings after platform commission"
    )
    estimated_driver_payout_pct: float = Field(
        description="Estimated driver take rate as a percentage (e.g. 75.0 means 75%)"
    )
    estimated_platform_fee_usd: float = Field(
        description="Estimated platform commission taken from this fare"
    )
    estimated_platform_fee_pct: float = Field(
        description="Estimated platform commission rate as a percentage"
    )
    source_note: str = Field(
        description="Disclosure of data sources and limitations for this estimate"
    )


class FarePreviewResponse(BaseModel):
    """Pre-booking fare transparency breakdown.

    Shows the estimated fare, driver earnings, and platform fees for
    OpenRide alongside equivalent estimates for Uber and Lyft.
    """

    # ── Trip parameters ──────────────────────────────────────────────────────
    distance_km: float = Field(description="Trip distance in kilometres")
    duration_min: float = Field(description="Estimated trip duration in minutes")
    surge_multiplier: float = Field(
        description="Surge multiplier in effect (1.0 = no surge)"
    )
    is_surge: bool = Field(
        description="True when surge_multiplier > 1.0"
    )

    # ── OpenRide fare ─────────────────────────────────────────────────────────
    estimated_fare_usd: float = Field(
        description="OpenRide estimated total fare the rider pays"
    )
    driver_payout_usd: float = Field(
        description="Estimated driver earnings on OpenRide (fare minus platform fee)"
    )
    driver_payout_pct: float = Field(
        description="Estimated driver share as a percentage of the fare"
    )
    platform_fee_usd: float = Field(
        description="Platform fee charged by OpenRide (0.00 — zero commission model)"
    )
    platform_fee_pct: float = Field(
        description="Platform fee as a percentage of the fare (0.0 — zero commission)"
    )

    # ── Competitors ───────────────────────────────────────────────────────────
    uber_estimate: FarePreviewCompetitor = Field(
        description="Estimated fare and driver earnings on Uber for the same trip"
    )
    lyft_estimate: FarePreviewCompetitor = Field(
        description="Estimated fare and driver earnings on Lyft for the same trip"
    )

    # ── Derived comparisons ───────────────────────────────────────────────────
    driver_earns_more_than_uber_usd: float = Field(
        description=(
            "How much more the driver earns on OpenRide vs Uber. "
            "Positive = driver earns more on OpenRide."
        )
    )
    driver_earns_more_than_lyft_usd: float = Field(
        description=(
            "How much more the driver earns on OpenRide vs Lyft. "
            "Positive = driver earns more on OpenRide."
        )
    )

    # ── Human-readable notes ──────────────────────────────────────────────────
    transparency_note: str = Field(
        description="Human-readable summary of the fare split for the rider app UI"
    )
    methodology_note: str = Field(
        description="Disclosure of data sources and limitations"
    )
