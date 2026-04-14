"""Schemas for scheduled ride endpoints."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from app.models.scheduled_ride import CancelledBy, ScheduledRideStatus

# ---------------------------------------------------------------------------
# Minimum lead time: rides must be booked at least 30 minutes in advance.
# ---------------------------------------------------------------------------
MIN_ADVANCE_MINUTES: int = 30
# Maximum: 30 days ahead.
MAX_ADVANCE_DAYS: int = 30


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class ScheduledRideCreateRequest(BaseModel):
    """Body for creating an advance ride booking."""

    # Pickup
    pickup_lat: float = Field(..., ge=-90, le=90)
    pickup_lon: float = Field(..., ge=-180, le=180)
    pickup_address: str = Field(..., min_length=1, max_length=500)

    # Dropoff
    dropoff_lat: float = Field(..., ge=-90, le=90)
    dropoff_lon: float = Field(..., ge=-180, le=180)
    dropoff_address: str = Field(..., min_length=1, max_length=500)

    # When the rider wants to be picked up (must be in the future).
    scheduled_for: datetime = Field(
        ...,
        description="UTC datetime when the rider wants to be picked up.",
    )

    # Optional fare estimate (caller may supply; service may override).
    estimated_fare: float | None = Field(None, ge=0)

    # Optional rider notes for the driver.
    notes: str | None = Field(None, max_length=1000)


class ScheduledRideCancelRequest(BaseModel):
    """Body for cancelling a scheduled ride."""

    reason: str | None = Field(None, max_length=500)


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class ScheduledRideResponse(BaseModel):
    """Full scheduled ride detail returned to rider or driver."""

    id: int
    rider_id: int
    driver_id: int | None

    pickup_lat: float
    pickup_lon: float
    pickup_address: str

    dropoff_lat: float
    dropoff_lon: float
    dropoff_address: str

    scheduled_for: datetime
    estimated_fare: float | None
    notes: str | None

    status: ScheduledRideStatus
    cancelled_by: CancelledBy | None
    cancellation_reason: str | None
    decline_count: int

    ride_id: int | None

    created_at: datetime
    accepted_at: datetime | None
    completed_at: datetime | None
    cancelled_at: datetime | None

    model_config = {"from_attributes": True}


class ScheduledRideListResponse(BaseModel):
    """Paginated list of scheduled rides."""

    items: list[ScheduledRideResponse]
    total: int
    page: int
    page_size: int


class ScheduledRideAcceptResponse(BaseModel):
    """Returned when a driver accepts a scheduled ride."""

    scheduled_ride_id: int
    status: ScheduledRideStatus
    message: str


class ScheduledRideDeclineResponse(BaseModel):
    """Returned when a driver declines a scheduled ride booking."""

    scheduled_ride_id: int
    status: ScheduledRideStatus
    decline_count: int
    message: str


class ScheduledRideCancelResponse(BaseModel):
    """Returned after cancelling a scheduled ride."""

    scheduled_ride_id: int
    cancelled: bool
    cancelled_by: CancelledBy
    message: str


# ---------------------------------------------------------------------------
# Admin schemas
# ---------------------------------------------------------------------------


class AdminScheduledRideSummary(BaseModel):
    """Aggregate stats for the admin dashboard."""

    total: int
    pending: int
    driver_assigned: int
    in_progress: int
    completed: int
    cancelled: int
