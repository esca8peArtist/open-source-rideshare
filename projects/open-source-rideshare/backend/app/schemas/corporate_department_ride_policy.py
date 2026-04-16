"""Pydantic v2 schemas for Corporate Department-Level Ride Policies.

Admins configure per-department overrides to the account-level ride policy.
Override fields that are ``None`` inherit from the account policy.

Public surface
--------------
DepartmentRidePolicySet      — request body for creating/upserting a policy.
DepartmentRidePolicyUpdate   — request body for partial updates.
DepartmentRidePolicyResponse — full policy record returned by the API.
DepartmentRidePolicyListResponse — list of policy records.
EffectiveDepartmentPolicyResponse — merged effective policy for a member
                                     (account → departments → member override).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class DepartmentRidePolicySet(BaseModel):
    """Request body for setting (creating or replacing) a department ride policy.

    All override fields are optional — set only the fields you want to
    constrain for this department.  Fields left as ``None`` inherit the
    account-level policy value.

    Attributes:
        allowed_vehicle_categories: Allowed vehicle types; null = inherit.
        max_per_ride_usd:           Per-ride cost cap; null = inherit.
        require_purpose:            Must employees supply a trip purpose?
                                    null = inherit.
        approved_purposes:          Allowed purpose codes; null = inherit.
        business_hours_only:        Restrict to business hours?
                                    null = inherit.
        notes:                      Admin-facing annotation (max 500 chars).
        is_active:                  Whether the policy takes effect immediately
                                    (default True).
    """

    allowed_vehicle_categories: Optional[List[str]] = None
    max_per_ride_usd: Optional[Decimal] = Field(None, ge=0)
    require_purpose: Optional[bool] = None
    approved_purposes: Optional[List[str]] = None
    business_hours_only: Optional[bool] = None
    notes: Optional[str] = Field(None, max_length=500)
    is_active: bool = True


class DepartmentRidePolicyUpdate(BaseModel):
    """Request body for partially updating a department ride policy.

    All fields are optional.  Only supplied (non-``None``) fields are written.

    To explicitly *remove* a constraint (set it back to inherit), pass the
    sentinel string ``"__clear__"`` for string/list fields or ``-1`` for
    numeric fields — the service layer interprets these as explicit nulls.
    (In practice, clients simply omit unchanged fields and the service merges.)
    """

    allowed_vehicle_categories: Optional[List[str]] = None
    max_per_ride_usd: Optional[Decimal] = Field(None, ge=0)
    require_purpose: Optional[bool] = None
    approved_purposes: Optional[List[str]] = None
    business_hours_only: Optional[bool] = None
    notes: Optional[str] = Field(None, max_length=500)
    is_active: Optional[bool] = None


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class DepartmentRidePolicyResponse(BaseModel):
    """Full department ride policy record returned by the API.

    Attributes:
        id:                          Primary key.
        account_id:                  Corporate account this policy belongs to.
        department_id:               Department this policy governs.
        set_by_id:                   Admin who last set/updated the policy.
        allowed_vehicle_categories:  Override (null = inherits from account).
        max_per_ride_usd:            Override (null = inherits from account).
        require_purpose:             Override (null = inherits from account).
        approved_purposes:           Override (null = inherits from account).
        business_hours_only:         Override (null = inherits from account).
        notes:                       Admin annotation.
        is_active:                   Whether this policy is currently applied.
        created_at:                  Creation timestamp.
        updated_at:                  Last-modified timestamp.
    """

    model_config = {"from_attributes": True}

    id: int
    account_id: int
    department_id: int
    set_by_id: Optional[int]
    allowed_vehicle_categories: Optional[List[str]]
    max_per_ride_usd: Optional[Decimal]
    require_purpose: Optional[bool]
    approved_purposes: Optional[List[str]]
    business_hours_only: Optional[bool]
    notes: Optional[str]
    is_active: bool
    created_at: datetime
    updated_at: datetime


class DepartmentRidePolicyListResponse(BaseModel):
    """List of department ride policy records.

    Attributes:
        items: Policy records.
        total: Number of records returned.
    """

    items: List[DepartmentRidePolicyResponse]
    total: int


# ---------------------------------------------------------------------------
# Effective policy schema
# ---------------------------------------------------------------------------


class EffectiveDepartmentPolicyResponse(BaseModel):
    """Resolved effective ride policy for a specific member.

    Combines all three layers of the policy hierarchy:
      1. Account-level ``CorporateRidePolicy`` (base defaults).
      2. Active ``CorporateDepartmentRidePolicy`` rows for each department the
         member belongs to (most restrictive field value wins across
         departments).
      3. Active ``CorporateMemberPolicyOverride`` for this member (wins over
         everything when set and active).

    Attributes:
        member_id:                    The member whose policy was resolved.
        account_id:                   Corporate account.
        department_ids_applied:       IDs of departments whose policies
                                      contributed to the resolution.
        has_member_override:          Whether a member-level override exists.
        member_override_is_active:    Whether that override is currently active.
        allowed_vehicle_categories:   Resolved vehicle type constraint.
        max_per_ride_usd:             Resolved per-ride cost cap.
        max_per_member_monthly_usd:   Monthly cap (always from account policy).
        require_purpose:              Resolved purpose requirement.
        approved_purposes:            Resolved allowed purposes.
        business_hours_only:          Resolved time-of-day restriction.
    """

    member_id: int
    account_id: int
    department_ids_applied: List[int]
    has_member_override: bool
    member_override_is_active: Optional[bool]
    allowed_vehicle_categories: Optional[List[str]]
    max_per_ride_usd: Optional[Decimal]
    max_per_member_monthly_usd: Optional[Decimal]
    require_purpose: bool
    approved_purposes: Optional[List[str]]
    business_hours_only: bool
