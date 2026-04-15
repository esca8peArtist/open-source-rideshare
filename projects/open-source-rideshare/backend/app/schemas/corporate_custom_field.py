"""Pydantic schemas for Corporate Custom Ride Fields."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.corporate_custom_field import CustomFieldType


# ---------------------------------------------------------------------------
# Field definition CRUD
# ---------------------------------------------------------------------------


class CustomFieldCreate(BaseModel):
    """Payload for creating a new custom ride field."""

    label: str = Field(..., min_length=1, max_length=200, description="Human-readable label shown to employees.")
    field_key: Optional[str] = Field(
        None,
        max_length=100,
        description=(
            "Machine-readable slug unique per account (e.g. 'project_code').  "
            "Auto-derived from label if omitted.  Only lowercase letters, digits, "
            "and underscores are allowed."
        ),
    )
    field_type: CustomFieldType = Field(..., description="Data type: text, number, dropdown, or checkbox.")
    dropdown_options: Optional[list[str]] = Field(
        None,
        description="Required when field_type is 'dropdown'.  List of selectable options.",
    )
    is_required: bool = Field(False, description="When True, a value must be provided on every corporate ride.")
    max_length: Optional[int] = Field(
        None,
        ge=1,
        le=10000,
        description="Maximum character length for text fields.  Ignored for other types.",
    )
    display_order: int = Field(0, ge=0, description="Ascending sort order in the UI.")

    @field_validator("field_key", mode="before")
    @classmethod
    def validate_field_key(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.lower().strip()
        if not re.match(r"^[a-z0-9_]+$", v):
            raise ValueError("field_key may only contain lowercase letters, digits, and underscores.")
        return v

    @model_validator(mode="after")
    def check_dropdown_options(self) -> CustomFieldCreate:
        if self.field_type == CustomFieldType.DROPDOWN:
            if not self.dropdown_options:
                raise ValueError("dropdown_options is required when field_type is 'dropdown'.")
            if len(self.dropdown_options) < 1:
                raise ValueError("dropdown_options must contain at least one option.")
        else:
            if self.dropdown_options:
                raise ValueError("dropdown_options should only be set when field_type is 'dropdown'.")
        return self


class CustomFieldUpdate(BaseModel):
    """Payload for updating a custom ride field.  All fields are optional.

    The field_key and field_type are immutable after creation.
    """

    label: Optional[str] = Field(None, min_length=1, max_length=200)
    dropdown_options: Optional[list[str]] = Field(
        None,
        description="Replace the dropdown options list.  Only valid for dropdown fields.",
    )
    is_required: Optional[bool] = None
    max_length: Optional[int] = Field(None, ge=1, le=10000)
    display_order: Optional[int] = Field(None, ge=0)
    is_active: Optional[bool] = None


class CustomFieldResponse(BaseModel):
    """Full representation of a custom ride field definition."""

    id: int
    account_id: int
    label: str
    field_key: str
    field_type: CustomFieldType
    dropdown_options: Optional[list[str]]
    is_required: bool
    max_length: Optional[int]
    display_order: int
    is_active: bool
    created_by_id: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CustomFieldListResponse(BaseModel):
    """Paginated list of custom fields for a corporate account."""

    account_id: int
    total: int
    fields: list[CustomFieldResponse]


# ---------------------------------------------------------------------------
# Ride field values
# ---------------------------------------------------------------------------


class RideFieldValueSet(BaseModel):
    """Payload for setting a custom field value on a ride."""

    value: str = Field(..., min_length=0, max_length=10000, description="Value to store (always serialised as text).")


class RideFieldValueResponse(BaseModel):
    """A custom field value recorded on a ride, with field metadata."""

    id: int
    field_id: int
    ride_id: int
    field_label: str
    field_key: str
    field_type: CustomFieldType
    value: str
    set_by_id: int
    set_at: datetime

    model_config = {"from_attributes": True}


class RideFieldValuesResponse(BaseModel):
    """All custom field values recorded on a specific ride."""

    ride_id: int
    values: list[RideFieldValueResponse]
