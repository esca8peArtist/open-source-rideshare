"""Pydantic schemas for corporate vehicle inspection checklists."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from app.models.corporate_vehicle_inspection import InspectionStatus, InspectionType


# ---------------------------------------------------------------------------
# Inspection item sub-schemas
# ---------------------------------------------------------------------------


class InspectionItemDefinition(BaseModel):
    """A single item in an inspection template."""

    item_name: str = Field(..., max_length=200, description="Name of the item to check.")
    category: str = Field(..., max_length=100, description="Category, e.g. 'Lights'.")
    is_required: bool = Field(
        True, description="Whether a failed result marks the whole inspection as failed."
    )


class InspectionItemChecked(BaseModel):
    """A single checked item in a submitted inspection."""

    item_name: str = Field(..., max_length=200)
    category: str = Field(..., max_length=100)
    passed: Optional[bool] = Field(None, description="True=pass, False=fail, None=not checked.")
    notes: Optional[str] = Field(None, max_length=500)


# ---------------------------------------------------------------------------
# Template schemas
# ---------------------------------------------------------------------------


class InspectionTemplateCreateRequest(BaseModel):
    """Request body to create a new inspection template."""

    name: str = Field(..., max_length=100, description="Template name, unique per account.")
    description: Optional[str] = Field(None, max_length=500)
    inspection_items: List[Dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "List of inspection item dicts: "
            "[{item_name, category, is_required}, ...]"
        ),
    )


class InspectionTemplateUpdateRequest(BaseModel):
    """Request body to update an inspection template.  All fields optional."""

    name: Optional[str] = Field(None, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    inspection_items: Optional[List[Dict[str, Any]]] = None
    is_active: Optional[bool] = None


class InspectionTemplateResponse(BaseModel):
    """Full inspection template detail."""

    id: uuid.UUID
    account_id: int
    name: str
    description: Optional[str]
    inspection_items: List[Dict[str, Any]]
    is_active: bool
    created_by_id: Optional[int]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class InspectionTemplateListResponse(BaseModel):
    """List of inspection templates."""

    total: int
    items: List[InspectionTemplateResponse]


# ---------------------------------------------------------------------------
# Inspection schemas
# ---------------------------------------------------------------------------


class InspectionCreateRequest(BaseModel):
    """Request body to create a new (pending) inspection."""

    fleet_vehicle_id: uuid.UUID = Field(..., description="UUID of the fleet vehicle.")
    inspection_type: InspectionType = Field(..., description="pre_trip / post_trip / scheduled / incident.")
    template_id: Optional[uuid.UUID] = Field(
        None, description="Optional template to pre-populate checklist items."
    )
    reservation_id: Optional[uuid.UUID] = Field(
        None, description="Optional reservation this inspection is linked to."
    )


class InspectionSubmitRequest(BaseModel):
    """Request body to submit a completed inspection."""

    items_checked: List[Dict[str, Any]] = Field(
        ...,
        description=(
            "Completed item list: "
            "[{item_name, category, passed: bool|null, notes: str|null}, ...]"
        ),
    )
    odometer_miles: Optional[int] = Field(None, ge=0)
    fuel_level_pct: Optional[int] = Field(None, ge=0, le=100)
    overall_notes: Optional[str] = Field(None, max_length=1000)


class InspectionResponse(BaseModel):
    """Full inspection detail."""

    id: uuid.UUID
    template_id: Optional[uuid.UUID]
    fleet_vehicle_id: uuid.UUID
    account_id: int
    reservation_id: Optional[uuid.UUID]
    inspection_type: InspectionType
    inspection_status: InspectionStatus
    inspected_by_id: Optional[int]
    inspected_at: Optional[datetime]
    odometer_miles: Optional[int]
    fuel_level_pct: Optional[int]
    items_checked: List[Dict[str, Any]]
    defects_noted: Optional[List[str]]
    overall_notes: Optional[str]
    maintenance_log_id: Optional[uuid.UUID]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class InspectionListResponse(BaseModel):
    """Paginated list of inspections."""

    total: int
    items: List[InspectionResponse]


# ---------------------------------------------------------------------------
# Summary schema
# ---------------------------------------------------------------------------


class InspectionSummaryResponse(BaseModel):
    """Aggregate inspection statistics for a corporate account."""

    account_id: int
    by_status: Dict[str, int]
    by_type: Dict[str, int]
    pass_rate_pct: Optional[float]
    vehicles_with_pending: int
    recent_failures: List[InspectionResponse]
