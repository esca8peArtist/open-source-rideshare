"""Driver and rider rating aggregation service.

Provides detailed rating analytics beyond a simple average:
- Rating distribution (1-5 star breakdown)
- Recent rating trend (last N rides vs lifetime)
- Rating summary for display in driver/rider profiles
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.driver import DriverProfile
from app.models.ride import Ride, RideStatus


@dataclass(frozen=True)
class RatingDistribution:
    one_star: int = 0
    two_star: int = 0
    three_star: int = 0
    four_star: int = 0
    five_star: int = 0


@dataclass(frozen=True)
class RatingsSummary:
    average: float
    total_ratings: int
    distribution: RatingDistribution
    recent_average: float | None  # avg of last N rides, None if < 5 rated rides
    recent_count: int


async def get_driver_ratings(
    driver_user_id: int,
    db: AsyncSession,
    recent_window: int = 20,
) -> RatingsSummary:
    """Compute a full rating summary for a driver.

    Queries all completed rides where the driver received a rating,
    computes distribution and recent trend.
    """
    # Distribution query — count ratings by star value
    dist_query = select(
        func.count(case((Ride.driver_rating == 1, 1))).label("one"),
        func.count(case((Ride.driver_rating == 2, 1))).label("two"),
        func.count(case((Ride.driver_rating == 3, 1))).label("three"),
        func.count(case((Ride.driver_rating == 4, 1))).label("four"),
        func.count(case((Ride.driver_rating == 5, 1))).label("five"),
        func.count(Ride.driver_rating).label("total"),
        func.avg(Ride.driver_rating).label("avg"),
    ).where(
        Ride.driver_id == driver_user_id,
        Ride.status == RideStatus.COMPLETED,
        Ride.driver_rating.isnot(None),
    )

    result = await db.execute(dist_query)
    row = result.one()

    total = row.total or 0
    average = round(float(row.avg), 2) if row.avg is not None else 5.0

    distribution = RatingDistribution(
        one_star=row.one or 0,
        two_star=row.two or 0,
        three_star=row.three or 0,
        four_star=row.four or 0,
        five_star=row.five or 0,
    )

    # Recent ratings — last N completed rides with a rating
    recent_query = (
        select(func.avg(Ride.driver_rating), func.count(Ride.driver_rating))
        .where(
            Ride.driver_id == driver_user_id,
            Ride.status == RideStatus.COMPLETED,
            Ride.driver_rating.isnot(None),
        )
        .order_by(Ride.completed_at.desc())
        .limit(recent_window)
    )

    recent_result = await db.execute(recent_query)
    recent_row = recent_result.one()
    recent_count = recent_row[1] or 0
    recent_average = round(float(recent_row[0]), 2) if recent_row[0] is not None and recent_count >= 5 else None

    return RatingsSummary(
        average=average,
        total_ratings=total,
        distribution=distribution,
        recent_average=recent_average,
        recent_count=recent_count,
    )


async def get_rider_ratings(
    rider_user_id: int,
    db: AsyncSession,
) -> RatingsSummary:
    """Compute a rating summary for a rider."""
    dist_query = select(
        func.count(case((Ride.rider_rating == 1, 1))).label("one"),
        func.count(case((Ride.rider_rating == 2, 1))).label("two"),
        func.count(case((Ride.rider_rating == 3, 1))).label("three"),
        func.count(case((Ride.rider_rating == 4, 1))).label("four"),
        func.count(case((Ride.rider_rating == 5, 1))).label("five"),
        func.count(Ride.rider_rating).label("total"),
        func.avg(Ride.rider_rating).label("avg"),
    ).where(
        Ride.rider_id == rider_user_id,
        Ride.status == RideStatus.COMPLETED,
        Ride.rider_rating.isnot(None),
    )

    result = await db.execute(dist_query)
    row = result.one()

    total = row.total or 0
    average = round(float(row.avg), 2) if row.avg is not None else 5.0

    distribution = RatingDistribution(
        one_star=row.one or 0,
        two_star=row.two or 0,
        three_star=row.three or 0,
        four_star=row.four or 0,
        five_star=row.five or 0,
    )

    return RatingsSummary(
        average=average,
        total_ratings=total,
        distribution=distribution,
        recent_average=None,
        recent_count=0,
    )


async def update_driver_rating_avg(driver_user_id: int, db: AsyncSession) -> float | None:
    """Recalculate and persist the driver's rating_avg on their profile.

    Returns the new average, or None if no profile found.
    """
    avg_result = await db.execute(
        select(func.avg(Ride.driver_rating)).where(
            Ride.driver_id == driver_user_id,
            Ride.driver_rating.isnot(None),
        )
    )
    new_avg = avg_result.scalar()

    if new_avg is None:
        return None

    profile_result = await db.execute(
        select(DriverProfile).where(DriverProfile.user_id == driver_user_id)
    )
    profile = profile_result.scalar_one_or_none()
    if profile:
        profile.rating_avg = round(float(new_avg), 2)
        return profile.rating_avg

    return None
