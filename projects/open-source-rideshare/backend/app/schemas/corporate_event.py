"""Pydantic v2 schemas for Corporate Event Management.

Enterprise coordinators organize company events, invite employees, and link
rides for consolidated billing.

Public surface
--------------
EventStatus             — str literal: draft / active / completed / cancelled.
AttendeeStatus          — str literal: invited / confirmed / declined / cancelled.
EventCreate             — payload for creating a new event.
EventUpdate             — partial update payload (all fields optional).
EventResponse           — full event record returned by the API.
EventListResponse       — paginated list of events.
AttendeeStatusUpdate    — payload for updating an attendee's status.
AttendeeResponse        — single attendee record returned by the API.
AttendeeListResponse    — paginated list of attendees.
InviteAttendeesRequest  — payload for bulk-inviting members to an event.
EventSummaryResponse    — lightweight summary: attendee counts and ride links.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Status literals
# ---------------------------------------------------------------------------


EventStatus = Literal["draft", "active", "completed", "cancelled"]
AttendeeStatus = Literal["invited", "confirmed", "declined", "cancelled"]


# ---------------------------------------------------------------------------
# Write schemas
# ---------------------------------------------------------------------------


class EventCreate(BaseModel):
    """Payload for creating a new corporate event.

    Attributes:
        title: Human-readable event name (required).
        description: Optional longer description.
        event_location_name: Name of the venue or location (required).
        event_address_line1: Optional street address.
        event_city: Optional city.
        event_state: Optional state/province.
        event_country: Optional country code.
        event_datetime: Date and time of the event (required).
        budget_usd: Optional total budget.
        max_attendees: Optional cap on attendee count.
        auto_approve_rides: When True, linked rides are auto-approved.
        notes: Optional internal notes.
        corporate_address_id: Optional FK to a saved corporate address.
    """

    title: str
    description: Optional[str] = None
    event_location_name: str
    event_address_line1: Optional[str] = None
    event_city: Optional[str] = None
    event_state: Optional[str] = None
    event_country: Optional[str] = None
    event_datetime: datetime
    budget_usd: Optional[Decimal] = None
    max_attendees: Optional[int] = None
    auto_approve_rides: bool = False
    notes: Optional[str] = None
    corporate_address_id: Optional[int] = None


class EventUpdate(BaseModel):
    """Partial update payload for a corporate event.

    All fields are optional — unset fields are left unchanged on update.

    Attributes:
        title: New event name.
        description: Updated description.
        event_location_name: Updated venue name.
        event_address_line1: Updated street address.
        event_city: Updated city.
        event_state: Updated state/province.
        event_country: Updated country code.
        event_datetime: Updated event date and time.
        budget_usd: Updated budget.
        max_attendees: Updated attendee cap.
        auto_approve_rides: Updated auto-approve flag.
        notes: Updated internal notes.
        corporate_address_id: Updated corporate address FK.
        is_active: Toggle visibility.
    """

    title: Optional[str] = None
    description: Optional[str] = None
    event_location_name: Optional[str] = None
    event_address_line1: Optional[str] = None
    event_city: Optional[str] = None
    event_state: Optional[str] = None
    event_country: Optional[str] = None
    event_datetime: Optional[datetime] = None
    budget_usd: Optional[Decimal] = None
    max_attendees: Optional[int] = None
    auto_approve_rides: Optional[bool] = None
    notes: Optional[str] = None
    corporate_address_id: Optional[int] = None
    is_active: Optional[bool] = None


# ---------------------------------------------------------------------------
# Read schemas
# ---------------------------------------------------------------------------


class EventResponse(BaseModel):
    """Full event record returned by the API.

    Returned by create, get, update, activate, cancel, and complete endpoints.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    account_id: int
    organizer_id: Optional[int]
    created_by_id: Optional[int]
    title: str
    description: Optional[str]
    event_location_name: str
    event_address_line1: Optional[str]
    event_city: Optional[str]
    event_state: Optional[str]
    event_country: Optional[str]
    event_latitude: Optional[Decimal]
    event_longitude: Optional[Decimal]
    corporate_address_id: Optional[int]
    event_datetime: datetime
    status: str
    budget_usd: Optional[Decimal]
    max_attendees: Optional[int]
    auto_approve_rides: bool
    notes: Optional[str]
    is_active: bool
    created_at: datetime
    updated_at: datetime


class EventListResponse(BaseModel):
    """Paginated list of events.

    Attributes:
        total: Total number of records matching the query (before pagination).
        limit: Page size used in this request.
        offset: Page offset used in this request.
        items: Events for this page.
    """

    total: int
    limit: int
    offset: int
    items: list[EventResponse]


# ---------------------------------------------------------------------------
# Attendee schemas
# ---------------------------------------------------------------------------


class AttendeeStatusUpdate(BaseModel):
    """Payload for updating an attendee's status.

    Attributes:
        status: New attendee lifecycle status.
    """

    status: AttendeeStatus


class AttendeeResponse(BaseModel):
    """A single attendee record returned by the API.

    Returned by invite-attendees and list-attendees endpoints.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    event_id: int
    member_id: Optional[int]
    ride_id: Optional[int]
    invited_by_id: Optional[int]
    status: str
    notes: Optional[str]
    created_at: datetime
    updated_at: datetime


class AttendeeListResponse(BaseModel):
    """Paginated list of attendees for an event.

    Attributes:
        total: Total number of attendee records (before pagination).
        limit: Page size used in this request.
        offset: Page offset used in this request.
        items: Attendee records for this page.
    """

    total: int
    limit: int
    offset: int
    items: list[AttendeeResponse]


class InviteAttendeesRequest(BaseModel):
    """Payload for bulk-inviting members to an event.

    Attributes:
        member_ids: List of user IDs to invite (1–50 per request).
        notes: Optional note included for all invited attendees.
    """

    member_ids: list[int] = Field(..., min_length=1, max_length=50)
    notes: Optional[str] = None


class EventSummaryResponse(BaseModel):
    """Lightweight summary of a corporate event.

    Suitable for dashboard widgets or event coordination views.

    Attributes:
        event_id: ID of the event.
        total_invited: Number of attendees with status "invited".
        total_confirmed: Number of attendees with status "confirmed".
        total_declined: Number of attendees with status "declined".
        total_cancelled: Number of attendees with status "cancelled".
        rides_linked: Number of attendees with a ride linked.
        budget_usd: Optional event budget.
    """

    event_id: int
    total_invited: int
    total_confirmed: int
    total_declined: int
    total_cancelled: int
    rides_linked: int
    budget_usd: Optional[Decimal]
