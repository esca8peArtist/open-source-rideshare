"""Pydantic schemas for Corporate SLA Policies & Compliance Reporting.

Schemas:
  SLAPolicyCreate           — admin POST body to create a new SLA policy
  SLAPolicyUpdate           — admin PUT body for partial updates
  SLAPolicyResponse         — full policy representation
  SLAPolicyListResponse     — list of policies with total count
  SLAEvaluationCreate       — body for recording a per-ride SLA evaluation
  SLARideRecordResponse     — full ride evaluation record representation
  SLARideRecordListResponse — list of ride records with total count
  DimensionSummary          — per-dimension compliance counts and percentage
  SLAComplianceSummary      — overall compliance summary for an account/period
  SLATrendEntry             — one month's compliance data for trend charts
  SLATrendResponse          — list of trend entries
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, field_validator


# ---------------------------------------------------------------------------
# Policy create / update schemas
# ---------------------------------------------------------------------------


class SLAPolicyCreate(BaseModel):
    """Fields required to create a new corporate SLA policy."""

    name: str
    max_wait_time_minutes: Optional[int] = None
    min_driver_rating: Optional[Decimal] = None
    on_time_window_minutes: Optional[int] = None
    target_completion_rate_pct: Optional[Decimal] = None
    is_active: bool = False
    effective_from: Optional[date] = None
    effective_until: Optional[date] = None

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("name must not be blank")
        return v.strip()

    @field_validator("min_driver_rating")
    @classmethod
    def rating_range(cls, v: Optional[Decimal]) -> Optional[Decimal]:
        if v is not None and not (Decimal("0") <= v <= Decimal("5")):
            raise ValueError("min_driver_rating must be between 0 and 5")
        return v

    @field_validator("target_completion_rate_pct")
    @classmethod
    def completion_rate_range(cls, v: Optional[Decimal]) -> Optional[Decimal]:
        if v is not None and not (Decimal("0") <= v <= Decimal("100")):
            raise ValueError("target_completion_rate_pct must be between 0 and 100")
        return v


class SLAPolicyUpdate(BaseModel):
    """Partial update schema — only supplied fields are written."""

    name: Optional[str] = None
    max_wait_time_minutes: Optional[int] = None
    min_driver_rating: Optional[Decimal] = None
    on_time_window_minutes: Optional[int] = None
    target_completion_rate_pct: Optional[Decimal] = None
    effective_from: Optional[date] = None
    effective_until: Optional[date] = None

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not v.strip():
            raise ValueError("name must not be blank")
        return v.strip() if v is not None else v


# ---------------------------------------------------------------------------
# Policy response schemas
# ---------------------------------------------------------------------------


class SLAPolicyResponse(BaseModel):
    """Full representation of a corporate SLA policy."""

    model_config = {"from_attributes": True}

    id: uuid.UUID
    account_id: int
    name: str
    max_wait_time_minutes: Optional[int]
    min_driver_rating: Optional[Decimal]
    on_time_window_minutes: Optional[int]
    target_completion_rate_pct: Optional[Decimal]
    is_active: bool
    effective_from: Optional[date]
    effective_until: Optional[date]
    created_by_id: Optional[int]
    created_at: datetime
    updated_at: datetime


class SLAPolicyListResponse(BaseModel):
    """List of SLA policies with total count."""

    items: list[SLAPolicyResponse]
    total: int


# ---------------------------------------------------------------------------
# Ride evaluation create schema
# ---------------------------------------------------------------------------


class SLAEvaluationCreate(BaseModel):
    """Body for recording a per-ride SLA evaluation."""

    wait_time_minutes: Optional[Decimal] = None
    driver_rating: Optional[Decimal] = None
    was_scheduled_ride: bool = False
    scheduled_pickup_at: Optional[datetime] = None
    actual_pickup_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Ride record response schemas
# ---------------------------------------------------------------------------


class SLARideRecordResponse(BaseModel):
    """Full representation of a per-ride SLA evaluation record."""

    model_config = {"from_attributes": True}

    id: uuid.UUID
    account_id: int
    policy_id: Optional[uuid.UUID]
    ride_id: Optional[int]
    member_id: Optional[int]
    wait_time_minutes: Optional[Decimal]
    driver_rating_at_time: Optional[Decimal]
    was_scheduled_ride: bool
    scheduled_pickup_at: Optional[datetime]
    actual_pickup_at: Optional[datetime]
    arrival_delta_minutes: Optional[Decimal]
    wait_time_met: Optional[bool]
    driver_rating_met: Optional[bool]
    on_time_met: Optional[bool]
    overall_sla_met: bool
    evaluated_at: datetime


class SLARideRecordListResponse(BaseModel):
    """List of SLA ride records with total count."""

    items: list[SLARideRecordResponse]
    total: int


# ---------------------------------------------------------------------------
# Compliance reporting schemas
# ---------------------------------------------------------------------------


class DimensionSummary(BaseModel):
    """Per-dimension compliance counts and percentage."""

    total: int
    met: int
    pct: Optional[float]


class SLAComplianceSummary(BaseModel):
    """Overall SLA compliance summary for an account or time period."""

    total_rides: int
    sla_met_count: int
    sla_breach_count: int
    compliance_pct: Optional[float]
    by_dimension: dict[str, DimensionSummary]


class SLATrendEntry(BaseModel):
    """One month's SLA compliance data for trend charts."""

    year: int
    month: int
    total_rides: int
    compliance_pct: Optional[float]


class SLATrendResponse(BaseModel):
    """Monthly SLA compliance trend."""

    items: list[SLATrendEntry]
