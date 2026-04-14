"""Schemas for the platform admin config API."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, field_validator

from app.models.platform_config import ConfigCategory, ConfigValueType


class PlatformConfigEntry(BaseModel):
    """Full representation of a single config entry, including the typed value."""

    key: str
    category: ConfigCategory
    value_type: ConfigValueType
    value: str
    typed_value: Any
    label: str
    description: str | None = None
    updated_at: datetime
    updated_by_id: int | None = None

    model_config = {"from_attributes": True}


class PlatformConfigUpdate(BaseModel):
    """Request body for updating a single config entry."""

    value: str
    description: str | None = None

    @field_validator("value")
    @classmethod
    def value_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("value must not be empty")
        return v


class BulkConfigUpdateItem(BaseModel):
    """A single key/value pair within a bulk update request."""

    key: str
    value: str


class BulkConfigUpdateRequest(BaseModel):
    updates: list[BulkConfigUpdateItem]


class BulkConfigUpdateResult(BaseModel):
    key: str
    success: bool
    error: str | None = None


class BulkConfigUpdateResponse(BaseModel):
    results: list[BulkConfigUpdateResult]
    updated_count: int
    failed_count: int


class PlatformConfigListResponse(BaseModel):
    entries: list[PlatformConfigEntry]
    total: int
