"""Pydantic schemas for the ride cancellation policy and fee system.

Separate request/response schemas for riders, drivers, and admin.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.models.cancellation import CancelledBy, FeeChargedTo, FeeStatus


# ---------------------------------------------------------------------------
# Policy schemas
# ---------------------------------------------------------------------------


class CancellationPolicyCreate(BaseModel):
    """Request body for creating or updating the cancellation policy."""

    rider_grace_period_seconds: int = Field(
        120,
        ge=0,
        description="Seconds after booking during which a rider can cancel for free.",
    )
    rider_fee_flat: Decimal = Field(
        Decimal("5.00"),
        ge=0,
        description="Flat fee (USD) charged to rider after grace period.",
    )
    rider_fee_percent: Decimal = Field(
        Decimal("0.0000"),
        ge=0,
        le=1,
        description="Percentage of estimated fare added to rider fee (0.0–1.0).",
    )
    driver_free_cancels_per_day: int = Field(
        3,
        ge=0,
        description="Number of free daily driver cancellations.",
    )
    driver_cancel_penalty: Decimal = Field(
        Decimal("2.00"),
        ge=0,
        description="Penalty (USD) per driver cancellation over the daily limit.",
    )


class CancellationPolicyResponse(BaseModel):
    """Response body for a cancellation policy."""

    id: int
    rider_grace_period_seconds: int
    rider_fee_flat: Decimal
    rider_fee_percent: Decimal
    driver_free_cancels_per_day: int
    driver_cancel_penalty: Decimal
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Cancellation request schemas
# ---------------------------------------------------------------------------


class RiderCancelRequest(BaseModel):
    """Request body for a rider cancelling their ride."""

    reason: str | None = Field(
        None,
        max_length=500,
        description="Optional reason for cancellation.",
    )


class DriverCancelRequest(BaseModel):
    """Request body for a driver cancelling a ride."""

    reason: str | None = Field(
        None,
        max_length=500,
        description="Optional reason for cancellation.",
    )


class WaiveFeeRequest(BaseModel):
    """Request body for an admin waiving a cancellation fee."""

    reason: str = Field(
        ...,
        min_length=1,
        max_length=1000,
        description="Admin-supplied reason for waiving the fee.",
    )


# ---------------------------------------------------------------------------
# Cancellation record response schemas
# ---------------------------------------------------------------------------


class CancellationRecordResponse(BaseModel):
    """Full response body for a cancellation record."""

    id: int
    ride_id: int
    cancelled_by: CancelledBy
    cancellation_reason: str | None
    cancelled_at: datetime
    grace_period_expired: bool
    fee_applied: Decimal
    fee_charged_to: FeeChargedTo
    fee_status: FeeStatus
    waived_by_admin_id: int | None
    waive_reason: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class RiderCancelResponse(BaseModel):
    """Slim response returned to a rider after cancelling."""

    message: str
    fee_applied: Decimal
    grace_expired: bool
    fee_status: FeeStatus
    record_id: int


class DriverCancelResponse(BaseModel):
    """Slim response returned to a driver after cancelling."""

    message: str
    fee_applied: Decimal
    fee_status: FeeStatus
    record_id: int


# ---------------------------------------------------------------------------
# Admin summary schema
# ---------------------------------------------------------------------------


class CancellationSummaryResponse(BaseModel):
    """Aggregate statistics returned by GET /admin/cancellations/summary."""

    total_cancellations: int
    total_fees_assessed_usd: float
    total_fees_pending_usd: float
    total_fees_charged_usd: float
    total_fees_waived_usd: float
    total_fees_refunded_usd: float
    cancellations_by_rider: int
    cancellations_by_driver: int
    cancellations_by_admin: int
    cancellations_by_system: int
