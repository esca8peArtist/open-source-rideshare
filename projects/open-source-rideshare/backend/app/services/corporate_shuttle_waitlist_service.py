"""Service layer for Corporate Shuttle Waitlist.

When a shuttle schedule run is at full capacity employees can join a waitlist.
The first waiting member is automatically promoted to a confirmed booking when
an existing booking is cancelled.

Public functions
----------------
join_waitlist           — add a member to the waitlist (404/409 variants).
leave_waitlist          — cancel a waitlist entry (404; 409 if not waiting).
get_waitlist_entry      — fetch one entry (404 if missing or wrong account).
get_schedule_waitlist   — ordered list of waiting entries for schedule+date.
promote_from_waitlist   — internal: promote first waiter when seat opens.
get_member_waitlists    — all waitlist entries for a member.
get_waitlist_summary    — aggregate stats for a schedule+date.
list_all_platform       — platform-admin cross-account listing.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import List, Optional

from fastapi import HTTPException, status
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.corporate_shuttle import (
    CorporateShuttleBooking,
    CorporateShuttleSchedule,
    ShuttleBookingStatus,
)
from app.models.corporate_shuttle_waitlist import (
    CorporateShuttleWaitlist,
    WaitlistStatus,
)
from app.schemas.corporate_shuttle_waitlist import (
    WaitlistResponse,
    WaitlistSummaryResponse,
)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _to_waitlist(row: CorporateShuttleWaitlist) -> WaitlistResponse:
    return WaitlistResponse.model_validate(row)


async def _fetch_schedule(
    db: AsyncSession,
    account_id: int,
    schedule_id: uuid.UUID,
) -> CorporateShuttleSchedule:
    """Return a schedule verifying account ownership.

    Raises:
        HTTPException 404: Schedule not found or belongs to a different account.
    """
    stmt = select(CorporateShuttleSchedule).where(
        CorporateShuttleSchedule.id == schedule_id,
        CorporateShuttleSchedule.account_id == account_id,
    )
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Shuttle schedule not found.",
        )
    return row


async def _next_queue_position(
    db: AsyncSession,
    schedule_id: uuid.UUID,
    booking_date: date,
) -> int:
    """Return the next queue position for a schedule+date (max + 1, or 1)."""
    stmt = select(func.max(CorporateShuttleWaitlist.queue_position)).where(
        CorporateShuttleWaitlist.schedule_id == schedule_id,
        CorporateShuttleWaitlist.booking_date == booking_date,
    )
    max_pos = (await db.execute(stmt)).scalar_one_or_none()
    return (max_pos or 0) + 1


# ---------------------------------------------------------------------------
# Join / leave
# ---------------------------------------------------------------------------


async def join_waitlist(
    db: AsyncSession,
    schedule_id: uuid.UUID,
    account_id: int,
    member_id: int,
    booking_date: date,
    notes: Optional[str] = None,
) -> WaitlistResponse:
    """Add a member to the waitlist for a specific schedule run date.

    Args:
        db: Async SQLAlchemy session.
        schedule_id: UUID of the schedule.
        account_id: Corporate account ID.
        member_id: User ID of the member joining the waitlist.
        booking_date: The calendar date of the run.
        notes: Optional free-text notes.

    Returns:
        ``WaitlistResponse`` for the created entry.

    Raises:
        HTTPException 404: Schedule not found or wrong account.
        HTTPException 409: Schedule is inactive.
        HTTPException 409: Member already has an active booking for this
            schedule and date (no need to waitlist).
        HTTPException 409: Member already has a waiting entry for this
            schedule and date.
    """
    schedule = await _fetch_schedule(db, account_id, schedule_id)
    if not schedule.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot join waitlist for an inactive schedule.",
        )

    # Guard: member already has an active booking
    existing_booking_stmt = select(CorporateShuttleBooking).where(
        CorporateShuttleBooking.schedule_id == schedule_id,
        CorporateShuttleBooking.member_id == member_id,
        CorporateShuttleBooking.booking_date == booking_date,
        CorporateShuttleBooking.status.in_(
            [ShuttleBookingStatus.confirmed, ShuttleBookingStatus.pending]
        ),
    )
    existing_booking = (await db.execute(existing_booking_stmt)).scalar_one_or_none()
    if existing_booking is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Member already has an active booking for this schedule and date.",
        )

    # Guard: member already on the waitlist
    existing_wait_stmt = select(CorporateShuttleWaitlist).where(
        CorporateShuttleWaitlist.schedule_id == schedule_id,
        CorporateShuttleWaitlist.member_id == member_id,
        CorporateShuttleWaitlist.booking_date == booking_date,
        CorporateShuttleWaitlist.status == WaitlistStatus.waiting,
    )
    existing_wait = (await db.execute(existing_wait_stmt)).scalar_one_or_none()
    if existing_wait is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Member is already on the waitlist for this schedule and date.",
        )

    queue_position = await _next_queue_position(db, schedule_id, booking_date)

    entry = CorporateShuttleWaitlist(
        schedule_id=schedule_id,
        account_id=account_id,
        member_id=member_id,
        booking_date=booking_date,
        status=WaitlistStatus.waiting,
        queue_position=queue_position,
        notes=notes,
    )
    db.add(entry)
    await db.flush()
    await db.refresh(entry)
    return _to_waitlist(entry)


async def leave_waitlist(
    db: AsyncSession,
    entry_id: uuid.UUID,
    account_id: int,
    reason: Optional[str] = None,
) -> WaitlistResponse:
    """Cancel a waitlist entry.

    Args:
        db: Async SQLAlchemy session.
        entry_id: UUID of the waitlist entry.
        account_id: Corporate account ID for ownership verification.
        reason: Optional cancellation reason.

    Returns:
        Updated ``WaitlistResponse`` with status=cancelled.

    Raises:
        HTTPException 404: Entry not found or belongs to a different account.
        HTTPException 409: Entry is not in 'waiting' status.
    """
    stmt = select(CorporateShuttleWaitlist).where(
        CorporateShuttleWaitlist.id == entry_id,
        CorporateShuttleWaitlist.account_id == account_id,
    )
    entry = (await db.execute(stmt)).scalar_one_or_none()
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Waitlist entry not found.",
        )
    if entry.status != WaitlistStatus.waiting:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Waitlist entry is not in 'waiting' status (current: {entry.status.value}).",
        )

    entry.status = WaitlistStatus.cancelled
    entry.cancelled_at = datetime.now(tz=timezone.utc)
    entry.cancellation_reason = reason

    await db.flush()
    await db.refresh(entry)
    return _to_waitlist(entry)


# ---------------------------------------------------------------------------
# Read operations
# ---------------------------------------------------------------------------


async def get_waitlist_entry(
    db: AsyncSession,
    entry_id: uuid.UUID,
    account_id: int,
) -> WaitlistResponse:
    """Fetch a single waitlist entry by ID.

    Args:
        db: Async SQLAlchemy session.
        entry_id: UUID of the waitlist entry.
        account_id: Corporate account ID for ownership verification.

    Returns:
        ``WaitlistResponse``.

    Raises:
        HTTPException 404: Entry not found or belongs to a different account.
    """
    stmt = select(CorporateShuttleWaitlist).where(
        CorporateShuttleWaitlist.id == entry_id,
        CorporateShuttleWaitlist.account_id == account_id,
    )
    entry = (await db.execute(stmt)).scalar_one_or_none()
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Waitlist entry not found.",
        )
    return _to_waitlist(entry)


async def get_schedule_waitlist(
    db: AsyncSession,
    schedule_id: uuid.UUID,
    account_id: int,
    booking_date: date,
    status_filter: Optional[WaitlistStatus] = None,
) -> List[WaitlistResponse]:
    """Return waitlist entries for a schedule+date, ordered by queue_position.

    Args:
        db: Async SQLAlchemy session.
        schedule_id: UUID of the schedule.
        account_id: Corporate account ID.
        booking_date: The calendar date of the run.
        status_filter: Optional status filter (defaults to all statuses).

    Returns:
        List of ``WaitlistResponse`` ordered by queue_position ascending.
    """
    stmt = select(CorporateShuttleWaitlist).where(
        CorporateShuttleWaitlist.schedule_id == schedule_id,
        CorporateShuttleWaitlist.account_id == account_id,
        CorporateShuttleWaitlist.booking_date == booking_date,
    )
    if status_filter is not None:
        stmt = stmt.where(CorporateShuttleWaitlist.status == status_filter)
    stmt = stmt.order_by(CorporateShuttleWaitlist.queue_position)
    result = await db.execute(stmt)
    return [_to_waitlist(r) for r in result.scalars().all()]


async def get_member_waitlists(
    db: AsyncSession,
    account_id: int,
    member_id: int,
    status_filter: Optional[WaitlistStatus] = None,
) -> List[WaitlistResponse]:
    """Return all waitlist entries for a member within an account.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        member_id: User ID of the member.
        status_filter: Optional status filter.

    Returns:
        List of ``WaitlistResponse`` ordered by booking_date descending.
    """
    stmt = select(CorporateShuttleWaitlist).where(
        CorporateShuttleWaitlist.account_id == account_id,
        CorporateShuttleWaitlist.member_id == member_id,
    )
    if status_filter is not None:
        stmt = stmt.where(CorporateShuttleWaitlist.status == status_filter)
    stmt = stmt.order_by(CorporateShuttleWaitlist.booking_date.desc())
    result = await db.execute(stmt)
    return [_to_waitlist(r) for r in result.scalars().all()]


# ---------------------------------------------------------------------------
# Promotion (called by cancel_booking endpoint)
# ---------------------------------------------------------------------------


async def promote_from_waitlist(
    db: AsyncSession,
    schedule_id: uuid.UUID,
    account_id: int,
    booking_date: date,
) -> Optional[WaitlistResponse]:
    """Promote the first waiting member to a confirmed booking.

    Called automatically when a booking is cancelled. Checks current capacity:
    if a seat is now available the member at queue_position=1 (lowest) is
    booked and their entry marked as promoted. If no waiters exist or the
    schedule is still full this is a no-op.

    Args:
        db: Async SQLAlchemy session.
        schedule_id: UUID of the schedule.
        account_id: Corporate account ID.
        booking_date: The calendar date of the run.

    Returns:
        Updated ``WaitlistResponse`` for the promoted entry, or ``None``
        if no promotion was possible.
    """
    # Load schedule for capacity
    sched_stmt = select(CorporateShuttleSchedule).where(
        CorporateShuttleSchedule.id == schedule_id,
        CorporateShuttleSchedule.account_id == account_id,
    )
    schedule = (await db.execute(sched_stmt)).scalar_one_or_none()
    if schedule is None or not schedule.is_active:
        return None

    # Current confirmed/pending count
    count_stmt = select(func.count()).where(
        CorporateShuttleBooking.schedule_id == schedule_id,
        CorporateShuttleBooking.booking_date == booking_date,
        CorporateShuttleBooking.status.in_(
            [ShuttleBookingStatus.confirmed, ShuttleBookingStatus.pending]
        ),
    )
    current_count = (await db.execute(count_stmt)).scalar_one()
    if current_count >= schedule.seat_capacity:
        return None

    # Find first waiter
    wait_stmt = (
        select(CorporateShuttleWaitlist)
        .where(
            CorporateShuttleWaitlist.schedule_id == schedule_id,
            CorporateShuttleWaitlist.account_id == account_id,
            CorporateShuttleWaitlist.booking_date == booking_date,
            CorporateShuttleWaitlist.status == WaitlistStatus.waiting,
        )
        .order_by(CorporateShuttleWaitlist.queue_position)
        .limit(1)
    )
    waiter = (await db.execute(wait_stmt)).scalar_one_or_none()
    if waiter is None or waiter.member_id is None:
        return None

    # Create a confirmed booking for the waiter
    booking = CorporateShuttleBooking(
        schedule_id=schedule_id,
        account_id=account_id,
        member_id=waiter.member_id,
        booking_date=booking_date,
        status=ShuttleBookingStatus.confirmed,
        notes="Auto-promoted from waitlist.",
    )
    db.add(booking)
    await db.flush()
    await db.refresh(booking)

    # Mark waitlist entry as promoted
    waiter.status = WaitlistStatus.promoted
    waiter.promoted_at = datetime.now(tz=timezone.utc)
    waiter.promoted_booking_id = booking.id

    await db.flush()
    await db.refresh(waiter)
    return _to_waitlist(waiter)


# ---------------------------------------------------------------------------
# Summary / analytics
# ---------------------------------------------------------------------------


async def get_waitlist_summary(
    db: AsyncSession,
    schedule_id: uuid.UUID,
    account_id: int,
    booking_date: date,
) -> WaitlistSummaryResponse:
    """Return aggregate statistics for a schedule waitlist on a given date.

    Args:
        db: Async SQLAlchemy session.
        schedule_id: UUID of the schedule.
        account_id: Corporate account ID.
        booking_date: The calendar date of the run.

    Returns:
        ``WaitlistSummaryResponse``.
    """
    base_stmt = select(
        CorporateShuttleWaitlist.status,
        func.count().label("cnt"),
    ).where(
        CorporateShuttleWaitlist.schedule_id == schedule_id,
        CorporateShuttleWaitlist.account_id == account_id,
        CorporateShuttleWaitlist.booking_date == booking_date,
    ).group_by(CorporateShuttleWaitlist.status)

    result = await db.execute(base_stmt)
    rows = result.all()

    counts: dict[str, int] = {r.status.value: r.cnt for r in rows}
    waiting_count = counts.get(WaitlistStatus.waiting.value, 0)
    promoted_count = counts.get(WaitlistStatus.promoted.value, 0)
    total_entries = sum(counts.values())

    return WaitlistSummaryResponse(
        schedule_id=schedule_id,
        booking_date=booking_date,
        waiting_count=waiting_count,
        promoted_count=promoted_count,
        total_entries=total_entries,
    )


# ---------------------------------------------------------------------------
# Platform-admin
# ---------------------------------------------------------------------------


async def list_all_platform(
    db: AsyncSession,
    account_id: Optional[int] = None,
    status_filter: Optional[WaitlistStatus] = None,
) -> List[WaitlistResponse]:
    """Return all waitlist entries across all accounts (platform-admin).

    Args:
        db: Async SQLAlchemy session.
        account_id: Optional filter by corporate account ID.
        status_filter: Optional status filter.

    Returns:
        List of ``WaitlistResponse``.
    """
    stmt = select(CorporateShuttleWaitlist)
    if account_id is not None:
        stmt = stmt.where(CorporateShuttleWaitlist.account_id == account_id)
    if status_filter is not None:
        stmt = stmt.where(CorporateShuttleWaitlist.status == status_filter)
    stmt = stmt.order_by(
        CorporateShuttleWaitlist.account_id,
        CorporateShuttleWaitlist.booking_date.desc(),
        CorporateShuttleWaitlist.queue_position,
    )
    result = await db.execute(stmt)
    return [_to_waitlist(r) for r in result.scalars().all()]
