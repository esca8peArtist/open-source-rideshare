"""Service layer for Corporate Recurring Ride Schedules.

Employees configure personal recurring ride schedules (daily commute,
weekly airport transfer, etc.).  Each schedule tracks its booking history
via CorporateRecurringRideBooking records.

Public surface
--------------
create_recurring_ride(db, account_id, member_id, data) -> RecurringRideResponse
get_recurring_ride(db, ride_id, account_id, member_id) -> RecurringRideResponse
list_recurring_rides(db, account_id, member_id, *, is_active) -> RecurringRideListResponse
update_recurring_ride(db, ride_id, account_id, member_id, data) -> RecurringRideResponse
activate_recurring_ride(db, ride_id, account_id, member_id) -> RecurringRideResponse
deactivate_recurring_ride(db, ride_id, account_id, member_id) -> RecurringRideResponse
delete_recurring_ride(db, ride_id, account_id, member_id) -> None
record_booking_attempt(db, ride_id, account_id, member_id, *, ...) -> RecurringRideBookingResponse
list_booking_history(db, ride_id, account_id, member_id, *, limit, offset) -> RecurringRideBookingListResponse
list_account_recurring_rides(db, account_id, *, is_active) -> RecurringRideListResponse
list_all_platform(db, *, account_id) -> RecurringRideListResponse
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.corporate_recurring_ride import (
    CorporateRecurringRide,
    CorporateRecurringRideBooking,
    RecurringRideBookingStatus,
)
from app.schemas.corporate_recurring_ride import (
    RecurringRideBookingListResponse,
    RecurringRideBookingResponse,
    RecurringRideCreate,
    RecurringRideListResponse,
    RecurringRideResponse,
    RecurringRideUpdate,
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _ride_to_response(ride: CorporateRecurringRide) -> RecurringRideResponse:
    """Convert a CorporateRecurringRide ORM instance to a response schema."""
    return RecurringRideResponse(
        id=ride.id,
        account_id=ride.account_id,
        member_id=ride.member_id,
        name=ride.name,
        pickup_address=ride.pickup_address,
        pickup_lat=float(ride.pickup_lat) if ride.pickup_lat is not None else None,
        pickup_lng=float(ride.pickup_lng) if ride.pickup_lng is not None else None,
        dropoff_address=ride.dropoff_address,
        dropoff_lat=float(ride.dropoff_lat) if ride.dropoff_lat is not None else None,
        dropoff_lng=float(ride.dropoff_lng) if ride.dropoff_lng is not None else None,
        vehicle_type=ride.vehicle_type,
        recurrence_type=ride.recurrence_type,
        days_of_week=ride.days_of_week,
        day_of_month=ride.day_of_month,
        scheduled_time=ride.scheduled_time,
        advance_booking_minutes=ride.advance_booking_minutes,
        cost_center_id=ride.cost_center_id,
        trip_purpose_id=ride.trip_purpose_id,
        notes=ride.notes,
        is_active=ride.is_active,
        created_at=ride.created_at,
        updated_at=ride.updated_at,
    )


def _booking_to_response(
    booking: CorporateRecurringRideBooking,
) -> RecurringRideBookingResponse:
    """Convert a CorporateRecurringRideBooking ORM instance to a response schema."""
    return RecurringRideBookingResponse(
        id=booking.id,
        recurring_ride_id=booking.recurring_ride_id,
        account_id=booking.account_id,
        member_id=booking.member_id,
        ride_id=booking.ride_id,
        scheduled_for=booking.scheduled_for,
        status=booking.status,
        failure_reason=booking.failure_reason,
        created_at=booking.created_at,
    )


async def _get_ride_row(
    db: AsyncSession,
    ride_id: uuid.UUID,
    account_id: int,
    member_id: Optional[int],
) -> CorporateRecurringRide | None:
    """Return the ride schedule for (account_id, ride_id[, member_id]) or None.

    When ``member_id`` is None the account-level lookup is performed
    (used by admin-scoped operations).
    """
    stmt = select(CorporateRecurringRide).where(
        CorporateRecurringRide.id == ride_id,
        CorporateRecurringRide.account_id == account_id,
    )
    if member_id is not None:
        stmt = stmt.where(CorporateRecurringRide.member_id == member_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def _get_ride_or_404(
    db: AsyncSession,
    ride_id: uuid.UUID,
    account_id: int,
    member_id: Optional[int] = None,
) -> CorporateRecurringRide:
    """Return the ride schedule or raise HTTP 404."""
    ride = await _get_ride_row(db, ride_id, account_id, member_id)
    if ride is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Recurring ride schedule not found.",
        )
    return ride


# ---------------------------------------------------------------------------
# Public service functions
# ---------------------------------------------------------------------------


async def create_recurring_ride(
    db: AsyncSession,
    account_id: int,
    member_id: int,
    data: RecurringRideCreate,
) -> RecurringRideResponse:
    """Create a new recurring-ride schedule for the member.

    Raises HTTP 409 if the member already has a schedule with this name
    in the same account.
    """
    existing = await db.execute(
        select(CorporateRecurringRide).where(
            CorporateRecurringRide.account_id == account_id,
            CorporateRecurringRide.member_id == member_id,
            CorporateRecurringRide.name == data.name,
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You already have a recurring ride schedule with this name.",
        )

    ride = CorporateRecurringRide(
        account_id=account_id,
        member_id=member_id,
        name=data.name,
        pickup_address=data.pickup_address,
        pickup_lat=data.pickup_lat,
        pickup_lng=data.pickup_lng,
        dropoff_address=data.dropoff_address,
        dropoff_lat=data.dropoff_lat,
        dropoff_lng=data.dropoff_lng,
        vehicle_type=data.vehicle_type,
        recurrence_type=data.recurrence_type,
        days_of_week=data.days_of_week,
        day_of_month=data.day_of_month,
        scheduled_time=data.scheduled_time,
        advance_booking_minutes=data.advance_booking_minutes,
        cost_center_id=data.cost_center_id,
        trip_purpose_id=data.trip_purpose_id,
        notes=data.notes,
        is_active=data.is_active,
    )
    db.add(ride)
    await db.commit()
    await db.refresh(ride)
    return _ride_to_response(ride)


async def get_recurring_ride(
    db: AsyncSession,
    ride_id: uuid.UUID,
    account_id: int,
    member_id: int,
) -> RecurringRideResponse:
    """Return a specific recurring-ride schedule owned by this member.

    Raises HTTP 404 if not found or belongs to a different member.
    """
    ride = await _get_ride_or_404(db, ride_id, account_id, member_id)
    return _ride_to_response(ride)


async def list_recurring_rides(
    db: AsyncSession,
    account_id: int,
    member_id: int,
    *,
    is_active: Optional[bool] = None,
) -> RecurringRideListResponse:
    """List recurring-ride schedules owned by this member, sorted by name.

    Optional filter:
      - ``is_active``: True → active only; False → inactive only.
    """
    stmt = select(CorporateRecurringRide).where(
        CorporateRecurringRide.account_id == account_id,
        CorporateRecurringRide.member_id == member_id,
    )
    if is_active is not None:
        stmt = stmt.where(CorporateRecurringRide.is_active == is_active)
    stmt = stmt.order_by(CorporateRecurringRide.name)

    result = await db.execute(stmt)
    rides = result.scalars().all()
    return RecurringRideListResponse(
        items=[_ride_to_response(r) for r in rides],
        total=len(rides),
    )


async def update_recurring_ride(
    db: AsyncSession,
    ride_id: uuid.UUID,
    account_id: int,
    member_id: int,
    data: RecurringRideUpdate,
) -> RecurringRideResponse:
    """Partially update a recurring-ride schedule.

    Raises HTTP 404 if not found.
    Raises HTTP 409 on name collision with another schedule for this member.
    """
    ride = await _get_ride_or_404(db, ride_id, account_id, member_id)

    update_data = data.model_dump(exclude_unset=True)

    if "name" in update_data and update_data["name"] != ride.name:
        collision = await db.execute(
            select(CorporateRecurringRide).where(
                CorporateRecurringRide.account_id == account_id,
                CorporateRecurringRide.member_id == member_id,
                CorporateRecurringRide.name == update_data["name"],
                CorporateRecurringRide.id != ride_id,
            )
        )
        if collision.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="You already have a recurring ride schedule with this name.",
            )

    for field, value in update_data.items():
        setattr(ride, field, value)

    await db.commit()
    await db.refresh(ride)
    return _ride_to_response(ride)


async def activate_recurring_ride(
    db: AsyncSession,
    ride_id: uuid.UUID,
    account_id: int,
    member_id: int,
) -> RecurringRideResponse:
    """Activate a recurring-ride schedule.

    Raises HTTP 404 if not found.
    Raises HTTP 409 if already active.
    """
    ride = await _get_ride_or_404(db, ride_id, account_id, member_id)
    if ride.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Recurring ride schedule is already active.",
        )
    ride.is_active = True
    await db.commit()
    await db.refresh(ride)
    return _ride_to_response(ride)


async def deactivate_recurring_ride(
    db: AsyncSession,
    ride_id: uuid.UUID,
    account_id: int,
    member_id: int,
) -> RecurringRideResponse:
    """Deactivate an active recurring-ride schedule.

    Raises HTTP 404 if not found.
    Raises HTTP 409 if already inactive.
    """
    ride = await _get_ride_or_404(db, ride_id, account_id, member_id)
    if not ride.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Recurring ride schedule is already inactive.",
        )
    ride.is_active = False
    await db.commit()
    await db.refresh(ride)
    return _ride_to_response(ride)


async def delete_recurring_ride(
    db: AsyncSession,
    ride_id: uuid.UUID,
    account_id: int,
    member_id: int,
) -> None:
    """Hard-delete a recurring-ride schedule and all its booking records.

    Raises HTTP 404 if not found.
    Raises HTTP 409 if the schedule is active — deactivate it first.
    """
    ride = await _get_ride_or_404(db, ride_id, account_id, member_id)
    if ride.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Cannot delete an active recurring ride schedule. "
                "Deactivate it first."
            ),
        )
    await db.delete(ride)
    await db.commit()


async def record_booking_attempt(
    db: AsyncSession,
    ride_id: uuid.UUID,
    account_id: int,
    member_id: int,
    *,
    scheduled_for: datetime,
    status: RecurringRideBookingStatus = RecurringRideBookingStatus.pending,
    linked_ride_id: Optional[int] = None,
    failure_reason: Optional[str] = None,
) -> RecurringRideBookingResponse:
    """Record a booking attempt for a recurring-ride schedule.

    Raises HTTP 404 if the schedule is not found.
    """
    # Verify the schedule exists — no ownership enforcement here so that
    # background schedulers (running without a specific member context) can
    # also record attempts using the account_id alone.
    ride = await _get_ride_or_404(db, ride_id, account_id, member_id=None)

    booking = CorporateRecurringRideBooking(
        recurring_ride_id=ride.id,
        account_id=account_id,
        member_id=ride.member_id,
        ride_id=linked_ride_id,
        scheduled_for=scheduled_for,
        status=status,
        failure_reason=failure_reason,
    )
    db.add(booking)
    await db.commit()
    await db.refresh(booking)
    return _booking_to_response(booking)


async def list_booking_history(
    db: AsyncSession,
    ride_id: uuid.UUID,
    account_id: int,
    member_id: int,
    *,
    limit: int = 50,
    offset: int = 0,
) -> RecurringRideBookingListResponse:
    """Return booking history for a recurring-ride schedule, newest first.

    Raises HTTP 404 if the schedule is not found.
    Supports pagination via ``limit`` and ``offset``.
    """
    # Verify ownership before exposing booking records.
    await _get_ride_or_404(db, ride_id, account_id, member_id)

    stmt = (
        select(CorporateRecurringRideBooking)
        .where(CorporateRecurringRideBooking.recurring_ride_id == ride_id)
        .order_by(CorporateRecurringRideBooking.scheduled_for.desc())
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(stmt)
    bookings = result.scalars().all()
    return RecurringRideBookingListResponse(
        items=[_booking_to_response(b) for b in bookings],
        total=len(bookings),
    )


async def list_account_recurring_rides(
    db: AsyncSession,
    account_id: int,
    *,
    is_active: Optional[bool] = None,
) -> RecurringRideListResponse:
    """Admin: list all recurring-ride schedules for an account.

    Optionally filtered by ``is_active``.  Sorted by member ID then name.
    """
    stmt = select(CorporateRecurringRide).where(
        CorporateRecurringRide.account_id == account_id,
    )
    if is_active is not None:
        stmt = stmt.where(CorporateRecurringRide.is_active == is_active)
    stmt = stmt.order_by(
        CorporateRecurringRide.member_id,
        CorporateRecurringRide.name,
    )
    result = await db.execute(stmt)
    rides = result.scalars().all()
    return RecurringRideListResponse(
        items=[_ride_to_response(r) for r in rides],
        total=len(rides),
    )


async def list_all_platform(
    db: AsyncSession,
    *,
    account_id: Optional[int] = None,
) -> RecurringRideListResponse:
    """Platform-admin: list all recurring-ride schedules, optionally by account."""
    stmt = select(CorporateRecurringRide)
    if account_id is not None:
        stmt = stmt.where(CorporateRecurringRide.account_id == account_id)
    stmt = stmt.order_by(
        CorporateRecurringRide.account_id,
        CorporateRecurringRide.member_id,
        CorporateRecurringRide.name,
    )
    result = await db.execute(stmt)
    rides = result.scalars().all()
    return RecurringRideListResponse(
        items=[_ride_to_response(r) for r in rides],
        total=len(rides),
    )
