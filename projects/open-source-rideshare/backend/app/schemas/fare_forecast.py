"""Fare forecast schemas — rider-facing future pricing transparency.

Public endpoint (no authentication required):
  GET /pricing/fare-forecast   — fare estimates across 6 future time slots

This lets riders pick the cheapest booking window for their trip. A
cooperative differentiator: Uber and Lyft show only current pricing,
never future estimates. All demand multipliers are clearly labelled as
heuristic estimates so riders always know what the data represents.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class ForecastSlot(BaseModel):
    """A single time slot in the fare forecast."""

    offset_minutes: int
    """Minutes from now when this slot begins."""

    estimated_departure: datetime
    """UTC datetime of this forecast slot."""

    surge_multiplier: float
    """Surge zone multiplier at this location and time (1.0 = no zone active)."""

    surge_zone_name: str | None
    """Name of the matching surge zone, or None if no zone is active."""

    demand_multiplier: float
    """Time-of-day demand multiplier (heuristic — not live Redis data)."""

    combined_multiplier: float
    """Product of surge and demand multipliers, rounded to 3 decimal places."""

    is_surge_active: bool
    """True when the combined multiplier exceeds 1.0."""

    estimated_fare: float
    """Estimated total fare in USD for this departure slot."""

    is_cheapest: bool
    """True for exactly one slot — the one with the lowest estimated fare.
    Ties are broken by picking the earliest slot.
    """


class FareForecastResponse(BaseModel):
    """Fare estimates at 6 evenly-spaced future time slots.

    ``demand_is_heuristic`` is always True — demand estimates are derived
    from time-of-day rules, not live Redis data. Clients should surface this
    clearly so riders understand the estimates are approximations.
    """

    origin_lat: float
    origin_lon: float
    dest_lat: float
    dest_lon: float

    distance_km: float
    """Haversine straight-line distance between pickup and dropoff."""

    estimated_duration_min: float
    """Estimated trip duration at 30 km/h average urban speed."""

    demand_is_heuristic: bool
    """Always True — demand multipliers are time-of-day estimates, not live."""

    forecast_generated_at: datetime
    """UTC timestamp when this forecast was generated (i.e. 'now')."""

    slots: list[ForecastSlot]
    """Six time slots ordered from earliest (offset 0) to latest."""

    recommendation: str
    """Plain-English guidance for the rider on when to book."""
