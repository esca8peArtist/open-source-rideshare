"""Scheduled rides API endpoints.

Rider-facing:
  POST   /riders/me/scheduled-rides              — create an advance booking
  GET    /riders/me/scheduled-rides              — list rider's bookings
  GET    /riders/me/scheduled-rides/{id}         — get a single booking
  DELETE /riders/me/scheduled-rides/{id}         — cancel a booking

Driver-facing:
  GET    /drivers/me/scheduled-rides             — list pending + assigned rides
  POST   /drivers/me/scheduled-rides/{id}/accept — accept a pending booking
  POST   /drivers/me/scheduled-rides/{id}/decline — decline an assigned booking

Admin:
  GET    /admin/scheduled-rides                  — list all rides with summary stats
"""

from __future__ import annotations

import logging
from datetime import timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.models.scheduled_ride import CancelledBy, ScheduledRideStatus
from app.models.user import User
from app.schemas.scheduled_ride import (
    AdminScheduledRideSummary,
    ScheduledRideAcceptResponse,
    ScheduledRideCancelRequest,
    ScheduledRideCancelResponse,
    ScheduledRideCreateRequest,
    ScheduledRideDeclineResponse,
    ScheduledRideListResponse,
    ScheduledRideResponse,
)
from app.services.scheduled_ride import (
    DEFAULT_PAGE_SIZE,
    cancel_scheduled_ride,
    create_scheduled_ride,
    driver_accept_scheduled_ride,
    driver_decline_scheduled_ride,
    get_admin_summary,
    get_scheduled_ride,
    list_driver_scheduled_rides,
    list_rider_scheduled_rides,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["scheduled-rides"])


# ---------------------------------------------------------------------------
# Rider endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/riders/me/scheduled-rides",
    response_model=ScheduledRideResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an advance ride booking",
)
async def create_booking(
    req: ScheduledRideCreateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Book a ride for a specific future date and time.

    - **scheduled_for**: UTC datetime for pickup; must be ≥ 30 minutes and
      ≤ 30 days from now.
    - **notes**: Optional message to the driver (e.g. flight number, terminal).
    - **estimated_fare**: Optional fare hint; the platform may recalculate at
      dispatch time.

    The booking starts in **pending** status.  Drivers may voluntarily accept it,
    or the platform will auto-assign a driver as the scheduled time approaches.
    """
    # Normalise to UTC
    scheduled_for = req.scheduled_for
    if scheduled_for.tzinfo is None:
        scheduled_for = scheduled_for.replace(tzinfo=timezone.utc)

    ride, err = await create_scheduled_ride(
        db,
        rider_id=user.id,
        pickup_lat=req.pickup_lat,
        pickup_lon=req.pickup_lon,
        pickup_address=req.pickup_address,
        dropoff_lat=req.dropoff_lat,
        dropoff_lon=req.dropoff_lon,
        dropoff_address=req.dropoff_address,
        scheduled_for=scheduled_for,
        estimated_fare=req.estimated_fare,
        notes=req.notes,
    )
    if err:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=err)
    return ride


@router.get(
    "/riders/me/scheduled-rides",
    response_model=ScheduledRideListResponse,
    summary="List the authenticated rider's scheduled ride bookings",
)
async def list_my_bookings(
    ride_status: ScheduledRideStatus | None = Query(
        None, alias="status", description="Filter by status"
    ),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a paginated list of the rider's advance bookings.

    Optionally filter by **status** (`pending`, `driver_assigned`,
    `in_progress`, `completed`, `cancelled`).
    """
    items, total = await list_rider_scheduled_rides(
        db,
        user.id,
        status=ride_status,
        page=page,
        page_size=page_size,
    )
    return ScheduledRideListResponse(
        items=list(items),
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/riders/me/scheduled-rides/{ride_id}",
    response_model=ScheduledRideResponse,
    summary="Get a single scheduled ride booking",
)
async def get_my_booking(
    ride_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Fetch detailed information about a specific scheduled ride booking."""
    ride = await get_scheduled_ride(db, ride_id)
    if ride is None or ride.rider_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Scheduled ride not found.",
        )
    return ride


@router.delete(
    "/riders/me/scheduled-rides/{ride_id}",
    response_model=ScheduledRideCancelResponse,
    summary="Cancel a scheduled ride booking",
)
async def cancel_my_booking(
    ride_id: int,
    req: ScheduledRideCancelRequest | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Cancel a pending or driver-assigned booking.

    Cancellation is not allowed once the ride is **in_progress** or already
    **completed** / **cancelled**.
    """
    # Verify ownership before attempting cancellation.
    ride = await get_scheduled_ride(db, ride_id)
    if ride is None or ride.rider_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Scheduled ride not found.",
        )

    reason = req.reason if req else None
    updated_ride, err = await cancel_scheduled_ride(
        db,
        ride_id,
        cancelled_by=CancelledBy.RIDER,
        reason=reason,
    )
    if err:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=err)

    return ScheduledRideCancelResponse(
        scheduled_ride_id=ride_id,
        cancelled=True,
        cancelled_by=CancelledBy.RIDER,
        message="Booking cancelled successfully.",
    )


# ---------------------------------------------------------------------------
# Driver endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/drivers/me/scheduled-rides",
    response_model=ScheduledRideListResponse,
    summary="List available and assigned scheduled rides",
)
async def list_driver_bookings(
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return scheduled rides that are either pending (available to accept)
    or already assigned to this driver.

    Use this endpoint to browse upcoming bookings and plan your schedule.
    """
    items, total = await list_driver_scheduled_rides(
        db, user.id, page=page, page_size=page_size
    )
    return ScheduledRideListResponse(
        items=list(items),
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post(
    "/drivers/me/scheduled-rides/{ride_id}/accept",
    response_model=ScheduledRideAcceptResponse,
    summary="Accept a pending scheduled ride booking",
)
async def accept_booking(
    ride_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Claim a pending scheduled ride booking.

    Once accepted the booking status becomes **driver_assigned** and other
    drivers can no longer accept it.  The driver may still decline the booking
    before it is dispatched.
    """
    ride, err = await driver_accept_scheduled_ride(db, ride_id, user.id)
    if err:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=err,
        )
    return ScheduledRideAcceptResponse(
        scheduled_ride_id=ride_id,
        status=ride.status,
        message="Booking accepted. You are now assigned to this scheduled ride.",
    )


@router.post(
    "/drivers/me/scheduled-rides/{ride_id}/decline",
    response_model=ScheduledRideDeclineResponse,
    summary="Decline an assigned scheduled ride booking",
)
async def decline_booking(
    ride_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Decline a booking you previously accepted.

    The ride returns to **pending** status so another driver can accept it.
    The decline count is incremented for platform visibility.
    """
    ride, err = await driver_decline_scheduled_ride(db, ride_id, user.id)
    if err:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=err,
        )
    return ScheduledRideDeclineResponse(
        scheduled_ride_id=ride_id,
        status=ride.status,
        decline_count=ride.decline_count,
        message="Booking declined. It has been returned to the pending pool.",
    )


# ---------------------------------------------------------------------------
# Admin endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/admin/scheduled-rides",
    response_model=ScheduledRideListResponse,
    summary="Admin: list all scheduled rides",
)
async def admin_list_rides(
    ride_status: ScheduledRideStatus | None = Query(None, alias="status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=100),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Admin-only view of all scheduled ride bookings across all riders.

    Supports filtering by status and pagination.
    """
    from sqlalchemy import select, func as sa_func
    from app.models.scheduled_ride import ScheduledRide

    q = select(ScheduledRide)
    if ride_status is not None:
        q = q.where(ScheduledRide.status == ride_status)

    count_result = await db.execute(
        select(sa_func.count()).select_from(q.subquery())
    )
    total = count_result.scalar_one()

    q = q.order_by(ScheduledRide.scheduled_for.asc())
    q = q.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(q)
    items = result.scalars().all()

    return ScheduledRideListResponse(
        items=list(items),
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/admin/scheduled-rides/summary",
    response_model=AdminScheduledRideSummary,
    summary="Admin: aggregate status counts for scheduled rides",
)
async def admin_summary(
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return aggregate counts of scheduled rides broken down by status.

    Useful for the admin dashboard to monitor the health of the advance
    booking queue.
    """
    counts = await get_admin_summary(db)
    return AdminScheduledRideSummary(**counts)
