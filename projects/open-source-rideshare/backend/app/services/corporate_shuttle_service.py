"""Service layer for Corporate Shuttle Routes & Seat Booking.

Enterprise accounts define fixed shuttle routes, attach recurring schedules to
each route, and employees book seats on specific run dates.

Public functions
----------------
create_route            — create a route for the account (409 on duplicate active name).
get_route               — fetch one route (404 if missing or wrong account).
list_routes             — filtered list by is_active; ordered by name.
update_route            — partial update (404; 409 on name collision).
deactivate_route        — soft-delete (409 if already inactive; cascades to schedules).
add_schedule            — add a schedule to a route (404 route missing/inactive).
get_schedule            — fetch one schedule (404 if missing or wrong account).
list_schedules          — filtered list by route_id / is_active; ordered by departure_time.
book_seat               — book a seat for a member (404/409 variants).
cancel_booking          — cancel a booking (404; 409 if completed/no_show).
get_schedule_roster     — all non-cancelled bookings for a schedule+date.
get_route_summary       — aggregate stats + upcoming run dates for a route.
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
    CorporateShuttleRoute,
    CorporateShuttleSchedule,
    ShuttleBookingStatus,
)
from app.schemas.corporate_shuttle import (
    BookingCreate,
    BookingResponse,
    RouteSummaryResponse,
    RouteCreate,
    RouteResponse,
    RouteUpdate,
    ScheduleCreate,
    ScheduleResponse,
)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _to_route(row: CorporateShuttleRoute) -> RouteResponse:
    return RouteResponse.model_validate(row)


def _to_schedule(row: CorporateShuttleSchedule) -> ScheduleResponse:
    return ScheduleResponse.model_validate(row)


def _to_booking(row: CorporateShuttleBooking) -> BookingResponse:
    return BookingResponse.model_validate(row)


async def _fetch_route(
    db: AsyncSession,
    account_id: int,
    route_id: uuid.UUID,
) -> CorporateShuttleRoute:
    """Return a route verifying account ownership.

    Raises:
        HTTPException 404: Route not found or belongs to a different account.
    """
    stmt = select(CorporateShuttleRoute).where(
        CorporateShuttleRoute.id == route_id,
        CorporateShuttleRoute.account_id == account_id,
    )
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Shuttle route not found.",
        )
    return row


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


# ---------------------------------------------------------------------------
# Route CRUD
# ---------------------------------------------------------------------------


async def create_route(
    db: AsyncSession,
    account_id: int,
    data: RouteCreate,
    created_by_id: Optional[int] = None,
) -> RouteResponse:
    """Create a new shuttle route for the account.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        data: Route creation payload.
        created_by_id: User ID of the admin creating the record.

    Returns:
        ``RouteResponse`` for the created route.

    Raises:
        HTTPException 409: A route with the same name already exists for this account.
    """
    stmt = select(CorporateShuttleRoute).where(
        CorporateShuttleRoute.account_id == account_id,
        CorporateShuttleRoute.name == data.name,
        CorporateShuttleRoute.is_active == True,
    )
    existing = (await db.execute(stmt)).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"An active shuttle route named '{data.name}' already exists for this account.",
        )

    route = CorporateShuttleRoute(
        account_id=account_id,
        name=data.name,
        description=data.description,
        origin_name=data.origin_name,
        origin_address=data.origin_address,
        origin_lat=data.origin_lat,
        origin_lng=data.origin_lng,
        destination_name=data.destination_name,
        destination_address=data.destination_address,
        destination_lat=data.destination_lat,
        destination_lng=data.destination_lng,
        route_stops=data.route_stops,
        default_capacity=data.default_capacity,
        notes=data.notes,
        is_active=True,
        created_by_id=created_by_id,
    )
    db.add(route)
    await db.flush()
    await db.refresh(route)
    return _to_route(route)


async def get_route(
    db: AsyncSession,
    route_id: uuid.UUID,
    account_id: int,
) -> RouteResponse:
    """Fetch a single shuttle route by ID.

    Args:
        db: Async SQLAlchemy session.
        route_id: UUID of the route.
        account_id: Corporate account ID for ownership verification.

    Returns:
        ``RouteResponse``.

    Raises:
        HTTPException 404: Route not found or belongs to a different account.
    """
    row = await _fetch_route(db, account_id, route_id)
    return _to_route(row)


async def list_routes(
    db: AsyncSession,
    account_id: int,
    is_active: Optional[bool] = None,
) -> List[RouteResponse]:
    """Return a filtered list of shuttle routes for an account.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        is_active: Optional filter — True/False/None (all).

    Returns:
        List of ``RouteResponse`` ordered by name.
    """
    stmt = select(CorporateShuttleRoute).where(
        CorporateShuttleRoute.account_id == account_id
    )
    if is_active is not None:
        stmt = stmt.where(CorporateShuttleRoute.is_active == is_active)
    stmt = stmt.order_by(CorporateShuttleRoute.name)
    result = await db.execute(stmt)
    return [_to_route(r) for r in result.scalars().all()]


async def update_route(
    db: AsyncSession,
    route_id: uuid.UUID,
    account_id: int,
    data: RouteUpdate,
) -> RouteResponse:
    """Partially update a shuttle route.

    Args:
        db: Async SQLAlchemy session.
        route_id: UUID of the route to update.
        account_id: Corporate account ID.
        data: Partial update payload.

    Returns:
        Updated ``RouteResponse``.

    Raises:
        HTTPException 404: Route not found.
        HTTPException 409: Name collision with another active route in the account.
    """
    route = await _fetch_route(db, account_id, route_id)

    if data.name is not None and data.name != route.name:
        stmt = select(CorporateShuttleRoute).where(
            CorporateShuttleRoute.account_id == account_id,
            CorporateShuttleRoute.name == data.name,
            CorporateShuttleRoute.id != route_id,
            CorporateShuttleRoute.is_active == True,
        )
        collision = (await db.execute(stmt)).scalar_one_or_none()
        if collision is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"An active shuttle route named '{data.name}' already exists for this account.",
            )
        route.name = data.name

    if data.description is not None:
        route.description = data.description
    if data.origin_name is not None:
        route.origin_name = data.origin_name
    if data.origin_address is not None:
        route.origin_address = data.origin_address
    if data.origin_lat is not None:
        route.origin_lat = data.origin_lat
    if data.origin_lng is not None:
        route.origin_lng = data.origin_lng
    if data.destination_name is not None:
        route.destination_name = data.destination_name
    if data.destination_address is not None:
        route.destination_address = data.destination_address
    if data.destination_lat is not None:
        route.destination_lat = data.destination_lat
    if data.destination_lng is not None:
        route.destination_lng = data.destination_lng
    if data.route_stops is not None:
        route.route_stops = data.route_stops
    if data.default_capacity is not None:
        route.default_capacity = data.default_capacity
    if data.notes is not None:
        route.notes = data.notes

    await db.flush()
    await db.refresh(route)
    return _to_route(route)


async def deactivate_route(
    db: AsyncSession,
    route_id: uuid.UUID,
    account_id: int,
    deactivated_by_id: Optional[int] = None,
) -> RouteResponse:
    """Soft-delete a shuttle route and cascade deactivation to active schedules.

    Args:
        db: Async SQLAlchemy session.
        route_id: UUID of the route.
        account_id: Corporate account ID.
        deactivated_by_id: User ID of the admin deactivating (unused but available for audit).

    Returns:
        Updated ``RouteResponse`` with is_active=False.

    Raises:
        HTTPException 404: Route not found.
        HTTPException 409: Route is already inactive.
    """
    route = await _fetch_route(db, account_id, route_id)
    if not route.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Shuttle route is already inactive.",
        )
    route.is_active = False

    # Cascade: deactivate all active schedules for this route
    sched_stmt = select(CorporateShuttleSchedule).where(
        CorporateShuttleSchedule.route_id == route_id,
        CorporateShuttleSchedule.is_active == True,
    )
    sched_result = await db.execute(sched_stmt)
    for sched in sched_result.scalars().all():
        sched.is_active = False

    await db.flush()
    await db.refresh(route)
    return _to_route(route)


# ---------------------------------------------------------------------------
# Schedule management
# ---------------------------------------------------------------------------


async def add_schedule(
    db: AsyncSession,
    route_id: uuid.UUID,
    account_id: int,
    data: ScheduleCreate,
    created_by_id: Optional[int] = None,
) -> ScheduleResponse:
    """Add a recurring schedule to a shuttle route.

    Args:
        db: Async SQLAlchemy session.
        route_id: UUID of the route.
        account_id: Corporate account ID.
        data: Schedule creation payload.
        created_by_id: User ID of the admin creating the record.

    Returns:
        ``ScheduleResponse`` for the created schedule.

    Raises:
        HTTPException 404: Route not found or wrong account.
        HTTPException 409: Route is inactive.
    """
    route = await _fetch_route(db, account_id, route_id)
    if not route.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot add a schedule to an inactive route.",
        )

    schedule = CorporateShuttleSchedule(
        route_id=route_id,
        account_id=account_id,
        schedule_name=data.schedule_name,
        days_of_week=data.days_of_week,
        departure_time=data.departure_time,
        estimated_duration_minutes=data.estimated_duration_minutes,
        seat_capacity=data.seat_capacity,
        notes=data.notes,
        is_active=True,
        created_by_id=created_by_id,
    )
    db.add(schedule)
    await db.flush()
    await db.refresh(schedule)
    return _to_schedule(schedule)


async def get_schedule(
    db: AsyncSession,
    schedule_id: uuid.UUID,
    account_id: int,
) -> ScheduleResponse:
    """Fetch a single shuttle schedule by ID.

    Args:
        db: Async SQLAlchemy session.
        schedule_id: UUID of the schedule.
        account_id: Corporate account ID for ownership verification.

    Returns:
        ``ScheduleResponse``.

    Raises:
        HTTPException 404: Schedule not found or belongs to a different account.
    """
    row = await _fetch_schedule(db, account_id, schedule_id)
    return _to_schedule(row)


async def list_schedules(
    db: AsyncSession,
    account_id: int,
    route_id: Optional[uuid.UUID] = None,
    is_active: Optional[bool] = None,
) -> List[ScheduleResponse]:
    """Return a filtered list of schedules for an account.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        route_id: Optional route filter.
        is_active: Optional active status filter.

    Returns:
        List of ``ScheduleResponse`` ordered by departure_time.
    """
    stmt = select(CorporateShuttleSchedule).where(
        CorporateShuttleSchedule.account_id == account_id
    )
    if route_id is not None:
        stmt = stmt.where(CorporateShuttleSchedule.route_id == route_id)
    if is_active is not None:
        stmt = stmt.where(CorporateShuttleSchedule.is_active == is_active)
    stmt = stmt.order_by(CorporateShuttleSchedule.departure_time)
    result = await db.execute(stmt)
    return [_to_schedule(r) for r in result.scalars().all()]


# ---------------------------------------------------------------------------
# Booking management
# ---------------------------------------------------------------------------


async def book_seat(
    db: AsyncSession,
    schedule_id: uuid.UUID,
    account_id: int,
    member_id: int,
    booking_date: date,
    notes: Optional[str] = None,
) -> BookingResponse:
    """Book a seat for a member on a specific scheduled run date.

    Args:
        db: Async SQLAlchemy session.
        schedule_id: UUID of the schedule.
        account_id: Corporate account ID.
        member_id: User ID of the member booking the seat.
        booking_date: The calendar date of the run.
        notes: Optional free-text notes.

    Returns:
        ``BookingResponse`` for the created booking.

    Raises:
        HTTPException 404: Schedule not found.
        HTTPException 409: Schedule is inactive.
        HTTPException 409: Member already has a booking for this schedule+date.
        HTTPException 409: Seat capacity exceeded for this schedule+date.
    """
    schedule = await _fetch_schedule(db, account_id, schedule_id)
    if not schedule.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot book a seat on an inactive schedule.",
        )

    # Check for duplicate booking
    dup_stmt = select(CorporateShuttleBooking).where(
        CorporateShuttleBooking.schedule_id == schedule_id,
        CorporateShuttleBooking.member_id == member_id,
        CorporateShuttleBooking.booking_date == booking_date,
        CorporateShuttleBooking.status != ShuttleBookingStatus.cancelled,
    )
    duplicate = (await db.execute(dup_stmt)).scalar_one_or_none()
    if duplicate is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Member already has a booking for this schedule and date.",
        )

    # Check capacity
    capacity_stmt = select(func.count()).where(
        CorporateShuttleBooking.schedule_id == schedule_id,
        CorporateShuttleBooking.booking_date == booking_date,
        CorporateShuttleBooking.status.in_(
            [ShuttleBookingStatus.confirmed, ShuttleBookingStatus.pending]
        ),
    )
    current_count = (await db.execute(capacity_stmt)).scalar_one()
    if current_count >= schedule.seat_capacity:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No seats available for this schedule and date.",
        )

    booking = CorporateShuttleBooking(
        schedule_id=schedule_id,
        account_id=account_id,
        member_id=member_id,
        booking_date=booking_date,
        status=ShuttleBookingStatus.confirmed,
        notes=notes,
    )
    db.add(booking)
    await db.flush()
    await db.refresh(booking)
    return _to_booking(booking)


async def cancel_booking(
    db: AsyncSession,
    booking_id: uuid.UUID,
    account_id: int,
    cancelled_by_id: int,
    reason: Optional[str] = None,
) -> BookingResponse:
    """Cancel a shuttle booking.

    Args:
        db: Async SQLAlchemy session.
        booking_id: UUID of the booking to cancel.
        account_id: Corporate account ID.
        cancelled_by_id: User ID of the person cancelling.
        reason: Optional cancellation reason.

    Returns:
        Updated ``BookingResponse`` with status=cancelled.

    Raises:
        HTTPException 404: Booking not found.
        HTTPException 409: Booking is already completed or no_show.
    """
    stmt = select(CorporateShuttleBooking).where(
        CorporateShuttleBooking.id == booking_id,
        CorporateShuttleBooking.account_id == account_id,
    )
    booking = (await db.execute(stmt)).scalar_one_or_none()
    if booking is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Shuttle booking not found.",
        )

    if booking.status == ShuttleBookingStatus.completed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot cancel a completed booking.",
        )
    if booking.status == ShuttleBookingStatus.no_show:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot cancel a no-show booking.",
        )

    booking.status = ShuttleBookingStatus.cancelled
    booking.cancelled_at = datetime.now(tz=timezone.utc)
    booking.cancelled_by_id = cancelled_by_id
    booking.cancellation_reason = reason

    await db.flush()
    await db.refresh(booking)
    return _to_booking(booking)


async def get_schedule_roster(
    db: AsyncSession,
    schedule_id: uuid.UUID,
    account_id: int,
    booking_date: date,
) -> List[BookingResponse]:
    """Return all non-cancelled bookings for a given schedule and date.

    Args:
        db: Async SQLAlchemy session.
        schedule_id: UUID of the schedule.
        account_id: Corporate account ID.
        booking_date: The specific calendar date of the run.

    Returns:
        List of ``BookingResponse`` (non-cancelled bookings only).
    """
    stmt = select(CorporateShuttleBooking).where(
        CorporateShuttleBooking.schedule_id == schedule_id,
        CorporateShuttleBooking.account_id == account_id,
        CorporateShuttleBooking.booking_date == booking_date,
        CorporateShuttleBooking.status != ShuttleBookingStatus.cancelled,
    )
    result = await db.execute(stmt)
    return [_to_booking(r) for r in result.scalars().all()]


# ---------------------------------------------------------------------------
# Summary / analytics
# ---------------------------------------------------------------------------


async def get_route_summary(
    db: AsyncSession,
    route_id: uuid.UUID,
    account_id: int,
) -> RouteSummaryResponse:
    """Return aggregate statistics for a shuttle route.

    Args:
        db: Async SQLAlchemy session.
        route_id: UUID of the route.
        account_id: Corporate account ID.

    Returns:
        ``RouteSummaryResponse`` with schedule counts, monthly booking count,
        and upcoming run dates for the next 7 days.

    Raises:
        HTTPException 404: Route not found.
    """
    route = await _fetch_route(db, account_id, route_id)

    # Total schedules
    total_sched_stmt = select(func.count()).where(
        CorporateShuttleSchedule.route_id == route_id
    )
    total_schedules = (await db.execute(total_sched_stmt)).scalar_one()

    # Active schedules
    active_sched_stmt = select(func.count()).where(
        CorporateShuttleSchedule.route_id == route_id,
        CorporateShuttleSchedule.is_active == True,
    )
    active_schedules = (await db.execute(active_sched_stmt)).scalar_one()

    # Bookings this month
    today = date.today()
    month_start = today.replace(day=1)
    if today.month == 12:
        month_end = today.replace(year=today.year + 1, month=1, day=1)
    else:
        month_end = today.replace(month=today.month + 1, day=1)

    # Get all schedule IDs for this route
    sched_ids_stmt = select(CorporateShuttleSchedule.id).where(
        CorporateShuttleSchedule.route_id == route_id
    )
    sched_ids_result = await db.execute(sched_ids_stmt)
    sched_ids = [r[0] for r in sched_ids_result.all()]

    if sched_ids:
        booking_count_stmt = select(func.count()).where(
            CorporateShuttleBooking.schedule_id.in_(sched_ids),
            CorporateShuttleBooking.booking_date >= month_start,
            CorporateShuttleBooking.booking_date < month_end,
            CorporateShuttleBooking.status != ShuttleBookingStatus.cancelled,
        )
        total_bookings_this_month = (await db.execute(booking_count_stmt)).scalar_one()
    else:
        total_bookings_this_month = 0

    # Upcoming run dates: next 7 days based on active schedule days_of_week
    active_sched_stmt2 = select(CorporateShuttleSchedule).where(
        CorporateShuttleSchedule.route_id == route_id,
        CorporateShuttleSchedule.is_active == True,
    )
    active_scheds_result = await db.execute(active_sched_stmt2)
    active_scheds = active_scheds_result.scalars().all()

    all_days: set[int] = set()
    for sched in active_scheds:
        for d in (sched.days_of_week or []):
            all_days.add(d)

    from datetime import timedelta

    upcoming_run_dates: list[date] = []
    for offset in range(7):
        check_date = today + timedelta(days=offset)
        # Python weekday(): Monday=0 ... Sunday=6 — matches our convention
        if check_date.weekday() in all_days:
            upcoming_run_dates.append(check_date)

    return RouteSummaryResponse(
        route=_to_route(route),
        total_schedules=total_schedules,
        active_schedules=active_schedules,
        total_bookings_this_month=total_bookings_this_month,
        upcoming_run_dates=upcoming_run_dates,
    )


async def list_member_bookings(
    db: AsyncSession,
    account_id: int,
    member_id: int,
) -> List[BookingResponse]:
    """Return a member's own bookings (upcoming and recent).

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        member_id: User ID of the member.

    Returns:
        List of ``BookingResponse`` ordered by booking_date descending.
    """
    stmt = select(CorporateShuttleBooking).where(
        CorporateShuttleBooking.account_id == account_id,
        CorporateShuttleBooking.member_id == member_id,
    ).order_by(CorporateShuttleBooking.booking_date.desc())
    result = await db.execute(stmt)
    return [_to_booking(r) for r in result.scalars().all()]


# ---------------------------------------------------------------------------
# Platform-admin
# ---------------------------------------------------------------------------


async def list_all_platform(
    db: AsyncSession,
    account_id: Optional[int] = None,
) -> List[RouteResponse]:
    """Return all shuttle routes across all accounts (platform-admin).

    Args:
        db: Async SQLAlchemy session.
        account_id: Optional filter by corporate account ID.

    Returns:
        List of ``RouteResponse``.
    """
    stmt = select(CorporateShuttleRoute)
    if account_id is not None:
        stmt = stmt.where(CorporateShuttleRoute.account_id == account_id)
    stmt = stmt.order_by(
        CorporateShuttleRoute.account_id,
        CorporateShuttleRoute.name,
    )
    result = await db.execute(stmt)
    return [_to_route(r) for r in result.scalars().all()]
