"""Pydantic schemas for corporate member fine-grained permissions."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.models.corporate_member_permission import PermissionScope


class PermissionGrantRequest(BaseModel):
    """Request body for granting a permission scope to a member."""

    member_id: int = Field(..., description="User ID of the member to grant the permission to.")
    permission_scope: PermissionScope = Field(..., description="Named permission scope to grant.")
    expires_at: Optional[datetime] = Field(
        None,
        description="Optional expiry timestamp (UTC).  If omitted the permission does not expire.",
    )
    notes: Optional[str] = Field(
        None, max_length=500, description="Optional admin note explaining the grant."
    )


class PermissionResponse(BaseModel):
    """A single member permission entry."""

    id: int
    account_id: int
    member_id: int
    permission_scope: PermissionScope
    granted_by_id: Optional[int]
    granted_at: datetime
    expires_at: Optional[datetime]
    is_active: bool
    notes: Optional[str]

    model_config = {"from_attributes": True}


class PermissionListResponse(BaseModel):
    """Paginated list of member permission entries."""

    account_id: int
    total: int
    items: list[PermissionResponse]


class PermissionCheckResponse(BaseModel):
    """Result of checking whether a member holds a specific permission scope."""

    account_id: int
    member_id: int
    permission_scope: PermissionScope
    has_permission: bool


class PermissionScopeCount(BaseModel):
    """Count of active grants for a single scope."""

    permission_scope: PermissionScope
    active_count: int


class PermissionSummaryResponse(BaseModel):
    """Summary of active permission grants for an account, grouped by scope."""

    account_id: int
    total_active_grants: int
    by_scope: list[PermissionScopeCount]
