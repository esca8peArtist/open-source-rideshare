"""Corporate Vehicle Inspection Checklist endpoints.

Fleet managers define reusable inspection templates; drivers or fleet managers
submit completed checklists before/after vehicle use.

Member/fleet-manager endpoints:
  GET  /corporate/vehicle-inspections/templates                    — list templates (200)
  GET  /corporate/vehicle-inspections/templates/{template_id}      — get template (200)
  POST /corporate/vehicle-inspections                              — create inspection (201)
  GET  /corporate/vehicle-inspections/{inspection_id}             — get inspection (200)
  POST /corporate/vehicle-inspections/{inspection_id}/submit       — submit inspection (200)
  GET  /corporate/vehicle-inspections                              — list inspections (200)
  GET  /corporate/vehicle-inspections/summary                      — account summary (200)

Admin endpoints:
  POST /corporate/vehicle-inspections/templates                    — create template (201)
  PUT  /corporate/vehicle-inspections/templates/{template_id}      — update template (200)
  POST /corporate/vehicle-inspections/templates/{template_id}/deactivate — deactivate (200)

Platform-admin endpoints:
  GET  /platform/corporate/vehicle-inspections                     — list all inspections (200)
  GET  /platform/corporate/vehicle-inspections/templates           — list all templates (200)
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.models.corporate_vehicle_inspection import InspectionStatus, InspectionType
from app.models.user import User
from app.schemas.corporate_vehicle_inspection import (
    InspectionCreateRequest,
    InspectionListResponse,
    InspectionResponse,
    InspectionSubmitRequest,
    InspectionSummaryResponse,
    InspectionTemplateCreateRequest,
    InspectionTemplateListResponse,
    InspectionTemplateResponse,
    InspectionTemplateUpdateRequest,
)
from app.services.corporate_account_mgmt import get_user_account
from app.services.corporate_vehicle_inspection_service import (
    create_inspection,
    create_template,
    deactivate_template,
    get_account_inspection_summary,
    get_inspection,
    get_template,
    list_all_platform,
    list_all_templates_platform,
    list_templates,
    list_vehicle_inspections,
    submit_inspection,
    update_template,
)
from fastapi import HTTPException

logger = logging.getLogger(__name__)

router = APIRouter(tags=["corporate-vehicle-inspections"])


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _resolve_account_id(db: AsyncSession, user_id: int) -> int:
    account = await get_user_account(db, user_id)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="You are not a member of any corporate account.",
        )
    return account.id


def _to_template_response(tmpl) -> InspectionTemplateResponse:
    return InspectionTemplateResponse.model_validate(tmpl)


def _to_inspection_response(insp) -> InspectionResponse:
    return InspectionResponse.model_validate(insp)


# ---------------------------------------------------------------------------
# Member: summary — declared BEFORE /{inspection_id} to avoid collision
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/vehicle-inspections/summary",
    response_model=InspectionSummaryResponse,
    summary="Member: get aggregate inspection statistics for my corporate account",
)
async def get_my_inspection_summary(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return aggregate inspection statistics for the caller's account."""
    account_id = await _resolve_account_id(db, user.id)
    raw = await get_account_inspection_summary(db, account_id=account_id)
    return InspectionSummaryResponse(
        account_id=raw["account_id"],
        by_status=raw["by_status"],
        by_type=raw["by_type"],
        pass_rate_pct=raw["pass_rate_pct"],
        vehicles_with_pending=raw["vehicles_with_pending"],
        recent_failures=[_to_inspection_response(i) for i in raw["recent_failures"]],
    )


# ---------------------------------------------------------------------------
# Member: list templates
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/vehicle-inspections/templates",
    response_model=InspectionTemplateListResponse,
    summary="Member: list inspection templates for my corporate account",
)
async def list_my_inspection_templates(
    is_active: Optional[bool] = Query(None, description="Filter by active status."),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all inspection templates for the caller's corporate account."""
    account_id = await _resolve_account_id(db, user.id)
    templates = await list_templates(db, account_id=account_id, is_active=is_active)
    return InspectionTemplateListResponse(
        total=len(templates),
        items=[_to_template_response(t) for t in templates],
    )


# ---------------------------------------------------------------------------
# Admin: create template (201)
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/vehicle-inspections/templates",
    response_model=InspectionTemplateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Admin: create a new inspection template",
)
async def create_my_inspection_template(
    data: InspectionTemplateCreateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a reusable inspection template.  Returns 409 on duplicate name."""
    account_id = await _resolve_account_id(db, user.id)
    tmpl = await create_template(
        db,
        account_id=account_id,
        name=data.name,
        description=data.description,
        inspection_items=data.inspection_items,
        created_by_id=user.id,
    )
    await db.commit()
    return _to_template_response(tmpl)


# ---------------------------------------------------------------------------
# Member: get template
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/vehicle-inspections/templates/{template_id}",
    response_model=InspectionTemplateResponse,
    summary="Member: get an inspection template by id",
)
async def get_my_inspection_template(
    template_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a single inspection template."""
    account_id = await _resolve_account_id(db, user.id)
    tmpl = await get_template(db, template_id=template_id, account_id=account_id)
    return _to_template_response(tmpl)


# ---------------------------------------------------------------------------
# Admin: update template
# ---------------------------------------------------------------------------


@router.put(
    "/corporate/vehicle-inspections/templates/{template_id}",
    response_model=InspectionTemplateResponse,
    summary="Admin: update an inspection template",
)
async def update_my_inspection_template(
    template_id: uuid.UUID,
    data: InspectionTemplateUpdateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Partially update an inspection template.  Returns 409 on name collision."""
    account_id = await _resolve_account_id(db, user.id)
    kwargs = {k: v for k, v in data.model_dump().items() if v is not None}
    tmpl = await update_template(
        db, template_id=template_id, account_id=account_id, **kwargs
    )
    await db.commit()
    return _to_template_response(tmpl)


# ---------------------------------------------------------------------------
# Admin: deactivate template
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/vehicle-inspections/templates/{template_id}/deactivate",
    response_model=InspectionTemplateResponse,
    summary="Admin: deactivate an inspection template",
)
async def deactivate_my_inspection_template(
    template_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Mark an inspection template as inactive.  Returns 409 if already inactive."""
    account_id = await _resolve_account_id(db, user.id)
    tmpl = await deactivate_template(
        db, template_id=template_id, account_id=account_id
    )
    await db.commit()
    return _to_template_response(tmpl)


# ---------------------------------------------------------------------------
# Member: list inspections
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/vehicle-inspections",
    response_model=InspectionListResponse,
    summary="Member: list inspections for my corporate account",
)
async def list_my_inspections(
    fleet_vehicle_id: Optional[uuid.UUID] = Query(None),
    inspection_type: Optional[InspectionType] = Query(None),
    inspection_status: Optional[InspectionStatus] = Query(None),
    date_from: Optional[datetime] = Query(None, description="ISO datetime filter (inspected_at >=)"),
    date_to: Optional[datetime] = Query(None, description="ISO datetime filter (inspected_at <=)"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return inspections for the caller's account, newest first."""
    account_id = await _resolve_account_id(db, user.id)
    inspections = await list_vehicle_inspections(
        db,
        account_id=account_id,
        fleet_vehicle_id=fleet_vehicle_id,
        inspection_type=inspection_type,
        inspection_status=inspection_status,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        offset=offset,
    )
    return InspectionListResponse(
        total=len(inspections),
        items=[_to_inspection_response(i) for i in inspections],
    )


# ---------------------------------------------------------------------------
# Member: create inspection (201)
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/vehicle-inspections",
    response_model=InspectionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Member: create a new (pending) vehicle inspection",
)
async def create_my_inspection(
    data: InspectionCreateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a pending inspection for a fleet vehicle.

    Returns 404 if the vehicle is not found.
    Returns 409 if the vehicle is inactive.
    """
    account_id = await _resolve_account_id(db, user.id)
    inspection = await create_inspection(
        db,
        account_id=account_id,
        fleet_vehicle_id=data.fleet_vehicle_id,
        inspection_type=data.inspection_type,
        template_id=data.template_id,
        reservation_id=data.reservation_id,
        created_by_id=user.id,
    )
    await db.commit()
    return _to_inspection_response(inspection)


# ---------------------------------------------------------------------------
# Member: get inspection
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/vehicle-inspections/{inspection_id}",
    response_model=InspectionResponse,
    summary="Member: get an inspection by id",
)
async def get_my_inspection(
    inspection_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a single inspection record."""
    account_id = await _resolve_account_id(db, user.id)
    inspection = await get_inspection(
        db, inspection_id=inspection_id, account_id=account_id
    )
    return _to_inspection_response(inspection)


# ---------------------------------------------------------------------------
# Member: submit inspection
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/vehicle-inspections/{inspection_id}/submit",
    response_model=InspectionResponse,
    summary="Member: submit a completed vehicle inspection",
)
async def submit_my_inspection(
    inspection_id: uuid.UUID,
    data: InspectionSubmitRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Submit a completed inspection.

    Returns 409 if the inspection has already been submitted.
    """
    account_id = await _resolve_account_id(db, user.id)
    inspection = await submit_inspection(
        db,
        inspection_id=inspection_id,
        account_id=account_id,
        items_checked=data.items_checked,
        odometer_miles=data.odometer_miles,
        fuel_level_pct=data.fuel_level_pct,
        overall_notes=data.overall_notes,
        inspected_by_id=user.id,
    )
    await db.commit()
    return _to_inspection_response(inspection)


# ---------------------------------------------------------------------------
# Platform-admin: list all inspections
# ---------------------------------------------------------------------------


@router.get(
    "/platform/corporate/vehicle-inspections",
    response_model=InspectionListResponse,
    summary="Platform admin: list vehicle inspections across all accounts",
)
async def platform_admin_list_inspections(
    account_id: Optional[int] = Query(None),
    inspection_type: Optional[InspectionType] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return vehicle inspections across all accounts (platform admin only)."""
    inspections = await list_all_platform(
        db,
        account_id=account_id,
        inspection_type=inspection_type,
        limit=limit,
        offset=offset,
    )
    return InspectionListResponse(
        total=len(inspections),
        items=[_to_inspection_response(i) for i in inspections],
    )


# ---------------------------------------------------------------------------
# Platform-admin: list all templates
# ---------------------------------------------------------------------------


@router.get(
    "/platform/corporate/vehicle-inspections/templates",
    response_model=InspectionTemplateListResponse,
    summary="Platform admin: list inspection templates across all accounts",
)
async def platform_admin_list_templates(
    account_id: Optional[int] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return inspection templates across all accounts (platform admin only)."""
    templates = await list_all_templates_platform(
        db,
        account_id=account_id,
        limit=limit,
        offset=offset,
    )
    return InspectionTemplateListResponse(
        total=len(templates),
        items=[_to_template_response(t) for t in templates],
    )
