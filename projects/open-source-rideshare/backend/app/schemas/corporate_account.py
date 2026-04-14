"""Pydantic v2 schemas for corporate/business account endpoints."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from app.models.corporate_account import MembershipStatus


# ---------------------------------------------------------------------------
# Corporate Account schemas
# ---------------------------------------------------------------------------


class CorporateAccountCreateRequest(BaseModel):
    """Body for creating a new corporate account."""

    company_name: str = Field(..., min_length=1, max_length=200)
    billing_email: str = Field(..., min_length=1, max_length=200)
    monthly_limit: float | None = Field(None, gt=0, description="Max monthly spend (NULL = unlimited)")
    per_ride_limit: float | None = Field(None, gt=0, description="Max per-ride cost (NULL = unlimited)")


class CorporateAccountUpdateRequest(BaseModel):
    """Body for partially updating a corporate account."""

    company_name: str | None = Field(None, min_length=1, max_length=200)
    billing_email: str | None = Field(None, min_length=1, max_length=200)
    monthly_limit: float | None = Field(None, gt=0)
    per_ride_limit: float | None = Field(None, gt=0)
    is_active: bool | None = None


class CorporateAccountResponse(BaseModel):
    """Full corporate account detail."""

    id: int
    company_name: str
    billing_email: str
    monthly_limit: float | None
    per_ride_limit: float | None
    is_active: bool
    current_month_spend: float
    current_month: str
    total_spend: float
    created_at: datetime

    model_config = {"from_attributes": True}


class CorporateAccountDetailResponse(CorporateAccountResponse):
    """Corporate account detail enriched with member/ride counts."""

    member_count: int
    total_rides: int


# ---------------------------------------------------------------------------
# Corporate Membership schemas
# ---------------------------------------------------------------------------


class InviteMemberRequest(BaseModel):
    """Body for inviting a user to a corporate account."""

    user_id: int = Field(..., gt=0)
    monthly_limit: float | None = Field(None, gt=0)


class CorporateMembershipResponse(BaseModel):
    """A single corporate membership record."""

    id: int
    account_id: int
    user_id: int
    monthly_limit: float | None
    status: MembershipStatus
    invited_at: datetime
    activated_at: datetime | None

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Spend summary schemas
# ---------------------------------------------------------------------------


class MonthlySpendItem(BaseModel):
    """Spend total for a single calendar month."""

    month: str  # "YYYY-MM"
    total: float


class SpendSummaryResponse(BaseModel):
    """Admin spend summary for a corporate account."""

    account_id: int
    current_month: str
    current_month_spend: float
    monthly_breakdown: list[MonthlySpendItem]


# ---------------------------------------------------------------------------
# Ride listing
# ---------------------------------------------------------------------------


class CorporateRideItem(BaseModel):
    """A ride entry in the admin ride listing for a corporate account."""

    id: int
    rider_id: int
    driver_id: int | None
    status: str
    estimated_fare: float
    actual_fare: float | None
    requested_at: datetime
    completed_at: datetime | None

    model_config = {"from_attributes": True}


class CorporateRideListResponse(BaseModel):
    """Paginated list of rides under a corporate account."""

    items: list[CorporateRideItem]
    total: int
    page: int
    page_size: int
