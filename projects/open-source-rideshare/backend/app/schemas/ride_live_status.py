"""Schema for the live-status polling endpoint.

GET /api/v1/rides/{ride_id}/live-status

Compact consolidated snapshot of a ride designed for frequent polling
(every 3–10 seconds) by the frontend.  Both riders and drivers use this
endpoint; the auth guard allows whichever party belongs to the ride.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class RideLiveStatus(BaseModel):
    """Current state snapshot of a ride, returned by the live-status endpoint.

    Fields
    ------
    ride_id:
        Primary key of the ride.
    status:
        Current ``RideStatus`` value string (e.g. ``"driver_en_route"``).

    driver_lat / driver_lng:
        Driver's current GPS position.  ``None`` if no driver is assigned or
        the driver has not submitted a GPS fix yet.

    distance_to_pickup_m:
        Haversine distance in metres from the driver's position to the pickup
        point.  ``None`` when the driver is not yet en route or has no GPS fix.
    eta_to_pickup_minutes:
        Estimated minutes until driver reaches pickup at 25 km/h.  ``None``
        under the same conditions as ``distance_to_pickup_m``.

    distance_to_dropoff_m:
        Haversine distance in metres from the driver's position to the dropoff
        point.  Only populated once the ride is ``in_progress``.
    eta_to_dropoff_minutes:
        Estimated minutes to dropoff at 25 km/h.  Only populated during
        ``in_progress``.

    requested_at:
        ISO-8601 timestamp when the ride was first requested.
    driver_matched_at:
        ISO-8601 timestamp when a driver was matched (``matched_at`` column).
        ``None`` if no driver has been matched yet.
    pickup_at:
        ISO-8601 timestamp when the driver arrived at the pickup point
        (``arrived_at`` column).  ``None`` until the driver marks arrival.
    completed_at:
        ISO-8601 timestamp when the ride completed.  ``None`` until done.

    phase_message:
        Human-readable description of the current ride phase suitable for
        display in the app UI.
    poll_interval_seconds:
        Hint to the client about how frequently to poll this endpoint, in
        seconds.  Varies by ride status (e.g. 5 s while active, 60 s once
        completed).
    """

    ride_id: int
    status: str

    # Driver position
    driver_lat: Optional[float] = None
    driver_lng: Optional[float] = None

    # Pickup info
    distance_to_pickup_m: Optional[float] = None
    eta_to_pickup_minutes: Optional[int] = None

    # Dropoff info
    distance_to_dropoff_m: Optional[float] = None
    eta_to_dropoff_minutes: Optional[int] = None

    # Key timestamps (ISO-8601 strings)
    requested_at: Optional[str] = None
    driver_matched_at: Optional[str] = None
    pickup_at: Optional[str] = None
    completed_at: Optional[str] = None

    # Client hints
    phase_message: str
    poll_interval_seconds: int
