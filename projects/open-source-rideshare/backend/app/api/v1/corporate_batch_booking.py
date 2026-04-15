"""Corporate Batch/Group Booking endpoints.

Member endpoints (any active member):
  GET  /corporate/accounts/me/batches                              — list batches
  GET  /corporate/accounts/me/batches/{batch_id}                   — get batch
  GET  /corporate/accounts/me/batches/{batch_id}/requests          — get requests

Admin endpoints (account admins only — enforced in service layer):
  POST   /corporate/accounts/me/batches                            — create batch
  PATCH  /corporate/accounts/me/batches/{batch_id}                 — update batch
  DELETE /corporate/accounts/me/batches/{batch_id}                 — cancel batch
  POST   /corporate/accounts/me/batches/{batch_id}/requests        — add ride request
  DELETE /corporate/accounts/me/batches/{batch_id}/requests/{rid}  — remove ride request
  POST   /corporate/accounts/me/batches/{batch_id}/submit          — submit batch

Platform-admin endpoints:
  GET /admin/corporate/accounts/{account_id}/batches
  GET /admin/corporate/accounts/{account_id}/batches/{batch_id}
  GET /admin/corporate/accounts/{account_id}/batches/{batch_id}/requests
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.models.corporate_batch_booking import BatchBookingStatus, BatchRideRequestStatus
from app.models.user import User
from app.schemas.corporate_batch_booking import (
    BatchBookingCreate,
    BatchBookingResponse,
    BatchBookingSummary,
    BatchBookingUpdate,
    BatchRideRequestCreate,
    BatchRideRequestListResponse,
    BatchRideRequestResponse,
    CancelBatchRequest,
)
from app.services.corporate_account_mgmt import get_user_account
from app.services.corporate_batch_booking import (
    add_ride_request,
    cancel_batch,
    create_batch,
    get_batch,
    get_batch_with_requests,
    list_batches,
    remove_ride_request,
    submit_batch,
    update_batch,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["corporate-batch-booking"])


# ---------------------------------------------------------------------------
# Internal helper: resolve the calling user's account_id
# ---------------------------------------------------------------------------


async def _resolve_account_id(db: AsyncSession, user_id: int) -> int:
    """Return the account_id for the authenticated user.

    Raises HTTP 404 if the user is not a member of any corporate account.
    """
    account = await get_user_account(db, user_id)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="You are not a member of any corporate account.",
        )
    return account.id


def _batch_response(batch, ride_request_count: int) -> BatchBookingResponse:
    """Build a BatchBookingResponse from an ORM object and a count."""
    return BatchBookingResponse(
        id=batch.id,
        account_id=batch.account_id,
        name=batch.name,
        event_date=batch.event_date,
        notes=batch.notes,
        status=batch.status,
        created_by_user_id=batch.created_by_user_id,
        submitted_at=batch.submitted_at,
        cancelled_at=batch.cancelled_at,
        cancellation_reason=batch.cancellation_reason,
        created_at=batch.created_at,
        updated_at=batch.updated_at,
        ride_request_count=ride_request_count,
    )


def _batch_summary(batch, ride_request_count: int) -> BatchBookingSummary:
    """Build a BatchBookingSummary from an ORM object and a count."""
    return BatchBookingSummary(
        id=batch.id,
        account_id=batch.account_id,
        name=batch.name,
        event_date=batch.event_date,
        status=batch.status,
        created_at=batch.created_at,
        ride_request_count=ride_request_count,
    )


# ---------------------------------------------------------------------------
# Member: list batches
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/batches",
    response_model=list[BatchBookingSummary],
    summary="List batch bookings for own corporate account",
)
async def list_my_batches(
    status: Optional[str] = Query(None, description="Filter by status: draft, submitted, cancelled"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all batch bookings for the authenticated user's corporate account.

    Any active member may call this endpoint.  Optionally filter by status.
    """
    account_id = await _resolve_account_id(db, user.id)

    status_filter: BatchBookingStatus | None = None
    if status is not None:
        try:
            status_filter = BatchBookingStatus(status.lower())
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid status value '{status}'. Must be one of: draft, submitted, cancelled.",
            )

    batches = await list_batches(db, account_id, requesting_user_id=user.id, status_filter=status_filter)
    return [_batch_summary(b, ride_request_count=0) for b in batches]


# ---------------------------------------------------------------------------
# Member: get batch
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/batches/{batch_id}",
    response_model=BatchBookingResponse,
    summary="Get a batch booking for own corporate account",
)
async def get_my_batch(
    batch_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a single batch booking by ID.

    Any active member may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    batch = await get_batch(db, account_id, batch_id, requesting_user_id=user.id)
    return _batch_response(batch, ride_request_count=0)


# ---------------------------------------------------------------------------
# Member: get batch with requests
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/batches/{batch_id}/requests",
    response_model=BatchRideRequestListResponse,
    summary="Get ride requests for a batch booking",
)
async def get_my_batch_requests(
    batch_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all non-removed ride requests for a batch booking.

    Any active member may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    batch, requests = await get_batch_with_requests(
        db, account_id, batch_id, requesting_user_id=user.id
    )

    pending_count = sum(1 for r in requests if r.status == BatchRideRequestStatus.PENDING)
    removed_count = sum(1 for r in requests if r.status == BatchRideRequestStatus.REMOVED)

    return BatchRideRequestListResponse(
        batch_id=batch.id,
        total_count=len(requests),
        pending_count=pending_count,
        removed_count=removed_count,
        requests=[BatchRideRequestResponse.model_validate(r) for r in requests],
    )


# ---------------------------------------------------------------------------
# Admin: create batch
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/accounts/me/batches",
    response_model=BatchBookingResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a batch booking (admin only)",
)
async def create_my_batch(
    data: BatchBookingCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new DRAFT batch booking.

    Only account admins may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    batch = await create_batch(db, account_id, requesting_user_id=user.id, data=data)
    return _batch_response(batch, ride_request_count=0)


# ---------------------------------------------------------------------------
# Admin: update batch
# ---------------------------------------------------------------------------


@router.patch(
    "/corporate/accounts/me/batches/{batch_id}",
    response_model=BatchBookingResponse,
    summary="Update a DRAFT batch booking (admin only)",
)
async def update_my_batch(
    batch_id: int,
    data: BatchBookingUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update the name, event date, or notes on a DRAFT batch booking.

    Only account admins may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    batch = await update_batch(db, account_id, batch_id, requesting_user_id=user.id, data=data)
    return _batch_response(batch, ride_request_count=0)


# ---------------------------------------------------------------------------
# Admin: cancel batch
# ---------------------------------------------------------------------------


@router.delete(
    "/corporate/accounts/me/batches/{batch_id}",
    response_model=BatchBookingResponse,
    summary="Cancel a batch booking (admin only)",
)
async def cancel_my_batch(
    batch_id: int,
    body: CancelBatchRequest = Body(default=CancelBatchRequest()),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Cancel a batch booking.

    An optional cancellation reason may be provided in the request body.
    Only account admins may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    batch = await cancel_batch(
        db, account_id, batch_id, requesting_user_id=user.id, reason=body.reason
    )
    return _batch_response(batch, ride_request_count=0)


# ---------------------------------------------------------------------------
# Admin: add ride request
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/accounts/me/batches/{batch_id}/requests",
    response_model=BatchRideRequestResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a ride request to a DRAFT batch (admin only)",
)
async def add_my_ride_request(
    batch_id: int,
    data: BatchRideRequestCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Add a single ride request to a DRAFT batch booking.

    The batch must be in DRAFT status and must not be at capacity (50 requests).
    Only account admins may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    ride_request = await add_ride_request(
        db, account_id, batch_id, requesting_user_id=user.id, data=data
    )
    return BatchRideRequestResponse.model_validate(ride_request)


# ---------------------------------------------------------------------------
# Admin: remove ride request
# ---------------------------------------------------------------------------


@router.delete(
    "/corporate/accounts/me/batches/{batch_id}/requests/{request_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a ride request from a DRAFT batch (admin only)",
)
async def remove_my_ride_request(
    batch_id: int,
    request_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Mark a ride request as REMOVED.

    Only account admins may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    await remove_ride_request(
        db, account_id, batch_id, request_id, requesting_user_id=user.id
    )


# ---------------------------------------------------------------------------
# Admin: submit batch
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/accounts/me/batches/{batch_id}/submit",
    response_model=BatchBookingResponse,
    summary="Submit a DRAFT batch booking (admin only)",
)
async def submit_my_batch(
    batch_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Submit a DRAFT batch booking for fulfilment.

    The batch must have at least one PENDING ride request.
    Only account admins may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    batch = await submit_batch(db, account_id, batch_id, requesting_user_id=user.id)
    return _batch_response(batch, ride_request_count=0)


# ---------------------------------------------------------------------------
# Platform admin: list batches for any account
# ---------------------------------------------------------------------------


@router.get(
    "/admin/corporate/accounts/{account_id}/batches",
    response_model=list[BatchBookingSummary],
    summary="Admin: list batch bookings for any corporate account",
)
async def admin_list_batches(
    account_id: int,
    status: Optional[str] = Query(None),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return all batch bookings for any corporate account (platform admin)."""
    status_filter: BatchBookingStatus | None = None
    if status is not None:
        try:
            status_filter = BatchBookingStatus(status.lower())
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status '{status}'.")

    batches = await list_batches(db, account_id, requesting_user_id=_admin.id, status_filter=status_filter)
    return [_batch_summary(b, ride_request_count=0) for b in batches]


# ---------------------------------------------------------------------------
# Platform admin: get batch for any account
# ---------------------------------------------------------------------------


@router.get(
    "/admin/corporate/accounts/{account_id}/batches/{batch_id}",
    response_model=BatchBookingResponse,
    summary="Admin: get a batch booking for any corporate account",
)
async def admin_get_batch(
    account_id: int,
    batch_id: int,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return a single batch booking for any account (platform admin)."""
    batch = await get_batch(db, account_id, batch_id, requesting_user_id=_admin.id)
    return _batch_response(batch, ride_request_count=0)


# ---------------------------------------------------------------------------
# Platform admin: get requests for any batch
# ---------------------------------------------------------------------------


@router.get(
    "/admin/corporate/accounts/{account_id}/batches/{batch_id}/requests",
    response_model=BatchRideRequestListResponse,
    summary="Admin: get ride requests for a batch in any corporate account",
)
async def admin_get_batch_requests(
    account_id: int,
    batch_id: int,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return all non-removed ride requests for any batch (platform admin)."""
    batch, requests = await get_batch_with_requests(
        db, account_id, batch_id, requesting_user_id=_admin.id
    )

    pending_count = sum(1 for r in requests if r.status == BatchRideRequestStatus.PENDING)
    removed_count = sum(1 for r in requests if r.status == BatchRideRequestStatus.REMOVED)

    return BatchRideRequestListResponse(
        batch_id=batch.id,
        total_count=len(requests),
        pending_count=pending_count,
        removed_count=removed_count,
        requests=[BatchRideRequestResponse.model_validate(r) for r in requests],
    )
