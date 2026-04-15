"""Pydantic v2 schemas for the Corporate Batch/Group Booking feature.

Corporate account admins can create a batch booking, add individual ride
requests, then submit the batch for fulfilment.  Members can view batches
and their associated ride requests.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, EmailStr, Field

from app.models.corporate_batch_booking import BatchBookingStatus, BatchRideRequestStatus


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class BatchBookingCreate(BaseModel):
    """Payload for creating a new batch booking (starts in DRAFT status)."""

    name: str = Field(..., min_length=1, max_length=200, description="Human-readable label for this batch")
    event_date: date | None = Field(None, description="Date the event/rides take place (optional)")
    notes: str | None = Field(None, max_length=500, description="Optional free-text notes")


class BatchBookingUpdate(BaseModel):
    """Payload for updating a DRAFT batch booking.

    Only non-None fields are applied.
    """

    name: str | None = Field(None, min_length=1, max_length=200)
    event_date: date | None = None
    notes: str | None = Field(None, max_length=500)


class CancelBatchRequest(BaseModel):
    """Optional payload for cancelling a batch booking."""

    reason: str | None = Field(None, max_length=300, description="Optional cancellation reason")


class BatchRideRequestCreate(BaseModel):
    """Payload for adding a ride request to a DRAFT batch."""

    passenger_name: str = Field(..., min_length=1, max_length=150)
    passenger_email: EmailStr | None = None
    passenger_phone: str | None = Field(None, max_length=20)

    pickup_address: str = Field(..., min_length=1, max_length=300)
    pickup_lat: Decimal | None = None
    pickup_lng: Decimal | None = None

    dropoff_address: str = Field(..., min_length=1, max_length=300)
    dropoff_lat: Decimal | None = None
    dropoff_lng: Decimal | None = None

    requested_time: datetime = Field(..., description="When the ride should start (tz-aware recommended)")
    notes: str | None = Field(None, max_length=300)


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class BatchRideRequestResponse(BaseModel):
    """Full representation of a single ride request within a batch."""

    model_config = {"from_attributes": True}

    id: int
    batch_id: int
    account_id: int
    passenger_name: str
    passenger_email: str | None
    passenger_phone: str | None
    pickup_address: str
    pickup_lat: Decimal | None
    pickup_lng: Decimal | None
    dropoff_address: str
    dropoff_lat: Decimal | None
    dropoff_lng: Decimal | None
    requested_time: datetime
    notes: str | None
    status: BatchRideRequestStatus
    added_at: datetime


class BatchBookingResponse(BaseModel):
    """Full representation of a batch booking, including a ride-request count."""

    model_config = {"from_attributes": True}

    id: int
    account_id: int
    name: str
    event_date: date | None
    notes: str | None
    status: BatchBookingStatus
    created_by_user_id: int
    submitted_at: datetime | None
    cancelled_at: datetime | None
    cancellation_reason: str | None
    created_at: datetime
    updated_at: datetime
    ride_request_count: int = Field(..., description="Number of PENDING ride requests in this batch")


class BatchBookingSummary(BaseModel):
    """Lightweight batch view used in list responses."""

    model_config = {"from_attributes": True}

    id: int
    account_id: int
    name: str
    event_date: date | None
    status: BatchBookingStatus
    created_at: datetime
    ride_request_count: int = Field(..., description="Number of PENDING ride requests in this batch")


class BatchRideRequestListResponse(BaseModel):
    """Ride-request list for a batch with aggregate counts."""

    batch_id: int
    total_count: int
    pending_count: int
    removed_count: int
    requests: list[BatchRideRequestResponse]
