"""Schemas for trip heatmap analytics endpoint."""
from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field


class HeatmapCell(BaseModel):
    """A single geographic grid cell with aggregated trip activity."""

    lat: float = Field(..., description="Cell center latitude (rounded to precision)")
    lng: float = Field(..., description="Cell center longitude (rounded to precision)")
    pickup_count: int = Field(..., ge=0, description="Rides that started in this cell")
    dropoff_count: int = Field(..., ge=0, description="Rides that ended in this cell")
    total_activity: int = Field(
        ..., ge=0, description="pickup_count + dropoff_count"
    )
    avg_fare: float | None = Field(
        None, description="Average actual or estimated fare for rides starting in this cell"
    )


class HeatmapFilters(BaseModel):
    """Applied filter parameters, echoed back in the response."""

    start_date: date | None = None
    end_date: date | None = None
    status: str | None = None
    precision: int
    min_activity: int


class HeatmapResponse(BaseModel):
    """Response payload for the trip heatmap endpoint."""

    cells: list[HeatmapCell]
    total_cells: int = Field(..., description="Number of cells returned")
    generated_at: datetime
    filters: HeatmapFilters
