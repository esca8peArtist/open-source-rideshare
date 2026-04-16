"""Service layer for Corporate Shift Auto-Booking.

Generates and processes ride auto-bookings for shift workers whose
``CorporateShiftAssignment.auto_request_rides`` flag is True.

Public functions
----------------
generate_shift_auto_bookings   — scan assignments, create pending records.
get_shift_auto_booking         — fetch one record (404 if missing).
list_shift_auto_bookings       — list with optional filters.
list_member_auto_bookings      — list for one member in an account.
cancel_shift_auto_booking      — cancel a pending record (409 if non-pending).
process_shift_auto_booking     — create the Ride and mark as booked (or failed).
get_shift_auto_booking_summary — aggregate stats for one shift.
list_all_platform              — platform-admin cross-account list.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import List, Optional

from fastapi import HTTPException, status
from geoalchemy2.elements import WKTElement
from sqlalchemy import and_, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.corporate_shift import CorporateShift, CorporateShiftAssignment
from app.models.corporate_shift_auto_booking import (
    CorporateShiftAutoBooking,
    ShiftAutoBookingDirection,
    ShiftAutoBookingStatus,
)
from app.models.ride import Ride, RideStatus
from app.schemas.corporate_shift_auto_booking import (
    AutoBookingListResponse,
    AutoBookingResponse,
    GenerateAutoBookingsRequest,
    GenerateAutoBookingsResponse,
    ShiftAutoBookingSummaryResponse,
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _upcoming_dates_for_shift(
    days_of_week: list[int],
    from_date: date,
    days_ahead: int,
) -> list[date]:
    """Return dates in [from_date, from_date + days_ahead) that fall on one
    of the given weekdays (0 = Monday … 6 = Sunday).

    Args:
        days_of_week: List of ISO weekday integers (0–6).
        from_date: Inclusive start date.
        days_ahead: Number of calendar days to scan.

    Returns:
        Sorted list of matching dates.
    """
    day_set = set(days_of_week)
    result: list[date] = []
    for offset in range(days_ahead):
        candidate = from_date + timedelta(days=offset)
        if candidate.weekday() in day_set:
            result.append(candidate)
    return result


def _build_address(line1, line2, city, state, postal_code, country) -> str:
    """Concatenate address components into a single readable string."""
    parts = [p for p in [line1, line2, city, state, postal_code, country] if p]
    return ", ".join(parts) if parts else ""


def _make_point(lat, lng) -> WKTElement:
    """Create a WKT POINT geometry element for PostGIS.

    Falls back to POINT(0 0) when lat/lng are absent.
    """
    try:
        if lat is not None and lng is not None:
            return WKTElement(f"POINT({float(lng)} {float(lat)})", srid=4326)
    except (TypeError, ValueError):
        pass
    return WKTElement("POINT(0 0)", srid=4326)


def _to_response(row: CorporateShiftAutoBooking) -> AutoBookingResponse:
    return AutoBookingResponse.model_validate(row)


# ---------------------------------------------------------------------------
# generate_shift_auto_bookings
# ---------------------------------------------------------------------------


async def generate_shift_auto_bookings(
    db: AsyncSession,
    account_id: int,
    data: GenerateAutoBookingsRequest,
) -> GenerateAutoBookingsResponse:
    """Scan active shift assignments and create pending auto-booking records.

    For every active shift assignment within the account where
    ``auto_request_rides = True``, this function:

    1. Computes upcoming dates in the next ``data.days_ahead`` days that
       match the shift's ``days_of_week``.
    2. Creates a ``to_work`` auto-booking for each upcoming date.
    3. Optionally creates a ``from_work`` booking when
       ``data.include_return_rides = True``.
    4. Skips records that already exist (unique constraint).

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account to scope to.
        data: ``GenerateAutoBookingsRequest`` payload.

    Returns:
        ``GenerateAutoBookingsResponse`` with counts of created vs skipped.
    """
    today = datetime.now(tz=timezone.utc).date()

    # Fetch all active shifts + active assignments with auto_request_rides=True
    stmt = (
        select(CorporateShift, CorporateShiftAssignment)
        .join(
            CorporateShiftAssignment,
            CorporateShiftAssignment.shift_id == CorporateShift.id,
        )
        .where(
            CorporateShift.account_id == account_id,
            CorporateShift.is_active.is_(True),
            CorporateShiftAssignment.is_active.is_(True),
            CorporateShiftAssignment.auto_request_rides.is_(True),
        )
    )
    result = await db.execute(stmt)
    pairs = result.all()

    created = 0
    skipped = 0

    for shift, assignment in pairs:
        upcoming = _upcoming_dates_for_shift(
            shift.days_of_week or [], today, data.days_ahead
        )

        directions: list[ShiftAutoBookingDirection] = [
            ShiftAutoBookingDirection.to_work
        ]
        if data.include_return_rides:
            directions.append(ShiftAutoBookingDirection.from_work)

        for shift_date in upcoming:
            for direction in directions:
                if direction == ShiftAutoBookingDirection.to_work:
                    t = shift.shift_start_time
                else:
                    t = shift.shift_end_time

                scheduled_for = datetime(
                    shift_date.year,
                    shift_date.month,
                    shift_date.day,
                    t.hour,
                    t.minute,
                    tzinfo=timezone.utc,
                )

                booking = CorporateShiftAutoBooking(
                    id=uuid.uuid4(),
                    shift_id=shift.id,
                    assignment_id=assignment.id,
                    member_id=assignment.member_id,
                    account_id=account_id,
                    shift_date=shift_date,
                    ride_direction=direction,
                    scheduled_for=scheduled_for,
                    status=ShiftAutoBookingStatus.pending,
                )
                db.add(booking)
                try:
                    await db.flush()
                    created += 1
                except IntegrityError:
                    await db.rollback()
                    skipped += 1
                    db.add(booking)  # re-add a fresh session after rollback
                    # Re-open transaction silently — the duplicate simply means
                    # this booking was already generated in a prior run.

    await db.commit()

    return GenerateAutoBookingsResponse(
        created=created,
        skipped=skipped,
        total_assignments_scanned=len(pairs),
    )


# ---------------------------------------------------------------------------
# get_shift_auto_booking
# ---------------------------------------------------------------------------


async def get_shift_auto_booking(
    db: AsyncSession,
    booking_id: uuid.UUID,
    account_id: int,
) -> AutoBookingResponse:
    """Return a single auto-booking record.

    Args:
        db: Async SQLAlchemy session.
        booking_id: UUID of the record.
        account_id: Account scope — raises 404 if the record belongs to another
            account.

    Returns:
        ``AutoBookingResponse``.

    Raises:
        HTTPException 404: Record not found or belongs to a different account.
    """
    stmt = select(CorporateShiftAutoBooking).where(
        CorporateShiftAutoBooking.id == booking_id,
        CorporateShiftAutoBooking.account_id == account_id,
    )
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Auto-booking record not found.",
        )
    return _to_response(row)


# ---------------------------------------------------------------------------
# list_shift_auto_bookings
# ---------------------------------------------------------------------------


async def list_shift_auto_bookings(
    db: AsyncSession,
    account_id: int,
    shift_id: Optional[int] = None,
    member_id: Optional[int] = None,
    booking_status: Optional[ShiftAutoBookingStatus] = None,
    direction: Optional[ShiftAutoBookingDirection] = None,
    limit: int = 100,
    offset: int = 0,
) -> AutoBookingListResponse:
    """List auto-booking records for an account with optional filters.

    Args:
        db: Async SQLAlchemy session.
        account_id: Account scope.
        shift_id: Optional filter by shift.
        member_id: Optional filter by member.
        booking_status: Optional filter by status.
        direction: Optional filter by ride direction.
        limit: Max records to return (default 100).
        offset: Records to skip (default 0).

    Returns:
        ``AutoBookingListResponse``.
    """
    conditions = [CorporateShiftAutoBooking.account_id == account_id]
    if shift_id is not None:
        conditions.append(CorporateShiftAutoBooking.shift_id == shift_id)
    if member_id is not None:
        conditions.append(CorporateShiftAutoBooking.member_id == member_id)
    if booking_status is not None:
        conditions.append(CorporateShiftAutoBooking.status == booking_status)
    if direction is not None:
        conditions.append(CorporateShiftAutoBooking.ride_direction == direction)

    count_stmt = select(func.count()).select_from(
        select(CorporateShiftAutoBooking).where(and_(*conditions)).subquery()
    )
    count_result = await db.execute(count_stmt)
    total = count_result.scalar_one()

    rows_stmt = (
        select(CorporateShiftAutoBooking)
        .where(and_(*conditions))
        .order_by(CorporateShiftAutoBooking.scheduled_for)
        .limit(limit)
        .offset(offset)
    )
    rows_result = await db.execute(rows_stmt)
    rows = rows_result.scalars().all()

    return AutoBookingListResponse(
        total=total,
        items=[_to_response(r) for r in rows],
    )


# ---------------------------------------------------------------------------
# list_member_auto_bookings
# ---------------------------------------------------------------------------


async def list_member_auto_bookings(
    db: AsyncSession,
    account_id: int,
    member_id: int,
) -> AutoBookingListResponse:
    """Return all auto-booking records for one member in an account.

    Includes all statuses; ordered by scheduled_for ascending.

    Args:
        db: Async SQLAlchemy session.
        account_id: Account scope.
        member_id: The corporate_account_members.id of the requesting member.

    Returns:
        ``AutoBookingListResponse``.
    """
    return await list_shift_auto_bookings(
        db, account_id, member_id=member_id, limit=200
    )


# ---------------------------------------------------------------------------
# cancel_shift_auto_booking
# ---------------------------------------------------------------------------


async def cancel_shift_auto_booking(
    db: AsyncSession,
    booking_id: uuid.UUID,
    account_id: int,
) -> AutoBookingResponse:
    """Cancel a pending auto-booking record.

    Only ``pending`` records can be cancelled.  Records that are already
    ``booked``, ``failed``, ``skipped``, or ``cancelled`` raise 409.

    Args:
        db: Async SQLAlchemy session.
        booking_id: UUID of the record.
        account_id: Account scope.

    Returns:
        Updated ``AutoBookingResponse`` with status ``cancelled``.

    Raises:
        HTTPException 404: Record not found.
        HTTPException 409: Record is not in ``pending`` status.
    """
    stmt = select(CorporateShiftAutoBooking).where(
        CorporateShiftAutoBooking.id == booking_id,
        CorporateShiftAutoBooking.account_id == account_id,
    )
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Auto-booking record not found.",
        )
    if row.status != ShiftAutoBookingStatus.pending:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Cannot cancel an auto-booking with status '{row.status.value}'. "
                "Only 'pending' bookings can be cancelled."
            ),
        )
    row.status = ShiftAutoBookingStatus.cancelled
    row.cancelled_at = datetime.now(tz=timezone.utc)
    await db.commit()
    await db.refresh(row)
    return _to_response(row)


# ---------------------------------------------------------------------------
# process_shift_auto_booking
# ---------------------------------------------------------------------------


async def process_shift_auto_booking(
    db: AsyncSession,
    booking_id: uuid.UUID,
    account_id: int,
) -> AutoBookingResponse:
    """Process a pending auto-booking by creating a scheduled Ride record.

    Looks up the associated shift and assignment to derive pickup/dropoff
    addresses and the member's user ID (via corporate_account_members).
    Creates a Ride with status SCHEDULED, then marks the booking as
    ``booked``.  If any step fails the booking is marked ``failed`` with
    a ``failure_reason``.

    Args:
        db: Async SQLAlchemy session.
        booking_id: UUID of the record.
        account_id: Account scope.

    Returns:
        Updated ``AutoBookingResponse``.

    Raises:
        HTTPException 404: Record not found.
        HTTPException 409: Record is not in ``pending`` status.
    """
    # 1 — Load the auto-booking
    stmt = select(CorporateShiftAutoBooking).where(
        CorporateShiftAutoBooking.id == booking_id,
        CorporateShiftAutoBooking.account_id == account_id,
    )
    result = await db.execute(stmt)
    booking = result.scalar_one_or_none()
    if booking is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Auto-booking record not found.",
        )
    if booking.status != ShiftAutoBookingStatus.pending:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Cannot process an auto-booking with status '{booking.status.value}'. "
                "Only 'pending' bookings can be processed."
            ),
        )

    # 2 — Load shift and assignment
    shift_stmt = select(CorporateShift).where(
        CorporateShift.id == booking.shift_id
    )
    assignment_stmt = select(CorporateShiftAssignment).where(
        CorporateShiftAssignment.id == booking.assignment_id
    )
    shift_result = await db.execute(shift_stmt)
    assignment_result = await db.execute(assignment_stmt)
    shift = shift_result.scalar_one_or_none()
    assignment = assignment_result.scalar_one_or_none()

    if shift is None or assignment is None:
        booking.status = ShiftAutoBookingStatus.failed
        booking.failure_reason = "Associated shift or assignment no longer exists."
        await db.commit()
        await db.refresh(booking)
        return _to_response(booking)

    # 3 — Resolve rider_id from corporate_account_members
    from app.models.corporate import BusinessAccountMember  # avoid circular
    member_stmt = select(BusinessAccountMember).where(
        BusinessAccountMember.id == booking.member_id
    )
    member_result = await db.execute(member_stmt)
    member = member_result.scalar_one_or_none()

    if member is None:
        booking.status = ShiftAutoBookingStatus.failed
        booking.failure_reason = "Corporate account member record not found."
        await db.commit()
        await db.refresh(booking)
        return _to_response(booking)

    # 4 — Build pickup / dropoff based on direction
    if booking.ride_direction == ShiftAutoBookingDirection.to_work:
        pickup_address = _build_address(
            assignment.pickup_address_line1,
            assignment.pickup_address_line2,
            assignment.pickup_city,
            assignment.pickup_state,
            assignment.pickup_postal_code,
            assignment.pickup_country,
        )
        dropoff_address = _build_address(
            shift.work_address_line1,
            shift.work_address_line2,
            shift.work_city,
            shift.work_state,
            shift.work_postal_code,
            shift.work_country,
        ) or shift.work_location_name
        pickup_geom = _make_point(assignment.pickup_latitude, assignment.pickup_longitude)
        dropoff_geom = _make_point(shift.work_latitude, shift.work_longitude)
    else:
        # from_work: reverse the direction
        pickup_address = _build_address(
            shift.work_address_line1,
            shift.work_address_line2,
            shift.work_city,
            shift.work_state,
            shift.work_postal_code,
            shift.work_country,
        ) or shift.work_location_name
        dropoff_address = _build_address(
            assignment.pickup_address_line1,
            assignment.pickup_address_line2,
            assignment.pickup_city,
            assignment.pickup_state,
            assignment.pickup_postal_code,
            assignment.pickup_country,
        )
        pickup_geom = _make_point(shift.work_latitude, shift.work_longitude)
        dropoff_geom = _make_point(assignment.pickup_latitude, assignment.pickup_longitude)

    if not pickup_address:
        pickup_address = "Pickup address not specified"
    if not dropoff_address:
        dropoff_address = "Dropoff address not specified"

    # 5 — Create the Ride
    try:
        ride = Ride(
            rider_id=member.user_id,
            status=RideStatus.SCHEDULED,
            pickup_location=pickup_geom,
            dropoff_location=dropoff_geom,
            pickup_address=pickup_address[:500],
            dropoff_address=dropoff_address[:500],
            estimated_fare=0.0,
            scheduled_for=booking.scheduled_for,
            corporate_account_id=account_id,
        )
        db.add(ride)
        await db.flush()  # get ride.id

        booking.status = ShiftAutoBookingStatus.booked
        booking.ride_id = ride.id
        booking.booked_at = datetime.now(tz=timezone.utc)
        await db.commit()
    except Exception as exc:  # noqa: BLE001
        await db.rollback()
        # Re-load booking after rollback and mark failed
        result2 = await db.execute(
            select(CorporateShiftAutoBooking).where(
                CorporateShiftAutoBooking.id == booking_id
            )
        )
        booking = result2.scalar_one()
        booking.status = ShiftAutoBookingStatus.failed
        booking.failure_reason = str(exc)[:500]
        await db.commit()

    await db.refresh(booking)
    return _to_response(booking)


# ---------------------------------------------------------------------------
# get_shift_auto_booking_summary
# ---------------------------------------------------------------------------


async def get_shift_auto_booking_summary(
    db: AsyncSession,
    shift_id: int,
    account_id: int,
) -> ShiftAutoBookingSummaryResponse:
    """Return aggregate statistics for auto-bookings belonging to one shift.

    Args:
        db: Async SQLAlchemy session.
        shift_id: The shift to summarise.
        account_id: Account scope — raises 404 if shift not found.

    Returns:
        ``ShiftAutoBookingSummaryResponse``.

    Raises:
        HTTPException 404: Shift not found in this account.
    """
    # Verify shift exists and belongs to account
    shift_check = await db.execute(
        select(CorporateShift).where(
            CorporateShift.id == shift_id,
            CorporateShift.account_id == account_id,
        )
    )
    if shift_check.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Shift not found.",
        )

    # Count by status
    rows_stmt = select(CorporateShiftAutoBooking).where(
        CorporateShiftAutoBooking.shift_id == shift_id,
        CorporateShiftAutoBooking.account_id == account_id,
    )
    rows_result = await db.execute(rows_stmt)
    rows = rows_result.scalars().all()

    counts: dict[str, int] = {s.value: 0 for s in ShiftAutoBookingStatus}
    to_work_count = 0
    from_work_count = 0

    for row in rows:
        counts[row.status.value] += 1
        if row.ride_direction == ShiftAutoBookingDirection.to_work:
            to_work_count += 1
        else:
            from_work_count += 1

    return ShiftAutoBookingSummaryResponse(
        shift_id=shift_id,
        total=len(rows),
        pending=counts["pending"],
        booked=counts["booked"],
        failed=counts["failed"],
        skipped=counts["skipped"],
        cancelled=counts["cancelled"],
        to_work_count=to_work_count,
        from_work_count=from_work_count,
    )


# ---------------------------------------------------------------------------
# list_all_platform
# ---------------------------------------------------------------------------


async def list_all_platform(
    db: AsyncSession,
    account_id: Optional[int] = None,
    booking_status: Optional[ShiftAutoBookingStatus] = None,
    limit: int = 100,
    offset: int = 0,
) -> AutoBookingListResponse:
    """Return auto-booking records across all accounts (platform admin).

    Args:
        db: Async SQLAlchemy session.
        account_id: Optional filter by account.
        booking_status: Optional filter by status.
        limit: Max records to return.
        offset: Records to skip.

    Returns:
        ``AutoBookingListResponse``.
    """
    conditions: list = []
    if account_id is not None:
        conditions.append(CorporateShiftAutoBooking.account_id == account_id)
    if booking_status is not None:
        conditions.append(CorporateShiftAutoBooking.status == booking_status)

    base = select(CorporateShiftAutoBooking)
    if conditions:
        base = base.where(and_(*conditions))

    count_stmt = select(func.count()).select_from(base.subquery())
    count_result = await db.execute(count_stmt)
    total = count_result.scalar_one()

    rows_stmt = (
        base.order_by(CorporateShiftAutoBooking.scheduled_for)
        .limit(limit)
        .offset(offset)
    )
    rows_result = await db.execute(rows_stmt)
    rows = rows_result.scalars().all()

    return AutoBookingListResponse(
        total=total,
        items=[_to_response(r) for r in rows],
    )
