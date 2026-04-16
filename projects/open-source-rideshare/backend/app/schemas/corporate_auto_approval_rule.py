"""Pydantic v2 schemas for Corporate Auto-Approval Rules.

Corporate account admins configure rules that automatically approve ride
requests when all specified conditions are met, removing the need for manual
approval on routine, low-risk rides.

Public surface
--------------
AutoApprovalRuleCreate   — request body for creating a new rule.
AutoApprovalRuleUpdate   — request body for updating an existing rule.
AutoApprovalRuleResponse — full rule record returned by the API.
AutoApprovalRuleListResponse — paginated list of rules.
EvaluateAutoApprovalRequest  — body for the /evaluate endpoint.
EvaluateAutoApprovalResponse — result of evaluation.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, model_validator


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class AutoApprovalRuleCreate(BaseModel):
    """Request body for creating a new auto-approval rule.

    Attributes:
        name:                 Human-readable label (required, max 200 chars).
        is_active:            Whether the rule is immediately active (default True).
        max_cost_usd:         Max estimated ride cost in USD; no constraint if null.
        trip_purpose_ids:     List of allowed trip-purpose IDs; no constraint if null.
        cost_center_ids:      List of allowed cost-center IDs; no constraint if null.
        employee_group_ids:   List of employee-group IDs; no constraint if null.
        allowed_days_of_week: List of ints 0–6 (Mon=0); no constraint if null.
        start_hour:           Start of allowed hour range 0–23; must be paired
                              with end_hour.
        end_hour:             End of allowed hour range 0–23 (inclusive); must be
                              paired with start_hour.
        priority:             Evaluation order (higher = evaluated first, default 0).
    """

    name: str = Field(..., min_length=1, max_length=200)
    is_active: bool = True
    max_cost_usd: Optional[float] = Field(None, ge=0)
    trip_purpose_ids: Optional[List[int]] = None
    cost_center_ids: Optional[List[int]] = None
    employee_group_ids: Optional[List[int]] = None
    allowed_days_of_week: Optional[List[int]] = Field(
        None,
        description="List of day-of-week ints (0=Monday … 6=Sunday)",
    )
    start_hour: Optional[int] = Field(None, ge=0, le=23)
    end_hour: Optional[int] = Field(None, ge=0, le=23)
    priority: int = 0

    @model_validator(mode="after")
    def _validate_hour_range(self) -> "AutoApprovalRuleCreate":
        if (self.start_hour is None) != (self.end_hour is None):
            raise ValueError(
                "start_hour and end_hour must both be set or both be null."
            )
        return self


class AutoApprovalRuleUpdate(BaseModel):
    """Request body for updating an existing auto-approval rule.

    All fields are optional; only supplied fields are applied.

    Attributes:
        name:                 New human-readable label.
        is_active:            Toggle the rule on or off.
        max_cost_usd:         New max cost constraint (null removes it).
        trip_purpose_ids:     New trip-purpose filter (null removes it).
        cost_center_ids:      New cost-center filter (null removes it).
        employee_group_ids:   New employee-group filter (null removes it).
        allowed_days_of_week: New day-of-week filter (null removes it).
        start_hour:           New start hour; must be paired with end_hour.
        end_hour:             New end hour; must be paired with start_hour.
        priority:             New priority value.
    """

    name: Optional[str] = Field(None, min_length=1, max_length=200)
    is_active: Optional[bool] = None
    max_cost_usd: Optional[float] = Field(None, ge=0)
    trip_purpose_ids: Optional[List[int]] = None
    cost_center_ids: Optional[List[int]] = None
    employee_group_ids: Optional[List[int]] = None
    allowed_days_of_week: Optional[List[int]] = None
    start_hour: Optional[int] = Field(None, ge=0, le=23)
    end_hour: Optional[int] = Field(None, ge=0, le=23)
    priority: Optional[int] = None

    @model_validator(mode="after")
    def _validate_hour_range(self) -> "AutoApprovalRuleUpdate":
        # Only validate when at least one is explicitly provided
        if (self.start_hour is None) != (self.end_hour is None):
            raise ValueError(
                "start_hour and end_hour must both be set or both be null."
            )
        return self


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class AutoApprovalRuleResponse(BaseModel):
    """Full auto-approval rule record returned by the API.

    Attributes:
        id:                   Primary key.
        account_id:           Corporate account the rule belongs to.
        name:                 Human-readable rule name.
        is_active:            Whether the rule is active.
        max_cost_usd:         Max cost constraint (null = no constraint).
        trip_purpose_ids:     Trip-purpose filter (null = no constraint).
        cost_center_ids:      Cost-center filter (null = no constraint).
        employee_group_ids:   Employee-group filter (null = no constraint).
        allowed_days_of_week: Day-of-week filter (null = no constraint).
        start_hour:           Start of hour range (null = no constraint).
        end_hour:             End of hour range (null = no constraint).
        priority:             Evaluation priority.
        created_by_id:        Admin who created the rule.
        created_at:           Creation timestamp.
        updated_at:           Last-modified timestamp.
    """

    model_config = {"from_attributes": True}

    id: int
    account_id: int
    name: str
    is_active: bool
    max_cost_usd: Optional[float]
    trip_purpose_ids: Optional[List[int]]
    cost_center_ids: Optional[List[int]]
    employee_group_ids: Optional[List[int]]
    allowed_days_of_week: Optional[List[int]]
    start_hour: Optional[int]
    end_hour: Optional[int]
    priority: int
    created_by_id: Optional[int]
    created_at: datetime
    updated_at: datetime


class AutoApprovalRuleListResponse(BaseModel):
    """Paginated list of auto-approval rule records.

    Attributes:
        items: Rule records.
        total: Number of records returned.
    """

    items: List[AutoApprovalRuleResponse]
    total: int


# ---------------------------------------------------------------------------
# Evaluation schemas
# ---------------------------------------------------------------------------


class EvaluateAutoApprovalRequest(BaseModel):
    """Request body for evaluating auto-approval for a hypothetical ride.

    Attributes:
        estimated_cost_usd: Estimated ride fare in USD.
        trip_purpose_id:    Trip purpose, if any.
        cost_center_id:     Cost center, if any.
        ride_datetime:      Proposed ride date/time (UTC); defaults to now.
    """

    estimated_cost_usd: float = Field(..., ge=0)
    trip_purpose_id: Optional[int] = None
    cost_center_id: Optional[int] = None
    ride_datetime: Optional[datetime] = None


class EvaluateAutoApprovalResponse(BaseModel):
    """Result of an auto-approval evaluation.

    Attributes:
        auto_approved:      True if a matching rule was found.
        matched_rule_id:    ID of the first matching rule (null if none).
        matched_rule_name:  Name of the first matching rule (null if none).
    """

    auto_approved: bool
    matched_rule_id: Optional[int]
    matched_rule_name: Optional[str]
