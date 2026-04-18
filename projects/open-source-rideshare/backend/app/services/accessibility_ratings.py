"""Accessibility rating service.

Business rules:
- Only riders may submit; the ride must be COMPLETED and belong to the caller.
- One rating per ride per rider (UniqueConstraint on the table; service raises
  ValueError on duplicate before hitting the DB constraint).
- Admins may view all ratings; riders may only view their own.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.accessibility_rating import AccommodationType, AccessibilityRating
from app.models.ride import Ride, RideStatus

logger = logging.getLogger(__name__)


async def submit_accessibility_rating(
    db: AsyncSession,
    ride_id: int,
    rider_id: int,
    rating: int,
    accommodation_type: AccommodationType | None = None,
    comment: str | None = None,
) -> AccessibilityRating:
    """Submit a rider's accessibility accommodation rating for a completed ride.

    Raises:
        LookupError: ride not found or not owned by this rider.
        ValueError: ride not completed, or rating already submitted.
    """
    result = await db.execute(
        select(Ride).where(Ride.id == ride_id, Ride.rider_id == rider_id)
    )
    ride = result.scalar_one_or_none()
    if ride is None:
        raise LookupError("Ride not found.")
    if ride.status != RideStatus.COMPLETED:
        raise ValueError("Accessibility ratings may only be submitted for completed rides.")

    existing = await db.execute(
        select(AccessibilityRating).where(
            AccessibilityRating.ride_id == ride_id,
            AccessibilityRating.rider_id == rider_id,
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise ValueError("An accessibility rating has already been submitted for this ride.")

    record = AccessibilityRating(
        ride_id=ride_id,
        rider_id=rider_id,
        rating=rating,
        accommodation_type=accommodation_type,
        comment=comment,
    )
    db.add(record)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise ValueError("An accessibility rating has already been submitted for this ride.")

    return record


async def get_accessibility_rating(
    db: AsyncSession,
    ride_id: int,
    rider_id: int,
) -> AccessibilityRating | None:
    """Return the accessibility rating for a ride+rider pair, or None."""
    result = await db.execute(
        select(AccessibilityRating).where(
            AccessibilityRating.ride_id == ride_id,
            AccessibilityRating.rider_id == rider_id,
        )
    )
    return result.scalar_one_or_none()


async def list_rider_accessibility_ratings(
    db: AsyncSession,
    rider_id: int,
    limit: int = 50,
    offset: int = 0,
) -> tuple[int, list[AccessibilityRating]]:
    """Return (total, page) of accessibility ratings submitted by a rider."""
    count_result = await db.execute(
        select(func.count()).where(AccessibilityRating.rider_id == rider_id)
    )
    total = count_result.scalar_one()

    items_result = await db.execute(
        select(AccessibilityRating)
        .where(AccessibilityRating.rider_id == rider_id)
        .order_by(AccessibilityRating.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return total, list(items_result.scalars())


async def get_admin_accommodation_summary(
    db: AsyncSession,
) -> dict[str, Any]:
    """Return aggregate accommodation quality stats across all ratings.

    Computes overall avg/count and per-accommodation-type breakdown.
    """
    overall_result = await db.execute(
        select(
            func.avg(AccessibilityRating.rating).label("avg"),
            func.count(AccessibilityRating.id).label("cnt"),
        )
    )
    row = overall_result.one()
    overall_avg = float(row.avg) if row.avg is not None else 0.0
    total = int(row.cnt)

    breakdown_result = await db.execute(
        select(
            AccessibilityRating.accommodation_type,
            func.avg(AccessibilityRating.rating).label("avg"),
            func.count(AccessibilityRating.id).label("cnt"),
        ).group_by(AccessibilityRating.accommodation_type)
    )
    by_type = [
        {
            "accommodation_type": r.accommodation_type,
            "avg_rating": round(float(r.avg), 2),
            "total_ratings": int(r.cnt),
        }
        for r in breakdown_result
    ]

    return {
        "overall_avg": round(overall_avg, 2),
        "total_ratings": total,
        "by_accommodation_type": by_type,
    }
