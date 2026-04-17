"""Pydantic schemas for rider trip history.

GET /riders/me/trip-history returns a paginated, filtered list of past trips
for the authenticated rider.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel


class TripSummary(BaseModel):
    """A single trip in the rider's history."""

    ride_id: int
    status: str  # RideStatus value
    pickup_address: str
    dropoff_address: str
    requested_at: datetime
    completed_at: Optional[datetime]
    cancelled_at: Optional[datetime]
    fare_usd: float  # actual_fare if completed, else estimated_fare
    distance_km: Optional[float]
    duration_min: Optional[float]
    tip_amount: float
    promo_discount: float
    driver_rating: Optional[int]  # rating the rider gave the driver (1–5)
    is_pool: bool
    cancellation_reason: Optional[str]


class TripHistoryFilters(BaseModel):
    """Echo of the filters applied to this response."""

    status: Literal["all", "completed", "cancelled"]
    from_date: Optional[date]
    to_date: Optional[date]
    limit: int
    offset: int


class RiderTripHistory(BaseModel):
    """Full paginated trip history response."""

    total_count: int  # total matching trips (before pagination)
    trips: list[TripSummary]
    filters_applied: TripHistoryFilters
