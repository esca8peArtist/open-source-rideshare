"""Pydantic v2 schemas for Corporate Driver Performance SLA.

Enterprise accounts track individual driver KPI performance against thresholds.
Policies define the thresholds; records capture per-driver evaluation snapshots.

Public surface
--------------
SLAPolicyCreate         — payload for creating a driver SLA policy.
SLAPolicyUpdate         — partial-update payload for a policy.
SLAPolicyResponse       — full policy returned by the API.
SLARecordResponse       — full evaluation record returned by the API.
DriverEvaluationInput   — metrics input for recording a driver evaluation.
DriverFlagInput         — payload for flagging a driver record for review.
DriverSLASummaryResponse — summary of recent evaluations for a driver.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Policy schemas
# ---------------------------------------------------------------------------


class SLAPolicyCreate(BaseModel):
    """Payload for creating a driver performance SLA policy.

    Attributes:
        name: Human-readable policy name (required), unique per account.
        description: Optional detailed description.
        min_on_time_rate_pct: Minimum on-time rate (0–100), nullable.
        min_avg_rating: Minimum average rating (0–5), nullable.
        max_cancellation_rate_pct: Maximum cancellation rate (0–100), nullable.
        min_acceptance_rate_pct: Minimum acceptance rate (0–100), nullable.
        evaluation_window_days: Rolling window in days (default 30).
    """

    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None
    min_on_time_rate_pct: Optional[float] = Field(None, ge=0, le=100)
    min_avg_rating: Optional[float] = Field(None, ge=0, le=5)
    max_cancellation_rate_pct: Optional[float] = Field(None, ge=0, le=100)
    min_acceptance_rate_pct: Optional[float] = Field(None, ge=0, le=100)
    evaluation_window_days: int = Field(30, ge=1, le=365)


class SLAPolicyUpdate(BaseModel):
    """Partial-update payload for a driver performance SLA policy.

    All fields are optional.
    """

    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = None
    min_on_time_rate_pct: Optional[float] = Field(None, ge=0, le=100)
    min_avg_rating: Optional[float] = Field(None, ge=0, le=5)
    max_cancellation_rate_pct: Optional[float] = Field(None, ge=0, le=100)
    min_acceptance_rate_pct: Optional[float] = Field(None, ge=0, le=100)
    evaluation_window_days: Optional[int] = Field(None, ge=1, le=365)
    is_active: Optional[bool] = None


class SLAPolicyResponse(BaseModel):
    """Full driver performance SLA policy returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    account_id: int
    name: str
    description: Optional[str]
    min_on_time_rate_pct: Optional[float]
    min_avg_rating: Optional[float]
    max_cancellation_rate_pct: Optional[float]
    min_acceptance_rate_pct: Optional[float]
    evaluation_window_days: int
    is_active: bool
    created_by_id: Optional[int]
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Record / evaluation schemas
# ---------------------------------------------------------------------------


class DriverEvaluationInput(BaseModel):
    """Metrics input for recording a driver evaluation.

    The service will look up the active policy and compute per-dimension pass/fail.

    Attributes:
        total_corporate_rides: Number of rides completed for this account in the window.
        on_time_rate_pct: Driver's on-time rate as a percentage (0–100), nullable.
        avg_rating: Driver's average rating on corporate rides (0–5), nullable.
        cancellation_rate_pct: Driver's cancellation rate (0–100), nullable.
        acceptance_rate_pct: Driver's acceptance rate (0–100), nullable.
        evaluation_window_days: Override for the evaluation window; defaults to policy value.
    """

    total_corporate_rides: int = Field(0, ge=0)
    on_time_rate_pct: Optional[float] = Field(None, ge=0, le=100)
    avg_rating: Optional[float] = Field(None, ge=0, le=5)
    cancellation_rate_pct: Optional[float] = Field(None, ge=0, le=100)
    acceptance_rate_pct: Optional[float] = Field(None, ge=0, le=100)
    evaluation_window_days: Optional[int] = Field(None, ge=1, le=365)


class DriverFlagInput(BaseModel):
    """Payload for flagging a driver SLA record for review.

    Attributes:
        reason: Optional free-text reason for flagging the record.
    """

    reason: Optional[str] = None


class SLARecordResponse(BaseModel):
    """Full driver SLA evaluation record returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    account_id: int
    sla_policy_id: Optional[uuid.UUID]
    driver_profile_id: Optional[int]
    evaluated_at: datetime
    evaluation_window_days: int
    total_corporate_rides: int
    on_time_rate_pct: Optional[float]
    avg_rating: Optional[float]
    cancellation_rate_pct: Optional[float]
    acceptance_rate_pct: Optional[float]
    on_time_met: Optional[bool]
    rating_met: Optional[bool]
    cancellation_met: Optional[bool]
    acceptance_met: Optional[bool]
    overall_sla_met: bool
    flagged_for_review: bool
    flagged_by_id: Optional[int]
    flagged_at: Optional[datetime]
    flag_reason: Optional[str]


class DriverSLASummaryResponse(BaseModel):
    """Summary of recent SLA evaluations for a driver.

    Attributes:
        driver_profile_id: ID of the driver.
        account_id: Corporate account ID.
        total_evaluations: Number of records in the summary window.
        pass_count: Number of evaluations where overall_sla_met is True.
        fail_count: Number of evaluations where overall_sla_met is False.
        pass_rate_pct: Percentage of evaluations that passed overall.
        flagged_count: Number of records flagged for review.
        recent_records: Most recent evaluation records (up to last_n_records).
    """

    driver_profile_id: Optional[int]
    account_id: int
    total_evaluations: int
    pass_count: int
    fail_count: int
    pass_rate_pct: float
    flagged_count: int
    recent_records: List[SLARecordResponse]
