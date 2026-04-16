"""Pydantic v2 schemas for Corporate Fleet Insurance Tracking.

Fleet managers track insurance policies for company vehicles — liability,
collision, comprehensive coverage — with expiry date alerts.

Public surface
--------------
InsurancePolicyCreate       — payload for creating an insurance policy.
InsurancePolicyUpdate       — partial-update payload.
InsurancePolicyResponse     — full insurance policy record returned by the API.
InsuranceExpiringResponse   — lightweight expiry alert entry.
InsuranceSummaryResponse    — aggregate counts and totals per account.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.corporate_fleet_insurance import InsuranceType

# ---------------------------------------------------------------------------
# Write schemas
# ---------------------------------------------------------------------------


class InsurancePolicyCreate(BaseModel):
    """Payload for creating a fleet vehicle insurance policy record.

    Attributes:
        fleet_vehicle_id: UUID of the fleet vehicle (required).
        policy_number: Insurance policy number (required, 1–100 chars).
        insurance_type: Category of coverage (required).
        provider_name: Name of the insurance provider (required, 1–200 chars).
        coverage_amount_usd: Maximum coverage amount in USD, nullable.
        deductible_usd: Policy deductible in USD, nullable.
        premium_annual_usd: Annual premium cost in USD, nullable.
        policy_start_date: Date the policy becomes effective (required).
        policy_end_date: Date the policy expires (required).
        notes: Optional free-text notes.
    """

    fleet_vehicle_id: uuid.UUID
    policy_number: str = Field(..., min_length=1, max_length=100)
    insurance_type: InsuranceType
    provider_name: str = Field(..., min_length=1, max_length=200)
    coverage_amount_usd: Optional[float] = Field(None, ge=0)
    deductible_usd: Optional[float] = Field(None, ge=0)
    premium_annual_usd: Optional[float] = Field(None, ge=0)
    policy_start_date: date
    policy_end_date: date
    notes: Optional[str] = None


class InsurancePolicyUpdate(BaseModel):
    """Partial-update payload for a fleet insurance policy.

    All fields are optional.  fleet_vehicle_id cannot be changed once created.
    """

    policy_number: Optional[str] = Field(None, min_length=1, max_length=100)
    insurance_type: Optional[InsuranceType] = None
    provider_name: Optional[str] = Field(None, min_length=1, max_length=200)
    coverage_amount_usd: Optional[float] = Field(None, ge=0)
    deductible_usd: Optional[float] = Field(None, ge=0)
    premium_annual_usd: Optional[float] = Field(None, ge=0)
    policy_start_date: Optional[date] = None
    policy_end_date: Optional[date] = None
    notes: Optional[str] = None


# ---------------------------------------------------------------------------
# Read schemas
# ---------------------------------------------------------------------------


class InsurancePolicyResponse(BaseModel):
    """Full fleet insurance policy record returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    account_id: int
    fleet_vehicle_id: uuid.UUID
    policy_number: str
    insurance_type: str
    provider_name: str
    coverage_amount_usd: Optional[float]
    deductible_usd: Optional[float]
    premium_annual_usd: Optional[float]
    policy_start_date: date
    policy_end_date: date
    is_active: bool
    notes: Optional[str]
    created_by_id: Optional[int]
    created_at: datetime
    updated_at: datetime


class InsuranceExpiringResponse(BaseModel):
    """A lightweight expiry alert for a fleet vehicle insurance policy.

    Attributes:
        policy_id: UUID of the insurance policy record.
        fleet_vehicle_id: UUID of the vehicle.
        policy_number: Insurance policy number.
        insurance_type: Category of coverage.
        provider_name: Name of the insurance provider.
        policy_end_date: Date the policy expires.
        days_until_expiry: Whole days remaining until policy_end_date from today.
    """

    policy_id: uuid.UUID
    fleet_vehicle_id: uuid.UUID
    policy_number: str
    insurance_type: str
    provider_name: str
    policy_end_date: date
    days_until_expiry: int


class InsuranceSummaryResponse(BaseModel):
    """Aggregate insurance statistics for a corporate account.

    Attributes:
        total_policies: Total number of insurance policy records.
        active_policies: Number of active policies.
        inactive_policies: Number of inactive policies.
        expiring_within_30_days: Active policies expiring within 30 days.
        total_annual_premium_usd: Sum of annual premiums for active policies.
        by_type: Policy count keyed by InsuranceType value.
    """

    total_policies: int
    active_policies: int
    inactive_policies: int
    expiring_within_30_days: int
    total_annual_premium_usd: float
    by_type: Dict[str, int]
