"""Pydantic schemas for surge zone auto-tuning endpoints.

Auto-tuning analyses historical demand data (hourly ride volume) for each
active surge zone's time window and suggests multiplier adjustments.
Admins preview recommendations before choosing to apply any or all of them.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class AutoTuneAction(str, Enum):
    """Classification of what the auto-tuner recommends for a zone."""

    increase = "increase"
    decrease = "decrease"
    no_change = "no_change"
    insufficient_data = "insufficient_data"


class SurgeZoneRecommendation(BaseModel):
    """Auto-tune recommendation for a single surge zone.

    The recommendation is based on how demand during the zone's active hours
    compares to the platform-wide hourly average. A zone whose time window
    catches consistently high-demand hours should have a higher multiplier;
    one covering low-demand hours may be over-priced.
    """

    zone_id: uuid.UUID
    zone_name: str
    current_multiplier: float
    recommended_multiplier: float
    action: AutoTuneAction

    # Demand context
    demand_ratio: float | None = Field(
        None,
        description=(
            "Average rides/hour in the zone's active window divided by "
            "the platform-wide average rides/hour. None when platform has no data."
        ),
    )
    zone_window_avg_rides: float | None = Field(
        None,
        description="Average rides per active hour slot in the zone's time window.",
    )
    platform_avg_rides: float = Field(
        description="Platform-wide average rides per hour across all 24 slots.",
    )
    recommendation_reason: str
    data_points: int = Field(
        description="Total rides observed during the zone's active hours in the lookback period.",
    )


class AutoTunePreviewResponse(BaseModel):
    """Full preview of auto-tune recommendations across all active surge zones."""

    recommendations: list[SurgeZoneRecommendation]
    total_zones: int
    zones_to_increase: int
    zones_to_decrease: int
    zones_no_change: int
    zones_insufficient_data: int
    generated_at: datetime
    lookback_days: int
    min_sample_size: int


class AutoTuneApplyRequest(BaseModel):
    """Request body for applying auto-tune recommendations.

    If zone_ids is None or empty, all actionable recommendations
    (increase / decrease) are applied. Pass a specific list to apply
    only selected zones.
    """

    zone_ids: list[uuid.UUID] | None = Field(
        None,
        description=(
            "Zone IDs to apply recommendations for. "
            "Omit or pass null to apply all actionable recommendations."
        ),
    )


class AutoTuneApplyDetail(BaseModel):
    """Per-zone result of an apply operation."""

    zone_id: uuid.UUID
    zone_name: str
    action: AutoTuneAction
    old_multiplier: float
    new_multiplier: float
    applied: bool
    skip_reason: str | None = None


class AutoTuneApplyResponse(BaseModel):
    """Result of applying auto-tune recommendations."""

    applied: int
    skipped: int
    details: list[AutoTuneApplyDetail]
    generated_at: datetime
