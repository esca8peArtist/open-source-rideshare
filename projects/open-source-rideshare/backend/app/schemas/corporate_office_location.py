"""Pydantic schemas for Corporate Office Location & Membership.

Schemas:
  OfficeLocationCreate      — admin POST body to create a new office location
  OfficeLocationUpdate      — admin PUT body for partial updates
  OfficeLocationResponse    — full office location representation
  OfficeLocationListResponse — list of office locations with total count
  OfficeMembershipResponse  — single membership record
  OfficeMembershipListResponse — list of memberships with total count
  OfficeSummaryResponse     — office + member counts
  AssignMemberRequest       — body for assigning a member to an office
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, field_validator


# ---------------------------------------------------------------------------
# Office location schemas
# ---------------------------------------------------------------------------


class OfficeLocationCreate(BaseModel):
    """Fields required to create a new corporate office location."""

    name: str
    description: Optional[str] = None
    address_line1: str
    address_line2: Optional[str] = None
    city: str
    state: str
    postal_code: str
    country: str = "US"
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    default_cost_center_id: Optional[int] = None
    is_headquarters: bool = False

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("name must not be blank")
        return v.strip()

    @field_validator("address_line1")
    @classmethod
    def address_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("address_line1 must not be blank")
        return v.strip()

    @field_validator("city")
    @classmethod
    def city_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("city must not be blank")
        return v.strip()

    @field_validator("state")
    @classmethod
    def state_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("state must not be blank")
        return v.strip()

    @field_validator("postal_code")
    @classmethod
    def postal_code_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("postal_code must not be blank")
        return v.strip()


class OfficeLocationUpdate(BaseModel):
    """Partial update schema — only supplied fields are written."""

    name: Optional[str] = None
    description: Optional[str] = None
    address_line1: Optional[str] = None
    address_line2: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    postal_code: Optional[str] = None
    country: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    default_cost_center_id: Optional[int] = None
    is_headquarters: Optional[bool] = None
    is_active: Optional[bool] = None

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not v.strip():
            raise ValueError("name must not be blank")
        return v.strip() if v is not None else v

    @field_validator("address_line1")
    @classmethod
    def address_not_empty(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not v.strip():
            raise ValueError("address_line1 must not be blank")
        return v.strip() if v is not None else v


class OfficeLocationResponse(BaseModel):
    """Full representation of a corporate office location."""

    model_config = {"from_attributes": True}

    id: uuid.UUID
    account_id: int
    name: str
    description: Optional[str]
    address_line1: str
    address_line2: Optional[str]
    city: str
    state: str
    postal_code: str
    country: str
    latitude: Optional[float]
    longitude: Optional[float]
    default_cost_center_id: Optional[int]
    is_headquarters: bool
    is_active: bool
    created_by_id: Optional[int]
    created_at: datetime
    updated_at: datetime


class OfficeLocationListResponse(BaseModel):
    """List of office locations with total count."""

    items: list[OfficeLocationResponse]
    total: int


# ---------------------------------------------------------------------------
# Membership schemas
# ---------------------------------------------------------------------------


class AssignMemberRequest(BaseModel):
    """Body for assigning a member to an office location."""

    member_id: int
    is_primary: bool = False
    notes: Optional[str] = None


class OfficeMembershipResponse(BaseModel):
    """Single office membership record."""

    model_config = {"from_attributes": True}

    id: uuid.UUID
    office_id: uuid.UUID
    member_id: int
    account_id: int
    is_primary: bool
    assigned_by_id: Optional[int]
    notes: Optional[str]
    is_active: bool
    created_at: datetime


class OfficeMembershipListResponse(BaseModel):
    """List of office memberships with total count."""

    items: list[OfficeMembershipResponse]
    total: int


# ---------------------------------------------------------------------------
# Summary schema
# ---------------------------------------------------------------------------


class OfficeSummaryResponse(BaseModel):
    """Office location details with member count stats."""

    model_config = {"from_attributes": True}

    office: OfficeLocationResponse
    total_members: int
    active_members: int
