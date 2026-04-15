"""Pydantic schemas for corporate preferred driver pool."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class DriverPoolAddRequest(BaseModel):
    """Request body for adding a driver to the preferred pool."""

    driver_id: int = Field(..., description="Driver profile ID to add to the pool.")
    notes: Optional[str] = Field(None, max_length=500, description="Optional admin notes.")


class DriverPoolUpdateRequest(BaseModel):
    """Request body for updating pool entry notes."""

    notes: Optional[str] = Field(None, max_length=500)


class DriverPoolEntryResponse(BaseModel):
    """A single preferred driver pool entry."""

    id: int
    account_id: int
    driver_id: int
    is_active: bool
    notes: Optional[str]
    added_by_id: int
    added_at: datetime

    model_config = {"from_attributes": True}


class DriverPoolListResponse(BaseModel):
    """Paginated list of preferred driver pool entries."""

    account_id: int
    total: int
    items: list[DriverPoolEntryResponse]


class DriverPoolCheckResponse(BaseModel):
    """Result of checking whether a specific driver is in the preferred pool."""

    account_id: int
    driver_id: int
    is_preferred: bool


class DriverPoolStatsResponse(BaseModel):
    """Stats for a driver: how many active corporate accounts prefer them."""

    driver_id: int
    preferred_by_account_count: int
