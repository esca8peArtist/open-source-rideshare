"""Schemas for surge zone boundary suggestion endpoint."""
from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field


class ZoneSuggestion(BaseModel):
    """A single suggested surge zone derived from heatmap clustering."""

    suggestion_id: int = Field(..., description="1-indexed identifier within this response")
    center_lat: float = Field(..., description="Cluster centroid latitude (activity-weighted)")
    center_lon: float = Field(..., description="Cluster centroid longitude (activity-weighted)")
    radius_km: float = Field(
        ...,
        description=(
            "Suggested zone radius in km — covers all cluster cells plus a half-cell buffer"
        ),
    )
    suggested_multiplier: float = Field(
        ...,
        description=(
            "Suggested initial surge multiplier (1.2–2.0), scaled by cluster activity "
            "relative to the busiest cluster in this response"
        ),
    )
    cell_count: int = Field(..., description="Number of heatmap cells in this cluster")
    total_activity: int = Field(
        ..., description="Sum of pickup + dropoff counts across all cells in the cluster"
    )
    avg_fare: float | None = Field(
        None,
        description="Activity-weighted average fare across pickup cells in the cluster",
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description=(
            "Confidence score 0.0–1.0, proportional to this cluster's activity relative "
            "to the highest-activity cluster returned"
        ),
    )
    reason: str = Field(..., description="Human-readable explanation of why this zone is suggested")
    overlaps_existing_zone: bool = Field(
        ..., description="True if the cluster centroid falls within an existing active surge zone"
    )
    overlapping_zone_name: str | None = Field(
        None, description="Name of the first overlapping zone (if overlaps_existing_zone is True)"
    )


class ZoneSuggestionsFilters(BaseModel):
    """Applied filter and clustering parameters, echoed back in the response."""

    start_date: date | None = None
    end_date: date | None = None
    min_activity: int
    precision: int
    cluster_radius_km: float
    min_cells: int
    max_suggestions: int


class ZoneSuggestionsResponse(BaseModel):
    """Response payload for GET /admin/surge-zones/suggestions."""

    suggestions: list[ZoneSuggestion]
    total_suggestions: int = Field(
        ..., description="Number of suggestions returned (capped at max_suggestions)"
    )
    filters: ZoneSuggestionsFilters
    generated_at: datetime
