"""Schemas for demand-by-hour analytics endpoint."""
from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field


class DemandHourSlot(BaseModel):
    """Aggregated demand data for a single hour of the day (0–23)."""

    hour: int = Field(..., ge=0, le=23, description="Hour of day in UTC (0–23)")
    hour_label: str = Field(..., description="Human-readable label, e.g. '14:00'")
    total_rides: int = Field(..., ge=0, description="All rides requested in this hour")
    completed_rides: int = Field(..., ge=0, description="Rides that reached COMPLETED status")
    cancelled_rides: int = Field(..., ge=0, description="Rides that reached CANCELLED status")
    avg_fare: float | None = Field(
        None, description="Average actual or estimated fare for rides in this hour"
    )
    avg_wait_minutes: float | None = Field(
        None,
        description=(
            "Average minutes between requested_at and matched_at for rides "
            "that were matched (NULL if no rides were matched in this hour)"
        ),
    )


class DemandByHourFilters(BaseModel):
    """Applied filter parameters, echoed back in the response."""

    start_date: date | None = None
    end_date: date | None = None
    day_of_week: int | None = Field(
        None,
        ge=0,
        le=6,
        description="PostgreSQL DOW: 0=Sunday, 1=Monday, …, 6=Saturday",
    )


class DemandByHourResponse(BaseModel):
    """Response payload for the demand-by-hour analytics endpoint."""

    slots: list[DemandHourSlot] = Field(
        ..., description="Always 24 entries — one per hour (0–23), sorted by hour ascending"
    )
    total_rides: int = Field(..., ge=0, description="Total rides across all hours in the result set")
    peak_hour: int | None = Field(
        None,
        ge=0,
        le=23,
        description="Hour with the highest total_rides (None if no rides found)",
    )
    generated_at: datetime
    filters: DemandByHourFilters
