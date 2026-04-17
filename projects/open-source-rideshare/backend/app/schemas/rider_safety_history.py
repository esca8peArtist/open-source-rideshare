"""Pydantic schemas for rider safety incident history.

GET /riders/me/safety-incidents

Returns a paginated, filterable history of safety events a rider has
triggered (panic alerts).  Designed to be extensible — the incident_type
field allows future SOS and other event types to be added without a
breaking schema change.

Cooperative platform principle: riders should be able to review their own
safety history to understand patterns, confirm past incidents were handled
correctly, and audit their own use of emergency features.
"""
from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class SafetyIncidentType(str, Enum):
    """Type of safety incident.  Currently only PANIC_ALERT; extensible."""
    PANIC_ALERT = "PANIC_ALERT"


class SafetyIncidentStatusFilter(str, Enum):
    """Filter values for incident status query parameter."""
    ALL = "all"
    ACTIVE = "active"
    RESOLVED = "resolved"
    FALSE_ALARM = "false_alarm"


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class SafetyIncidentRecord(BaseModel):
    """A single safety incident in the rider's history."""

    id: str = Field(..., description="Unique incident identifier (UUID).")
    incident_type: SafetyIncidentType = Field(
        ...,
        description="Type of safety event.",
    )
    ride_id: int = Field(..., description="ID of the ride during which this event occurred.")
    driver_id: int = Field(..., description="ID of the driver on the ride.")
    status: str = Field(..., description="Current incident status: ACTIVE, RESOLVED, or FALSE_ALARM.")
    location_lat: Optional[float] = Field(None, description="Rider latitude at trigger time.")
    location_lng: Optional[float] = Field(None, description="Rider longitude at trigger time.")
    triggered_at: datetime = Field(..., description="UTC timestamp when the event was triggered.")
    resolved_at: Optional[datetime] = Field(None, description="UTC timestamp of resolution, if resolved.")
    resolution_notes: Optional[str] = Field(None, description="Notes recorded when the incident was resolved.")

    model_config = {"from_attributes": True}


class SafetyIncidentSummary(BaseModel):
    """All-time counts across a rider's safety history (not filtered)."""

    total_all_time: int = Field(..., description="Total incidents ever triggered by this rider.")
    active_count: int = Field(..., description="Incidents currently in ACTIVE status.")
    resolved_count: int = Field(..., description="Incidents resolved by admin.")
    false_alarm_count: int = Field(..., description="Incidents the rider cancelled as a false alarm.")


class SafetyIncidentFilters(BaseModel):
    """Echo of query parameters applied to this response."""

    incident_type: str = Field(..., description="Incident type filter applied.")
    status: str = Field(..., description="Status filter applied.")
    from_date: Optional[date] = Field(None, description="Start of date range filter (inclusive).")
    to_date: Optional[date] = Field(None, description="End of date range filter (inclusive).")
    limit: int = Field(..., description="Page size limit.")
    offset: int = Field(..., description="Page offset.")


class RiderSafetyHistory(BaseModel):
    """Paginated safety incident history for the authenticated rider."""

    total_count: int = Field(
        ...,
        description="Total incidents matching the applied filters (before pagination).",
    )
    incidents: list[SafetyIncidentRecord] = Field(
        ...,
        description="Page of incident records, newest-first.",
    )
    summary: SafetyIncidentSummary = Field(
        ...,
        description="All-time counts for this rider (unaffected by filters).",
    )
    filters_applied: SafetyIncidentFilters = Field(
        ...,
        description="Echo of query parameters used to produce this response.",
    )
