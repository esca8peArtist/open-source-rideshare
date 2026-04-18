"""Service layer for per-ride driver earnings breakdown.

Given a completed ride's stored data, decomposes driver pay into:
  base_fare / distance_earnings / time_earnings / platform_fee / net_fare / tip

The component breakdown (base/distance/time) is reconstructed from pricing
params using the stored distance_km and duration_min.  Because surge and
demand multipliers are not persisted per-ride, the components are scaled to
match actual_fare so the sum is always exact.
"""

from __future__ import annotations

from datetime import datetime

from app.schemas.driver_ride_earnings import DriverRideEarnings
from app.services.pricing import calculate_fare_breakdown, get_pricing_params


def compute_driver_ride_earnings(
    ride_id: int,
    pickup_address: str,
    dropoff_address: str,
    actual_fare: float,
    tip_amount: float,
    distance_km: float | None,
    duration_min: float | None,
    completed_at: datetime,
) -> DriverRideEarnings:
    """Compute driver earnings breakdown for a completed ride.

    Args:
        actual_fare: Total fare paid by rider (includes platform fee).
        tip_amount:  Tip paid by rider directly to driver.
        distance_km: Stored trip distance; None if unavailable.
        duration_min: Stored trip duration; None if unavailable.
        completed_at: Ride completion timestamp (used for time-of-day multipliers).
    """
    params = get_pricing_params()
    pct = params["platform_fee_percent"]

    # Derive driver's net from actual_fare.
    # actual_fare = subtotal * (1 + pct/100)  →  subtotal = actual_fare / (1 + pct/100)
    if pct > 0:
        subtotal = round(actual_fare / (1.0 + pct / 100.0), 2)
    else:
        subtotal = round(actual_fare, 2)
    platform_fee = round(actual_fare - subtotal, 2)
    net_fare = subtotal

    # Reconstruct fare components via pricing service.
    # Components are scaled to match actual_fare so they sum correctly.
    d = distance_km if distance_km is not None else 0.0
    dur = duration_min if duration_min is not None else 0.0
    breakdown = calculate_fare_breakdown(d, dur, at_time=completed_at)

    if breakdown.total > 0:
        scale = actual_fare / breakdown.total
    else:
        scale = 0.0

    base_fare = round(breakdown.base * scale, 2)
    distance_earnings = round(breakdown.distance * scale, 2)
    time_earnings = round(breakdown.time * scale, 2)

    tip = round(float(tip_amount), 2)
    total_driver_earnings = round(net_fare + tip, 2)

    return DriverRideEarnings(
        ride_id=ride_id,
        pickup_address=pickup_address,
        dropoff_address=dropoff_address,
        distance_km=distance_km,
        duration_min=duration_min,
        completed_at=completed_at,
        base_fare=base_fare,
        distance_earnings=distance_earnings,
        time_earnings=time_earnings,
        subtotal=subtotal,
        platform_fee=platform_fee,
        net_fare=net_fare,
        tip=tip,
        total_driver_earnings=total_driver_earnings,
    )
