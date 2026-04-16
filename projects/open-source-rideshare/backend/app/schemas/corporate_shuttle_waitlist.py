"""Pydantic v2 schemas for Corporate Shuttle Waitlist.

When a shuttle schedule run is at full capacity employees can join a waitlist.
The first waiting member is automatically promoted when a booking is cancelled.

Public surface
--------------
WaitlistJoinRequest     — payload for joining a waitlist.
WaitlistLeaveRequest    — payload for leaving a waitlist.
WaitlistResponse        — full waitlist entry returned by the API.
WaitlistSummaryResponse — aggregate stats for a schedule+date waitlist.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.corporate_shuttle_waitlist import WaitlistStatus


class WaitlistJoinRequest(BaseModel):
    """Payload for joining a shuttle schedule waitlist.

    Attributes:
        booking_date: The calendar date of the run (YYYY-MM-DD).
        notes: Optional free-text notes.
    """

    booking_date: date
    notes: Optional[str] = Field(None, max_length=1000)


class WaitlistLeaveRequest(BaseModel):
    """Payload for leaving a shuttle schedule waitlist."""

    reason: Optional[str] = Field(None, max_length=500)


class WaitlistResponse(BaseModel):
    """Full waitlist entry returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    schedule_id: uuid.UUID
    account_id: int
    member_id: Optional[int]
    booking_date: date
    status: WaitlistStatus
    queue_position: int
    notes: Optional[str]
    promoted_at: Optional[datetime]
    promoted_booking_id: Optional[uuid.UUID]
    cancelled_at: Optional[datetime]
    cancellation_reason: Optional[str]
    created_at: datetime
    updated_at: datetime


class WaitlistSummaryResponse(BaseModel):
    """Aggregate statistics for a shuttle schedule waitlist on a given date.

    Attributes:
        schedule_id: The schedule UUID.
        booking_date: The run date.
        waiting_count: Number of entries currently in 'waiting' status.
        promoted_count: Number of entries ever promoted on this date.
        total_entries: Total waitlist entries for this schedule+date.
    """

    schedule_id: uuid.UUID
    booking_date: date
    waiting_count: int
    promoted_count: int
    total_entries: int
