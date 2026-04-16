"""Pydantic v2 schemas for Corporate Travel Itinerary.

Employees create named business trips that group multiple rides for
consolidated expense reporting.

Public surface
--------------
ItineraryStatus             — str enum: draft / active / completed / cancelled.
ItineraryCreate             — payload for creating a new itinerary.
ItineraryUpdate             — partial update payload (all fields optional).
ItineraryResponse           — full itinerary returned by the API.
ItineraryListResponse       — paginated list of itineraries.
ItineraryRideCreate         — payload for adding a ride to an itinerary.
ItineraryRideResponse       — single ride association returned by the API.
ItineraryRideListResponse   — paginated list of ride associations.
ItinerarySummaryResponse    — lightweight summary: counts and ride IDs.
"""

from __future__ import annotations

import enum
from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, field_validator


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ItineraryStatus(str, enum.Enum):
    """Lifecycle states for a travel itinerary."""

    draft = "draft"
    active = "active"
    completed = "completed"
    cancelled = "cancelled"


# ---------------------------------------------------------------------------
# Write schemas
# ---------------------------------------------------------------------------


class ItineraryCreate(BaseModel):
    """Payload for creating a new corporate travel itinerary.

    Attributes:
        title: Human-readable name for the trip (required, min 1 character).
        description: Optional longer description.
        start_date: Optional planned start date.
        end_date: Optional planned end date.
        cost_center_id: Optional cost center to associate all rides with.
        trip_purpose_id: Optional trip purpose to associate all rides with.
    """

    title: str
    description: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    cost_center_id: Optional[int] = None
    trip_purpose_id: Optional[int] = None

    @field_validator("title")
    @classmethod
    def title_not_empty(cls, v: str) -> str:
        """Validate that title is not an empty or whitespace-only string."""
        if not v or not v.strip():
            raise ValueError("title must not be empty")
        return v


class ItineraryUpdate(BaseModel):
    """Partial update payload for a corporate travel itinerary.

    All fields are optional — unset fields are left unchanged on update.

    Attributes:
        title: New trip name.
        description: Updated description.
        start_date: Updated start date.
        end_date: Updated end date.
        cost_center_id: Updated cost center.
        trip_purpose_id: Updated trip purpose.
        status: New lifecycle status.
        is_active: Toggle visibility.
    """

    title: Optional[str] = None
    description: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    cost_center_id: Optional[int] = None
    trip_purpose_id: Optional[int] = None
    status: Optional[ItineraryStatus] = None
    is_active: Optional[bool] = None


# ---------------------------------------------------------------------------
# Read schemas
# ---------------------------------------------------------------------------


class ItineraryResponse(BaseModel):
    """Full itinerary record returned by the API.

    Returned by create, get, update, cancel, and complete endpoints.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    account_id: int
    created_by_id: Optional[int]
    title: str
    description: Optional[str]
    start_date: Optional[date]
    end_date: Optional[date]
    cost_center_id: Optional[int]
    trip_purpose_id: Optional[int]
    status: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class ItineraryListResponse(BaseModel):
    """Paginated list of itineraries.

    Attributes:
        total: Total number of records matching the query (before pagination).
        limit: Page size used in this request.
        offset: Page offset used in this request.
        items: Itineraries for this page.
    """

    total: int
    limit: int
    offset: int
    items: list[ItineraryResponse]


# ---------------------------------------------------------------------------
# Ride association schemas
# ---------------------------------------------------------------------------


class ItineraryRideCreate(BaseModel):
    """Payload for adding a ride to an itinerary.

    Attributes:
        ride_id: ID of the ride to add.
        notes: Optional note about why this ride belongs to the itinerary.
    """

    ride_id: int
    notes: Optional[str] = None


class ItineraryRideResponse(BaseModel):
    """A ride association returned by the API.

    Returned by add-ride and list-rides endpoints.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    itinerary_id: int
    ride_id: Optional[int]
    added_by_id: Optional[int]
    notes: Optional[str]
    added_at: datetime


class ItineraryRideListResponse(BaseModel):
    """Paginated list of ride associations for an itinerary.

    Attributes:
        total: Total number of ride associations (before pagination).
        limit: Page size used in this request.
        offset: Page offset used in this request.
        items: Ride associations for this page.
    """

    total: int
    limit: int
    offset: int
    items: list[ItineraryRideResponse]


class ItinerarySummaryResponse(BaseModel):
    """Lightweight summary of an itinerary.

    Suitable for dashboard widgets or expense-report headers.

    Attributes:
        itinerary_id: ID of the itinerary.
        title: Human-readable trip name.
        status: Current lifecycle state.
        total_rides: Number of rides associated with this itinerary.
        ride_ids: List of ride IDs associated with this itinerary.
    """

    itinerary_id: int
    title: str
    status: str
    total_rides: int
    ride_ids: list[int]
