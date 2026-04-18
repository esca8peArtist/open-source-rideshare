"""Service layer for rider-submitted driver ratings.

Riders rate their driver after a completed ride. Ratings are stored in
RideFeedback (role="rider") — the same table the driver_ratings history
endpoint reads from. Ride.driver_rating is updated as a denormalized
fast-access copy.

One rating per rider per ride is enforced by a service-layer duplicate check.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.feedback import RideFeedback
from app.models.ride import Ride, RideStatus

logger = logging.getLogger(__name__)


class DriverRatingError(Exception):
    def __init__(self, message: str, status_code: int = 409) -> None:
        super().__init__(message)
        self.status_code = status_code


async def submit_driver_rating(
    db: AsyncSession,
    ride_id: int,
    rider_user_id: int,
    rating: int,
    comment: str | None = None,
) -> RideFeedback:
    """Submit a rider's rating for the driver on a completed ride.

    Validates:
    - Ride exists and is COMPLETED.
    - The rider was the passenger on this ride.
    - No rating already submitted by this rider for this ride.

    Updates Ride.driver_rating to keep the denormalized aggregate current.
    """
    if rating < 1 or rating > 5:
        raise DriverRatingError("Rating must be between 1 and 5", status_code=422)

    ride_result = await db.execute(select(Ride).where(Ride.id == ride_id))
    ride = ride_result.scalar_one_or_none()

    if not ride:
        raise DriverRatingError("Ride not found", status_code=404)

    if ride.rider_id != rider_user_id:
        raise DriverRatingError("You were not the rider on this ride", status_code=403)

    if ride.status != RideStatus.COMPLETED:
        raise DriverRatingError(
            "Driver ratings can only be submitted for completed rides",
            status_code=409,
        )

    # One rating per rider per ride
    existing_result = await db.execute(
        select(RideFeedback).where(
            RideFeedback.ride_id == ride_id,
            RideFeedback.user_id == rider_user_id,
            RideFeedback.role == "rider",
        )
    )
    if existing_result.scalar_one_or_none():
        raise DriverRatingError(
            "You have already rated the driver for this ride",
            status_code=409,
        )

    feedback = RideFeedback(
        ride_id=ride_id,
        user_id=rider_user_id,
        role="rider",
        rating=rating,
        comment=comment,
    )
    db.add(feedback)

    # Update denormalized column on the ride so driver_ratings history stays consistent
    ride.driver_rating = rating

    await db.commit()
    await db.refresh(feedback)

    logger.info(
        "Driver rating %d submitted for ride %d by rider %d",
        rating,
        ride_id,
        rider_user_id,
    )
    return feedback


async def get_driver_rating_for_ride(
    db: AsyncSession,
    ride_id: int,
    rider_user_id: int,
) -> RideFeedback | None:
    """Return the rider's submitted rating for a specific ride, or None.

    Only returns the rating submitted by the given rider (ownership check).
    """
    result = await db.execute(
        select(RideFeedback).where(
            RideFeedback.ride_id == ride_id,
            RideFeedback.user_id == rider_user_id,
            RideFeedback.role == "rider",
        )
    )
    return result.scalar_one_or_none()
