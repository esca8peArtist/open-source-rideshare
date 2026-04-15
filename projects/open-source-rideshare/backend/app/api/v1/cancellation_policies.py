"""Ride cancellation policy and fee API endpoints.

Rider endpoints:
  POST /rides/{ride_id}/cancel              — rider cancels a booked ride
  GET  /riders/me/cancellations             — rider's own cancellation history

Driver endpoints:
  POST /drivers/me/rides/{ride_id}/cancel   — driver cancels their current ride
  GET  /drivers/me/cancellations            — driver's own cancellation history

Admin endpoints:
  GET  /admin/cancellation-policy           — get active policy
  POST /admin/cancellation-policy           — create/update policy (upsert)
  GET  /admin/cancellations                 — list all with optional fee_status filter
  POST /admin/cancellations/{id}/waive      — waive a fee with reason
  GET  /admin/cancellations/summary         — aggregate stats
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_admin, require_driver
from app.db.database import get_db
from app.models.cancellation import (
    CancelledBy,
    CancellationPolicy,
    CancellationRecord,
    FeeStatus,
)
from app.models.ride import Ride, RideStatus
from app.models.user import User
from app.schemas.cancellation import (
    CancellationPolicyCreate,
    CancellationPolicyResponse,
    CancellationRecordResponse,
    CancellationSummaryResponse,
    DriverCancelRequest,
    DriverCancelResponse,
    RiderCancelRequest,
    RiderCancelResponse,
    WaiveFeeRequest,
)
from app.services.cancellation import (
    CancellationError,
    admin_get_all,
    admin_get_summary,
    get_active_policy,
    record_cancellation,
    waive_fee,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["cancellation"])


def _http(exc: CancellationError) -> HTTPException:
    """Convert a service-layer CancellationError to an HTTPException."""
    return HTTPException(status_code=exc.status_code, detail=str(exc))


# ---------------------------------------------------------------------------
# Rider endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/rides/{ride_id}/cancel",
    response_model=RiderCancelResponse,
    status_code=status.HTTP_200_OK,
    summary="Rider cancels a ride",
)
async def rider_cancel_ride(
    ride_id: int,
    req: RiderCancelRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Rider cancels a booked ride.

    A cancellation fee may apply if the grace period has expired.
    Returns the fee amount and whether the grace period had lapsed.

    The ride must belong to the authenticated rider and must not already
    be cancelled, completed, or in progress.
    """
    result = await db.execute(select(Ride).where(Ride.id == ride_id))
    ride = result.scalar_one_or_none()
    if ride is None:
        raise HTTPException(status_code=404, detail="Ride not found")
    if ride.rider_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not the rider on this ride",
        )
    if ride.status in (RideStatus.CANCELLED, RideStatus.COMPLETED, RideStatus.IN_PROGRESS):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Ride cannot be cancelled in its current status: {ride.status.value}",
        )

    try:
        record = await record_cancellation(
            db,
            ride_id=ride_id,
            cancelled_by=CancelledBy.rider,
            reason=req.reason,
            estimated_fare=ride.estimated_fare,
            booking_time=ride.requested_at,
        )
    except CancellationError as exc:
        raise _http(exc)

    # Update the ride status
    ride.status = RideStatus.CANCELLED
    ride.cancellation_reason = req.reason

    await db.commit()
    await db.refresh(record)

    return RiderCancelResponse(
        message="Ride cancelled successfully",
        fee_applied=record.fee_applied,
        grace_expired=record.grace_period_expired,
        fee_status=record.fee_status,
        record_id=record.id,
    )


@router.get(
    "/riders/me/cancellations",
    response_model=list[CancellationRecordResponse],
    summary="Rider's own cancellation history",
)
async def rider_list_cancellations(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the authenticated rider's cancellation records, newest first.

    Only returns records where the rider was the cancelling party.
    """
    result = await db.execute(
        select(CancellationRecord)
        .join(Ride, Ride.id == CancellationRecord.ride_id)
        .where(
            Ride.rider_id == user.id,
            CancellationRecord.cancelled_by == CancelledBy.rider,
        )
        .order_by(CancellationRecord.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Driver endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/drivers/me/rides/{ride_id}/cancel",
    response_model=DriverCancelResponse,
    status_code=status.HTTP_200_OK,
    summary="Driver cancels a ride",
)
async def driver_cancel_ride(
    ride_id: int,
    req: DriverCancelRequest,
    driver: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    """Driver cancels a ride they are assigned to.

    A penalty may apply if the driver has exceeded their daily free
    cancellation limit. Returns the penalty amount.

    The ride must be assigned to the authenticated driver and must not
    already be cancelled, completed, or in progress.
    """
    result = await db.execute(select(Ride).where(Ride.id == ride_id))
    ride = result.scalar_one_or_none()
    if ride is None:
        raise HTTPException(status_code=404, detail="Ride not found")
    if ride.driver_id != driver.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not the driver assigned to this ride",
        )
    if ride.status in (RideStatus.CANCELLED, RideStatus.COMPLETED, RideStatus.IN_PROGRESS):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Ride cannot be cancelled in its current status: {ride.status.value}",
        )

    try:
        record = await record_cancellation(
            db,
            ride_id=ride_id,
            cancelled_by=CancelledBy.driver,
            reason=req.reason,
            estimated_fare=ride.estimated_fare,
            booking_time=ride.requested_at,
            driver_id=driver.id,
        )
    except CancellationError as exc:
        raise _http(exc)

    ride.status = RideStatus.CANCELLED
    ride.cancellation_reason = req.reason

    await db.commit()
    await db.refresh(record)

    return DriverCancelResponse(
        message="Ride cancelled successfully",
        fee_applied=record.fee_applied,
        fee_status=record.fee_status,
        record_id=record.id,
    )


@router.get(
    "/drivers/me/cancellations",
    response_model=list[CancellationRecordResponse],
    summary="Driver's own cancellation history",
)
async def driver_list_cancellations(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    driver: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    """Return the authenticated driver's cancellation records, newest first.

    Only returns records where the driver was the cancelling party.
    """
    result = await db.execute(
        select(CancellationRecord)
        .join(Ride, Ride.id == CancellationRecord.ride_id)
        .where(
            Ride.driver_id == driver.id,
            CancellationRecord.cancelled_by == CancelledBy.driver,
        )
        .order_by(CancellationRecord.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Admin endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/admin/cancellation-policy",
    response_model=CancellationPolicyResponse,
    summary="Admin: get active cancellation policy",
)
async def admin_get_policy(
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return the currently active cancellation policy.

    If no policy has been configured, returns the platform default values
    (not persisted to database).
    """
    return await get_active_policy(db)


@router.post(
    "/admin/cancellation-policy",
    response_model=CancellationPolicyResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Admin: create or update cancellation policy",
)
async def admin_upsert_policy(
    req: CancellationPolicyCreate,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Create a new cancellation policy (upsert — only one active at a time).

    Deactivates the current active policy and inserts a new one. Previous
    policies are preserved for audit purposes.
    """
    # Deactivate existing active policies
    existing_result = await db.execute(
        select(CancellationPolicy).where(CancellationPolicy.is_active == True)  # noqa: E712
    )
    for old_policy in existing_result.scalars().all():
        old_policy.is_active = False

    new_policy = CancellationPolicy(
        rider_grace_period_seconds=req.rider_grace_period_seconds,
        rider_fee_flat=req.rider_fee_flat,
        rider_fee_percent=req.rider_fee_percent,
        driver_free_cancels_per_day=req.driver_free_cancels_per_day,
        driver_cancel_penalty=req.driver_cancel_penalty,
        is_active=True,
    )
    db.add(new_policy)
    await db.commit()
    await db.refresh(new_policy)
    return new_policy


@router.get(
    "/admin/cancellations/summary",
    response_model=CancellationSummaryResponse,
    summary="Admin: aggregate cancellation statistics",
)
async def admin_cancellations_summary(
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return aggregate statistics: total fees, breakdown by status and party.

    Note: this route must be declared before /admin/cancellations/{record_id}/waive
    to avoid the literal "summary" being interpreted as a record_id path param.
    """
    return await admin_get_summary(db)


@router.get(
    "/admin/cancellations",
    response_model=list[CancellationRecordResponse],
    summary="Admin: list all cancellation records",
)
async def admin_list_cancellations(
    fee_status: FeeStatus | None = Query(None, description="Filter by fee status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return all cancellation records, optionally filtered by fee_status."""
    return await admin_get_all(db, skip=offset, limit=limit, fee_status_filter=fee_status)


@router.post(
    "/admin/cancellations/{record_id}/waive",
    response_model=CancellationRecordResponse,
    summary="Admin: waive a cancellation fee",
)
async def admin_waive_cancellation_fee(
    record_id: int,
    req: WaiveFeeRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Admin waives the fee on a cancellation record.

    Sets fee_status to 'waived' and records the admin and reason.
    Returns 409 if the fee is already waived or refunded.
    """
    try:
        record = await waive_fee(
            db,
            cancellation_record_id=record_id,
            admin_id=admin.id,
            reason=req.reason,
        )
    except CancellationError as exc:
        raise _http(exc)

    await db.commit()
    await db.refresh(record)
    return record
