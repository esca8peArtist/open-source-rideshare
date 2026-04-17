"""Pickup verification service.

Allows a rider to confirm whether the driver's photo and vehicle license plate
match what was shown in the app before they enter the vehicle.  The result is
recorded on the Ride row regardless of outcome — a mismatch is logged and
flagged so ops teams can follow up, but the verification never blocks the rider
from proceeding (they retain full autonomy over whether to enter the vehicle).

Verification is only permitted when the driver has marked the ride ARRIVED.
Subsequent calls overwrite the previous result (last-write-wins) so the rider
can correct a mistaken tap.

Public API:
    verify_pickup(db, ride_id, rider_id, driver_photo_confirmed, plate_confirmed)
        -> dict with keys: ride_id, driver_photo_confirmed, plate_confirmed,
                           verified_at, mismatch_flagged
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ride import Ride, RideStatus

logger = logging.getLogger(__name__)


async def verify_pickup(
    db: AsyncSession,
    ride_id: int,
    rider_id: int,
    driver_photo_confirmed: bool,
    plate_confirmed: bool,
) -> dict:
    """Record a rider's pickup verification result.

    Args:
        db: Async database session.
        ride_id: The ride being verified.
        rider_id: The authenticated rider submitting the verification.
        driver_photo_confirmed: Whether the driver's face matches their profile photo.
        plate_confirmed: Whether the vehicle's license plate matches the app.

    Returns:
        dict with verification outcome fields.

    Raises:
        ValueError: If the ride is not in ARRIVED status.
        PermissionError: If the caller is not the rider on this ride.
        LookupError: If the ride does not exist.
    """
    result = await db.execute(select(Ride).where(Ride.id == ride_id))
    ride = result.scalar_one_or_none()

    if ride is None:
        raise LookupError(f"Ride {ride_id} not found")

    if ride.rider_id != rider_id:
        raise PermissionError("Not authorized to verify this ride")

    if ride.status != RideStatus.ARRIVED:
        raise ValueError(
            f"Pickup verification is only available when the driver has arrived. "
            f"Current status: {ride.status.value}"
        )

    now = datetime.now(tz=timezone.utc)
    ride.pickup_verification_at = now
    ride.driver_photo_confirmed = driver_photo_confirmed
    ride.plate_confirmed = plate_confirmed

    mismatch_flagged = not driver_photo_confirmed or not plate_confirmed
    if mismatch_flagged:
        logger.warning(
            "Pickup verification mismatch on ride %d: photo_confirmed=%s plate_confirmed=%s",
            ride_id,
            driver_photo_confirmed,
            plate_confirmed,
        )

    return {
        "ride_id": ride_id,
        "driver_photo_confirmed": driver_photo_confirmed,
        "plate_confirmed": plate_confirmed,
        "verified_at": now,
        "mismatch_flagged": mismatch_flagged,
    }
