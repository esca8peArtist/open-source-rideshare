"""Ride feedback service.

Handles submission and retrieval of rider/driver feedback for completed rides.
Feedback includes a 1-5 rating, optional comment, and optional issue categories.
Integrates with the existing rating system to keep driver_rating/rider_rating
on the Ride model in sync.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.feedback import RideFeedback
from app.models.ride import Ride, RideStatus


async def submit_feedback(
    ride_id: int,
    user_id: int,
    role: str,
    rating: int,
    comment: str | None,
    categories: list[str] | None,
    tip_amount: float,
    db: AsyncSession,
) -> RideFeedback:
    """Submit feedback for a completed ride.

    - Validates ride exists and is completed
    - Prevents duplicate feedback from the same user on the same ride
    - Syncs numeric rating to the Ride model (driver_rating / rider_rating)
    - Stores tip if rider is submitting
    """
    result = await db.execute(select(Ride).where(Ride.id == ride_id))
    ride = result.scalar_one_or_none()

    if not ride:
        raise ValueError("Ride not found")
    if ride.status != RideStatus.COMPLETED:
        raise ValueError("Can only leave feedback on completed rides")

    # Check authorization
    if role == "rider" and ride.rider_id != user_id:
        raise PermissionError("Not authorized")
    if role == "driver" and ride.driver_id != user_id:
        raise PermissionError("Not authorized")

    # Check for duplicate feedback
    existing = await db.execute(
        select(RideFeedback).where(
            RideFeedback.ride_id == ride_id,
            RideFeedback.user_id == user_id,
        )
    )
    if existing.scalar_one_or_none():
        raise ValueError("Feedback already submitted for this ride")

    # Store categories as comma-separated string
    categories_str = ",".join(categories) if categories else None

    feedback = RideFeedback(
        ride_id=ride_id,
        user_id=user_id,
        role=role,
        rating=rating,
        comment=comment,
        categories=categories_str,
    )
    db.add(feedback)

    # Sync rating to ride model and handle tip
    if role == "rider":
        ride.driver_rating = rating
        ride.tip_amount = tip_amount
        # Update driver's aggregate rating
        if ride.driver_id:
            from app.services.ratings import update_driver_rating_avg
            await update_driver_rating_avg(ride.driver_id, db)
    elif role == "driver":
        ride.rider_rating = rating

    await db.commit()
    await db.refresh(feedback)
    return feedback


async def get_ride_feedback(
    ride_id: int,
    db: AsyncSession,
) -> list[RideFeedback]:
    """Get all feedback for a ride."""
    result = await db.execute(
        select(RideFeedback).where(RideFeedback.ride_id == ride_id)
    )
    return list(result.scalars().all())


async def get_user_feedback(
    user_id: int,
    role: str | None,
    db: AsyncSession,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[RideFeedback], int]:
    """Get feedback submitted by or about a user."""
    query = select(RideFeedback).where(RideFeedback.user_id == user_id)
    if role:
        query = query.where(RideFeedback.role == role)

    count_query = select(func.count()).select_from(query.subquery())
    count_result = await db.execute(count_query)
    total = count_result.scalar() or 0

    query = query.order_by(RideFeedback.created_at.desc()).offset(offset).limit(limit)
    result = await db.execute(query)
    return list(result.scalars().all()), total
