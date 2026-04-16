"""Pydantic schemas for corporate mileage reimbursement."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator

from app.models.corporate_mileage_reimbursement import ClaimStatus


class MileagePolicyUpdateRequest(BaseModel):
    """Request body to update mileage reimbursement policy.

    All fields are optional; only supplied fields are updated.
    """

    rate_per_mile: Optional[Decimal] = Field(
        None,
        ge=0,
        description="USD reimbursement rate per mile.",
    )
    max_miles_per_claim: Optional[int] = Field(
        None,
        ge=1,
        description="Hard cap on miles per claim.  Omit to remove the cap.",
    )
    requires_approval_above_usd: Optional[Decimal] = Field(
        None,
        ge=0,
        description="Claims above this USD amount require admin review.",
    )
    requires_approval_above_miles: Optional[int] = Field(
        None,
        ge=1,
        description="Claims above this mileage require admin review.",
    )
    require_trip_purpose: Optional[bool] = Field(
        None,
        description="If True, employees must select a trip purpose when submitting.",
    )
    is_active: Optional[bool] = Field(
        None,
        description="Enable or disable the mileage reimbursement programme.",
    )


class MileagePolicyResponse(BaseModel):
    """Current mileage reimbursement policy for a corporate account."""

    id: int
    account_id: int
    rate_per_mile: Decimal
    max_miles_per_claim: Optional[int]
    requires_approval_above_usd: Optional[Decimal]
    requires_approval_above_miles: Optional[int]
    require_trip_purpose: bool
    is_active: bool
    created_by_id: Optional[int]

    model_config = {"from_attributes": True}


class MileageClaimCreateRequest(BaseModel):
    """Request body to create a new mileage claim."""

    trip_date: date = Field(..., description="Date of the trip.")
    miles: Decimal = Field(..., description="Distance driven in miles.")
    description: str = Field(
        ..., max_length=500, description="Brief description of the trip."
    )
    trip_purpose_id: Optional[int] = Field(None, description="Trip purpose ID.")
    cost_center_id: Optional[int] = Field(None, description="Cost center ID.")

    @field_validator("miles")
    @classmethod
    def miles_must_be_positive(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError("miles must be greater than 0")
        return v


class MileageClaimUpdateRequest(BaseModel):
    """Request body to update a draft mileage claim.

    All fields are optional; only supplied fields are updated.
    """

    trip_date: Optional[date] = None
    miles: Optional[Decimal] = Field(None, gt=0)
    description: Optional[str] = Field(None, max_length=500)
    trip_purpose_id: Optional[int] = None
    cost_center_id: Optional[int] = None


class MileageClaimReviewRequest(BaseModel):
    """Request body for an admin to approve or reject a claim."""

    action: Literal["approve", "reject"] = Field(
        ..., description="Review decision: 'approve' or 'reject'."
    )
    note: Optional[str] = Field(
        None, max_length=500, description="Optional admin note."
    )


class MileageClaimResponse(BaseModel):
    """Full mileage claim detail."""

    id: int
    account_id: int
    member_id: Optional[int]
    trip_date: date
    miles: Decimal
    rate_used_usd: Decimal
    amount_usd: Decimal
    description: str
    trip_purpose_id: Optional[int]
    cost_center_id: Optional[int]
    status: ClaimStatus
    submitted_at: Optional[datetime]
    reviewed_by_id: Optional[int]
    reviewed_at: Optional[datetime]
    review_note: Optional[str]
    paid_at: Optional[datetime]

    model_config = {"from_attributes": True}


class MileageClaimListResponse(BaseModel):
    """Paginated list of mileage claims."""

    total: int
    items: List[MileageClaimResponse]


class MileageClaimStatusBreakdown(BaseModel):
    """Claim count and amount for a single status."""

    status: ClaimStatus
    count: int
    total_amount_usd: Decimal


class MileageClaimSummaryResponse(BaseModel):
    """Account-level aggregate summary of mileage claims."""

    account_id: int
    total_claims: int
    total_miles: Decimal
    total_amount_usd: Decimal
    pending_approval_count: int
    pending_approval_amount_usd: Decimal
    by_status: List[MileageClaimStatusBreakdown]
