"""Pydantic schemas for Corporate Carpool Groups.

Schemas:
  CarpoolGroupCreate         — POST body to create a carpool group
  CarpoolGroupUpdate         — PUT body for partial updates
  CarpoolGroupResponse       — full group representation
  CarpoolGroupListResponse   — paginated list of groups
  CarpoolMemberCreate        — POST body to add a member
  CarpoolMemberUpdate        — PUT body for partial member updates
  CarpoolMemberResponse      — full member representation
  CarpoolMemberListResponse  — paginated list of members
  CarpoolGroupSummary        — lightweight summary with member counts
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, field_validator


# ---------------------------------------------------------------------------
# Create / update — groups
# ---------------------------------------------------------------------------


class CarpoolGroupCreate(BaseModel):
    """Fields to create a new corporate carpool group."""

    name: str
    description: Optional[str] = None
    max_members: Optional[int] = None
    home_base_address: Optional[str] = None
    home_base_lat: Optional[float] = None
    home_base_lng: Optional[float] = None
    destination_address: Optional[str] = None
    destination_lat: Optional[float] = None
    destination_lng: Optional[float] = None
    departure_time: Optional[str] = None
    days_of_week: Optional[List[int]] = None
    vehicle_type: Optional[str] = None
    cost_center_id: Optional[int] = None
    trip_purpose_id: Optional[int] = None

    @field_validator("name")
    @classmethod
    def name_max_length(cls, v: str) -> str:
        if len(v) > 120:
            raise ValueError("name must be at most 120 characters")
        return v

    @field_validator("max_members")
    @classmethod
    def max_members_positive(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v < 1:
            raise ValueError("max_members must be at least 1")
        return v

    @field_validator("departure_time")
    @classmethod
    def departure_time_format(cls, v: Optional[str]) -> Optional[str]:
        import re
        if v is not None and not re.match(r"^\d{2}:\d{2}$", v):
            raise ValueError("departure_time must be in HH:MM format")
        return v

    @field_validator("vehicle_type")
    @classmethod
    def vehicle_type_max_length(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and len(v) > 50:
            raise ValueError("vehicle_type must be at most 50 characters")
        return v


class CarpoolGroupUpdate(BaseModel):
    """All fields optional for partial updates to a carpool group."""

    name: Optional[str] = None
    description: Optional[str] = None
    max_members: Optional[int] = None
    home_base_address: Optional[str] = None
    home_base_lat: Optional[float] = None
    home_base_lng: Optional[float] = None
    destination_address: Optional[str] = None
    destination_lat: Optional[float] = None
    destination_lng: Optional[float] = None
    departure_time: Optional[str] = None
    days_of_week: Optional[List[int]] = None
    vehicle_type: Optional[str] = None
    cost_center_id: Optional[int] = None
    trip_purpose_id: Optional[int] = None

    @field_validator("name")
    @classmethod
    def name_max_length(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and len(v) > 120:
            raise ValueError("name must be at most 120 characters")
        return v

    @field_validator("max_members")
    @classmethod
    def max_members_positive(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v < 1:
            raise ValueError("max_members must be at least 1")
        return v

    @field_validator("departure_time")
    @classmethod
    def departure_time_format(cls, v: Optional[str]) -> Optional[str]:
        import re
        if v is not None and not re.match(r"^\d{2}:\d{2}$", v):
            raise ValueError("departure_time must be in HH:MM format")
        return v

    @field_validator("vehicle_type")
    @classmethod
    def vehicle_type_max_length(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and len(v) > 50:
            raise ValueError("vehicle_type must be at most 50 characters")
        return v


# ---------------------------------------------------------------------------
# Response schemas — groups
# ---------------------------------------------------------------------------


class CarpoolGroupResponse(BaseModel):
    """Full representation of a corporate carpool group."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    account_id: int
    name: str
    description: Optional[str] = None
    max_members: Optional[int] = None
    home_base_address: Optional[str] = None
    home_base_lat: Optional[float] = None
    home_base_lng: Optional[float] = None
    destination_address: Optional[str] = None
    destination_lat: Optional[float] = None
    destination_lng: Optional[float] = None
    departure_time: Optional[str] = None
    days_of_week: Optional[List[int]] = None
    vehicle_type: Optional[str] = None
    cost_center_id: Optional[int] = None
    trip_purpose_id: Optional[int] = None
    is_active: bool
    created_by_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime


class CarpoolGroupListResponse(BaseModel):
    """Paginated list of corporate carpool groups."""

    items: List[CarpoolGroupResponse]
    total: int


# ---------------------------------------------------------------------------
# Create / update — members
# ---------------------------------------------------------------------------


class CarpoolMemberCreate(BaseModel):
    """Fields to enroll an employee in a carpool group."""

    member_id: int
    pickup_address: Optional[str] = None
    pickup_lat: Optional[float] = None
    pickup_lng: Optional[float] = None
    pickup_sequence: Optional[int] = None
    notes: Optional[str] = None

    @field_validator("pickup_sequence")
    @classmethod
    def pickup_sequence_positive(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v < 1:
            raise ValueError("pickup_sequence must be at least 1")
        return v


class CarpoolMemberUpdate(BaseModel):
    """All fields optional for partial updates to a carpool membership."""

    pickup_address: Optional[str] = None
    pickup_lat: Optional[float] = None
    pickup_lng: Optional[float] = None
    pickup_sequence: Optional[int] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None


# ---------------------------------------------------------------------------
# Response schemas — members
# ---------------------------------------------------------------------------


class CarpoolMemberResponse(BaseModel):
    """Full representation of a carpool group membership."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    carpool_group_id: uuid.UUID
    account_id: int
    member_id: int
    pickup_address: Optional[str] = None
    pickup_lat: Optional[float] = None
    pickup_lng: Optional[float] = None
    pickup_sequence: Optional[int] = None
    is_active: bool
    added_by_id: Optional[int] = None
    notes: Optional[str] = None
    joined_at: datetime


class CarpoolMemberListResponse(BaseModel):
    """Paginated list of carpool group members."""

    items: List[CarpoolMemberResponse]
    total: int


# ---------------------------------------------------------------------------
# Summary schema
# ---------------------------------------------------------------------------


class CarpoolGroupSummary(BaseModel):
    """Lightweight summary of a carpool group with member counts.

    Attributes:
        group_id: UUID of the group.
        name: Display name.
        total_members: All membership records (active and inactive).
        active_members: Only currently active members.
        has_destination: True if destination_address is set.
        has_departure_time: True if departure_time is set.
        days_of_week: Operating days list, or None if not configured.
    """

    group_id: uuid.UUID
    name: str
    total_members: int
    active_members: int
    has_destination: bool
    has_departure_time: bool
    days_of_week: Optional[List[int]] = None
