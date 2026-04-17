"""Fare preview schemas — rider-facing transparent pricing response."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class FareComponentsResponse(BaseModel):
    """Itemised fare components before multipliers."""

    base: float
    distance: float
    time: float


class SurgeZoneInfo(BaseModel):
    """Admin-defined surge zone details (shown only when active)."""

    multiplier: float
    zone_name: str | None
    zone_description: str | None


class DemandPricingInfo(BaseModel):
    """Real-time supply/demand pricing transparency."""

    multiplier: float
    multiplier_cap: float
    demand_count: int
    supply_count: int
    is_elevated: bool
    explanation: str


class FarePreviewResponse(BaseModel):
    """Full transparent fare preview — shown to rider before confirming a ride.

    Two surge signals are always disclosed separately:
    - ``surge_zone``: admin-defined geographic zones (e.g. airport, stadium)
    - ``demand_pricing``: real-time supply/demand (ride requests vs available drivers)

    The ``pricing_summary`` field provides a plain-English explanation of any
    elevated pricing, including percentage increases and driver/demand counts.
    """

    # Route information
    origin_lat: float
    origin_lon: float
    dest_lat: float
    dest_lon: float
    distance_km: float
    duration_min: float
    route_source: Literal["osrm", "estimate"]

    # Surge zone (admin-defined geographic zones)
    surge_zone: SurgeZoneInfo

    # Real-time demand pricing
    demand_pricing: DemandPricingInfo

    # Time-of-day multiplier (operator-configured)
    time_of_day_multiplier: float
    time_of_day_label: str | None

    # Fare components
    components: FareComponentsResponse

    # Totals
    combined_multiplier: float
    subtotal: float
    platform_fee: float
    estimated_fare: float

    # Transparency
    pricing_summary: str
    is_surge_active: bool
    currency: str = "USD"
