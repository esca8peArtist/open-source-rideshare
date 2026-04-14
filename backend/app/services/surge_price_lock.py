"""Surge price lock service.

Riders can lock the current demand multiplier for a short window before they
complete a ride booking.  If they book within the window, their locked (and
potentially lower) multiplier is applied to the fare.

Pure helpers (is_lock_active, seconds_remaining, build_response) contain no
I/O and are fully unit-testable.  Async functions handle DB operations.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.surge_price_lock import SurgePriceLock
from app.schemas.surge_price_lock import SurgePriceLockResponse

# ---------------------------------------------------------------------------
# Policy constant
# ---------------------------------------------------------------------------

#: How long a lock is valid (minutes).
LOCK_DURATION_MINUTES: int = 5


# ---------------------------------------------------------------------------
# Pure helpers — no I/O, easy to unit test
# ---------------------------------------------------------------------------


def is_lock_active(lock: SurgePriceLock, now: datetime | None = None) -> bool:
    """Return True if the lock is still valid (not expired, used, or cancelled)."""
    if now is None:
        now = datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    if lock.used_at is not None:
        return False
    if lock.cancelled_at is not None:
        return False

    expires_at = lock.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return now < expires_at


def seconds_remaining(lock: SurgePriceLock, now: datetime | None = None) -> int:
    """Return seconds until the lock expires.  Returns 0 if already expired."""
    if now is None:
        now = datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    expires_at = lock.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    delta = (expires_at - now).total_seconds()
    return max(0, int(delta))


def build_response(lock: SurgePriceLock, now: datetime | None = None) -> SurgePriceLockResponse:
    """Convert a SurgePriceLock row into an API response."""
    if now is None:
        now = datetime.now(timezone.utc)
    return SurgePriceLockResponse(
        id=lock.id,
        rider_id=lock.rider_id,
        pickup_lat=lock.pickup_lat,
        pickup_lon=lock.pickup_lon,
        pickup_address=lock.pickup_address,
        locked_multiplier=lock.locked_multiplier,
        locked_at=lock.locked_at,
        expires_at=lock.expires_at,
        seconds_remaining=seconds_remaining(lock, now),
        is_active=is_lock_active(lock, now),
        used_at=lock.used_at,
        cancelled_at=lock.cancelled_at,
    )


# ---------------------------------------------------------------------------
# Async DB operations
# ---------------------------------------------------------------------------


async def get_active_lock(db: AsyncSession, rider_id: int) -> SurgePriceLock | None:
    """Return the rider's current active lock, or None if none exists.

    A lock is active when it has not been used, cancelled, or expired.
    """
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(SurgePriceLock).where(
            SurgePriceLock.rider_id == rider_id,
            SurgePriceLock.used_at.is_(None),
            SurgePriceLock.cancelled_at.is_(None),
            SurgePriceLock.expires_at > now,
        )
    )
    return result.scalar_one_or_none()


async def create_lock(
    db: AsyncSession,
    rider_id: int,
    pickup_lat: float,
    pickup_lon: float,
    pickup_address: str | None,
    multiplier: float,
    now: datetime | None = None,
) -> SurgePriceLock:
    """Create a new surge price lock for the rider.

    If the rider already has an active lock it is cancelled first so there is
    never more than one active lock per rider.

    Args:
        db: Database session.
        rider_id: ID of the rider requesting the lock.
        pickup_lat / pickup_lon: Pickup coordinates at lock time.
        pickup_address: Human-readable address (optional, for display).
        multiplier: Current demand multiplier to lock.
        now: Override for "now" (useful in tests).

    Returns:
        The newly created SurgePriceLock row.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    # Cancel any existing active lock for this rider.
    existing = await get_active_lock(db, rider_id)
    if existing is not None:
        existing.cancelled_at = now
        db.add(existing)

    lock = SurgePriceLock(
        rider_id=rider_id,
        pickup_lat=pickup_lat,
        pickup_lon=pickup_lon,
        pickup_address=pickup_address,
        locked_multiplier=multiplier,
        locked_at=now,
        expires_at=now + timedelta(minutes=LOCK_DURATION_MINUTES),
    )
    db.add(lock)
    await db.commit()
    await db.refresh(lock)
    return lock


async def cancel_lock(db: AsyncSession, rider_id: int) -> bool:
    """Cancel the rider's active surge price lock.

    Returns:
        True if a lock was found and cancelled; False if no active lock exists.
    """
    lock = await get_active_lock(db, rider_id)
    if lock is None:
        return False

    lock.cancelled_at = datetime.now(timezone.utc)
    db.add(lock)
    await db.commit()
    return True


async def consume_lock(
    db: AsyncSession,
    lock: SurgePriceLock,
    ride_id: int,
) -> None:
    """Mark the lock as consumed when a ride is booked using it.

    Sets used_at and ride_id on the lock row.
    """
    lock.used_at = datetime.now(timezone.utc)
    lock.ride_id = ride_id
    db.add(lock)
    # Caller is responsible for committing.
