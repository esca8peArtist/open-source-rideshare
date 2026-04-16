"""Pydantic v2 schemas for Corporate Shuttle Routes & Seat Booking.

Enterprise accounts define fixed shuttle routes, attach recurring schedules to
each route, and employees book seats on specific run dates.

Public surface
--------------
RouteCreate             — payload for creating a shuttle route.
RouteUpdate             — partial-update payload for a route.
RouteResponse           — full route returned by the API.
ScheduleCreate          — payload for adding a schedule to a route.
ScheduleResponse        — full schedule returned by the API.
BookingCreate           — payload for booking a seat.
BookingResponse         — full booking returned by the API.
BookingCancelRequest    — payload for cancelling a booking.
RouteSummaryResponse    — aggregate stats for a route.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.corporate_shuttle import ShuttleBookingStatus


# ---------------------------------------------------------------------------
# Route schemas
# ---------------------------------------------------------------------------


class RouteCreate(BaseModel):
    """Payload for creating a shuttle route.

    Attributes:
        name: Human-readable route name (required, unique per account).
        description: Optional description.
        origin_name: Display name for the origin.
        origin_address: Full street address of the origin.
        origin_lat: Latitude of origin (optional).
        origin_lng: Longitude of origin (optional).
        destination_name: Display name for the destination.
        destination_address: Full street address of the destination.
        destination_lat: Latitude of destination (optional).
        destination_lng: Longitude of destination (optional).
        route_stops: Optional list of intermediate stops.
        default_capacity: Default seat count for runs (default 20).
        notes: Free-text notes.
    """

    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    origin_name: str = Field(..., min_length=1, max_length=200)
    origin_address: str = Field(..., min_length=1, max_length=500)
    origin_lat: Optional[float] = None
    origin_lng: Optional[float] = None
    destination_name: str = Field(..., min_length=1, max_length=200)
    destination_address: str = Field(..., min_length=1, max_length=500)
    destination_lat: Optional[float] = None
    destination_lng: Optional[float] = None
    route_stops: Optional[List[Dict[str, Any]]] = None
    default_capacity: int = Field(20, ge=1)
    notes: Optional[str] = None


class RouteUpdate(BaseModel):
    """Partial-update payload for a shuttle route."""

    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = None
    origin_name: Optional[str] = Field(None, min_length=1, max_length=200)
    origin_address: Optional[str] = Field(None, min_length=1, max_length=500)
    origin_lat: Optional[float] = None
    origin_lng: Optional[float] = None
    destination_name: Optional[str] = Field(None, min_length=1, max_length=200)
    destination_address: Optional[str] = Field(None, min_length=1, max_length=500)
    destination_lat: Optional[float] = None
    destination_lng: Optional[float] = None
    route_stops: Optional[List[Dict[str, Any]]] = None
    default_capacity: Optional[int] = Field(None, ge=1)
    notes: Optional[str] = None


class RouteResponse(BaseModel):
    """Full shuttle route returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    account_id: int
    name: str
    description: Optional[str]
    origin_name: str
    origin_address: str
    origin_lat: Optional[float]
    origin_lng: Optional[float]
    destination_name: str
    destination_address: str
    destination_lat: Optional[float]
    destination_lng: Optional[float]
    route_stops: Optional[List[Dict[str, Any]]]
    default_capacity: int
    notes: Optional[str]
    is_active: bool
    created_by_id: Optional[int]
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Schedule schemas
# ---------------------------------------------------------------------------


class ScheduleCreate(BaseModel):
    """Payload for adding a schedule to a route.

    Attributes:
        schedule_name: Human-readable schedule name (e.g., "Morning Run").
        days_of_week: List of ints 0–6 (0=Monday).
        departure_time: "HH:MM" in 24h format.
        estimated_duration_minutes: Approximate run time (optional).
        seat_capacity: Number of bookable seats per run.
        notes: Free-text notes.
    """

    schedule_name: str = Field(..., min_length=1, max_length=200)
    days_of_week: List[int] = Field(..., min_length=1)
    departure_time: str = Field(..., pattern=r"^\d{2}:\d{2}$")
    estimated_duration_minutes: Optional[int] = Field(None, ge=1)
    seat_capacity: int = Field(..., ge=1)
    notes: Optional[str] = None


class ScheduleResponse(BaseModel):
    """Full shuttle schedule returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    route_id: uuid.UUID
    account_id: int
    schedule_name: str
    days_of_week: List[int]
    departure_time: str
    estimated_duration_minutes: Optional[int]
    seat_capacity: int
    notes: Optional[str]
    is_active: bool
    created_by_id: Optional[int]
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Booking schemas
# ---------------------------------------------------------------------------


class BookingCreate(BaseModel):
    """Payload for booking a seat on a scheduled run.

    Attributes:
        booking_date: The calendar date of the run (YYYY-MM-DD).
        notes: Optional free-text notes.
    """

    booking_date: date
    notes: Optional[str] = None


class BookingCancelRequest(BaseModel):
    """Payload for cancelling a booking."""

    reason: Optional[str] = Field(None, max_length=500)


class BookingResponse(BaseModel):
    """Full shuttle booking returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    schedule_id: uuid.UUID
    account_id: int
    member_id: Optional[int]
    booking_date: date
    status: ShuttleBookingStatus
    notes: Optional[str]
    cancelled_at: Optional[datetime]
    cancelled_by_id: Optional[int]
    cancellation_reason: Optional[str]
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Summary schema
# ---------------------------------------------------------------------------


class RouteSummaryResponse(BaseModel):
    """Aggregate statistics for a shuttle route.

    Attributes:
        route: The route detail.
        total_schedules: Total schedules attached to the route.
        active_schedules: Number of currently active schedules.
        total_bookings_this_month: Count of bookings in the current calendar month.
        upcoming_run_dates: Next 7 days that have a run based on days_of_week.
    """

    route: RouteResponse
    total_schedules: int
    active_schedules: int
    total_bookings_this_month: int
    upcoming_run_dates: List[date]
