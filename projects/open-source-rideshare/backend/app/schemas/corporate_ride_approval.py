"""Pydantic schemas for Corporate Ride Approval.

Request schemas (inbound):
    RideApprovalRequest     — employee submits an approval request
    RideApprovalDecision    — admin approves, with optional cost ceiling
    RideDenialRequest       — admin denies, with optional note
    ApprovalVerifyRequest   — verify an approval code before booking

Response schemas (outbound):
    CorporateRideApprovalResponse — full approval record
    ApprovalVerifyResponse        — result of a verification check
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.corporate_ride_approval import ApprovalStatus


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class RideApprovalRequest(BaseModel):
    """Submitted by an employee to request a pre-booking approval."""

    purpose: str | None = Field(
        None,
        max_length=200,
        description="Reason for the trip (e.g. 'Client meeting at HQ')",
    )
    destination_description: str | None = Field(
        None,
        max_length=300,
        description="Where the ride is going (freeform — no geocoding required)",
    )
    estimated_cost_usd: Decimal | None = Field(
        None,
        description="Employee's best estimate of the ride cost",
    )
    # How many hours the approval should stay valid after being granted.
    # Default 48 h; max 168 h (1 week).
    validity_hours: int = Field(
        48,
        ge=1,
        le=168,
        description="How many hours the approval remains valid after being granted",
    )

    @field_validator("estimated_cost_usd")
    @classmethod
    def positive_cost(cls, v: Decimal | None) -> Decimal | None:
        if v is not None and v <= 0:
            raise ValueError("estimated_cost_usd must be greater than 0")
        return v


class RideApprovalDecision(BaseModel):
    """Submitted by an account admin to approve a pending request."""

    max_cost_usd: Decimal | None = Field(
        None,
        description=(
            "Optional cost ceiling for the approved ride. "
            "If omitted, falls back to the estimated cost or unlimited."
        ),
    )
    review_note: str | None = Field(
        None,
        max_length=300,
        description="Optional note to the employee",
    )

    @field_validator("max_cost_usd")
    @classmethod
    def positive_max_cost(cls, v: Decimal | None) -> Decimal | None:
        if v is not None and v <= 0:
            raise ValueError("max_cost_usd must be greater than 0")
        return v


class RideDenialRequest(BaseModel):
    """Submitted by an account admin to deny a pending request."""

    review_note: str | None = Field(
        None,
        max_length=300,
        description="Reason for denial (shown to the employee)",
    )


class ApprovalVerifyRequest(BaseModel):
    """Sent at booking time to verify an approval code is still valid."""

    approval_code: str = Field(..., description="The unique approval code")
    estimated_cost_usd: Decimal | None = Field(
        None,
        description="Estimated cost of the ride being booked (checked against max_cost_usd)",
    )

    @field_validator("estimated_cost_usd")
    @classmethod
    def positive_cost(cls, v: Decimal | None) -> Decimal | None:
        if v is not None and v <= 0:
            raise ValueError("estimated_cost_usd must be greater than 0")
        return v


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class CorporateRideApprovalResponse(BaseModel):
    """Full approval record returned to the caller."""

    id: int
    account_id: int
    requester_user_id: int
    approved_by_user_id: int | None
    purpose: str | None
    destination_description: str | None
    estimated_cost_usd: Decimal | None
    status: ApprovalStatus
    approval_code: str
    max_cost_usd: Decimal | None
    expires_at: datetime
    review_note: str | None
    reviewed_at: datetime | None
    used_at: datetime | None
    requested_at: datetime

    model_config = {"from_attributes": True}


class ApprovalVerifyResponse(BaseModel):
    """Result of an approval-code verification check."""

    valid: bool
    reason: str | None = None
    approval_id: int | None = None
    max_cost_usd: Decimal | None = None
