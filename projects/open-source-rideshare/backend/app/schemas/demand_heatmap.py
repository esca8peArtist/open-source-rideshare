"""Schemas for the trip demand heatmap feature."""

from __future__ import annotations

import enum
from datetime import date

from pydantic import BaseModel, Field


class HeatmapResolution(str, enum.Enum):
    LOW = "low"      # 0.1°  ≈ 11 km per cell
    MEDIUM = "medium"  # 0.01° ≈  1.1 km per cell
    HIGH = "high"    # 0.001° ≈ 110 m per cell


class HeatmapCell(BaseModel):
    """A single geographic grid cell with demand counts."""

    lat: float = Field(..., description="Cell centre latitude (rounded to resolution)")
    lng: float = Field(..., description="Cell centre longitude (rounded to resolution)")
    request_count: int = Field(..., description="Total ride requests with pickup in this cell")
    completed_count: int = Field(..., description="Completed rides with pickup in this cell")


class HeatmapCellWithFare(HeatmapCell):
    """Heatmap cell that also includes fare aggregates (admin view)."""

    avg_fare: float | None = Field(
        None, description="Average actual fare for completed rides in this cell (null if none)"
    )
    total_fare: float = Field(
        0.0, description="Sum of actual fares for completed rides in this cell"
    )


class FiltersApplied(BaseModel):
    period_start: date
    period_end: date
    resolution: HeatmapResolution
    hour_start: int | None
    hour_end: int | None
    day_of_week: int | None
    limit: int


class DriverDemandHeatmapResponse(BaseModel):
    """Demand heatmap response for drivers — pickup counts only, no fare data."""

    period_start: date
    period_end: date
    resolution: HeatmapResolution
    resolution_degrees: float = Field(
        ..., description="Size of each grid cell in degrees"
    )
    total_requests: int = Field(..., description="Total ride requests in the period")
    total_cells: int = Field(..., description="Number of grid cells returned")
    cells: list[HeatmapCell] = Field(
        ..., description="Grid cells sorted by request_count descending"
    )


class AdminDemandHeatmapResponse(BaseModel):
    """Demand heatmap response for admins — includes fare aggregates."""

    period_start: date
    period_end: date
    resolution: HeatmapResolution
    resolution_degrees: float
    total_requests: int
    total_cells: int
    filters_applied: FiltersApplied
    cells: list[HeatmapCellWithFare] = Field(
        ..., description="Grid cells sorted by request_count descending"
    )
