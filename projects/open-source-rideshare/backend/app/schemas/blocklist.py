"""Schemas for the user blocklist feature."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class BlockUserRequest(BaseModel):
    """Request body for blocking a user."""

    blocked_user_id: int = Field(..., description="ID of the user to block")
    reason: str | None = Field(
        None,
        max_length=500,
        description="Optional reason (internal only, not shared with the blocked user)",
    )


class BlocklistEntryResponse(BaseModel):
    """A single blocklist entry as returned to the blocker."""

    id: int
    blocked_user_id: int
    reason: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class AdminBlocklistEntryResponse(BaseModel):
    """Admin view of a blocklist entry — includes both sides."""

    id: int
    blocker_id: int
    blocked_id: int
    reason: str | None
    created_at: datetime

    model_config = {"from_attributes": True}
