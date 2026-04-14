"""Schemas for the rider-facing busy hours indicator."""
from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class DemandLevel(str, Enum):
    """Rider-friendly demand classification for a given hour."""

    low = "low"
    medium = "medium"
    high = "high"
    peak = "peak"


class BusyHourSlot(BaseModel):
    """Demand summary for a single hour, expressed in rider-friendly terms."""

    hour: int = Field(..., ge=0, le=23, description="Hour of day in UTC (0–23)")
    hour_label: str = Field(..., description="Human-readable label, e.g. '14:00'")
    demand_level: DemandLevel = Field(
        ...,
        description=(
            "Relative demand classification: low / medium / high / peak. "
            "Based on historical ride volume for this hour."
        ),
    )
    typical_wait_minutes: float | None = Field(
        None,
        description=(
            "Typical minutes between requesting a ride and being matched to a driver. "
            "None if no historical data exists for this hour."
        ),
    )
    is_current_hour: bool = Field(
        ...,
        description="True if this slot represents the current UTC hour.",
    )


class BusyHoursResponse(BaseModel):
    """Response payload for GET /rides/busy-hours."""

    slots: list[BusyHourSlot] = Field(
        ...,
        description="Always 24 entries — one per hour (0–23), sorted by hour ascending.",
    )
    peak_hour: int | None = Field(
        None,
        ge=0,
        le=23,
        description="Hour with the highest historical demand (None if no data).",
    )
    current_hour: int = Field(
        ...,
        ge=0,
        le=23,
        description="Current UTC hour at response generation time.",
    )
    current_demand_level: DemandLevel = Field(
        ...,
        description="Demand level for the current hour.",
    )
    day_of_week: int | None = Field(
        None,
        ge=0,
        le=6,
        description=(
            "Day-of-week filter applied to the historical data (0=Sunday … 6=Saturday). "
            "None means all days were included."
        ),
    )
    generated_at: datetime
