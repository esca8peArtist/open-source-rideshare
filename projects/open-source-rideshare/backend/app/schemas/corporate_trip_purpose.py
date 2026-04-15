"""Pydantic v2 schemas for the Corporate Trip Purpose Codes feature.

Corporate account admins define valid purpose codes.  Employees tag rides
with a purpose code at booking time or after completion.  Analytics can
break down spend by purpose.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class CorporateTripPurposeCreate(BaseModel):
    """Payload for creating a new trip purpose code (admin only)."""

    code: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description="Short machine-readable identifier, e.g. CLIENT_MEETING.  Stored uppercase.",
    )
    label: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Human-readable display label, e.g. 'Client Meeting'.",
    )
    requires_notes: bool = Field(
        False,
        description="When True, employees must supply notes when using this purpose.",
    )


class CorporateTripPurposeUpdate(BaseModel):
    """Payload for updating an existing trip purpose (admin only).

    Only non-None fields are applied.
    """

    label: str | None = Field(None, min_length=1, max_length=100)
    is_active: bool | None = None
    requires_notes: bool | None = None


class SetRideTripPurposeRequest(BaseModel):
    """Payload for tagging (or clearing) a ride with a trip purpose."""

    trip_purpose_id: int | None = Field(
        None,
        description="ID of the purpose to assign.  Pass null to clear the tag.",
    )
    trip_notes: str | None = Field(
        None,
        max_length=500,
        description="Optional notes describing the trip purpose in more detail.",
    )


class TripPurposeAnalyticsRequest(BaseModel):
    """Optional date range for trip-purpose spend analytics."""

    start_date: date | None = None
    end_date: date | None = None


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class CorporateTripPurposeResponse(BaseModel):
    """Full representation of a single trip purpose code."""

    model_config = {"from_attributes": True}

    id: int
    account_id: int
    code: str
    label: str
    is_active: bool
    requires_notes: bool
    created_at: datetime
    updated_at: datetime


class TripPurposeSpendItem(BaseModel):
    """Spend totals for a single purpose code within an analytics window."""

    purpose_id: int
    code: str
    label: str
    ride_count: int
    total_usd: Decimal
    avg_usd: Decimal | None


class TripPurposeSpendResponse(BaseModel):
    """Full spend-by-purpose analytics response for a corporate account."""

    account_id: int
    items: list[TripPurposeSpendItem]
    untagged_ride_count: int
    untagged_total_usd: Decimal
