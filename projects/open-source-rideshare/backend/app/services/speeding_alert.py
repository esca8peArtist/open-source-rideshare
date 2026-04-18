"""Driver speeding alert for active rides.

When a driver submits a location update during an IN_PROGRESS ride, this
service estimates their current speed from consecutive GPS positions.  If
the computed speed exceeds the configured threshold and the ride hasn't
already been flagged, the rider is notified and the flag is persisted
(fires only once per ride).

Speed is approximated using the haversine formula between consecutive
positions divided by elapsed time.  A minimum interval of 3 seconds
is enforced to discard near-instantaneous samples that would produce
unreliable speed estimates.

Usage
-----
Called fire-and-forget from the driver location update endpoint:

    asyncio.ensure_future(
        check_and_notify_speeding(user_id=driver_user_id, lat=lat, lng=lng, db=db)
    )
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

DEFAULT_SPEEDING_THRESHOLD_MPH: float = 90.0
MIN_INTERVAL_SECONDS: float = 3.0
_EARTH_RADIUS_MILES: float = 3_958.8

# Maps driver_user_id → (lat, lng, recorded_at)
_prev_positions: dict[int, tuple[float, float, datetime]] = {}


def _clear_prev_positions() -> None:
    """Test helper — reset the in-memory position store."""
    _prev_positions.clear()


def compute_speed_mph(
    lat1: float,
    lng1: float,
    t1: datetime,
    lat2: float,
    lng2: float,
    t2: datetime,
) -> float:
    """Return the average speed in mph between two GPS samples.

    Uses haversine great-circle distance.  Returns 0.0 if elapsed time is
    zero or negative to avoid division errors.
    """
    elapsed_seconds = (t2 - t1).total_seconds()
    if elapsed_seconds <= 0:
        return 0.0

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lam = math.radians(lng2 - lng1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lam / 2) ** 2
    distance_miles = 2 * math.asin(math.sqrt(a)) * _EARTH_RADIUS_MILES

    elapsed_hours = elapsed_seconds / 3_600
    return distance_miles / elapsed_hours


async def check_and_notify_speeding(
    user_id: int,
    lat: float,
    lng: float,
    db: AsyncSession,
    threshold_mph: float = DEFAULT_SPEEDING_THRESHOLD_MPH,
    _now: datetime | None = None,
) -> bool:
    """Check whether the driver is travelling above the speed threshold.

    Computes speed from the driver's previous and current GPS positions.
    If speed exceeds *threshold_mph* and the active ride hasn't already been
    flagged, the flag is persisted and the rider is notified.

    Returns True if a new speeding event was detected and the rider notified,
    False otherwise (no active ride, already flagged, within threshold, or error).

    This function is designed to be called fire-and-forget.  Any exception is
    caught and logged so that location updates are never blocked.
    """
    now = _now if _now is not None else datetime.now(timezone.utc)

    # Always update the position store before returning — even on early exit.
    # Capture previous position first.
    prev = _prev_positions.get(user_id)
    _prev_positions[user_id] = (lat, lng, now)

    try:
        from sqlalchemy import select, update

        from app.models.ride import Ride, RideStatus
        from app.services.notification_events import notify_speeding_alert

        # Need a previous position to compute speed
        if prev is None:
            return False

        prev_lat, prev_lng, prev_ts = prev
        elapsed = (now - prev_ts).total_seconds()
        if elapsed < MIN_INTERVAL_SECONDS:
            return False

        # 1. Find the driver's active IN_PROGRESS ride
        result = await db.execute(
            select(Ride.id).where(
                Ride.driver_id == user_id,
                Ride.status == RideStatus.IN_PROGRESS,
            )
        )
        row = result.first()
        if row is None:
            return False
        ride_id = row[0]

        # 2. Check if ride already flagged
        result = await db.execute(
            select(Ride.speeding_flagged_at, Ride.rider_id).where(Ride.id == ride_id)
        )
        ride_row = result.one_or_none()
        if ride_row is None or ride_row.speeding_flagged_at is not None:
            return False

        rider_id = ride_row.rider_id

        # 3. Compute speed
        speed_mph = compute_speed_mph(prev_lat, prev_lng, prev_ts, lat, lng, now)
        if speed_mph <= threshold_mph:
            return False

        # 4. Persist flag (idempotent — only set once)
        await db.execute(
            update(Ride)
            .where(Ride.id == ride_id, Ride.speeding_flagged_at.is_(None))
            .values(speeding_flagged_at=now)
        )
        await db.commit()

        # 5. Notify rider (fire-and-forget, exception-safe)
        await notify_speeding_alert(
            db=db,
            rider_id=rider_id,
            ride_id=ride_id,
        )

        logger.warning(
            "Speeding flagged for ride %d (driver user %d, %.0f mph)",
            ride_id,
            user_id,
            speed_mph,
        )
        return True

    except Exception:
        logger.exception(
            "Unexpected error in speeding check for driver user %d", user_id
        )
        return False
