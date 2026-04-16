"""Corporate Vehicle Reservation Booking endpoints.

Employees can reserve company fleet vehicles for self-drive use during
specified time windows — like an internal Zipcar.

Member endpoints (any authenticated account member):
  POST /corporate/{account_id}/vehicle-reservations/                      — create → 201
  GET  /corporate/{account_id}/vehicle-reservations/                      — list
  GET  /corporate/{account_id}/vehicle-reservations/my                    — my reservations
  GET  /corporate/{account_id}/vehicle-reservations/summary               — summary stats
  GET  /corporate/{account_id}/vehicle-reservations/{reservation_id}      — get one
  POST /corporate/{account_id}/vehicle-reservations/{reservation_id}/cancel — cancel own

Admin endpoints (account admins only):
  PUT  /corporate/{account_id}/vehicle-reservations/{reservation_id}         — update
  POST /corporate/{account_id}/vehicle-reservations/{reservation_id}/confirm  — confirm
  POST /corporate/{account_id}/vehicle-reservations/{reservation_id}/complete — complete
  POST /corporate/{account_id}/vehicle-reservations/{reservation_id}/no-show  — no-show
  GET  /corporate/{account_id}/fleet-vehicles/{vehicle_id}/availability       — check availability

Platform-admin endpoints:
  GET /platform/corporate/vehicle-reservations/              — all reservations
  GET /platform/corporate/vehicle-reservations/{account_id}  — for one account
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.models.corporate_vehicle_reservation import ReservationStatus
from app.models.user import User
from app.schemas.corporate_vehicle_reservation import (
    VehicleAvailabilityResponse,
    VehicleReservationCancel,
    VehicleReservationCreate,
    VehicleReservationResponse,
    VehicleReservationSummaryResponse,
    VehicleReservationUpdate,
)
from app.services.corporate_account_mgmt import get_account
from app.services.corporate_trip_purpose import _require_account_admin
from app.services.corporate_vehicle_reservation_service import (
    cancel_reservation,
    check_vehicle_availability,
    complete_reservation,
    confirm_reservation,
    create_reservation,
    get_reservation,
    get_reservation_summary,
    list_all_platform,
    list_member_reservations,
    list_reservations,
    no_show_reservation,
    update_reservation,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Corporate Vehicle Reservations"])


# ---------------------------------------------------------------------------
# Member: create reservation
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/{account_id}/vehicle-reservations/",
    response_model=VehicleReservationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a vehicle reservation",
)
async def create_reservation_endpoint(
    account_id: int,
    data: VehicleReservationCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Reserve a fleet vehicle for a specified time window.

    Returns 404 if the vehicle does not exist in this account.
    Returns 409 if the vehicle is inactive or the time window overlaps an existing reservation.
    """
    await get_account(db, account_id)
    return await create_reservation(db, account_id, user.id, data)


# ---------------------------------------------------------------------------
# Member: list reservations  ← MUST be before /{reservation_id}
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/vehicle-reservations/",
    response_model=List[VehicleReservationResponse],
    summary="List vehicle reservations for a corporate account",
)
async def list_reservations_endpoint(
    account_id: int,
    fleet_vehicle_id: Optional[uuid.UUID] = Query(None, description="Filter by vehicle UUID"),
    status: Optional[ReservationStatus] = Query(None, description="Filter by status"),
    from_time: Optional[datetime] = Query(None, description="Filter: start_time >= from_time"),
    to_time: Optional[datetime] = Query(None, description="Filter: start_time <= to_time"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a paginated list of vehicle reservations for the account.

    Any authenticated user may call this endpoint.
    """
    await get_account(db, account_id)
    return await list_reservations(
        db,
        account_id,
        fleet_vehicle_id=fleet_vehicle_id,
        status=status,
        from_time=from_time,
        to_time=to_time,
        skip=skip,
        limit=limit,
    )


# ---------------------------------------------------------------------------
# Member: my reservations  ← MUST be before /{reservation_id}
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/vehicle-reservations/my",
    response_model=List[VehicleReservationResponse],
    summary="List my vehicle reservations",
)
async def list_my_reservations_endpoint(
    account_id: int,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the calling user's reservations for this account, newest first."""
    await get_account(db, account_id)
    return await list_member_reservations(db, account_id, user.id, skip=skip, limit=limit)


# ---------------------------------------------------------------------------
# Member: summary  ← MUST be before /{reservation_id}
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/vehicle-reservations/summary",
    response_model=VehicleReservationSummaryResponse,
    summary="Get vehicle reservation summary statistics",
)
async def get_reservation_summary_endpoint(
    account_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return aggregate reservation counts by status for the account.

    Any authenticated user may call this endpoint.
    """
    await get_account(db, account_id)
    return await get_reservation_summary(db, account_id)


# ---------------------------------------------------------------------------
# Member: get one reservation
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/vehicle-reservations/{reservation_id}",
    response_model=VehicleReservationResponse,
    summary="Get a single vehicle reservation",
)
async def get_reservation_endpoint(
    account_id: int,
    reservation_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return details for a single reservation.

    Returns 404 if the reservation does not exist or belongs to a different account.
    """
    await get_account(db, account_id)
    return await get_reservation(db, account_id, reservation_id)


# ---------------------------------------------------------------------------
# Member: cancel own reservation
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/{account_id}/vehicle-reservations/{reservation_id}/cancel",
    response_model=VehicleReservationResponse,
    summary="Cancel a vehicle reservation",
)
async def cancel_reservation_endpoint(
    account_id: int,
    reservation_id: uuid.UUID,
    data: VehicleReservationCancel = VehicleReservationCancel(),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Cancel a vehicle reservation.

    Members may only cancel their own reservations.  Account admins may cancel
    any reservation in the account.
    Returns 409 if the reservation is already completed or a no-show.
    """
    await get_account(db, account_id)
    reservation = await get_reservation(db, account_id, reservation_id)

    # Check ownership — admin check by attempting _require_account_admin
    is_admin = False
    try:
        await _require_account_admin(db, account_id, user.id)
        is_admin = True
    except HTTPException:
        pass

    if not is_admin and reservation.reserved_by_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only cancel your own reservations.",
        )

    return await cancel_reservation(db, account_id, reservation_id, user.id, data)


# ---------------------------------------------------------------------------
# Admin: update reservation
# ---------------------------------------------------------------------------


@router.put(
    "/corporate/{account_id}/vehicle-reservations/{reservation_id}",
    response_model=VehicleReservationResponse,
    summary="Update a pending vehicle reservation (admin only)",
)
async def update_reservation_endpoint(
    account_id: int,
    reservation_id: uuid.UUID,
    data: VehicleReservationUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Partially update a pending reservation.

    Returns 409 if the reservation is not in pending status or if the new
    time window conflicts with another reservation.
    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    return await update_reservation(db, account_id, reservation_id, data)


# ---------------------------------------------------------------------------
# Admin: confirm reservation
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/{account_id}/vehicle-reservations/{reservation_id}/confirm",
    response_model=VehicleReservationResponse,
    summary="Confirm a pending vehicle reservation (admin only)",
)
async def confirm_reservation_endpoint(
    account_id: int,
    reservation_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Confirm a pending vehicle reservation.

    Returns 409 if the reservation is not pending.
    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    return await confirm_reservation(db, account_id, reservation_id, user.id)


# ---------------------------------------------------------------------------
# Admin: complete reservation
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/{account_id}/vehicle-reservations/{reservation_id}/complete",
    response_model=VehicleReservationResponse,
    summary="Complete a confirmed vehicle reservation (admin only)",
)
async def complete_reservation_endpoint(
    account_id: int,
    reservation_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Mark a confirmed reservation as completed.

    Returns 409 if the reservation is not confirmed.
    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    return await complete_reservation(db, account_id, reservation_id)


# ---------------------------------------------------------------------------
# Admin: no-show reservation
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/{account_id}/vehicle-reservations/{reservation_id}/no-show",
    response_model=VehicleReservationResponse,
    summary="Mark a vehicle reservation as no-show (admin only)",
)
async def no_show_reservation_endpoint(
    account_id: int,
    reservation_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Mark a confirmed reservation as a no-show.

    Returns 409 if the reservation is not confirmed.
    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    return await no_show_reservation(db, account_id, reservation_id)


# ---------------------------------------------------------------------------
# Admin: check vehicle availability
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/fleet-vehicles/{vehicle_id}/availability",
    response_model=VehicleAvailabilityResponse,
    summary="Check fleet vehicle availability for a time window (admin only)",
)
async def check_availability_endpoint(
    account_id: int,
    vehicle_id: uuid.UUID,
    start_time: datetime = Query(..., description="Window start (ISO 8601 with timezone)"),
    end_time: datetime = Query(..., description="Window end (ISO 8601 with timezone)"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return whether a fleet vehicle is available for the requested window.

    Returns a list of conflicting reservations if the vehicle is unavailable.
    Only account admins may call this endpoint.
    """
    await get_account(db, account_id)
    await _require_account_admin(db, account_id, user.id)
    return await check_vehicle_availability(
        db, account_id, vehicle_id, start_time, end_time
    )


# ---------------------------------------------------------------------------
# Platform-admin: list all reservations
# ---------------------------------------------------------------------------


@router.get(
    "/platform/corporate/vehicle-reservations/",
    response_model=List[VehicleReservationResponse],
    summary="Admin: list all corporate vehicle reservations across all accounts",
)
async def admin_list_reservations(
    account_id: Optional[int] = Query(None, description="Filter by corporate account ID"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return vehicle reservations across all corporate accounts.

    Platform admin only.  Optionally filter by account_id.
    """
    return await list_all_platform(db, account_id=account_id, skip=skip, limit=limit)


# ---------------------------------------------------------------------------
# Platform-admin: list reservations for one account
# ---------------------------------------------------------------------------


@router.get(
    "/platform/corporate/vehicle-reservations/{account_id}",
    response_model=List[VehicleReservationResponse],
    summary="Admin: list vehicle reservations for a specific corporate account",
)
async def admin_list_account_reservations(
    account_id: int,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return vehicle reservations for a specific corporate account.

    Platform admin only.
    """
    return await list_all_platform(db, account_id=account_id, skip=skip, limit=limit)
