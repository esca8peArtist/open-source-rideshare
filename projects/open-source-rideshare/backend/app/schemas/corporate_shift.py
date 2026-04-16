"""Pydantic v2 schemas for Corporate Shift-Based Ride Scheduling.

Companies with shift workers need coordinated transportation to/from shift
start and end times.  Admins define named shifts and assign employees.

Public surface
--------------
ShiftCreate             — payload for creating a new shift.
ShiftUpdate             — partial update payload (all fields optional).
ShiftResponse           — full shift record returned by the API.
ShiftListResponse       — list of shifts.
AssignmentCreate        — payload for assigning a member to a shift.
AssignmentUpdate        — partial update payload for an assignment.
AssignmentResponse      — single assignment record returned by the API.
AssignmentListResponse  — list of assignments.
ShiftSummaryResponse    — lightweight summary: member counts and flags.
"""

from __future__ import annotations

from datetime import datetime, time
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Shift write schemas
# ---------------------------------------------------------------------------


class ShiftCreate(BaseModel):
    """Payload for creating a new corporate shift.

    Attributes:
        name: Human-readable shift name, unique per account (required).
        description: Optional longer description.
        work_location_name: Name of the work site (required).
        work_address_line1: Optional street address line 1.
        work_address_line2: Optional street address line 2.
        work_city: Optional city.
        work_state: Optional state/province.
        work_country: Optional country.
        work_postal_code: Optional postal/zip code.
        shift_start_time: Time when the shift begins (required).
        shift_end_time: Time when the shift ends (required).
        days_of_week: List of ints (0=Monday … 6=Sunday).
    """

    name: str = Field(..., max_length=100)
    description: Optional[str] = None
    work_location_name: str = Field(..., max_length=200)
    work_address_line1: Optional[str] = Field(None, max_length=200)
    work_address_line2: Optional[str] = Field(None, max_length=200)
    work_city: Optional[str] = Field(None, max_length=100)
    work_state: Optional[str] = Field(None, max_length=100)
    work_country: Optional[str] = Field(None, max_length=100)
    work_postal_code: Optional[str] = Field(None, max_length=20)
    shift_start_time: time
    shift_end_time: time
    days_of_week: List[int] = Field(default_factory=list)


class ShiftUpdate(BaseModel):
    """Partial update payload for a corporate shift.

    All fields are optional — unset fields are left unchanged on update.

    Attributes:
        name: Updated shift name.
        description: Updated description.
        work_location_name: Updated work site name.
        work_address_line1: Updated street address line 1.
        work_address_line2: Updated street address line 2.
        work_city: Updated city.
        work_state: Updated state/province.
        work_country: Updated country.
        work_postal_code: Updated postal/zip code.
        shift_start_time: Updated shift start time.
        shift_end_time: Updated shift end time.
        days_of_week: Updated days of week list.
    """

    name: Optional[str] = Field(None, max_length=100)
    description: Optional[str] = None
    work_location_name: Optional[str] = Field(None, max_length=200)
    work_address_line1: Optional[str] = Field(None, max_length=200)
    work_address_line2: Optional[str] = Field(None, max_length=200)
    work_city: Optional[str] = Field(None, max_length=100)
    work_state: Optional[str] = Field(None, max_length=100)
    work_country: Optional[str] = Field(None, max_length=100)
    work_postal_code: Optional[str] = Field(None, max_length=20)
    shift_start_time: Optional[time] = None
    shift_end_time: Optional[time] = None
    days_of_week: Optional[List[int]] = None


# ---------------------------------------------------------------------------
# Shift read schemas
# ---------------------------------------------------------------------------


class ShiftResponse(BaseModel):
    """Full shift record returned by the API.

    Returned by create, get, update, deactivate, and reactivate endpoints.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    account_id: int
    name: str
    description: Optional[str]
    work_location_name: str
    work_address_line1: Optional[str]
    work_address_line2: Optional[str]
    work_city: Optional[str]
    work_state: Optional[str]
    work_country: Optional[str]
    work_postal_code: Optional[str]
    work_latitude: Optional[Decimal]
    work_longitude: Optional[Decimal]
    shift_start_time: time
    shift_end_time: time
    days_of_week: List[int]
    is_active: bool
    created_by_id: Optional[int]
    created_at: datetime
    updated_at: datetime


class ShiftListResponse(BaseModel):
    """List of corporate shifts.

    Attributes:
        total: Total number of records matching the query.
        items: Shift records.
    """

    total: int
    items: List[ShiftResponse]


# ---------------------------------------------------------------------------
# Assignment write schemas
# ---------------------------------------------------------------------------


class AssignmentCreate(BaseModel):
    """Payload for assigning a member to a shift.

    Attributes:
        member_id: ID of the corporate account member to assign (required).
        pickup_address_line1: Optional pickup street address line 1.
        pickup_address_line2: Optional pickup street address line 2.
        pickup_city: Optional pickup city.
        pickup_state: Optional pickup state/province.
        pickup_country: Optional pickup country.
        pickup_postal_code: Optional pickup postal/zip code.
        auto_request_rides: Preference flag (does not trigger ride creation).
        advance_booking_minutes: Minutes before shift to book the ride.
        notes: Optional notes.
    """

    member_id: int
    pickup_address_line1: Optional[str] = Field(None, max_length=200)
    pickup_address_line2: Optional[str] = Field(None, max_length=200)
    pickup_city: Optional[str] = Field(None, max_length=100)
    pickup_state: Optional[str] = Field(None, max_length=100)
    pickup_country: Optional[str] = Field(None, max_length=100)
    pickup_postal_code: Optional[str] = Field(None, max_length=20)
    auto_request_rides: bool = False
    advance_booking_minutes: int = Field(60, ge=0)
    notes: Optional[str] = None


class AssignmentUpdate(BaseModel):
    """Partial update payload for a shift assignment.

    All fields are optional — unset fields are left unchanged on update.

    Attributes:
        pickup_address_line1: Updated pickup street address line 1.
        pickup_address_line2: Updated pickup street address line 2.
        pickup_city: Updated pickup city.
        pickup_state: Updated pickup state/province.
        pickup_country: Updated pickup country.
        pickup_postal_code: Updated pickup postal/zip code.
        auto_request_rides: Updated preference flag.
        advance_booking_minutes: Updated advance booking window.
        is_active: Toggle assignment active state.
        notes: Updated notes.
    """

    pickup_address_line1: Optional[str] = Field(None, max_length=200)
    pickup_address_line2: Optional[str] = Field(None, max_length=200)
    pickup_city: Optional[str] = Field(None, max_length=100)
    pickup_state: Optional[str] = Field(None, max_length=100)
    pickup_country: Optional[str] = Field(None, max_length=100)
    pickup_postal_code: Optional[str] = Field(None, max_length=20)
    auto_request_rides: Optional[bool] = None
    advance_booking_minutes: Optional[int] = Field(None, ge=0)
    is_active: Optional[bool] = None
    notes: Optional[str] = None


# ---------------------------------------------------------------------------
# Assignment read schemas
# ---------------------------------------------------------------------------


class AssignmentResponse(BaseModel):
    """A single assignment record returned by the API.

    Returned by assign-member and list-members endpoints.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    shift_id: int
    member_id: int
    pickup_address_line1: Optional[str]
    pickup_address_line2: Optional[str]
    pickup_city: Optional[str]
    pickup_state: Optional[str]
    pickup_country: Optional[str]
    pickup_postal_code: Optional[str]
    pickup_latitude: Optional[Decimal]
    pickup_longitude: Optional[Decimal]
    auto_request_rides: bool
    advance_booking_minutes: int
    is_active: bool
    assigned_by_id: Optional[int]
    notes: Optional[str]
    created_at: datetime
    updated_at: datetime


class AssignmentListResponse(BaseModel):
    """List of shift assignments.

    Attributes:
        total: Total number of records matching the query.
        items: Assignment records.
    """

    total: int
    items: List[AssignmentResponse]


# ---------------------------------------------------------------------------
# Summary schema
# ---------------------------------------------------------------------------


class ShiftSummaryResponse(BaseModel):
    """Lightweight summary of a corporate shift.

    Suitable for dashboard views or quick status checks.

    Attributes:
        shift_id: ID of the shift.
        name: Shift name.
        is_active: Whether the shift is active.
        total_members: Total number of assignments.
        active_members: Number of active assignments.
        inactive_members: Number of inactive assignments.
        members_with_auto_request: Number of members with auto_request_rides=True.
    """

    shift_id: int
    name: str
    is_active: bool
    total_members: int
    active_members: int
    inactive_members: int
    members_with_auto_request: int
