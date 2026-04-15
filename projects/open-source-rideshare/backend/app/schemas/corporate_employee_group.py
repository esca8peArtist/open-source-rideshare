"""Pydantic schemas for Corporate Employee Groups."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Group schemas
# ---------------------------------------------------------------------------


class GroupCreate(BaseModel):
    """Request body for creating a new employee group."""

    name: str = Field(..., min_length=1, max_length=100, description="Display name for the group.")
    description: Optional[str] = Field(None, max_length=500, description="Optional description.")
    color: Optional[str] = Field(
        None, max_length=7, description="Hex colour for UI display, e.g. '#FF5733'."
    )


class GroupUpdate(BaseModel):
    """Request body for updating an existing employee group."""

    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    color: Optional[str] = Field(None, max_length=7)
    is_active: Optional[bool] = None


class GroupResponse(BaseModel):
    """A single employee group."""

    id: int
    account_id: int
    name: str
    description: Optional[str]
    color: Optional[str]
    is_active: bool
    created_by_id: Optional[int]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class GroupListResponse(BaseModel):
    """Paginated list of employee groups."""

    account_id: int
    total: int
    items: list[GroupResponse]


# ---------------------------------------------------------------------------
# Membership schemas
# ---------------------------------------------------------------------------


class AddMemberToGroupRequest(BaseModel):
    """Request body for adding a member to a group."""

    member_id: int = Field(..., description="BusinessAccountMember ID to add to the group.")


class MembershipResponse(BaseModel):
    """A single group membership record."""

    id: int
    group_id: int
    member_id: int
    added_by_id: Optional[int]
    created_at: datetime

    model_config = {"from_attributes": True}


class GroupMembersResponse(BaseModel):
    """Paginated list of memberships for a group."""

    group_id: int
    total: int
    items: list[MembershipResponse]


class MemberGroupsResponse(BaseModel):
    """All groups a member belongs to."""

    member_id: int
    items: list[GroupResponse]


# ---------------------------------------------------------------------------
# Stats schema
# ---------------------------------------------------------------------------


class GroupStatsResponse(BaseModel):
    """Aggregate statistics for a single group."""

    group_id: int
    name: str
    member_count: int
    active_members: int
    created_at: datetime
