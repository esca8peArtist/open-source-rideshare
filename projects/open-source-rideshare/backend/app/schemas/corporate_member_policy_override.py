"""Pydantic schemas for the Corporate Member Policy Override API."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class MemberPolicyOverrideCreate(BaseModel):
    """Request body for creating a per-member policy override.

    All override fields are optional.  A ``None`` value means "inherit
    from the account policy" for that dimension.  Only the fields that
    differ from the account policy need to be specified.
    """

    member_id: int

    allowed_vehicle_categories: list[str] | None = None
    max_per_ride_usd: Decimal | None = None
    require_purpose: bool | None = None
    approved_purposes: list[str] | None = None
    business_hours_only: bool | None = None

    reason: str | None = Field(None, max_length=300)
    custom_notes: str | None = Field(None, max_length=500)
    valid_until: datetime | None = None


class MemberPolicyOverrideUpdate(BaseModel):
    """Request body for updating an existing per-member policy override.

    All fields are optional.  Only supplied (non-None) fields are written.
    To explicitly clear a boolean or list override field, supply the value
    as ``null`` in the JSON body — this will be interpreted as "revert to
    account policy default" for that dimension.
    """

    allowed_vehicle_categories: list[str] | None = None
    max_per_ride_usd: Decimal | None = None
    require_purpose: bool | None = None
    approved_purposes: list[str] | None = None
    business_hours_only: bool | None = None
    reason: str | None = None
    custom_notes: str | None = None
    valid_until: datetime | None = None
    is_active: bool | None = None


class MemberPolicyOverrideResponse(BaseModel):
    """Per-member policy override as returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    account_id: int
    member_id: int
    overridden_by_id: int | None

    allowed_vehicle_categories: list[str] | None
    max_per_ride_usd: Decimal | None
    require_purpose: bool | None
    approved_purposes: list[str] | None
    business_hours_only: bool | None
    reason: str | None
    custom_notes: str | None

    is_active: bool
    valid_from: datetime
    valid_until: datetime | None

    created_at: datetime
    updated_at: datetime


class MemberPolicyOverrideListResponse(BaseModel):
    """Paginated list of per-member policy overrides."""

    overrides: list[MemberPolicyOverrideResponse]
    total: int


class EffectivePolicyResponse(BaseModel):
    """Merged effective ride policy for a specific member.

    Combines the account-level ``CorporateRidePolicy`` with any active
    per-member ``CorporateMemberPolicyOverride``.  Override fields take
    precedence when the override row exists, is active (``is_active=True``),
    and the field is not ``None`` in the override row.

    ``max_per_member_monthly_usd`` is always sourced from the account policy
    (not overridable at per-member level — that would be circular).
    """

    member_id: int
    account_id: int
    has_override: bool
    override_is_active: bool | None  # None when no override row exists

    # Effective values after merging
    allowed_vehicle_categories: list[str] | None
    max_per_ride_usd: Decimal | None
    max_per_member_monthly_usd: Decimal | None  # always from account policy
    require_purpose: bool
    approved_purposes: list[str] | None
    business_hours_only: bool
