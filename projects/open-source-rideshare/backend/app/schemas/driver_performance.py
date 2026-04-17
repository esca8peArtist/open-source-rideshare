"""Pydantic schemas for the driver performance scoring feature.

Provides:
- DriverPerformanceSnapshotResponse  — full snapshot returned to admin or driver
- DriverScorecardResponse            — condensed self-view for the authenticated driver
- AdminPerformanceListItem           — single row in the admin paginated list
- AdminPerformanceListResponse       — paginated wrapper for the admin list
- AdminRecalculateResponse           — result of a bulk recalculation run
- DriverPerformanceAlertResponse     — single alert record
- MetricTrend                        — trend data for a single KPI metric
- WeeklyScorePoint                   — one data point in the weekly score series
- PerformanceTrendResponse           — full trend analysis response
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Trend analysis schemas
# ---------------------------------------------------------------------------


class MetricTrend(BaseModel):
    """Trend data for a single KPI metric over the analysis window.

    ``direction`` is one of: ``improving``, ``declining``, ``stable``, ``unknown``.
    ``unknown`` means there is only one snapshot (no previous to compare against).
    For ``cancellation_rate`` *lower* values are better, so a decrease is
    reported as ``improving`` and an increase as ``declining``.
    """

    current: float = Field(..., description="Value in the most-recent snapshot")
    previous: float | None = Field(None, description="Value in the preceding snapshot")
    four_week_avg: float | None = Field(
        None, description="Average over up to the last 4 snapshots"
    )
    direction: str = Field(
        ..., description="improving | declining | stable | unknown"
    )
    change_from_previous: float | None = Field(
        None, description="Absolute change: current − previous"
    )


class WeeklyScorePoint(BaseModel):
    """One data point in the driver's weekly performance score series."""

    period_start: date
    performance_score: float
    score_tier: str
    rides_completed: int


class PerformanceTrendResponse(BaseModel):
    """Full trend analysis for a driver over a requested window of weeks.

    ``score_velocity`` is the least-squares slope of the weekly performance
    scores in points-per-week; positive values mean improvement.

    ``score_percentile`` is the driver's position relative to the rest of the
    fleet (0 = bottom, 100 = top).  ``None`` when fleet data is unavailable.

    ``strengths`` lists the metric names where the driver is at or above the
    platform target threshold.  ``improvement_areas`` lists those that fall
    below threshold.  Both lists are drawn from:
    ``acceptance_rate``, ``completion_rate``, ``on_time_rate``,
    ``average_rider_rating``, ``cancellation_rate``.
    """

    driver_id: int
    weeks_requested: int
    snapshots_analyzed: int
    overall_direction: str = Field(
        ..., description="improving | declining | stable | unknown"
    )
    score_velocity: float = Field(
        ..., description="Points per week (positive = improving)"
    )
    current_score: float
    current_tier: str

    # Per-metric trends
    performance_score: MetricTrend
    acceptance_rate: MetricTrend
    completion_rate: MetricTrend
    cancellation_rate: MetricTrend
    no_show_rate: MetricTrend
    on_time_rate: MetricTrend
    average_rider_rating: MetricTrend

    # Fleet comparison
    fleet_avg_score: float | None = None
    score_percentile: int | None = None

    # Qualitative summary
    strengths: list[str]
    improvement_areas: list[str]

    # Raw weekly data for charting (oldest → newest)
    weekly_scores: list[WeeklyScorePoint]


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
    total_no_shows: int

    # Rates
    acceptance_rate: float
    completion_rate: float
    cancellation_rate: float
    no_show_rate: float

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
    cancellation_rate: float
    no_show_rate: float
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
