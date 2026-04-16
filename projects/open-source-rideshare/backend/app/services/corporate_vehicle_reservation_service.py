"""Service layer for Corporate Vehicle Reservation Booking.

Employees can reserve company fleet vehicles for self-drive use during
specified time windows — like an internal Zipcar.  Reservations must not
overlap for the same vehicle.

Public functions
----------------
create_reservation          — create a new reservation (409 on overlap or inactive vehicle).
get_reservation             — fetch a single reservation (404 if missing or wrong account).
list_reservations           — filtered, paginated list for an account.
list_member_reservations    — reservations by a specific user.
update_reservation          — partial update (pending only; 409 on overlap).
confirm_reservation         — admin confirms a pending reservation.
cancel_reservation          — member or admin cancels a reservation.
complete_reservation        — admin marks a confirmed reservation completed.
no_show_reservation         — admin marks a confirmed reservation as no-show.
check_vehicle_availability  — check for conflicts in a time window.
get_reservation_summary     — aggregate counts by status.
list_all_platform           — platform-admin cross-account listing.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.corporate_fleet_vehicle import CorporateFleetVehicle
from app.models.corporate_vehicle_reservation import (
    CorporateVehicleReservation,
    ReservationStatus,
)
from app.schemas.corporate_vehicle_reservation import (
    VehicleAvailabilityResponse,
    VehicleReservationCancel,
    VehicleReservationCreate,
    VehicleReservationResponse,
    VehicleReservationSummaryResponse,
    VehicleReservationUpdate,
)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_ACTIVE_STATUSES = (ReservationStatus.pending, ReservationStatus.confirmed)


def _to_response(row: CorporateVehicleReservation) -> VehicleReservationResponse:
    return VehicleReservationResponse.model_validate(row)


async def _fetch_vehicle(
    db: AsyncSession,
    account_id: int,
    fleet_vehicle_id: uuid.UUID,
) -> CorporateFleetVehicle:
    """Return a fleet vehicle verifying account ownership.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        fleet_vehicle_id: UUID of the fleet vehicle.

    Returns:
        ``CorporateFleetVehicle`` ORM instance.

    Raises:
        HTTPException 404: Vehicle not found or does not belong to this account.
    """
    stmt = select(CorporateFleetVehicle).where(
        CorporateFleetVehicle.id == fleet_vehicle_id,
        CorporateFleetVehicle.account_id == account_id,
    )
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Fleet vehicle not found for this account.",
        )
    return row


async def _fetch_reservation(
    db: AsyncSession,
    account_id: int,
    reservation_id: uuid.UUID,
) -> CorporateVehicleReservation:
    """Return a reservation verifying account ownership.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        reservation_id: UUID of the reservation.

    Returns:
        ``CorporateVehicleReservation`` ORM instance.

    Raises:
        HTTPException 404: Reservation not found or wrong account.
    """
    stmt = select(CorporateVehicleReservation).where(
        CorporateVehicleReservation.id == reservation_id,
        CorporateVehicleReservation.account_id == account_id,
    )
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Reservation not found.",
        )
    return row


async def _check_overlap(
    db: AsyncSession,
    fleet_vehicle_id: uuid.UUID,
    start_time: datetime,
    end_time: datetime,
    exclude_id: Optional[uuid.UUID] = None,
) -> list[CorporateVehicleReservation]:
    """Return conflicting reservations for a vehicle time window.

    Two reservations conflict when:
      existing.start_time < new.end_time AND existing.end_time > new.start_time
    and the existing reservation is in an active status (pending or confirmed).

    Args:
        db: Async SQLAlchemy session.
        fleet_vehicle_id: UUID of the vehicle to check.
        start_time: Proposed window start.
        end_time: Proposed window end.
        exclude_id: Reservation UUID to exclude (used during update).

    Returns:
        List of conflicting ``CorporateVehicleReservation`` rows.
    """
    conditions = [
        CorporateVehicleReservation.fleet_vehicle_id == fleet_vehicle_id,
        CorporateVehicleReservation.status.in_(_ACTIVE_STATUSES),
        CorporateVehicleReservation.start_time < end_time,
        CorporateVehicleReservation.end_time > start_time,
    ]
    if exclude_id is not None:
        conditions.append(CorporateVehicleReservation.id != exclude_id)

    stmt = select(CorporateVehicleReservation).where(and_(*conditions))
    result = await db.execute(stmt)
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# create_reservation
# ---------------------------------------------------------------------------


async def create_reservation(
    db: AsyncSession,
    account_id: int,
    reserved_by_id: Optional[int],
    data: VehicleReservationCreate,
) -> VehicleReservationResponse:
    """Create a new vehicle reservation for a corporate account.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        reserved_by_id: ID of the user making the reservation.
        data: Reservation creation payload.

    Returns:
        ``VehicleReservationResponse`` for the new reservation.

    Raises:
        HTTPException 404: Fleet vehicle not found for this account.
        HTTPException 409: Fleet vehicle is inactive.
        HTTPException 409: Vehicle already reserved for the requested window.
    """
    vehicle = await _fetch_vehicle(db, account_id, data.fleet_vehicle_id)

    if not vehicle.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Fleet vehicle is not active and cannot be reserved.",
        )

    conflicts = await _check_overlap(
        db, data.fleet_vehicle_id, data.start_time, data.end_time
    )
    if conflicts:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Vehicle already reserved for this time window.",
        )

    reservation = CorporateVehicleReservation(
        id=uuid.uuid4(),
        account_id=account_id,
        fleet_vehicle_id=data.fleet_vehicle_id,
        reserved_by_id=reserved_by_id,
        approved_by_id=None,
        start_time=data.start_time,
        end_time=data.end_time,
        purpose=data.purpose,
        pickup_location=data.pickup_location,
        dropoff_location=data.dropoff_location,
        notes=data.notes,
        trip_purpose_id=data.trip_purpose_id,
        cost_center_id=data.cost_center_id,
        status=ReservationStatus.pending,
    )
    db.add(reservation)
    await db.commit()
    await db.refresh(reservation)
    return _to_response(reservation)


# ---------------------------------------------------------------------------
# get_reservation
# ---------------------------------------------------------------------------


async def get_reservation(
    db: AsyncSession,
    account_id: int,
    reservation_id: uuid.UUID,
) -> VehicleReservationResponse:
    """Return a single reservation.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        reservation_id: UUID of the reservation.

    Returns:
        ``VehicleReservationResponse``.

    Raises:
        HTTPException 404: Reservation not found or wrong account.
    """
    row = await _fetch_reservation(db, account_id, reservation_id)
    return _to_response(row)


# ---------------------------------------------------------------------------
# list_reservations
# ---------------------------------------------------------------------------


async def list_reservations(
    db: AsyncSession,
    account_id: int,
    *,
    fleet_vehicle_id: Optional[uuid.UUID] = None,
    reserved_by_id: Optional[int] = None,
    status: Optional[ReservationStatus] = None,
    from_time: Optional[datetime] = None,
    to_time: Optional[datetime] = None,
    skip: int = 0,
    limit: int = 50,
) -> list[VehicleReservationResponse]:
    """Return a filtered, paginated list of reservations for an account.

    Results are ordered by start_time descending (newest first).

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        fleet_vehicle_id: Optional filter by vehicle UUID.
        reserved_by_id: Optional filter by reserving user ID.
        status: Optional filter by reservation status.
        from_time: Optional filter: start_time >= from_time.
        to_time: Optional filter: start_time <= to_time.
        skip: Records to skip (default 0).
        limit: Max records to return (default 50).

    Returns:
        List of ``VehicleReservationResponse``.
    """
    conditions = [CorporateVehicleReservation.account_id == account_id]
    if fleet_vehicle_id is not None:
        conditions.append(CorporateVehicleReservation.fleet_vehicle_id == fleet_vehicle_id)
    if reserved_by_id is not None:
        conditions.append(CorporateVehicleReservation.reserved_by_id == reserved_by_id)
    if status is not None:
        conditions.append(CorporateVehicleReservation.status == status)
    if from_time is not None:
        conditions.append(CorporateVehicleReservation.start_time >= from_time)
    if to_time is not None:
        conditions.append(CorporateVehicleReservation.start_time <= to_time)

    stmt = (
        select(CorporateVehicleReservation)
        .where(and_(*conditions))
        .order_by(CorporateVehicleReservation.start_time.desc())
        .offset(skip)
        .limit(limit)
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return [_to_response(r) for r in rows]


# ---------------------------------------------------------------------------
# list_member_reservations
# ---------------------------------------------------------------------------


async def list_member_reservations(
    db: AsyncSession,
    account_id: int,
    reserved_by_id: int,
    *,
    skip: int = 0,
    limit: int = 50,
) -> list[VehicleReservationResponse]:
    """Return reservations made by a specific user, newest first.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        reserved_by_id: ID of the user whose reservations to return.
        skip: Records to skip (default 0).
        limit: Max records to return (default 50).

    Returns:
        List of ``VehicleReservationResponse``.
    """
    stmt = (
        select(CorporateVehicleReservation)
        .where(
            CorporateVehicleReservation.account_id == account_id,
            CorporateVehicleReservation.reserved_by_id == reserved_by_id,
        )
        .order_by(CorporateVehicleReservation.start_time.desc())
        .offset(skip)
        .limit(limit)
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return [_to_response(r) for r in rows]


# ---------------------------------------------------------------------------
# update_reservation
# ---------------------------------------------------------------------------


async def update_reservation(
    db: AsyncSession,
    account_id: int,
    reservation_id: uuid.UUID,
    data: VehicleReservationUpdate,
) -> VehicleReservationResponse:
    """Partially update a pending reservation.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        reservation_id: UUID of the reservation.
        data: Fields to update (None values are ignored).

    Returns:
        Updated ``VehicleReservationResponse``.

    Raises:
        HTTPException 404: Reservation not found.
        HTTPException 409: Only pending reservations can be updated.
        HTTPException 409: Vehicle already reserved for the new time window.
    """
    row = await _fetch_reservation(db, account_id, reservation_id)

    if row.status != ReservationStatus.pending:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only pending reservations can be updated.",
        )

    update_data = data.model_dump(exclude_none=True)

    # Determine effective times for overlap check
    new_start = update_data.get("start_time", row.start_time)
    new_end = update_data.get("end_time", row.end_time)

    if "start_time" in update_data or "end_time" in update_data:
        conflicts = await _check_overlap(
            db, row.fleet_vehicle_id, new_start, new_end, exclude_id=reservation_id
        )
        if conflicts:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Vehicle already reserved for this time window.",
            )

    for field, value in update_data.items():
        setattr(row, field, value)

    await db.commit()
    await db.refresh(row)
    return _to_response(row)


# ---------------------------------------------------------------------------
# confirm_reservation
# ---------------------------------------------------------------------------


async def confirm_reservation(
    db: AsyncSession,
    account_id: int,
    reservation_id: uuid.UUID,
    approved_by_id: int,
) -> VehicleReservationResponse:
    """Confirm a pending reservation.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        reservation_id: UUID of the reservation.
        approved_by_id: ID of the admin confirming the reservation.

    Returns:
        Updated ``VehicleReservationResponse``.

    Raises:
        HTTPException 404: Reservation not found.
        HTTPException 409: Only pending reservations can be confirmed.
    """
    row = await _fetch_reservation(db, account_id, reservation_id)

    if row.status != ReservationStatus.pending:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only pending reservations can be confirmed.",
        )

    row.status = ReservationStatus.confirmed
    row.approved_by_id = approved_by_id
    await db.commit()
    await db.refresh(row)
    return _to_response(row)


# ---------------------------------------------------------------------------
# cancel_reservation
# ---------------------------------------------------------------------------


async def cancel_reservation(
    db: AsyncSession,
    account_id: int,
    reservation_id: uuid.UUID,
    cancelled_by_id: int,
    data: VehicleReservationCancel,
) -> VehicleReservationResponse:
    """Cancel a reservation.

    A reservation in completed or no_show status cannot be cancelled.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        reservation_id: UUID of the reservation.
        cancelled_by_id: ID of the user performing the cancellation.
        data: Cancellation payload (optional reason).

    Returns:
        Updated ``VehicleReservationResponse``.

    Raises:
        HTTPException 404: Reservation not found.
        HTTPException 409: Completed or no-show reservations cannot be cancelled.
    """
    row = await _fetch_reservation(db, account_id, reservation_id)

    if row.status in (ReservationStatus.completed, ReservationStatus.no_show):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Completed or no-show reservations cannot be cancelled.",
        )

    row.status = ReservationStatus.cancelled
    row.cancelled_at = datetime.now(tz=timezone.utc)
    row.cancelled_by_id = cancelled_by_id
    row.cancellation_reason = data.cancellation_reason
    await db.commit()
    await db.refresh(row)
    return _to_response(row)


# ---------------------------------------------------------------------------
# complete_reservation
# ---------------------------------------------------------------------------


async def complete_reservation(
    db: AsyncSession,
    account_id: int,
    reservation_id: uuid.UUID,
) -> VehicleReservationResponse:
    """Mark a confirmed reservation as completed.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        reservation_id: UUID of the reservation.

    Returns:
        Updated ``VehicleReservationResponse``.

    Raises:
        HTTPException 404: Reservation not found.
        HTTPException 409: Only confirmed reservations can be completed.
    """
    row = await _fetch_reservation(db, account_id, reservation_id)

    if row.status != ReservationStatus.confirmed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only confirmed reservations can be completed.",
        )

    row.status = ReservationStatus.completed
    await db.commit()
    await db.refresh(row)
    return _to_response(row)


# ---------------------------------------------------------------------------
# no_show_reservation
# ---------------------------------------------------------------------------


async def no_show_reservation(
    db: AsyncSession,
    account_id: int,
    reservation_id: uuid.UUID,
) -> VehicleReservationResponse:
    """Mark a confirmed reservation as a no-show.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        reservation_id: UUID of the reservation.

    Returns:
        Updated ``VehicleReservationResponse``.

    Raises:
        HTTPException 404: Reservation not found.
        HTTPException 409: Only confirmed reservations can be marked no-show.
    """
    row = await _fetch_reservation(db, account_id, reservation_id)

    if row.status != ReservationStatus.confirmed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only confirmed reservations can be marked as no-show.",
        )

    row.status = ReservationStatus.no_show
    await db.commit()
    await db.refresh(row)
    return _to_response(row)


# ---------------------------------------------------------------------------
# check_vehicle_availability
# ---------------------------------------------------------------------------


async def check_vehicle_availability(
    db: AsyncSession,
    account_id: int,
    fleet_vehicle_id: uuid.UUID,
    start_time: datetime,
    end_time: datetime,
) -> VehicleAvailabilityResponse:
    """Check whether a vehicle is available for a given time window.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        fleet_vehicle_id: UUID of the vehicle to check.
        start_time: Window start.
        end_time: Window end.

    Returns:
        ``VehicleAvailabilityResponse`` with is_available and any conflicts.

    Raises:
        HTTPException 404: Fleet vehicle not found for this account.
    """
    await _fetch_vehicle(db, account_id, fleet_vehicle_id)

    conflicts = await _check_overlap(db, fleet_vehicle_id, start_time, end_time)
    return VehicleAvailabilityResponse(
        fleet_vehicle_id=fleet_vehicle_id,
        is_available=len(conflicts) == 0,
        conflicts=[_to_response(c) for c in conflicts],
    )


# ---------------------------------------------------------------------------
# get_reservation_summary
# ---------------------------------------------------------------------------


async def get_reservation_summary(
    db: AsyncSession,
    account_id: int,
) -> VehicleReservationSummaryResponse:
    """Return aggregate reservation counts by status for a corporate account.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.

    Returns:
        ``VehicleReservationSummaryResponse`` with counts per status.
    """
    stmt = select(CorporateVehicleReservation).where(
        CorporateVehicleReservation.account_id == account_id
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()

    counts: dict[str, int] = {s.value: 0 for s in ReservationStatus}
    for row in rows:
        counts[row.status.value] += 1

    return VehicleReservationSummaryResponse(
        total=len(rows),
        pending=counts["pending"],
        confirmed=counts["confirmed"],
        cancelled=counts["cancelled"],
        completed=counts["completed"],
        no_show=counts["no_show"],
    )


# ---------------------------------------------------------------------------
# list_all_platform
# ---------------------------------------------------------------------------


async def list_all_platform(
    db: AsyncSession,
    *,
    account_id: Optional[int] = None,
    skip: int = 0,
    limit: int = 100,
) -> list[VehicleReservationResponse]:
    """Return reservations across all corporate accounts (platform admin).

    Args:
        db: Async SQLAlchemy session.
        account_id: Optional filter to a specific account.
        skip: Records to skip (default 0).
        limit: Max records to return (default 100).

    Returns:
        List of ``VehicleReservationResponse``.
    """
    conditions = []
    if account_id is not None:
        conditions.append(CorporateVehicleReservation.account_id == account_id)

    base = select(CorporateVehicleReservation)
    if conditions:
        base = base.where(and_(*conditions))

    stmt = (
        base.order_by(
            CorporateVehicleReservation.account_id,
            CorporateVehicleReservation.start_time.desc(),
        )
        .offset(skip)
        .limit(limit)
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return [_to_response(r) for r in rows]
