"""Service functions for corporate vehicle inspection checklists.

Fleet managers define reusable inspection templates; drivers or fleet managers
submit completed checklists before/after vehicle use.  Defects are automatically
flagged for maintenance tracking.

Public API
----------
create_template          — create a new inspection template; 409 on duplicate name
get_template             — fetch one template by id; 404 if not found
list_templates           — list templates for an account; optional is_active filter
update_template          — partial update; 409 on name collision with another template
deactivate_template      — soft-deactivate; 409 if already inactive
create_inspection        — create a pending inspection; 404/409 on vehicle issues
get_inspection           — fetch one inspection by id; 404 if not found
submit_inspection        — submit a completed inspection; 409 if not pending
list_vehicle_inspections — multi-filter listing, newest first
get_account_inspection_summary — counts/rates/recent failures for an account
list_all_platform        — platform-admin cross-account listing
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.corporate_fleet_vehicle import CorporateFleetVehicle
from app.models.corporate_vehicle_inspection import (
    CorporateVehicleInspection,
    CorporateVehicleInspectionTemplate,
    InspectionStatus,
    InspectionType,
)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _now_utc() -> datetime:
    return datetime.now(tz=timezone.utc)


async def _get_template_or_404(
    db: AsyncSession,
    template_id: uuid.UUID,
    account_id: int,
) -> CorporateVehicleInspectionTemplate:
    result = await db.execute(
        select(CorporateVehicleInspectionTemplate).where(
            CorporateVehicleInspectionTemplate.id == template_id,
            CorporateVehicleInspectionTemplate.account_id == account_id,
        )
    )
    obj = result.scalar_one_or_none()
    if obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Inspection template not found.",
        )
    return obj


async def _template_name_exists(
    db: AsyncSession,
    account_id: int,
    name: str,
    exclude_id: Optional[uuid.UUID] = None,
) -> bool:
    query = select(CorporateVehicleInspectionTemplate.id).where(
        CorporateVehicleInspectionTemplate.account_id == account_id,
        CorporateVehicleInspectionTemplate.name == name,
    )
    if exclude_id is not None:
        query = query.where(CorporateVehicleInspectionTemplate.id != exclude_id)
    result = await db.execute(query)
    return result.scalar_one_or_none() is not None


async def _get_inspection_or_404(
    db: AsyncSession,
    inspection_id: uuid.UUID,
    account_id: int,
) -> CorporateVehicleInspection:
    result = await db.execute(
        select(CorporateVehicleInspection).where(
            CorporateVehicleInspection.id == inspection_id,
            CorporateVehicleInspection.account_id == account_id,
        )
    )
    obj = result.scalar_one_or_none()
    if obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Inspection not found.",
        )
    return obj


# ---------------------------------------------------------------------------
# Template management
# ---------------------------------------------------------------------------


async def create_template(
    db: AsyncSession,
    account_id: int,
    name: str,
    inspection_items: list,
    created_by_id: Optional[int] = None,
    description: Optional[str] = None,
) -> CorporateVehicleInspectionTemplate:
    """Create a new inspection template.

    Raises 409 if a template with the same *name* already exists for the account.
    """
    if await _template_name_exists(db, account_id, name):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"An inspection template named '{name}' already exists for this account.",
        )

    template = CorporateVehicleInspectionTemplate(
        id=uuid.uuid4(),
        account_id=account_id,
        name=name,
        description=description,
        inspection_items=inspection_items,
        created_by_id=created_by_id,
    )
    db.add(template)
    await db.flush()
    return template


async def get_template(
    db: AsyncSession,
    template_id: uuid.UUID,
    account_id: int,
) -> CorporateVehicleInspectionTemplate:
    """Return a template by id.  Raises 404 if not found."""
    return await _get_template_or_404(db, template_id, account_id)


async def list_templates(
    db: AsyncSession,
    account_id: int,
    is_active: Optional[bool] = None,
) -> list[CorporateVehicleInspectionTemplate]:
    """Return inspection templates for an account, ordered by name.

    Optionally filter by *is_active*.
    """
    query = (
        select(CorporateVehicleInspectionTemplate)
        .where(CorporateVehicleInspectionTemplate.account_id == account_id)
        .order_by(CorporateVehicleInspectionTemplate.name)
    )
    if is_active is not None:
        query = query.where(
            CorporateVehicleInspectionTemplate.is_active == is_active
        )
    result = await db.execute(query)
    return list(result.scalars().all())


async def update_template(
    db: AsyncSession,
    template_id: uuid.UUID,
    account_id: int,
    **kwargs,
) -> CorporateVehicleInspectionTemplate:
    """Partially update an inspection template.

    Raises 409 if the new *name* collides with another template in the account.
    """
    template = await _get_template_or_404(db, template_id, account_id)

    if "name" in kwargs and kwargs["name"] is not None:
        if await _template_name_exists(
            db, account_id, kwargs["name"], exclude_id=template_id
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"An inspection template named '{kwargs['name']}' already exists for this account.",
            )

    for key, value in kwargs.items():
        setattr(template, key, value)

    await db.flush()
    return template


async def deactivate_template(
    db: AsyncSession,
    template_id: uuid.UUID,
    account_id: int,
) -> CorporateVehicleInspectionTemplate:
    """Mark a template inactive.  Raises 409 if already inactive."""
    template = await _get_template_or_404(db, template_id, account_id)
    if not template.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Inspection template is already inactive.",
        )
    template.is_active = False
    await db.flush()
    return template


# ---------------------------------------------------------------------------
# Inspection lifecycle
# ---------------------------------------------------------------------------


async def create_inspection(
    db: AsyncSession,
    account_id: int,
    fleet_vehicle_id: uuid.UUID,
    inspection_type: InspectionType,
    template_id: Optional[uuid.UUID] = None,
    reservation_id: Optional[uuid.UUID] = None,
    created_by_id: Optional[int] = None,
) -> CorporateVehicleInspection:
    """Create a pending inspection for a fleet vehicle.

    Pre-populates *items_checked* from the template's *inspection_items*
    (with ``passed=None`` and ``notes=None``).

    Raises 404 if the fleet vehicle is not found for the account.
    Raises 409 if the fleet vehicle is inactive.
    """
    # Validate fleet vehicle
    vehicle_result = await db.execute(
        select(CorporateFleetVehicle).where(
            CorporateFleetVehicle.id == fleet_vehicle_id,
            CorporateFleetVehicle.account_id == account_id,
        )
    )
    vehicle = vehicle_result.scalar_one_or_none()
    if vehicle is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Fleet vehicle not found.",
        )
    if not vehicle.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot create an inspection for an inactive fleet vehicle.",
        )

    # Pre-populate items_checked from template if provided
    items_checked: list = []
    if template_id is not None:
        tmpl_result = await db.execute(
            select(CorporateVehicleInspectionTemplate).where(
                CorporateVehicleInspectionTemplate.id == template_id,
                CorporateVehicleInspectionTemplate.account_id == account_id,
            )
        )
        tmpl = tmpl_result.scalar_one_or_none()
        if tmpl is not None:
            items_checked = [
                {
                    "item_name": item.get("item_name", ""),
                    "category": item.get("category", ""),
                    "passed": None,
                    "notes": None,
                }
                for item in (tmpl.inspection_items or [])
            ]

    inspection = CorporateVehicleInspection(
        id=uuid.uuid4(),
        template_id=template_id,
        fleet_vehicle_id=fleet_vehicle_id,
        account_id=account_id,
        reservation_id=reservation_id,
        inspection_type=inspection_type,
        inspection_status=InspectionStatus.pending,
        inspected_by_id=created_by_id,
        items_checked=items_checked,
    )
    db.add(inspection)
    await db.flush()
    return inspection


async def get_inspection(
    db: AsyncSession,
    inspection_id: uuid.UUID,
    account_id: int,
) -> CorporateVehicleInspection:
    """Return an inspection by id.  Raises 404 if not found."""
    return await _get_inspection_or_404(db, inspection_id, account_id)


async def submit_inspection(
    db: AsyncSession,
    inspection_id: uuid.UUID,
    account_id: int,
    items_checked: list,
    odometer_miles: Optional[int] = None,
    fuel_level_pct: Optional[int] = None,
    overall_notes: Optional[str] = None,
    inspected_by_id: Optional[int] = None,
) -> CorporateVehicleInspection:
    """Submit a completed inspection.

    Evaluates the overall result:
    - *passed*             — all required items passed (or no required items).
    - *requires_attention* — at least one non-required item failed.
    - *failed*             — at least one required item failed.

    Sets *defects_noted* to a list of ``item_name`` strings for any item with
    ``passed=False``.

    Raises 409 if the inspection is not in *pending* status.
    """
    inspection = await _get_inspection_or_404(db, inspection_id, account_id)

    if inspection.inspection_status != InspectionStatus.pending:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Inspection has already been submitted.",
        )

    # Determine required item names from the template if we have one
    required_item_names: set[str] = set()
    if inspection.template_id is not None:
        tmpl_result = await db.execute(
            select(CorporateVehicleInspectionTemplate).where(
                CorporateVehicleInspectionTemplate.id == inspection.template_id,
            )
        )
        tmpl = tmpl_result.scalar_one_or_none()
        if tmpl is not None:
            for item in (tmpl.inspection_items or []):
                if item.get("is_required", False):
                    required_item_names.add(item.get("item_name", ""))

    # Evaluate pass/fail
    defects: list[str] = []
    has_required_failure = False
    has_optional_failure = False

    for item in items_checked:
        if item.get("passed") is False:
            defects.append(item.get("item_name", ""))
            if item.get("item_name", "") in required_item_names:
                has_required_failure = True
            else:
                has_optional_failure = True

    if has_required_failure:
        new_status = InspectionStatus.failed
    elif has_optional_failure:
        new_status = InspectionStatus.requires_attention
    else:
        new_status = InspectionStatus.passed

    inspection.items_checked = items_checked
    inspection.inspection_status = new_status
    inspection.inspected_at = _now_utc()
    inspection.defects_noted = defects if defects else None
    inspection.odometer_miles = odometer_miles
    inspection.fuel_level_pct = fuel_level_pct
    inspection.overall_notes = overall_notes
    if inspected_by_id is not None:
        inspection.inspected_by_id = inspected_by_id

    await db.flush()
    return inspection


async def list_vehicle_inspections(
    db: AsyncSession,
    account_id: int,
    fleet_vehicle_id: Optional[uuid.UUID] = None,
    inspection_type: Optional[InspectionType] = None,
    inspection_status: Optional[InspectionStatus] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    limit: int = 100,
    offset: int = 0,
) -> list[CorporateVehicleInspection]:
    """Return inspections for an account, newest first.

    Supports filtering by vehicle, type, status, and date range.
    """
    query = (
        select(CorporateVehicleInspection)
        .where(CorporateVehicleInspection.account_id == account_id)
        .order_by(CorporateVehicleInspection.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    if fleet_vehicle_id is not None:
        query = query.where(
            CorporateVehicleInspection.fleet_vehicle_id == fleet_vehicle_id
        )
    if inspection_type is not None:
        query = query.where(
            CorporateVehicleInspection.inspection_type == inspection_type
        )
    if inspection_status is not None:
        query = query.where(
            CorporateVehicleInspection.inspection_status == inspection_status
        )
    if date_from is not None:
        query = query.where(CorporateVehicleInspection.inspected_at >= date_from)
    if date_to is not None:
        query = query.where(CorporateVehicleInspection.inspected_at <= date_to)

    result = await db.execute(query)
    return list(result.scalars().all())


async def get_account_inspection_summary(
    db: AsyncSession,
    account_id: int,
) -> dict:
    """Return aggregate inspection statistics for a corporate account.

    Includes:
    - counts by status
    - counts by type
    - overall pass_rate_pct (submitted inspections only)
    - vehicles_with_pending count
    - recent_failures (last 10 failed/requires_attention inspections)
    """
    # Counts by status
    status_rows = await db.execute(
        select(
            CorporateVehicleInspection.inspection_status,
            func.count(CorporateVehicleInspection.id).label("cnt"),
        )
        .where(CorporateVehicleInspection.account_id == account_id)
        .group_by(CorporateVehicleInspection.inspection_status)
    )
    by_status: dict[str, int] = {}
    total_submitted = 0
    total_passed = 0
    for row in status_rows:
        s, cnt = row
        by_status[s.value] = cnt
        if s != InspectionStatus.pending:
            total_submitted += cnt
        if s == InspectionStatus.passed:
            total_passed += cnt

    # Counts by type
    type_rows = await db.execute(
        select(
            CorporateVehicleInspection.inspection_type,
            func.count(CorporateVehicleInspection.id).label("cnt"),
        )
        .where(CorporateVehicleInspection.account_id == account_id)
        .group_by(CorporateVehicleInspection.inspection_type)
    )
    by_type: dict[str, int] = {row[0].value: row[1] for row in type_rows}

    # Pass rate
    pass_rate_pct: float | None = None
    if total_submitted > 0:
        pass_rate_pct = round(total_passed / total_submitted * 100, 2)

    # Vehicles with pending inspections
    pending_vehicles_result = await db.execute(
        select(
            func.count(
                CorporateVehicleInspection.fleet_vehicle_id.distinct()
            )
        ).where(
            CorporateVehicleInspection.account_id == account_id,
            CorporateVehicleInspection.inspection_status == InspectionStatus.pending,
        )
    )
    vehicles_with_pending: int = pending_vehicles_result.scalar_one()

    # Recent failures (last 10)
    failures_result = await db.execute(
        select(CorporateVehicleInspection)
        .where(
            CorporateVehicleInspection.account_id == account_id,
            CorporateVehicleInspection.inspection_status.in_(
                [InspectionStatus.failed, InspectionStatus.requires_attention]
            ),
        )
        .order_by(CorporateVehicleInspection.inspected_at.desc())
        .limit(10)
    )
    recent_failures = list(failures_result.scalars().all())

    return {
        "account_id": account_id,
        "by_status": by_status,
        "by_type": by_type,
        "pass_rate_pct": pass_rate_pct,
        "vehicles_with_pending": vehicles_with_pending,
        "recent_failures": recent_failures,
    }


async def list_all_platform(
    db: AsyncSession,
    account_id: Optional[int] = None,
    inspection_type: Optional[InspectionType] = None,
    limit: int = 100,
    offset: int = 0,
) -> list[CorporateVehicleInspection]:
    """Platform-admin: list inspections across all accounts.

    Optionally filtered by *account_id* or *inspection_type*.
    """
    query = (
        select(CorporateVehicleInspection)
        .order_by(
            CorporateVehicleInspection.account_id,
            CorporateVehicleInspection.created_at.desc(),
        )
        .limit(limit)
        .offset(offset)
    )
    if account_id is not None:
        query = query.where(CorporateVehicleInspection.account_id == account_id)
    if inspection_type is not None:
        query = query.where(
            CorporateVehicleInspection.inspection_type == inspection_type
        )
    result = await db.execute(query)
    return list(result.scalars().all())


async def list_all_templates_platform(
    db: AsyncSession,
    account_id: Optional[int] = None,
    limit: int = 100,
    offset: int = 0,
) -> list[CorporateVehicleInspectionTemplate]:
    """Platform-admin: list inspection templates across all accounts.

    Optionally filtered by *account_id*.
    """
    query = (
        select(CorporateVehicleInspectionTemplate)
        .order_by(
            CorporateVehicleInspectionTemplate.account_id,
            CorporateVehicleInspectionTemplate.name,
        )
        .limit(limit)
        .offset(offset)
    )
    if account_id is not None:
        query = query.where(
            CorporateVehicleInspectionTemplate.account_id == account_id
        )
    result = await db.execute(query)
    return list(result.scalars().all())
