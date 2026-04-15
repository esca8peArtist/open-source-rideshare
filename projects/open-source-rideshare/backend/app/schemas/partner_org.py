"""Pydantic schemas for the Community Partner Organization system.

Partners (hospitals, NGOs, social services) issue ride credits to riders they serve.
Platform admins manage partner accounts; partner admins view their org's activity;
riders see and benefit from credits issued to them.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, EmailStr, Field

from app.models.partner_org import PartnerCreditStatus, PartnerOrgStatus, PartnerOrgType


# ---------------------------------------------------------------------------
# Partner Organization schemas
# ---------------------------------------------------------------------------


class PartnerOrgCreateRequest(BaseModel):
    """Platform admin creates a new partner org account."""

    name: str = Field(..., min_length=1, max_length=255)
    org_type: PartnerOrgType
    contact_name: str = Field(..., min_length=1, max_length=255)
    contact_email: str = Field(..., max_length=255)
    contact_phone: str | None = Field(None, max_length=50)
    partner_admin_user_id: int | None = Field(
        None,
        description="User ID of a platform user who will act as the org's admin contact.",
    )
    monthly_credit_limit_usd: Decimal | None = Field(
        None,
        ge=Decimal("0"),
        description="Monthly credit issuance cap in USD. NULL = no cap.",
    )
    description: str | None = Field(None, max_length=2000)
    admin_note: str | None = Field(None, max_length=2000)


class PartnerOrgUpdateRequest(BaseModel):
    """Platform admin updates an existing partner org."""

    name: str | None = Field(None, min_length=1, max_length=255)
    contact_name: str | None = Field(None, min_length=1, max_length=255)
    contact_email: str | None = Field(None, max_length=255)
    contact_phone: str | None = Field(None, max_length=50)
    partner_admin_user_id: int | None = None
    monthly_credit_limit_usd: Decimal | None = Field(None, ge=Decimal("0"))
    description: str | None = Field(None, max_length=2000)
    admin_note: str | None = Field(None, max_length=2000)


class PartnerOrgResponse(BaseModel):
    """Full representation of a partner org."""

    id: int
    name: str
    org_type: PartnerOrgType
    status: PartnerOrgStatus
    contact_name: str
    contact_email: str
    contact_phone: str | None
    partner_admin_user_id: int | None
    monthly_credit_limit_usd: Decimal | None
    description: str | None
    admin_note: str | None
    created_at: datetime
    updated_at: datetime
    activated_at: datetime | None
    suspended_at: datetime | None

    model_config = {"from_attributes": True}


class PartnerOrgSummaryResponse(BaseModel):
    """Aggregate stats for one partner org."""

    organization_id: int
    organization_name: str
    org_type: PartnerOrgType
    status: PartnerOrgStatus
    total_grants_issued: int
    total_credits_issued_usd: float
    total_credits_used_usd: float
    total_credits_remaining_usd: float
    active_grants: int
    riders_served: int
    rides_funded: int


class PlatformPartnerSummaryResponse(BaseModel):
    """Platform-wide aggregate across all partner orgs."""

    total_organizations: int
    active_organizations: int
    pending_organizations: int
    total_credits_issued_usd: float
    total_credits_used_usd: float
    total_rides_funded: int
    total_riders_served: int


# ---------------------------------------------------------------------------
# Credit Grant schemas
# ---------------------------------------------------------------------------


class PartnerCreditGrantRequest(BaseModel):
    """Platform admin or partner admin issues a credit to a rider."""

    rider_id: int
    amount_usd: Decimal = Field(..., gt=Decimal("0"), description="Total credit amount in USD.")
    per_ride_cap_usd: Decimal | None = Field(
        None,
        gt=Decimal("0"),
        description="Max credit applied per single ride. NULL = no cap.",
    )
    purpose: str | None = Field(
        None,
        max_length=500,
        description="Human-readable reason (e.g. 'Post-discharge medical visits').",
    )
    expiry_date: date | None = Field(
        None,
        description="Date after which the grant expires. NULL = never expires.",
    )


class RevokeGrantRequest(BaseModel):
    """Admin revokes an active credit grant."""

    reason: str = Field(..., min_length=1, max_length=1000)


class PartnerCreditGrantResponse(BaseModel):
    """Full representation of a credit grant."""

    id: int
    organization_id: int
    rider_id: int
    issued_by_admin_id: int | None
    status: PartnerCreditStatus
    amount_usd: Decimal
    amount_used_usd: Decimal
    amount_remaining_usd: Decimal
    per_ride_cap_usd: Decimal | None
    purpose: str | None
    expiry_date: date | None
    revoked_by_admin_id: int | None
    revoke_reason: str | None
    revoked_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Credit Usage schemas
# ---------------------------------------------------------------------------


class PartnerCreditUsageResponse(BaseModel):
    """Record of a grant being applied to one ride."""

    id: int
    grant_id: int
    ride_id: int
    amount_applied_usd: Decimal
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Rider-facing schemas
# ---------------------------------------------------------------------------


class RiderPartnerCreditSummary(BaseModel):
    """Overview of a rider's available partner credits."""

    total_active_grants: int
    total_available_usd: float
    grants: list[PartnerCreditGrantResponse]


class RiderPartnerCreditHistoryItem(BaseModel):
    """One usage record visible to the rider."""

    ride_id: int
    amount_applied_usd: Decimal
    organization_name: str
    purpose: str | None
    used_at: datetime
