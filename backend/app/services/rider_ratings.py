"""Rider rating service — driver-submitted ratings for riders after completed trips.

Provides:
- submit_rider_rating: validates and persists a driver's rating of a rider
- get_rider_rating_summary: aggregate stats (avg, count, distribution, low-rated flag)
- get_rider_rating_for_ride: fetch the single rating for a specific ride

Low-rated flag logic
--------------------
A rider is flagged as ``low_rated`` when their 30-day average is below 3.0 and
they have received more than 5 ratings in that window. The flag is a soft
signal for admin visibility only — it is never exposed directly to the rider.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ride import Ride, RideStatus
from app.models.rider_rating import RiderRating
from app.schemas.rider_rating import RatingDistribution, RiderRatingSummary

logger = logging.getLogger(__name__)

# Thresholds for the low-rated soft flag.
LOW_RATED_THRESHOLD = 3.0
LOW_RATED_MIN_RATINGS = 5
LOW_RATED_WINDOW_DAYS = 30


class RiderRatingError(Exception):
    """Raised for expected business-rule violations during rating submission."""

    def __init__(self, message: str, status_code: int = 409) -> None:
        super().__init__(message)
        self.status_code = status_code


async def submit_rider_rating(
    db: AsyncSession,
    ride_id: int,
    driver_user_id: int,
    rating: int,
    comment: str | None = None,
) -> RiderRating:
    """Submit a driver's rating for the rider on a completed ride.

    Validates:
    - Ride exists and is completed.
    - The driver was assigned to this ride.
    - No rating has already been submitted for this ride by this driver.
    - Rating value is in the 1-5 range (Pydantic enforces this at the API
      boundary; the service re-validates to guard direct service calls).

    Args:
        db: Active async database session.
        ride_id: ID of the completed ride.
        driver_user_id: ID of the authenticated driver submitting the rating.
        rating: Integer 1-5 star value.
        comment: Optional free-text note from the driver.

    Returns:
        The newly created RiderRating record.

    Raises:
        RiderRatingError: On any business-rule violation.
    """
    if rating < 1 or rating > 5:
        raise RiderRatingError("Rating must be between 1 and 5", status_code=422)

    result = await db.execute(select(Ride).where(Ride.id == ride_id))
    ride = result.scalar_one_or_none()

    if not ride:
        raise RiderRatingError("Ride not found", status_code=404)

    if ride.driver_id != driver_user_id:
        raise RiderRatingError(
            "Only the driver for this ride can submit a rider rating",
            status_code=403,
        )

    if ride.status != RideStatus.COMPLETED:
        raise RiderRatingError(
            "Rider ratings can only be submitted for completed rides",
            status_code=409,
        )

    # Duplicate check — one rating per ride per driver
    existing_result = await db.execute(
        select(RiderRating).where(
            RiderRating.ride_id == ride_id,
            RiderRating.driver_id == driver_user_id,
        )
    )
    if existing_result.scalar_one_or_none():
        raise RiderRatingError(
            "A rating has already been submitted for this rider on this ride",
            status_code=409,
        )

    rider_rating = RiderRating(
        ride_id=ride_id,
        driver_id=driver_user_id,
        rider_id=ride.rider_id,
        rating=rating,
        comment=comment,
    )
    db.add(rider_rating)
    await db.commit()
    await db.refresh(rider_rating)

    logger.info(
        "Rider rating %d submitted for ride %d (driver %d, rider %d)",
        rating,
        ride_id,
        driver_user_id,
        ride.rider_id,
    )
    return rider_rating


async def get_rider_rating_summary(
    db: AsyncSession,
    rider_id: int,
    include_low_rated_flag: bool = False,
) -> RiderRatingSummary:
    """Compute an aggregate rating summary for a rider.

    Args:
        db: Active async database session.
        rider_id: User ID of the rider.
        include_low_rated_flag: When True, computes and includes the low_rated
            soft flag (for admin callers). Requires an additional query.

    Returns:
        RiderRatingSummary with avg, count, distribution, and optionally the
        low_rated flag.
    """
    dist_query = select(
        func.count(case((RiderRating.rating == 1, 1))).label("one"),
        func.count(case((RiderRating.rating == 2, 1))).label("two"),
        func.count(case((RiderRating.rating == 3, 1))).label("three"),
        func.count(case((RiderRating.rating == 4, 1))).label("four"),
        func.count(case((RiderRating.rating == 5, 1))).label("five"),
        func.count(RiderRating.rating).label("total"),
        func.avg(RiderRating.rating).label("avg"),
    ).where(RiderRating.rider_id == rider_id)

    result = await db.execute(dist_query)
    row = result.one()

    total = row.total or 0
    avg_rating = round(float(row.avg), 2) if row.avg is not None else 5.0

    distribution = RatingDistribution(
        one_star=row.one or 0,
        two_star=row.two or 0,
        three_star=row.three or 0,
        four_star=row.four or 0,
        five_star=row.five or 0,
    )

    low_rated: bool | None = None
    if include_low_rated_flag:
        cutoff = datetime.now(timezone.utc) - timedelta(days=LOW_RATED_WINDOW_DAYS)
        recent_result = await db.execute(
            select(
                func.avg(RiderRating.rating).label("avg"),
                func.count(RiderRating.rating).label("count"),
            ).where(
                RiderRating.rider_id == rider_id,
                RiderRating.created_at >= cutoff,
            )
        )
        recent_row = recent_result.one()
        recent_count = recent_row.count or 0
        recent_avg = float(recent_row.avg) if recent_row.avg is not None else None

        low_rated = (
            recent_avg is not None
            and recent_count > LOW_RATED_MIN_RATINGS
            and recent_avg < LOW_RATED_THRESHOLD
        )

    return RiderRatingSummary(
        avg_rating=avg_rating,
        total_ratings=total,
        rating_distribution=distribution,
        low_rated=low_rated,
    )


async def get_rider_rating_for_ride(
    db: AsyncSession,
    ride_id: int,
) -> RiderRating | None:
    """Return the driver's rating of the rider for a specific ride, or None.

    Args:
        db: Active async database session.
        ride_id: ID of the ride.

    Returns:
        RiderRating or None if no rating has been submitted.
    """
    result = await db.execute(
        select(RiderRating).where(RiderRating.ride_id == ride_id)
    )
    return result.scalar_one_or_none()


async def list_low_rated_riders(
    db: AsyncSession,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """Return a list of rider IDs flagged as low-rated with their recent averages.

    A rider is low-rated when their 30-day average is below 3.0 and they have
    received more than 5 ratings in that window.

    Args:
        db: Active async database session.
        limit: Maximum number of results.
        offset: Pagination offset.

    Returns:
        List of dicts with rider_id, recent_avg, and recent_count.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=LOW_RATED_WINDOW_DAYS)

    query = (
        select(
            RiderRating.rider_id,
            func.avg(RiderRating.rating).label("recent_avg"),
            func.count(RiderRating.rating).label("recent_count"),
        )
        .where(RiderRating.created_at >= cutoff)
        .group_by(RiderRating.rider_id)
        .having(
            func.count(RiderRating.rating) > LOW_RATED_MIN_RATINGS,
            func.avg(RiderRating.rating) < LOW_RATED_THRESHOLD,
        )
        .order_by(func.avg(RiderRating.rating).asc())
        .limit(limit)
        .offset(offset)
    )

    result = await db.execute(query)
    rows = result.all()
    return [
        {
            "rider_id": row.rider_id,
            "recent_avg": round(float(row.recent_avg), 2),
            "recent_count": row.recent_count,
        }
        for row in rows
    ]
