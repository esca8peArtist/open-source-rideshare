"""Pydantic schemas for corporate driver blacklist."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class DriverBlacklistAddRequest(BaseModel):
    """Request body for blacklisting a driver."""

    driver_id: int = Field(..., description="Driver profile ID to blacklist.")
    reason: Optional[str] = Field(
        None, max_length=500, description="Optional reason for blacklisting."
    )


class DriverBlacklistEntryResponse(BaseModel):
    """A single driver blacklist entry."""

    id: int
    account_id: int
    driver_id: int
    is_active: bool
    reason: Optional[str]
    blacklisted_by_id: Optional[int]
    blacklisted_at: datetime

    model_config = {"from_attributes": True}


class DriverBlacklistListResponse(BaseModel):
    """Paginated list of blacklisted driver entries."""

    account_id: int
    total: int
    items: list[DriverBlacklistEntryResponse]


class DriverBlacklistCheckResponse(BaseModel):
    """Result of checking whether a specific driver is blacklisted."""

    account_id: int
    driver_id: int
    is_blacklisted: bool
