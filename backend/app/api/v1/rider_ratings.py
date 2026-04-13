"""Rider Ratings API — driver-submitted ratings for riders after completed trips.

POST /rider-ratings/                        — driver submits a rating for a rider
GET  /riders/{rider_id}/rating              — get a rider's public rating summary
GET  /rides/{ride_id}/rider-rating          — get the rating a driver gave for a ride
GET  /admin/rider-ratings/low-rated         — list riders flagged as low-rated (admin only)
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_admin, require_driver
from app.db.database import get_db
from app.models.ride import Ride
from app.models.user import User, UserRole
from app.schemas.rider_rating import RiderRatingCreate, RiderRatingResponse, RiderRatingSummary
from app.services.rider_ratings import (
    RiderRatingError,
    get_rider_rating_for_ride,
    get_rider_rating_summary,
    list_low_rated_riders,
    submit_rider_rating,
)
from sqlalchemy import select

logger = logging.getLogger(__name__)
router = APIRouter(tags=["rider-ratings"])


@router.post("/rider-ratings/", response_model=RiderRatingResponse, status_code=201)
async def create_rider_rating(
    req: RiderRatingCreate,
    user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    """Submit a rating for the rider on a completed ride.

    Only the driver who was assigned to the ride may submit a rating.
    Each ride permits at most one rating from the driver.
    """
    try:
        rating = await submit_rider_rating(
            db,
            ride_id=req.ride_id,
            driver_user_id=user.id,
            rating=req.rating,
            comment=req.comment,
        )
    except RiderRatingError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))

    return rating


@router.get("/riders/{rider_id}/rating", response_model=RiderRatingSummary)
async def get_rider_rating(
    rider_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a rider's public rating summary.

    Accessible by drivers (to inform ride acceptance decisions) and admins.
    The low_rated flag is only included for admin callers.
    """
    if user.role not in (UserRole.DRIVER, UserRole.ADMIN):
        raise HTTPException(status_code=403, detail="Driver or admin access required")

    include_flag = user.role == UserRole.ADMIN
    summary = await get_rider_rating_summary(db, rider_id=rider_id, include_low_rated_flag=include_flag)
    return summary


@router.get("/rides/{ride_id}/rider-rating", response_model=RiderRatingResponse)
async def get_ride_rider_rating(
    ride_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the driver's rating of the rider for a specific completed ride.

    Accessible by the driver who did the ride or an admin.
    """
    ride_result = await db.execute(select(Ride).where(Ride.id == ride_id))
    ride = ride_result.scalar_one_or_none()

    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")

    is_admin = user.role == UserRole.ADMIN
    is_driver = ride.driver_id == user.id

    if not (is_admin or is_driver):
        raise HTTPException(status_code=403, detail="Not authorised to view this rating")

    rating = await get_rider_rating_for_ride(db, ride_id=ride_id)
    if not rating:
        raise HTTPException(status_code=404, detail="No rider rating found for this ride")

    return rating


@router.get("/admin/rider-ratings/low-rated")
async def admin_list_low_rated_riders(
    limit: int = Query(50, ge=1, le=200, description="Page size"),
    offset: int = Query(0, ge=0, description="Page offset"),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """List riders flagged as low-rated (admin only).

    A rider is flagged when their 30-day average is below 3.0 and they have
    more than 5 ratings in that window. Results are sorted by average ascending
    (worst-rated first).

    Returns a list of objects with rider_id, recent_avg, and recent_count.
    """
    results = await list_low_rated_riders(db, limit=limit, offset=offset)
    return results
