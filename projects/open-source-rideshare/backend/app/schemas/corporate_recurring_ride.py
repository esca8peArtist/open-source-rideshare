"""Pydantic schemas for Corporate Recurring Ride Schedules.

Schemas:
  RecurringRideCreate          — member POST body to create a schedule
  RecurringRideUpdate          — member PUT body for partial updates
  RecurringRideResponse        — full schedule representation
  RecurringRideListResponse    — paginated list of schedules
  RecurringRideBookingResponse — single booking-attempt record
  RecurringRideBookingListResponse — paginated list of booking records
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, field_validator, model_validator

from app.models.corporate_recurring_ride import (
    RecurrenceType,
    RecurringRideBookingStatus,
)

_TIME_RE = re.compile(r"^\d{2}:\d{2}$")


# ---------------------------------------------------------------------------
# Create / update
# ---------------------------------------------------------------------------


class RecurringRideCreate(BaseModel):
    """Fields required to create a new recurring-ride schedule."""

    name: str
    pickup_address: str
    pickup_lat: Optional[float] = None
    pickup_lng: Optional[float] = None
    dropoff_address: str
    dropoff_lat: Optional[float] = None
    dropoff_lng: Optional[float] = None
    vehicle_type: Optional[str] = None
    recurrence_type: RecurrenceType
    days_of_week: Optional[List[int]] = None
    day_of_month: Optional[int] = None
    scheduled_time: str
    advance_booking_minutes: int = 60
    cost_center_id: Optional[int] = None
    trip_purpose_id: Optional[int] = None
    notes: Optional[str] = None
    is_active: bool = True

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("name must not be blank")
        return v.strip()

    @field_validator("pickup_address", "dropoff_address")
    @classmethod
    def address_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("address must not be blank")
        return v.strip()

    @field_validator("scheduled_time")
    @classmethod
    def valid_time_format(cls, v: str) -> str:
        if not _TIME_RE.match(v):
            raise ValueError("scheduled_time must be in HH:MM format")
        hour, minute = int(v[:2]), int(v[3:])
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError("scheduled_time has invalid hour or minute value")
        return v

    @field_validator("days_of_week")
    @classmethod
    def valid_days(cls, v: Optional[List[int]]) -> Optional[List[int]]:
        if v is not None:
            for d in v:
                if not (0 <= d <= 6):
                    raise ValueError("days_of_week values must be 0–6 (Mon–Sun)")
        return v

    @field_validator("day_of_month")
    @classmethod
    def valid_day_of_month(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and not (1 <= v <= 31):
            raise ValueError("day_of_month must be between 1 and 31")
        return v

    @field_validator("advance_booking_minutes")
    @classmethod
    def positive_advance(cls, v: int) -> int:
        if v < 1:
            raise ValueError("advance_booking_minutes must be at least 1")
        return v

    @model_validator(mode="after")
    def recurrence_fields_consistent(self) -> "RecurringRideCreate":
        if self.recurrence_type == RecurrenceType.weekly:
            if not self.days_of_week:
                raise ValueError(
                    "days_of_week is required for weekly recurrence"
                )
        if self.recurrence_type == RecurrenceType.monthly:
            if self.day_of_month is None:
                raise ValueError(
                    "day_of_month is required for monthly recurrence"
                )
        return self


class RecurringRideUpdate(BaseModel):
    """All fields optional for partial updates to a recurring-ride schedule."""

    name: Optional[str] = None
    pickup_address: Optional[str] = None
    pickup_lat: Optional[float] = None
    pickup_lng: Optional[float] = None
    dropoff_address: Optional[str] = None
    dropoff_lat: Optional[float] = None
    dropoff_lng: Optional[float] = None
    vehicle_type: Optional[str] = None
    recurrence_type: Optional[RecurrenceType] = None
    days_of_week: Optional[List[int]] = None
    day_of_month: Optional[int] = None
    scheduled_time: Optional[str] = None
    advance_booking_minutes: Optional[int] = None
    cost_center_id: Optional[int] = None
    trip_purpose_id: Optional[int] = None
    notes: Optional[str] = None

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not v.strip():
            raise ValueError("name must not be blank")
        return v.strip() if v is not None else v

    @field_validator("scheduled_time")
    @classmethod
    def valid_time_format(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            if not _TIME_RE.match(v):
                raise ValueError("scheduled_time must be in HH:MM format")
            hour, minute = int(v[:2]), int(v[3:])
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                raise ValueError("scheduled_time has invalid hour or minute value")
        return v

    @field_validator("days_of_week")
    @classmethod
    def valid_days(cls, v: Optional[List[int]]) -> Optional[List[int]]:
        if v is not None:
            for d in v:
                if not (0 <= d <= 6):
                    raise ValueError("days_of_week values must be 0–6 (Mon–Sun)")
        return v

    @field_validator("day_of_month")
    @classmethod
    def valid_day_of_month(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and not (1 <= v <= 31):
            raise ValueError("day_of_month must be between 1 and 31")
        return v

    @field_validator("advance_booking_minutes")
    @classmethod
    def positive_advance(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v < 1:
            raise ValueError("advance_booking_minutes must be at least 1")
        return v


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class RecurringRideResponse(BaseModel):
    """Full representation of a recurring-ride schedule."""

    model_config = {"from_attributes": True}

    id: uuid.UUID
    account_id: int
    member_id: int
    name: str
    pickup_address: str
    pickup_lat: Optional[float] = None
    pickup_lng: Optional[float] = None
    dropoff_address: str
    dropoff_lat: Optional[float] = None
    dropoff_lng: Optional[float] = None
    vehicle_type: Optional[str] = None
    recurrence_type: RecurrenceType
    days_of_week: Optional[List[int]] = None
    day_of_month: Optional[int] = None
    scheduled_time: str
    advance_booking_minutes: int
    cost_center_id: Optional[int] = None
    trip_purpose_id: Optional[int] = None
    notes: Optional[str] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class RecurringRideListResponse(BaseModel):
    """Paginated list of recurring-ride schedules."""

    items: List[RecurringRideResponse]
    total: int


# ---------------------------------------------------------------------------
# Booking response schemas
# ---------------------------------------------------------------------------


class RecurringRideBookingResponse(BaseModel):
    """Full representation of a single recurring-ride booking attempt."""

    model_config = {"from_attributes": True}

    id: uuid.UUID
    recurring_ride_id: uuid.UUID
    account_id: int
    member_id: int
    ride_id: Optional[int] = None
    scheduled_for: datetime
    status: RecurringRideBookingStatus
    failure_reason: Optional[str] = None
    created_at: datetime


class RecurringRideBookingListResponse(BaseModel):
    """Paginated list of recurring-ride booking records."""

    items: List[RecurringRideBookingResponse]
    total: int
