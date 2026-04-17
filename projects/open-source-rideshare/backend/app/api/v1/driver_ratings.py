"""Driver Ratings API — rider-submitted ratings for drivers after completed trips.

GET /drivers/{driver_id}/rating          — driver's public aggregate rating summary
GET /rides/{ride_id}/driver-rating       — the rating a rider gave for a specific ride
GET /admin/driver-ratings/low-rated      — list drivers flagged as low-rated (admin only)

Riders rate drivers via POST /rides/{ride_id}/feedback (ride_feedback.py).
These endpoints surface the read-side of that data.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_admin
from app.db.database import get_db
from app.models.ride import Ride, RideStatus
from app.models.user import User, UserRole
from app.schemas.driver_ratings import (
    DriverRatingDistribution,
    DriverRatingSummary,
    RideDriverRatingResponse,
)
from app.services.ratings import get_driver_ratings, list_low_rated_drivers
from sqlalchemy import select

logger = logging.getLogger(__name__)
router = APIRouter(tags=["driver-ratings"])


@router.get("/drivers/{driver_id}/rating", response_model=DriverRatingSummary)
async def get_driver_rating_summary(
    driver_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a driver's public aggregate rating summary.

    Accessible by any authenticated user. The low_rated flag is only
    included for admin callers — it is never exposed to riders or drivers.

    Returns a 5.0 average with zero ratings when the driver has no completed
    rated rides yet.
    """
    summary = await get_driver_ratings(driver_user_id=driver_id, db=db)

    include_low_rated = user.role == UserRole.ADMIN
    low_rated: bool | None = None

    if include_low_rated:
        # Reuse list_low_rated_drivers with a large window to check just this driver.
        # Simpler than a separate per-driver query; result set is tiny.
        low_rated_list = await list_low_rated_drivers(db, limit=1000, offset=0)
        low_rated = any(row["driver_id"] == driver_id for row in low_rated_list)

    return DriverRatingSummary(
        driver_id=driver_id,
        avg_rating=summary.average,
        total_ratings=summary.total_ratings,
        rating_distribution=DriverRatingDistribution(
            one_star=summary.distribution.one_star,
            two_star=summary.distribution.two_star,
            three_star=summary.distribution.three_star,
            four_star=summary.distribution.four_star,
            five_star=summary.distribution.five_star,
        ),
        recent_avg=summary.recent_average,
        recent_count=summary.recent_count,
        low_rated=low_rated,
    )


@router.get("/rides/{ride_id}/driver-rating", response_model=RideDriverRatingResponse)
async def get_ride_driver_rating(
    ride_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the rider's rating of the driver for a specific completed ride.

    Accessible by the rider who submitted the rating, the driver on the ride,
    or an admin. Returns 404 if the ride has no driver rating yet.
    """
    result = await db.execute(select(Ride).where(Ride.id == ride_id))
    ride = result.scalar_one_or_none()

    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")

    is_admin = user.role == UserRole.ADMIN
    is_rider = ride.rider_id == user.id
    is_driver = ride.driver_id == user.id

    if not (is_admin or is_rider or is_driver):
        raise HTTPException(status_code=403, detail="Not authorised to view this rating")

    if ride.driver_rating is None:
        raise HTTPException(status_code=404, detail="No driver rating found for this ride")

    return RideDriverRatingResponse(
        ride_id=ride.id,
        driver_id=ride.driver_id,
        rider_id=ride.rider_id,
        rating=ride.driver_rating,
        rated_at=ride.completed_at,
    )


@router.get("/admin/driver-ratings/low-rated")
async def admin_list_low_rated_drivers(
    limit: int = Query(50, ge=1, le=200, description="Page size"),
    offset: int = Query(0, ge=0, description="Page offset"),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """List drivers flagged as low-rated (admin only).

    A driver is flagged when their 30-day average is below 3.0 and they have
    more than 5 ratings in that window. Results are sorted by average ascending
    (worst-rated first).

    Returns a list of objects with driver_id, recent_avg, and recent_count.
    """
    results = await list_low_rated_drivers(db, limit=limit, offset=offset)
    return results
