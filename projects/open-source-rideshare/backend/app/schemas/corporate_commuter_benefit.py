"""Pydantic schemas for Corporate Commuter Benefits."""

from __future__ import annotations

from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Program schemas
# ---------------------------------------------------------------------------


class CommuterProgramCreate(BaseModel):
    """Request body for creating a new commuter benefit program."""

    name: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Display name for the program, e.g. 'Employee Commuter Benefit'.",
    )
    description: Optional[str] = Field(
        None, max_length=500, description="Optional human-readable description."
    )
    monthly_allowance_usd: float = Field(
        ...,
        gt=0,
        description="Monthly allowance in USD given to each eligible employee.",
    )
    rollover_enabled: bool = Field(
        False,
        description="When True, unused balance carries forward to the next month.",
    )
    max_rollover_usd: Optional[float] = Field(
        None,
        gt=0,
        description="Cap on the rollover amount. Only relevant when rollover_enabled=True.",
    )
    eligible_trip_purpose_ids: Optional[List[int]] = Field(
        None,
        description="List of CorporateTripPurpose IDs that qualify. Null means all purposes.",
    )
    eligible_group_ids: Optional[List[int]] = Field(
        None,
        description="List of CorporateEmployeeGroup IDs that receive the benefit. Null means all members.",
    )
    valid_from: Optional[date] = Field(
        None, description="Date the program becomes effective."
    )
    valid_until: Optional[date] = Field(
        None, description="Expiry date of the program."
    )


class CommuterProgramUpdate(BaseModel):
    """Request body for updating an existing commuter benefit program."""

    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    monthly_allowance_usd: Optional[float] = Field(None, gt=0)
    rollover_enabled: Optional[bool] = None
    max_rollover_usd: Optional[float] = Field(None, gt=0)
    eligible_trip_purpose_ids: Optional[List[int]] = None
    eligible_group_ids: Optional[List[int]] = None
    is_active: Optional[bool] = None
    valid_from: Optional[date] = None
    valid_until: Optional[date] = None


class CommuterProgramResponse(BaseModel):
    """A single commuter benefit program."""

    id: int
    account_id: int
    name: str
    description: Optional[str]
    monthly_allowance_usd: float
    rollover_enabled: bool
    max_rollover_usd: Optional[float]
    eligible_trip_purpose_ids: Optional[List[int]]
    eligible_group_ids: Optional[List[int]]
    is_active: bool
    valid_from: Optional[date]
    valid_until: Optional[date]
    created_by_id: Optional[int]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Allotment schemas
# ---------------------------------------------------------------------------


class CommuterAllotmentResponse(BaseModel):
    """A single monthly commuter allotment record for an employee."""

    id: int
    program_id: int
    member_id: int
    period_year: int
    period_month: int
    allotted_usd: float
    used_usd: float
    rolled_over_usd: float
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Stats schema
# ---------------------------------------------------------------------------


class CommuterStatsResponse(BaseModel):
    """Aggregate utilisation statistics for a commuter program in a given period."""

    total_members_enrolled: int
    total_allotted: float
    total_used: float
    total_remaining: float
    utilization_pct: float
