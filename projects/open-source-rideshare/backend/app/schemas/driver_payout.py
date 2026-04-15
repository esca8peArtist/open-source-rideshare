"""Pydantic schemas for the driver payout / disbursement feature."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.models.driver_payout import DriverPayoutMethod, DriverPayoutStatus


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class PayoutRequestRequest(BaseModel):
    """Payload to request a payout for a given earning period."""

    period_start: date | None = Field(
        default=None,
        description="Start of earning period (inclusive). Defaults to 7 days ago.",
    )
    period_end: date | None = Field(
        default=None,
        description="End of earning period (inclusive). Defaults to today.",
    )
    method: DriverPayoutMethod = Field(
        default=DriverPayoutMethod.stripe_transfer,
        description="Disbursement method.",
    )


class AdminFailPayoutRequest(BaseModel):
    """Admin payload to mark a payout as failed."""

    reason: str = Field(..., description="Human-readable reason for failure.")


class AdminProcessPayoutRequest(BaseModel):
    """Admin payload to process a payout."""

    notes: str | None = Field(default=None, description="Optional admin notes.")


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class DriverPayoutResponse(BaseModel):
    """Payout details returned to a driver."""

    id: int
    driver_id: int
    amount_usd: Decimal
    platform_fee_usd: Decimal
    net_payout_usd: Decimal
    status: DriverPayoutStatus
    method: DriverPayoutMethod
    period_start: date
    period_end: date
    requested_at: datetime
    processed_at: datetime | None
    failed_reason: str | None
    stripe_transfer_id: str | None
    notes: str | None

    model_config = {"from_attributes": True}


class AdminPayoutResponse(DriverPayoutResponse):
    """Extended payout view for admins — same fields, accessed via admin auth."""

    pass


class PendingEarningsResponse(BaseModel):
    """Unpaid earnings summary for a driver over a given period."""

    driver_id: int
    period_start: date
    period_end: date
    gross_usd: Decimal
    platform_fee_usd: Decimal
    net_usd: Decimal
    ride_count: int
    commission_pct: float


class PayoutStatsResponse(BaseModel):
    """Aggregate payout statistics for admin overview."""

    total_pending_usd: Decimal
    total_completed_usd: Decimal
    pending_count: int
    completed_count: int
    failed_count: int
    avg_payout_usd: Decimal
