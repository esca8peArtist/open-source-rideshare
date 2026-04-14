"""Pydantic schemas for the fare dispute & refund feature."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.models.fare_dispute import DisputeCategory, DisputeStatus


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------

class FareDisputeCreateRequest(BaseModel):
    category: DisputeCategory
    description: str = Field(..., min_length=10, max_length=2000)
    disputed_amount: float = Field(..., gt=0)


class AdminReviewRequest(BaseModel):
    decision: DisputeStatus = Field(
        ...,
        description="Must be one of: approved, partial, denied",
    )
    admin_notes: str = Field(..., min_length=5, max_length=2000)
    refund_amount: float | None = Field(
        None,
        ge=0,
        description="Required when decision is approved or partial",
    )
    stripe_refund_id: str | None = None

    @field_validator("decision")
    @classmethod
    def decision_must_be_terminal(cls, v: DisputeStatus) -> DisputeStatus:
        allowed = {DisputeStatus.APPROVED, DisputeStatus.PARTIAL, DisputeStatus.DENIED}
        if v not in allowed:
            raise ValueError("decision must be one of: approved, partial, denied")
        return v


# ---------------------------------------------------------------------------
# Responses
# ---------------------------------------------------------------------------

class FareDisputeResponse(BaseModel):
    id: int
    ride_id: int
    rider_id: int
    category: DisputeCategory
    description: str
    disputed_amount: float
    status: DisputeStatus
    refund_amount: float | None
    admin_notes: str | None
    resolved_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class FareDisputeListResponse(BaseModel):
    disputes: list[FareDisputeResponse]
    total: int
    page: int
    page_size: int


class AdminFareDisputeResponse(FareDisputeResponse):
    """Admin view includes stripe_refund_id and reviewer id."""
    reviewed_by_admin_id: int | None
    stripe_refund_id: str | None


class AdminFareDisputeListResponse(BaseModel):
    disputes: list[AdminFareDisputeResponse]
    total: int
    page: int
    page_size: int


class DisputeSummaryResponse(BaseModel):
    total_disputes: int
    pending: int
    under_review: int
    approved: int
    partial: int
    denied: int
    withdrawn: int
    total_refunded: float
    avg_disputed_amount: float
