"""Pydantic v2 schemas for Corporate Vehicle Reservation Booking.

Employees can reserve company fleet vehicles for self-drive use during
specified time windows.

Public surface
--------------
VehicleReservationCreate        — payload for creating a reservation.
VehicleReservationUpdate        — partial-update payload (pending only).
VehicleReservationCancel        — payload carrying a cancellation reason.
VehicleReservationResponse      — full reservation record returned by the API.
VehicleAvailabilityResponse     — availability check result for a vehicle.
VehicleReservationSummaryResponse — aggregate counts by status.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Write schemas
# ---------------------------------------------------------------------------


class VehicleReservationCreate(BaseModel):
    """Payload for creating a vehicle reservation.

    Attributes:
        fleet_vehicle_id: UUID of the fleet vehicle to reserve (required).
        start_time: Reservation window start, timezone-aware (required).
        end_time: Reservation window end, timezone-aware (required).
        purpose: Short description of the trip purpose.
        pickup_location: Optional pickup location text.
        dropoff_location: Optional drop-off location text.
        notes: Free-text notes.
        trip_purpose_id: Optional FK to corporate trip purpose.
        cost_center_id: Optional FK to corporate cost center.
    """

    fleet_vehicle_id: uuid.UUID
    start_time: datetime
    end_time: datetime
    purpose: Optional[str] = Field(None, max_length=200)
    pickup_location: Optional[str] = Field(None, max_length=300)
    dropoff_location: Optional[str] = Field(None, max_length=300)
    notes: Optional[str] = None
    trip_purpose_id: Optional[uuid.UUID] = None
    cost_center_id: Optional[uuid.UUID] = None


class VehicleReservationUpdate(BaseModel):
    """Partial-update payload for a pending vehicle reservation.

    All fields are optional.  fleet_vehicle_id cannot be changed once created.
    Only pending reservations may be updated.
    """

    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    purpose: Optional[str] = Field(None, max_length=200)
    pickup_location: Optional[str] = Field(None, max_length=300)
    dropoff_location: Optional[str] = Field(None, max_length=300)
    notes: Optional[str] = None
    trip_purpose_id: Optional[uuid.UUID] = None
    cost_center_id: Optional[uuid.UUID] = None


class VehicleReservationCancel(BaseModel):
    """Payload for cancelling a reservation.

    Attributes:
        cancellation_reason: Optional explanation for the cancellation.
    """

    cancellation_reason: Optional[str] = Field(None, max_length=500)


# ---------------------------------------------------------------------------
# Read schemas
# ---------------------------------------------------------------------------


class VehicleReservationResponse(BaseModel):
    """Full vehicle reservation record returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    account_id: int
    fleet_vehicle_id: uuid.UUID
    reserved_by_id: Optional[int]
    approved_by_id: Optional[int]
    start_time: datetime
    end_time: datetime
    purpose: Optional[str]
    pickup_location: Optional[str]
    dropoff_location: Optional[str]
    notes: Optional[str]
    trip_purpose_id: Optional[uuid.UUID]
    cost_center_id: Optional[uuid.UUID]
    status: str
    cancelled_at: Optional[datetime]
    cancelled_by_id: Optional[int]
    cancellation_reason: Optional[str]
    created_at: datetime
    updated_at: datetime


class VehicleAvailabilityResponse(BaseModel):
    """Result of a vehicle availability check.

    Attributes:
        fleet_vehicle_id: UUID of the vehicle checked.
        is_available: True if no conflicting reservations exist.
        conflicts: List of conflicting reservation records.
    """

    fleet_vehicle_id: uuid.UUID
    is_available: bool
    conflicts: List[VehicleReservationResponse]


class VehicleReservationSummaryResponse(BaseModel):
    """Aggregate reservation counts by status for a corporate account.

    Attributes:
        total: Total number of reservations.
        pending: Reservations awaiting confirmation.
        confirmed: Confirmed reservations.
        cancelled: Cancelled reservations.
        completed: Completed reservations.
        no_show: Reservations marked as no-show.
    """

    total: int
    pending: int
    confirmed: int
    cancelled: int
    completed: int
    no_show: int
