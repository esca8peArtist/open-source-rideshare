"""Pydantic v2 schemas for the Driver Emergency Assistance Fund."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.models.hardship_fund import ApplicationStatus, ApplicationType, ContributionSource


# ---------------------------------------------------------------------------
# Fund balance
# ---------------------------------------------------------------------------


class HardshipFundBalanceResponse(BaseModel):
    """Detailed fund balance — admin only."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    total_balance_usd: Decimal
    total_contributed_usd: Decimal
    total_disbursed_usd: Decimal
    updated_at: datetime


class PublicFundBalanceResponse(BaseModel):
    """Public fund balance — only exposes total available balance."""

    model_config = ConfigDict(from_attributes=True)

    total_balance_usd: Decimal


# ---------------------------------------------------------------------------
# Contributions
# ---------------------------------------------------------------------------


class ContributionRequest(BaseModel):
    source: ContributionSource
    amount_usd: Decimal = Field(gt=0)
    driver_id: int | None = None
    note: str | None = Field(default=None, max_length=500)


class ContributionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source: ContributionSource
    driver_id: int | None
    amount_usd: Decimal
    note: str | None
    created_at: datetime


# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------


class ApplicationCreateRequest(BaseModel):
    application_type: ApplicationType
    description: str = Field(min_length=10, max_length=2000)
    amount_requested_usd: Decimal = Field(gt=0, le=5000)


class ApplicationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    driver_id: int
    application_type: ApplicationType
    description: str
    amount_requested_usd: Decimal
    status: ApplicationStatus
    approved_amount_usd: Decimal | None
    admin_note: str | None
    reviewed_by_id: int | None
    reviewed_at: datetime | None
    disbursed_at: datetime | None
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Review / approval actions
# ---------------------------------------------------------------------------


class ReviewStartRequest(BaseModel):
    """Empty body — just marks the application as under_review."""
    pass


class ApproveApplicationRequest(BaseModel):
    approved_amount_usd: Decimal = Field(gt=0)
    admin_note: str | None = Field(default=None, max_length=1000)


class DenyApplicationRequest(BaseModel):
    admin_note: str = Field(min_length=1, max_length=1000)


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


class FundSummaryResponse(BaseModel):
    """Aggregate overview of the fund — admin only."""

    model_config = ConfigDict(from_attributes=True)

    # Fund balance fields
    id: int
    total_balance_usd: Decimal
    total_contributed_usd: Decimal
    updated_at: datetime

    # Application counts
    total_applications: int
    pending_count: int
    under_review_count: int
    approved_count: int       # approved but not yet disbursed
    disbursed_count: int
    denied_count: int

    # Monetary aggregates
    total_requested_usd: Decimal
    total_approved_usd: Decimal
    total_disbursed_usd: Decimal
