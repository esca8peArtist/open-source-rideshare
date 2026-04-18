"""Driver rating history service.

Provides aggregate stats and paginated rating history for the authenticated
driver.  All ratings are sourced from the RideFeedback table (role="rider"),
which is the canonical store for rider-submitted ratings of drivers.  The
Ride.driver_rating column is a denormalized copy used for fast aggregation;
we query it here for aggregate stats and join to RideFeedback for comments.

Privacy guarantee: rider identity is never included in any returned data.
"""

from __future__ import annotations

import math

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.feedback import RideFeedback
from app.models.ride import Ride, RideStatus
from app.schemas.driver_ratings import (
    DriverRatingItem,
    DriverRatingsResponse,
    RatingBreakdown,
)

# Number of most-recent ratings used for the trend calculation.
TREND_WINDOW = 10


async def get_driver_ratings_history(
    db: AsyncSession,
    driver_user_id: int,
    page: int,
    page_size: int,
) -> DriverRatingsResponse:
    """Return paginated rating history and aggregate stats for a driver.

    Aggregates (average, breakdown, trend) are derived from Ride.driver_rating
    for efficiency.  The paginated list is sourced from RideFeedback joined to
    Ride so that comments are included and results are correctly scoped to the
    requesting driver.

    Args:
        db: Active async database session.
        driver_user_id: The authenticated driver's user ID.
        page: 1-based page number.
        page_size: Number of items per page (caller must enforce max).

    Returns:
        DriverRatingsResponse with aggregate stats and paginated list.
    """
    # ------------------------------------------------------------------
    # Aggregate stats — query Ride.driver_rating for the lifetime summary
    # ------------------------------------------------------------------
    agg_query = select(
        func.count(Ride.driver_rating).label("total"),
        func.avg(Ride.driver_rating).label("avg"),
        func.count(case((Ride.driver_rating == 1, 1))).label("one"),
        func.count(case((Ride.driver_rating == 2, 1))).label("two"),
        func.count(case((Ride.driver_rating == 3, 1))).label("three"),
        func.count(case((Ride.driver_rating == 4, 1))).label("four"),
        func.count(case((Ride.driver_rating == 5, 1))).label("five"),
    ).where(
        Ride.driver_id == driver_user_id,
        Ride.status == RideStatus.COMPLETED,
        Ride.driver_rating.isnot(None),
    )

    agg_result = await db.execute(agg_query)
    agg_row = agg_result.one()

    total_ratings: int = agg_row.total or 0
    average_rating: float | None = (
        round(float(agg_row.avg), 2) if agg_row.avg is not None else None
    )
    breakdown = RatingBreakdown.model_validate(
        {
            "1": agg_row.one or 0,
            "2": agg_row.two or 0,
            "3": agg_row.three or 0,
            "4": agg_row.four or 0,
            "5": agg_row.five or 0,
        }
    )

    # ------------------------------------------------------------------
    # Recent trend — average of last TREND_WINDOW rated completed rides
    # ------------------------------------------------------------------
    recent_trend: float | None = None
    if total_ratings > 0:
        trend_query = (
            select(Ride.driver_rating)
            .where(
                Ride.driver_id == driver_user_id,
                Ride.status == RideStatus.COMPLETED,
                Ride.driver_rating.isnot(None),
            )
            .order_by(Ride.completed_at.desc())
            .limit(TREND_WINDOW)
        )
        trend_result = await db.execute(trend_query)
        recent_values = [row[0] for row in trend_result.all()]
        if recent_values:
            recent_trend = round(sum(recent_values) / len(recent_values), 2)

    # ------------------------------------------------------------------
    # Paginated list — join RideFeedback (role="rider") to get comments
    # ------------------------------------------------------------------
    # Base filter: feedback submitted by riders about this driver's rides
    list_base = (
        select(RideFeedback)
        .join(Ride, Ride.id == RideFeedback.ride_id)
        .where(
            Ride.driver_id == driver_user_id,
            Ride.status == RideStatus.COMPLETED,
            RideFeedback.role == "rider",
        )
    )

    count_query = select(func.count()).select_from(list_base.subquery())
    count_result = await db.execute(count_query)
    # Use the aggregate total from the Ride query (consistent source of truth).
    # Fall back to feedback count if the two diverge (e.g. during migration).
    feedback_total: int = count_result.scalar() or 0
    # Use whichever total is available; they should match in a consistent DB.
    canonical_total = total_ratings if total_ratings >= feedback_total else feedback_total

    offset = (page - 1) * page_size
    list_query = (
        list_base.order_by(RideFeedback.created_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    list_result = await db.execute(list_query)
    feedback_rows: list[RideFeedback] = list(list_result.scalars().all())

    rating_items = [
        DriverRatingItem(
            ride_id=fb.ride_id,
            rating=fb.rating,
            comment=fb.comment,
            rated_at=fb.created_at,
        )
        for fb in feedback_rows
    ]

    total_pages = max(1, math.ceil(canonical_total / page_size))

    return DriverRatingsResponse(
        average_rating=average_rating,
        total_ratings=canonical_total,
        rating_breakdown=breakdown,
        recent_trend=recent_trend,
        ratings=rating_items,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )
