"""Service layer for Corporate Batch/Group Booking.

Companies can create a batch booking (DRAFT), add individual ride requests,
then submit the batch.  Admins may also cancel a batch at any stage.

All write operations require the requesting user to be an active admin of the
corporate account.  Read operations are available to any active member.

Public surface
--------------
create_batch(db, account_id, requesting_user_id, data)
get_batch(db, account_id, batch_id, requesting_user_id)
list_batches(db, account_id, requesting_user_id, status_filter=None)
update_batch(db, account_id, batch_id, requesting_user_id, data)
add_ride_request(db, account_id, batch_id, requesting_user_id, data)
remove_ride_request(db, account_id, batch_id, request_id, requesting_user_id)
submit_batch(db, account_id, batch_id, requesting_user_id)
cancel_batch(db, account_id, batch_id, requesting_user_id, reason=None)
get_batch_with_requests(db, account_id, batch_id, requesting_user_id)
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.corporate import BusinessAccountMember, MemberRole
from app.models.corporate_batch_booking import (
    BatchBookingStatus,
    BatchRideRequestStatus,
    CorporateBatchBooking,
    CorporateBatchRideRequest,
)
from app.schemas.corporate_batch_booking import (
    BatchBookingCreate,
    BatchBookingUpdate,
    BatchRideRequestCreate,
)

_BATCH_CAPACITY = 50


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _require_account_admin(
    db: AsyncSession, account_id: int, user_id: int
) -> BusinessAccountMember:
    """Raise HTTP 403 when the user is not an active admin of the account."""
    result = await db.execute(
        select(BusinessAccountMember).where(
            BusinessAccountMember.account_id == account_id,
            BusinessAccountMember.user_id == user_id,
            BusinessAccountMember.role == MemberRole.ADMIN,
            BusinessAccountMember.is_active.is_(True),
        )
    )
    member = result.scalar_one_or_none()
    if member is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have admin access to this corporate account.",
        )
    return member


async def _require_account_member(
    db: AsyncSession, account_id: int, user_id: int
) -> BusinessAccountMember:
    """Raise HTTP 403 when the user is not an active member of the account."""
    result = await db.execute(
        select(BusinessAccountMember).where(
            BusinessAccountMember.account_id == account_id,
            BusinessAccountMember.user_id == user_id,
            BusinessAccountMember.is_active.is_(True),
        )
    )
    member = result.scalar_one_or_none()
    if member is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not an active member of this corporate account.",
        )
    return member


async def _get_batch_or_404(
    db: AsyncSession, account_id: int, batch_id: int
) -> CorporateBatchBooking:
    """Fetch a batch belonging to account_id; raise 404 if not found."""
    result = await db.execute(
        select(CorporateBatchBooking).where(
            CorporateBatchBooking.id == batch_id,
            CorporateBatchBooking.account_id == account_id,
        )
    )
    batch = result.scalar_one_or_none()
    if batch is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Batch booking not found.",
        )
    return batch


# ---------------------------------------------------------------------------
# Public service functions
# ---------------------------------------------------------------------------


async def create_batch(
    db: AsyncSession,
    account_id: int,
    requesting_user_id: int,
    data: BatchBookingCreate,
) -> CorporateBatchBooking:
    """Create a new DRAFT batch booking for a corporate account.

    Args:
        db: Database session.
        account_id: Corporate account identifier.
        requesting_user_id: ID of the authenticated user (must be admin).
        data: Validated creation payload.

    Returns:
        The newly created CorporateBatchBooking.

    Raises:
        HTTP 403: When the user is not an account admin.
    """
    await _require_account_admin(db, account_id, requesting_user_id)

    batch = CorporateBatchBooking(
        account_id=account_id,
        name=data.name,
        event_date=data.event_date,
        notes=data.notes,
        status=BatchBookingStatus.DRAFT,
        created_by_user_id=requesting_user_id,
    )
    db.add(batch)
    await db.flush()
    return batch


async def get_batch(
    db: AsyncSession,
    account_id: int,
    batch_id: int,
    requesting_user_id: int,
) -> CorporateBatchBooking:
    """Fetch a single batch booking by ID.

    Args:
        db: Database session.
        account_id: Corporate account identifier.
        batch_id: Batch booking identifier.
        requesting_user_id: ID of the authenticated user (must be member).

    Returns:
        The requested CorporateBatchBooking.

    Raises:
        HTTP 403: When the user is not an active member.
        HTTP 404: When the batch does not exist or belongs to a different account.
    """
    await _require_account_member(db, account_id, requesting_user_id)
    return await _get_batch_or_404(db, account_id, batch_id)


async def list_batches(
    db: AsyncSession,
    account_id: int,
    requesting_user_id: int,
    status_filter: BatchBookingStatus | None = None,
) -> list[CorporateBatchBooking]:
    """Return all batches for a corporate account, optionally filtered by status.

    Args:
        db: Database session.
        account_id: Corporate account identifier.
        requesting_user_id: ID of the authenticated user (must be member).
        status_filter: Optional status to filter by.

    Returns:
        List of CorporateBatchBooking ordered by created_at descending.

    Raises:
        HTTP 403: When the user is not an active member.
    """
    await _require_account_member(db, account_id, requesting_user_id)

    q = select(CorporateBatchBooking).where(
        CorporateBatchBooking.account_id == account_id
    )
    if status_filter is not None:
        q = q.where(CorporateBatchBooking.status == status_filter)
    q = q.order_by(CorporateBatchBooking.created_at.desc())

    result = await db.execute(q)
    return list(result.scalars().all())


async def update_batch(
    db: AsyncSession,
    account_id: int,
    batch_id: int,
    requesting_user_id: int,
    data: BatchBookingUpdate,
) -> CorporateBatchBooking:
    """Update name, event_date, or notes on a DRAFT batch booking.

    Args:
        db: Database session.
        account_id: Corporate account identifier.
        batch_id: Batch booking identifier.
        requesting_user_id: ID of the authenticated user (must be admin).
        data: Validated update payload (only non-None fields are applied).

    Returns:
        The updated CorporateBatchBooking.

    Raises:
        HTTP 400: When the batch is not in DRAFT status.
        HTTP 403: When the user is not an account admin.
        HTTP 404: When the batch does not exist or belongs to a different account.
    """
    await _require_account_admin(db, account_id, requesting_user_id)
    batch = await _get_batch_or_404(db, account_id, batch_id)

    if batch.status != BatchBookingStatus.DRAFT:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only DRAFT batches can be updated.",
        )

    if data.name is not None:
        batch.name = data.name
    if data.event_date is not None:
        batch.event_date = data.event_date
    if data.notes is not None:
        batch.notes = data.notes

    await db.flush()
    return batch


async def add_ride_request(
    db: AsyncSession,
    account_id: int,
    batch_id: int,
    requesting_user_id: int,
    data: BatchRideRequestCreate,
) -> CorporateBatchRideRequest:
    """Add a ride request to a DRAFT batch.

    Args:
        db: Database session.
        account_id: Corporate account identifier.
        batch_id: Batch booking identifier.
        requesting_user_id: ID of the authenticated user (must be admin).
        data: Validated ride request payload.

    Returns:
        The newly created CorporateBatchRideRequest.

    Raises:
        HTTP 400: When the batch is not DRAFT, or is already at capacity (50).
        HTTP 403: When the user is not an account admin.
        HTTP 404: When the batch does not exist.
    """
    await _require_account_admin(db, account_id, requesting_user_id)
    batch = await _get_batch_or_404(db, account_id, batch_id)

    if batch.status != BatchBookingStatus.DRAFT:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ride requests can only be added to DRAFT batches.",
        )

    count_result = await db.execute(
        select(func.count(CorporateBatchRideRequest.id)).where(
            CorporateBatchRideRequest.batch_id == batch_id,
            CorporateBatchRideRequest.status == BatchRideRequestStatus.PENDING,
        )
    )
    pending_count = count_result.scalar() or 0

    if pending_count >= _BATCH_CAPACITY:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Batch is at capacity ({_BATCH_CAPACITY} ride requests)",
        )

    ride_request = CorporateBatchRideRequest(
        batch_id=batch_id,
        account_id=account_id,
        passenger_name=data.passenger_name,
        passenger_email=str(data.passenger_email) if data.passenger_email else None,
        passenger_phone=data.passenger_phone,
        pickup_address=data.pickup_address,
        pickup_lat=data.pickup_lat,
        pickup_lng=data.pickup_lng,
        dropoff_address=data.dropoff_address,
        dropoff_lat=data.dropoff_lat,
        dropoff_lng=data.dropoff_lng,
        requested_time=data.requested_time,
        notes=data.notes,
        status=BatchRideRequestStatus.PENDING,
    )
    db.add(ride_request)
    await db.flush()
    return ride_request


async def remove_ride_request(
    db: AsyncSession,
    account_id: int,
    batch_id: int,
    request_id: int,
    requesting_user_id: int,
) -> None:
    """Mark a ride request as REMOVED within a DRAFT batch.

    Args:
        db: Database session.
        account_id: Corporate account identifier.
        batch_id: Batch booking identifier.
        request_id: Ride request identifier.
        requesting_user_id: ID of the authenticated user (must be admin).

    Raises:
        HTTP 400: When the batch is not in DRAFT status.
        HTTP 403: When the user is not an account admin.
        HTTP 404: When the batch or ride request does not exist, or the request
            is already REMOVED.
    """
    await _require_account_admin(db, account_id, requesting_user_id)
    batch = await _get_batch_or_404(db, account_id, batch_id)

    if batch.status != BatchBookingStatus.DRAFT:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ride requests can only be removed from DRAFT batches.",
        )

    req_result = await db.execute(
        select(CorporateBatchRideRequest).where(
            CorporateBatchRideRequest.id == request_id,
            CorporateBatchRideRequest.batch_id == batch_id,
        )
    )
    ride_request = req_result.scalar_one_or_none()

    if ride_request is None or ride_request.status == BatchRideRequestStatus.REMOVED:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ride request not found.",
        )

    ride_request.status = BatchRideRequestStatus.REMOVED
    await db.flush()


async def submit_batch(
    db: AsyncSession,
    account_id: int,
    batch_id: int,
    requesting_user_id: int,
) -> CorporateBatchBooking:
    """Submit a DRAFT batch booking for fulfilment.

    The batch must have at least one PENDING ride request.

    Args:
        db: Database session.
        account_id: Corporate account identifier.
        batch_id: Batch booking identifier.
        requesting_user_id: ID of the authenticated user (must be admin).

    Returns:
        The updated CorporateBatchBooking with status SUBMITTED.

    Raises:
        HTTP 400: When the batch is not DRAFT, or has no PENDING requests.
        HTTP 403: When the user is not an account admin.
        HTTP 404: When the batch does not exist.
    """
    await _require_account_admin(db, account_id, requesting_user_id)
    batch = await _get_batch_or_404(db, account_id, batch_id)

    if batch.status != BatchBookingStatus.DRAFT:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only DRAFT batches can be submitted.",
        )

    count_result = await db.execute(
        select(func.count(CorporateBatchRideRequest.id)).where(
            CorporateBatchRideRequest.batch_id == batch_id,
            CorporateBatchRideRequest.status == BatchRideRequestStatus.PENDING,
        )
    )
    pending_count = count_result.scalar() or 0

    if pending_count == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot submit a batch with no ride requests",
        )

    batch.status = BatchBookingStatus.SUBMITTED
    batch.submitted_at = datetime.now(timezone.utc)
    await db.flush()
    return batch


async def cancel_batch(
    db: AsyncSession,
    account_id: int,
    batch_id: int,
    requesting_user_id: int,
    reason: str | None = None,
) -> CorporateBatchBooking:
    """Cancel a batch booking.

    Args:
        db: Database session.
        account_id: Corporate account identifier.
        batch_id: Batch booking identifier.
        requesting_user_id: ID of the authenticated user (must be admin).
        reason: Optional cancellation reason.

    Returns:
        The updated CorporateBatchBooking with status CANCELLED.

    Raises:
        HTTP 400: When the batch is already CANCELLED.
        HTTP 403: When the user is not an account admin.
        HTTP 404: When the batch does not exist.
    """
    await _require_account_admin(db, account_id, requesting_user_id)
    batch = await _get_batch_or_404(db, account_id, batch_id)

    if batch.status == BatchBookingStatus.CANCELLED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Batch is already cancelled",
        )

    batch.status = BatchBookingStatus.CANCELLED
    batch.cancelled_at = datetime.now(timezone.utc)
    batch.cancellation_reason = reason
    await db.flush()
    return batch


async def get_batch_with_requests(
    db: AsyncSession,
    account_id: int,
    batch_id: int,
    requesting_user_id: int,
) -> tuple[CorporateBatchBooking, list[CorporateBatchRideRequest]]:
    """Fetch a batch and all its non-removed ride requests.

    Args:
        db: Database session.
        account_id: Corporate account identifier.
        batch_id: Batch booking identifier.
        requesting_user_id: ID of the authenticated user (must be member).

    Returns:
        Tuple of (CorporateBatchBooking, list[CorporateBatchRideRequest]).

    Raises:
        HTTP 403: When the user is not an active member.
        HTTP 404: When the batch does not exist.
    """
    await _require_account_member(db, account_id, requesting_user_id)
    batch = await _get_batch_or_404(db, account_id, batch_id)

    req_result = await db.execute(
        select(CorporateBatchRideRequest)
        .where(
            CorporateBatchRideRequest.batch_id == batch_id,
            CorporateBatchRideRequest.status != BatchRideRequestStatus.REMOVED,
        )
        .order_by(CorporateBatchRideRequest.added_at)
    )
    requests = list(req_result.scalars().all())

    return batch, requests
