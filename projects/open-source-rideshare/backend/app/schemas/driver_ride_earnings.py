from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class DriverRideEarnings(BaseModel):
    ride_id: int
    pickup_address: str
    dropoff_address: str
    distance_km: float | None
    duration_min: float | None
    completed_at: datetime
    # Fare components (scaled to match actual_fare)
    base_fare: float
    distance_earnings: float
    time_earnings: float
    # Fare totals
    subtotal: float
    platform_fee: float
    net_fare: float
    # Tip
    tip: float
    # Summary
    total_driver_earnings: float
