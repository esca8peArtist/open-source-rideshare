"""Pydantic v2 schemas for Corporate Shift Auto-Booking.

When an employee's shift assignment has ``auto_request_rides = True``, the
platform can generate pending auto-booking records for upcoming shift dates.
Admins trigger generation, then process individual records to create Rides.

Public surface
--------------
GenerateAutoBookingsRequest     — payload for the generate endpoint.
GenerateAutoBookingsResponse    — summary of how many bookings were created / skipped.
AutoBookingResponse             — a single auto-booking record returned by the API.
AutoBookingListResponse         — paginated list of auto-booking records.
ShiftAutoBookingSummaryResponse — aggregate stats for a single shift.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.corporate_shift_auto_booking import (
    ShiftAutoBookingDirection,
    ShiftAutoBookingStatus,
)


# ---------------------------------------------------------------------------
# Write schemas
# ---------------------------------------------------------------------------


class GenerateAutoBookingsRequest(BaseModel):
    """Payload for generating pending auto-booking records.

    Attributes:
        days_ahead: How many calendar days ahead to scan for upcoming shifts.
            Defaults to 7.  Maximum 30.
        include_return_rides: When True a ``from_work`` booking is created in
            addition to the ``to_work`` booking for each upcoming shift date.
            Defaults to True.
    """

    days_ahead: int = Field(7, ge=1, le=30)
    include_return_rides: bool = True


# ---------------------------------------------------------------------------
# Read schemas
# ---------------------------------------------------------------------------


class GenerateAutoBookingsResponse(BaseModel):
    """Summary returned by the generate endpoint.

    Attributes:
        created: Number of new pending auto-booking records created.
        skipped: Number of records skipped because they already exist
            (the unique constraint ``uq_corp_shift_auto_booking`` prevents
            duplicates across repeated generation runs).
        total_assignments_scanned: Number of active assignments with
            ``auto_request_rides = True`` that were examined.
    """

    created: int
    skipped: int
    total_assignments_scanned: int


class AutoBookingResponse(BaseModel):
    """Full auto-booking record returned by the API.

    Returned by get, cancel, and process endpoints.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    shift_id: int
    assignment_id: int
    member_id: Optional[int]
    account_id: int
    shift_date: date
    ride_direction: ShiftAutoBookingDirection
    scheduled_for: datetime
    status: ShiftAutoBookingStatus
    ride_id: Optional[int]
    failure_reason: Optional[str]
    booked_at: Optional[datetime]
    cancelled_at: Optional[datetime]
    created_at: datetime


class AutoBookingListResponse(BaseModel):
    """Paginated list of auto-booking records.

    Attributes:
        total: Total number of records matching the query.
        items: Auto-booking records for the current page.
    """

    total: int
    items: List[AutoBookingResponse]


class ShiftAutoBookingSummaryResponse(BaseModel):
    """Aggregate statistics for auto-bookings belonging to one shift.

    Attributes:
        shift_id: The shift being summarised.
        total: Total auto-booking records for this shift.
        pending: Records awaiting processing.
        booked: Records successfully converted to Ride records.
        failed: Records where ride creation failed.
        skipped: Records that were skipped (shift not running).
        cancelled: Records manually cancelled.
        to_work_count: Total ``to_work`` direction records.
        from_work_count: Total ``from_work`` direction records.
    """

    shift_id: int
    total: int
    pending: int
    booked: int
    failed: int
    skipped: int
    cancelled: int
    to_work_count: int
    from_work_count: int
