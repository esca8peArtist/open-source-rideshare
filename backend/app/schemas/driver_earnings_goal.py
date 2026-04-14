"""Schemas for driver earnings goals."""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.models.driver_earnings_goal import GoalPeriodType


class EarningsGoalRequest(BaseModel):
    """Request body to create or update an earnings goal."""

    period_type: GoalPeriodType = Field(
        ...,
        description="Whether the target resets daily or weekly",
    )
    target_amount: float = Field(
        ...,
        gt=0,
        le=2000,
        description="Target earnings in USD for the period (1–2 000)",
    )


class EarningsGoalResponse(BaseModel):
    """Stored earnings goal — no progress data."""

    driver_profile_id: int
    period_type: GoalPeriodType
    target_amount: float
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class EarningsGoalProgressResponse(BaseModel):
    """Earnings goal with real-time progress for the current period."""

    driver_profile_id: int
    period_type: GoalPeriodType
    target_amount: float

    # Current period bounds
    period_start: date
    period_end: date

    # Progress
    current_earnings: float = Field(
        description="Net earnings (fare - platform fee + tips) for the current period"
    )
    rides_completed: int
    percentage: float = Field(
        description="current_earnings / target_amount * 100, clamped to 0–100"
    )
    on_track: bool = Field(
        description=(
            "True when the driver's current pace (earnings / elapsed fraction of period) "
            "puts them on course to meet the target by period end"
        )
    )
    remaining: float = Field(
        description="target_amount - current_earnings (0 when goal is met)"
    )

    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}
