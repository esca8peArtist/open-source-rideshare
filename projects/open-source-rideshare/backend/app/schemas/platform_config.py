"""Pydantic v2 schemas for the platform config API."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from pydantic import BaseModel, computed_field

# Re-export enums so callers can import from schemas instead of models
from app.models.platform_config import ConfigCategory, ConfigValueType  # noqa: F401


def _parse_typed_value(value: str, value_type: ConfigValueType) -> Any:
    """Parse a raw string into the appropriate Python type."""
    vt = value_type.value if hasattr(value_type, "value") else value_type
    if vt == "string":
        return value
    if vt == "integer":
        try:
            return int(value)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"Cannot parse {value!r} as integer") from exc
    if vt == "float":
        try:
            return float(value)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"Cannot parse {value!r} as float") from exc
    if vt == "boolean":
        normalised = value.strip().lower()
        if normalised in ("true", "1", "yes"):
            return True
        if normalised in ("false", "0", "no"):
            return False
        raise ValueError(f"Cannot parse {value!r} as boolean")
    if vt == "json":
        try:
            return json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Cannot parse {value!r} as JSON") from exc
    # Fallback — treat as string
    return value


class ConfigEntryResponse(BaseModel):
    id: int
    key: str
    value: str
    value_type: ConfigValueType
    category: ConfigCategory
    description: str
    is_active: bool
    updated_at: datetime
    updated_by: int | None

    model_config = {"from_attributes": True}

    @computed_field  # type: ignore[misc]
    @property
    def typed_value(self) -> Any:
        try:
            return _parse_typed_value(self.value, self.value_type)
        except ValueError:
            return self.value


class ConfigEntryUpdate(BaseModel):
    value: str
    reason: str | None = None


class ConfigBulkUpdateItem(BaseModel):
    key: str
    value: str
    reason: str | None = None


class ConfigBulkUpdateRequest(BaseModel):
    updates: list[ConfigBulkUpdateItem]


class ConfigBulkUpdateResponse(BaseModel):
    updated: list[ConfigEntryResponse]
    failed: list[dict]


class ConfigCategoryResponse(BaseModel):
    category: str
    entries: list[ConfigEntryResponse]


class ConfigHistoryEntry(BaseModel):
    id: int
    config_key: str
    old_value: str | None
    new_value: str
    changed_by: int | None
    changed_at: datetime
    reason: str | None

    model_config = {"from_attributes": True}


class ConfigHistoryResponse(BaseModel):
    key: str
    history: list[ConfigHistoryEntry]


class ConfigSeedResponse(BaseModel):
    seeded: int
    skipped: int
