"""Service layer for GET /riders/{rider_id}/public-profile."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ride import Ride, RideStatus
from app.models.rider_rating import RiderRating
from app.models.user import User, UserRole
from app.schemas.rider_public_profile import RiderPublicProfile


async def get_rider_public_profile(
    db: AsyncSession,
    rider_id: int,
) -> RiderPublicProfile | None:
    """Return a rider's public profile by User.id.

    Returns None when:
    - No user exists with that id
    - The user exists but is not a rider (wrong role)
    - The user account is inactive

    rating_avg is null when the rider has received no driver ratings yet.
    total_completed_rides counts rides with status COMPLETED.
    """
    user_stmt = select(User).where(
        User.id == rider_id,
        User.role == UserRole.RIDER,
        User.is_active.is_(True),
    )
    user_result = await db.execute(user_stmt)
    user: User | None = user_result.scalar_one_or_none()

    if user is None:
        return None

    # Average rating from drivers
    rating_stmt = select(func.avg(RiderRating.rating)).where(
        RiderRating.rider_id == rider_id
    )
    rating_result = await db.execute(rating_stmt)
    avg_raw = rating_result.scalar()
    rating_avg = round(float(avg_raw), 2) if avg_raw is not None else None

    # Completed rides count
    count_stmt = select(func.count(Ride.id)).where(
        Ride.rider_id == rider_id,
        Ride.status == RideStatus.COMPLETED,
    )
    count_result = await db.execute(count_stmt)
    total_completed = count_result.scalar() or 0

    return RiderPublicProfile(
        rider_id=user.id,
        rating_avg=rating_avg,
        total_completed_rides=total_completed,
        member_since=user.created_at,
    )
