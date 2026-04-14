"""Pydantic schemas for the driver performance scoring feature.

Provides:
- DriverPerformanceSnapshotResponse  — full snapshot returned to admin or driver
- DriverScorecardResponse            — condensed self-view for the authenticated driver
- AdminPerformanceListItem           — single row in the admin paginated list
- AdminPerformanceListResponse       — paginated wrapper for the admin list
- AdminRecalculateResponse           — result of a bulk recalculation run
- DriverPerformanceAlertResponse     — single alert record
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field


class DriverPerformanceSnapshotResponse(BaseModel):
    """Full performance snapshot with all KPI metrics."""

    id: int
    driver_id: int
    period_start: date
    period_end: date

    # Volume
    total_rides_completed: int
    total_rides_offered: int
    total_rides_accepted: int
    total_rides_cancelled_by_driver: int

    # Rates
    acceptance_rate: float
    completion_rate: float
    cancellation_rate: float

    # Timing
    average_pickup_time_minutes: float
    on_time_rate: float

    # Quality
    average_rider_rating: float
    total_rider_ratings: int
    total_complaints: int

    # Score
    performance_score: float
    score_tier: str

    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DriverScorecardResponse(BaseModel):
    """Condensed scorecard for a driver's self-view.

    Exposes the composite score, tier, and the four headline KPIs without
    leaking administrative detail (complaints count is omitted).
    """

    driver_id: int
    period_start: date
    period_end: date
    performance_score: float = Field(..., description="Composite score 0–100")
    score_tier: str = Field(..., description="bronze / silver / gold / platinum")
    acceptance_rate: float
    completion_rate: float
    on_time_rate: float
    average_rider_rating: float
    total_rides_completed: int

    model_config = {"from_attributes": True}


class AdminPerformanceListItem(BaseModel):
    """Single row in the admin performance list."""

    driver_id: int
    driver_name: str | None = None
    performance_score: float
    score_tier: str
    acceptance_rate: float
    cancellation_rate: float
    completion_rate: float
    average_rider_rating: float
    total_rides_completed: int
    period_start: date
    period_end: date

    model_config = {"from_attributes": True}


class AdminPerformanceListResponse(BaseModel):
    """Paginated list of driver performance summaries for the admin dashboard."""

    total: int
    limit: int
    offset: int
    items: list[AdminPerformanceListItem]


class AdminRecalculateResponse(BaseModel):
    """Result of a bulk recalculation run."""

    recalculated: int = Field(..., description="Number of drivers successfully recalculated")
    errors: int = Field(..., description="Number of drivers that failed recalculation")
    error_details: list[str] = Field(
        default_factory=list,
        description="Human-readable description of each failure",
    )


class DriverPerformanceAlertResponse(BaseModel):
    """Single performance alert record."""

    id: int
    driver_id: int
    snapshot_id: int
    alert_type: str
    threshold_value: float
    actual_value: float
    is_resolved: bool
    created_at: datetime
    resolved_at: datetime | None

    model_config = {"from_attributes": True}


class PerformanceTrendPeriod(BaseModel):
    """One weekly period in a driver's performance trend series.

    Delta fields compare each metric to the previous period.  The first
    period in the series (oldest) always has ``None`` for all delta fields
    because there is no earlier period to compare against.
    """

    period_start: date
    period_end: date
    performance_score: float
    score_tier: str
    acceptance_rate: float
    completion_rate: float
    cancellation_rate: float
    average_rider_rating: float
    total_rides_completed: int
    total_rides_offered: int

    # Week-over-week deltas (None for the first period)
    score_delta: float | None = Field(
        None, description="Change in performance_score vs. previous period"
    )
    rating_delta: float | None = Field(
        None, description="Change in average_rider_rating vs. previous period"
    )
    acceptance_delta: float | None = Field(
        None, description="Change in acceptance_rate vs. previous period"
    )


class PerformanceTrendsResponse(BaseModel):
    """Response envelope for the driver performance trends endpoint.

    ``periods`` is ordered oldest-first so that time-series charts can
    render left-to-right without client-side reversal.
    """

    driver_id: int
    weeks_requested: int
    periods: list[PerformanceTrendPeriod]
