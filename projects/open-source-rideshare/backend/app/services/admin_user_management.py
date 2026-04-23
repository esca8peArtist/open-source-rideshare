"""Admin user management service.

Provides the business logic for:
- Listing users with filters and pagination
- Fetching a detailed user profile with ride stats
- Suspending a user account
- Activating (reactivating) a suspended user account

Notifications are fire-and-forget: failures are logged but never raised.
The service relies on the existing account_verification notification type,
which is the closest generic template for account status changes.
"""

from __future__ import annotations

import logging
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ride import Ride, RideStatus
from app.models.user import User, UserRole, UserStatus
from app.schemas.admin_user_management import (
    ActivateUserRequest,
    SuspendUserRequest,
    UserDetailResponse,
    UserListResponse,
    UserRideStats,
    UserStatusChangeResponse,
    UserSummary,
)

logger = logging.getLogger(__name__)

RoleFilter = Literal["rider", "driver", "all"]
StatusFilter = Literal["active", "suspended", "all"]


async def list_users(
    db: AsyncSession,
    role: RoleFilter = "all",
    status: StatusFilter = "all",
    search: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> UserListResponse:
    """Return a paginated list of all platform users with optional filters.

    Args:
        db: Async SQLAlchemy session.
        role: Filter by role — 'rider', 'driver', or 'all'.
        status: Filter by account status — 'active', 'suspended', or 'all'.
        search: Case-insensitive substring match on email or name.
        page: 1-based page number.
        page_size: Number of rows per page (capped at 100 to protect the DB).

    Returns:
        UserListResponse with paginated user rows and total count.
    """
    page_size = min(page_size, 100)

    # Build base query — exclude ADMIN users from the management list
    stmt = select(User).where(User.role != UserRole.ADMIN)

    if role != "all":
        stmt = stmt.where(User.role == UserRole(role))

    if status != "all":
        stmt = stmt.where(User.status == UserStatus(status))

    if search:
        pattern = f"%{search}%"
        stmt = stmt.where(
            User.name.ilike(pattern) | User.email.ilike(pattern)
        )

    # Count before pagination
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total_count: int = (await db.execute(count_stmt)).scalar_one()

    # Apply ordering and pagination
    stmt = stmt.order_by(User.created_at.desc())
    offset = (page - 1) * page_size
    stmt = stmt.offset(offset).limit(page_size)

    result = await db.execute(stmt)
    users = list(result.scalars().all())

    if not users:
        return UserListResponse(users=[], total_count=total_count, page=page, page_size=page_size)

    # Fetch ride counts for returned users in one query
    user_ids = [u.id for u in users]
    ride_count_result = await db.execute(
        select(Ride.rider_id, func.count(Ride.id))
        .where(Ride.rider_id.in_(user_ids))
        .group_by(Ride.rider_id)
    )
    ride_counts: dict[int, int] = {row[0]: row[1] for row in ride_count_result.all()}

    # Also count rides for drivers (driver_id)
    driver_ride_count_result = await db.execute(
        select(Ride.driver_id, func.count(Ride.id))
        .where(Ride.driver_id.in_(user_ids))
        .group_by(Ride.driver_id)
    )
    for row in driver_ride_count_result.all():
        if row[0] is not None:
            ride_counts[row[0]] = ride_counts.get(row[0], 0) + row[1]

    rows = [
        UserSummary(
            id=u.id,
            name=u.name,
            email=u.email,
            phone=u.phone,
            role=u.role.value,
            status=u.status.value,
            is_active=u.is_active,
            created_at=u.created_at,
            ride_count=ride_counts.get(u.id, 0),
        )
        for u in users
    ]

    return UserListResponse(users=rows, total_count=total_count, page=page, page_size=page_size)


async def get_user_detail(db: AsyncSession, user_id: int) -> UserDetailResponse:
    """Return a detailed user profile including ride statistics.

    Args:
        db: Async SQLAlchemy session.
        user_id: Primary key of the user to inspect.

    Raises:
        ValueError: If no user with user_id exists.

    Returns:
        UserDetailResponse with all profile fields and ride stats.
    """
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise ValueError(f"User {user_id} not found")

    # Ride stats — combine rider and driver perspectives
    # Total rides as rider
    rider_total_result = await db.execute(
        select(func.count(Ride.id)).where(Ride.rider_id == user_id)
    )
    rider_total: int = rider_total_result.scalar_one() or 0

    # Completed rides as rider
    rider_completed_result = await db.execute(
        select(func.count(Ride.id)).where(
            Ride.rider_id == user_id, Ride.status == RideStatus.COMPLETED
        )
    )
    rider_completed: int = rider_completed_result.scalar_one() or 0

    # Cancelled rides as rider
    rider_cancelled_result = await db.execute(
        select(func.count(Ride.id)).where(
            Ride.rider_id == user_id, Ride.status == RideStatus.CANCELLED
        )
    )
    rider_cancelled: int = rider_cancelled_result.scalar_one() or 0

    # Driver-side counts (only meaningful if the user is a driver)
    driver_total_result = await db.execute(
        select(func.count(Ride.id)).where(Ride.driver_id == user_id)
    )
    driver_total: int = driver_total_result.scalar_one() or 0

    driver_completed_result = await db.execute(
        select(func.count(Ride.id)).where(
            Ride.driver_id == user_id, Ride.status == RideStatus.COMPLETED
        )
    )
    driver_completed: int = driver_completed_result.scalar_one() or 0

    driver_cancelled_result = await db.execute(
        select(func.count(Ride.id)).where(
            Ride.driver_id == user_id, Ride.status == RideStatus.CANCELLED
        )
    )
    driver_cancelled: int = driver_cancelled_result.scalar_one() or 0

    total_rides = rider_total + driver_total
    completed_rides = rider_completed + driver_completed
    cancelled_rides = rider_cancelled + driver_cancelled

    # Average rating received — riders receive driver_rating, drivers receive rider_rating
    avg_rating: float | None = None
    if user.role == UserRole.RIDER:
        rating_result = await db.execute(
            select(func.avg(Ride.driver_rating)).where(
                Ride.rider_id == user_id,
                Ride.driver_rating.is_not(None),
            )
        )
        raw = rating_result.scalar_one()
        avg_rating = round(float(raw), 2) if raw is not None else None
    elif user.role == UserRole.DRIVER:
        rating_result = await db.execute(
            select(func.avg(Ride.rider_rating)).where(
                Ride.driver_id == user_id,
                Ride.rider_rating.is_not(None),
            )
        )
        raw = rating_result.scalar_one()
        avg_rating = round(float(raw), 2) if raw is not None else None

    return UserDetailResponse(
        id=user.id,
        name=user.name,
        email=user.email,
        phone=user.phone,
        role=user.role.value,
        status=user.status.value,
        is_active=user.is_active,
        phone_verified=user.phone_verified,
        suspension_reason=user.suspension_reason,
        referral_code=user.referral_code,
        referred_by=user.referred_by,
        created_at=user.created_at,
        updated_at=user.updated_at,
        ride_stats=UserRideStats(
            total_rides=total_rides,
            completed_rides=completed_rides,
            cancelled_rides=cancelled_rides,
            avg_rating=avg_rating,
        ),
    )


async def suspend_user(
    db: AsyncSession,
    user_id: int,
    admin_id: int,
    body: SuspendUserRequest,
) -> UserStatusChangeResponse:
    """Suspend a user account.

    Args:
        db: Async SQLAlchemy session.
        user_id: Primary key of the user to suspend.
        admin_id: Admin performing the action (for logging).
        body: Request body with reason and notify_user flag.

    Raises:
        ValueError: If the user is not found.
        ValueError: If the user is already suspended (HTTP 409 via router).

    Returns:
        UserStatusChangeResponse.
    """
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise ValueError(f"User {user_id} not found")

    if user.status == UserStatus.SUSPENDED:
        raise _AlreadyInStateError(f"User {user_id} is already suspended")

    previous_status = user.status.value
    user.status = UserStatus.SUSPENDED
    user.suspension_reason = body.reason
    await db.flush()

    logger.info(
        "Admin %d suspended user %d. Reason: %s", admin_id, user_id, body.reason
    )

    notified = False
    if body.notify_user:
        notified = await _notify_status_change(db, user, "suspended", body.reason)

    return UserStatusChangeResponse(
        user_id=user_id,
        previous_status=previous_status,
        new_status=UserStatus.SUSPENDED.value,
        notified=notified,
    )


async def activate_user(
    db: AsyncSession,
    user_id: int,
    admin_id: int,
    body: ActivateUserRequest,
) -> UserStatusChangeResponse:
    """Reactivate a suspended user account.

    Args:
        db: Async SQLAlchemy session.
        user_id: Primary key of the user to activate.
        admin_id: Admin performing the action (for logging).
        body: Request body with optional reason and notify_user flag.

    Raises:
        ValueError: If the user is not found.
        ValueError: If the user is already active (HTTP 409 via router).

    Returns:
        UserStatusChangeResponse.
    """
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise ValueError(f"User {user_id} not found")

    if user.status == UserStatus.ACTIVE:
        raise _AlreadyInStateError(f"User {user_id} is already active")

    previous_status = user.status.value
    user.status = UserStatus.ACTIVE
    user.suspension_reason = None
    await db.flush()

    logger.info("Admin %d reactivated user %d.", admin_id, user_id)

    notified = False
    if body.notify_user:
        notified = await _notify_status_change(db, user, "active", body.reason)

    return UserStatusChangeResponse(
        user_id=user_id,
        previous_status=previous_status,
        new_status=UserStatus.ACTIVE.value,
        notified=notified,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


class _AlreadyInStateError(ValueError):
    """Raised when a status transition is a no-op (user already in target state)."""


async def _notify_status_change(
    db: AsyncSession,
    user: User,
    new_status: str,
    reason: str,
) -> bool:
    """Send an account status notification. Returns True on success, never raises."""
    try:
        from app.services.notifications import NotificationType, send_ride_notification

        status_label = "suspended" if new_status == "suspended" else "reactivated"
        await send_ride_notification(
            user_id=user.id,
            type=NotificationType.ACCOUNT_VERIFICATION,
            ride_id=0,  # No ride associated — 0 is a sentinel for account-level events
            db=db,
            phone=user.phone,
            email=user.email,
            status=status_label,
        )
        return True
    except Exception:
        logger.exception(
            "Failed to send status change notification to user %d (new_status=%s)",
            user.id,
            new_status,
        )
        return False
