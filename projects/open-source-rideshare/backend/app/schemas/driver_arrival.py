"""Schema for the driver arrival countdown endpoint.

GET /rides/{ride_id}/driver-arrival — rider-facing ETA and distance while
a driver is en route to the pickup point.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class DriverArrivalResponse(BaseModel):
    """Real-time driver arrival information returned to the rider.

    Fields
    ------
    ride_id:
        The ride being tracked.
    status:
        Current ride status string (e.g. ``"driver_en_route"``).
    driver_assigned:
        True when a driver has been matched to the ride.
    driver_lat:
        Driver's current GPS latitude.  None if no location fix is available.
    driver_lng:
        Driver's current GPS longitude.  None if no location fix is available.
    pickup_lat:
        Rider's requested pickup latitude.
    pickup_lng:
        Rider's requested pickup longitude.
    distance_to_pickup_m:
        Haversine distance in meters from the driver's current position to the
        pickup point.  None when ``driver_lat``/``driver_lng`` are unavailable.
    eta_minutes:
        Estimated minutes until driver arrives at pickup, computed at 25 km/h.
        None when location is unavailable.
    message:
        Human-readable status description, e.g.
        ``"Driver is 0.8 km away, arriving in ~3 minutes"``.
    """

    ride_id: int
    status: str
    driver_assigned: bool
    driver_lat: Optional[float] = None
    driver_lng: Optional[float] = None
    pickup_lat: float
    pickup_lng: float
    distance_to_pickup_m: Optional[float] = None
    eta_minutes: Optional[int] = None
    message: str
