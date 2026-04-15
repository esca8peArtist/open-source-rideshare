"""Pydantic v2 schemas for the corporate business accounts feature."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, EmailStr, Field

from app.models.corporate import CorporateAccountStatus, InvoiceStatus, MemberRole


# ---------------------------------------------------------------------------
# CorporateAccount schemas
# ---------------------------------------------------------------------------


class CorporateAccountCreate(BaseModel):
    """Request body for creating a new corporate account."""

    name: str = Field(..., min_length=1, max_length=200, description="Company display name")
    billing_email: str = Field(..., min_length=1, max_length=254, description="Billing contact email")
    tax_id: str | None = Field(None, max_length=100, description="Optional tax / VAT identifier")
    billing_address: str | None = Field(None, max_length=500, description="Optional postal billing address")
    monthly_budget_limit: Decimal | None = Field(
        None, gt=0, description="Optional platform-wide monthly spend cap (NULL = unlimited)"
    )


class CorporateAccountUpdate(BaseModel):
    """Request body for updating a corporate account (all fields optional)."""

    name: str | None = Field(None, min_length=1, max_length=200)
    billing_email: str | None = Field(None, min_length=1, max_length=254)
    tax_id: str | None = Field(None, max_length=100)
    billing_address: str | None = Field(None, max_length=500)
    monthly_budget_limit: Decimal | None = Field(None, gt=0)


class CorporateAccountResponse(BaseModel):
    """Response for a corporate account, including member count."""

    id: int
    name: str
    billing_email: str
    tax_id: str | None
    billing_address: str | None
    status: CorporateAccountStatus
    monthly_budget_limit: Decimal | None
    created_at: datetime
    updated_at: datetime
    member_count: int = 0

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# CorporateAccountMember schemas
# ---------------------------------------------------------------------------


class CorporateAccountMemberAdd(BaseModel):
    """Request body for adding a member to a corporate account."""

    user_id: int = Field(..., gt=0, description="ID of the user to add")
    role: MemberRole = Field(MemberRole.MEMBER, description="Role within the account")
    monthly_spend_limit: Decimal | None = Field(
        None, gt=0, description="Optional per-member monthly cap (NULL = no cap)"
    )


class CorporateAccountMemberUpdate(BaseModel):
    """Request body for updating a member (all fields optional)."""

    role: MemberRole | None = None
    monthly_spend_limit: Decimal | None = Field(None, gt=0)
    is_active: bool | None = None


class CorporateAccountMemberResponse(BaseModel):
    """Response for a corporate account member, enriched with user info."""

    id: int
    account_id: int
    user_id: int
    role: MemberRole
    monthly_spend_limit: Decimal | None
    is_active: bool
    joined_at: datetime
    user_email: str | None = None
    user_name: str | None = None

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# CorporateInvoice schemas
# ---------------------------------------------------------------------------


class InvoiceGenerateRequest(BaseModel):
    """Request body for generating a new invoice for a billing period."""

    period_start: date = Field(..., description="First day of the billing period")
    period_end: date = Field(..., description="Last day of the billing period")


class CorporateInvoiceResponse(BaseModel):
    """Response for a corporate invoice."""

    id: int
    account_id: int
    billing_period_start: date
    billing_period_end: date
    total_rides: int
    total_amount: Decimal
    status: InvoiceStatus
    issued_at: datetime | None
    paid_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Spend summary
# ---------------------------------------------------------------------------


class CorporateSpendSummary(BaseModel):
    """Summary of current-month spend for a corporate account."""

    account_id: int
    account_name: str
    current_month_spend: Decimal
    member_count: int
    monthly_budget_limit: Decimal | None
    budget_utilization_pct: float | None = Field(
        None, description="Percentage of monthly budget used (NULL if no budget set)"
    )


# ---------------------------------------------------------------------------
# Platform-wide admin summary
# ---------------------------------------------------------------------------


class CorporatePlatformSummary(BaseModel):
    """Platform-wide summary of corporate accounts."""

    total_accounts: int
    accounts_by_status: dict[str, int]
    total_members: int
    revenue_this_month: Decimal
