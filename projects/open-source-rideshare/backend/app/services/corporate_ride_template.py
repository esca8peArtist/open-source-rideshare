"""Service layer for Corporate Ride Templates.

Corporate admins define named, reusable booking configurations — saved routes
with pre-filled pickup/dropoff addresses, preferred vehicle type, and default
cost centre / trip purpose.  Employees browse templates and get pre-filled
data when booking, reducing friction for frequent corporate trips.

Public surface
--------------
create_ride_template(db, account_id, created_by_id, data) -> RideTemplateResponse
get_ride_template(db, template_id, account_id) -> RideTemplateResponse
list_ride_templates(db, account_id, is_active) -> RideTemplateListResponse
update_ride_template(db, template_id, account_id, data) -> RideTemplateResponse
deactivate_ride_template(db, template_id, account_id) -> RideTemplateResponse
reactivate_ride_template(db, template_id, account_id) -> RideTemplateResponse
delete_ride_template(db, template_id, account_id) -> None
record_template_use(db, template_id, account_id) -> RideTemplateResponse
get_popular_templates(db, account_id, limit) -> RideTemplateListResponse
list_all_platform(db, account_id) -> RideTemplateListResponse
"""

from __future__ import annotations

from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.corporate_ride_template import CorporateRideTemplate
from app.schemas.corporate_ride_template import (
    RideTemplateCreate,
    RideTemplateListResponse,
    RideTemplateResponse,
    RideTemplateUpdate,
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _to_response(template: CorporateRideTemplate) -> RideTemplateResponse:
    """Convert a CorporateRideTemplate model instance to RideTemplateResponse."""
    return RideTemplateResponse(
        id=template.id,
        account_id=template.account_id,
        created_by_id=template.created_by_id,
        name=template.name,
        description=template.description,
        pickup_location_name=template.pickup_location_name,
        pickup_address_line1=template.pickup_address_line1,
        pickup_address_line2=template.pickup_address_line2,
        pickup_city=template.pickup_city,
        pickup_state=template.pickup_state,
        pickup_country=template.pickup_country,
        pickup_postal_code=template.pickup_postal_code,
        pickup_latitude=float(template.pickup_latitude)
        if template.pickup_latitude is not None
        else None,
        pickup_longitude=float(template.pickup_longitude)
        if template.pickup_longitude is not None
        else None,
        dropoff_location_name=template.dropoff_location_name,
        dropoff_address_line1=template.dropoff_address_line1,
        dropoff_address_line2=template.dropoff_address_line2,
        dropoff_city=template.dropoff_city,
        dropoff_state=template.dropoff_state,
        dropoff_country=template.dropoff_country,
        dropoff_postal_code=template.dropoff_postal_code,
        dropoff_latitude=float(template.dropoff_latitude)
        if template.dropoff_latitude is not None
        else None,
        dropoff_longitude=float(template.dropoff_longitude)
        if template.dropoff_longitude is not None
        else None,
        vehicle_type=template.vehicle_type,
        default_cost_center_id=template.default_cost_center_id,
        default_trip_purpose_id=template.default_trip_purpose_id,
        notes=template.notes,
        use_count=template.use_count,
        is_active=template.is_active,
        created_at=template.created_at,
        updated_at=template.updated_at,
    )


async def _get_template_or_404(
    db: AsyncSession, template_id: int, account_id: int
) -> CorporateRideTemplate:
    """Fetch a template by ID scoped to the account; raise 404 if not found."""
    result = await db.execute(
        select(CorporateRideTemplate).where(
            CorporateRideTemplate.id == template_id,
            CorporateRideTemplate.account_id == account_id,
        )
    )
    template = result.scalar_one_or_none()
    if template is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ride template not found.",
        )
    return template


async def _check_name_conflict(
    db: AsyncSession,
    account_id: int,
    name: str,
    exclude_id: Optional[int] = None,
) -> None:
    """Raise 409 if another active template with the same name exists in the account."""
    stmt = select(CorporateRideTemplate).where(
        CorporateRideTemplate.account_id == account_id,
        CorporateRideTemplate.name == name,
    )
    if exclude_id is not None:
        stmt = stmt.where(CorporateRideTemplate.id != exclude_id)
    result = await db.execute(stmt)
    if result.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A ride template named '{name}' already exists for this account.",
        )


# ---------------------------------------------------------------------------
# Public service functions
# ---------------------------------------------------------------------------


async def create_ride_template(
    db: AsyncSession,
    account_id: int,
    created_by_id: Optional[int],
    data: RideTemplateCreate,
) -> RideTemplateResponse:
    """Create a new corporate ride template.

    Raises 409 if a template with the same name already exists in the account.
    """
    await _check_name_conflict(db, account_id, data.name)

    template = CorporateRideTemplate(
        account_id=account_id,
        created_by_id=created_by_id,
        name=data.name,
        description=data.description,
        pickup_location_name=data.pickup_location_name,
        pickup_address_line1=data.pickup_address_line1,
        pickup_address_line2=data.pickup_address_line2,
        pickup_city=data.pickup_city,
        pickup_state=data.pickup_state,
        pickup_country=data.pickup_country,
        pickup_postal_code=data.pickup_postal_code,
        pickup_latitude=data.pickup_latitude,
        pickup_longitude=data.pickup_longitude,
        dropoff_location_name=data.dropoff_location_name,
        dropoff_address_line1=data.dropoff_address_line1,
        dropoff_address_line2=data.dropoff_address_line2,
        dropoff_city=data.dropoff_city,
        dropoff_state=data.dropoff_state,
        dropoff_country=data.dropoff_country,
        dropoff_postal_code=data.dropoff_postal_code,
        dropoff_latitude=data.dropoff_latitude,
        dropoff_longitude=data.dropoff_longitude,
        vehicle_type=data.vehicle_type,
        default_cost_center_id=data.default_cost_center_id,
        default_trip_purpose_id=data.default_trip_purpose_id,
        notes=data.notes,
        use_count=0,
        is_active=True,
    )
    db.add(template)
    await db.commit()
    await db.refresh(template)
    return _to_response(template)


async def get_ride_template(
    db: AsyncSession,
    template_id: int,
    account_id: int,
) -> RideTemplateResponse:
    """Return a single ride template by ID, scoped to the account."""
    template = await _get_template_or_404(db, template_id, account_id)
    return _to_response(template)


async def list_ride_templates(
    db: AsyncSession,
    account_id: int,
    is_active: Optional[bool] = None,
) -> RideTemplateListResponse:
    """Return all ride templates for an account, optionally filtered by status."""
    stmt = select(CorporateRideTemplate).where(
        CorporateRideTemplate.account_id == account_id
    )
    if is_active is not None:
        stmt = stmt.where(CorporateRideTemplate.is_active == is_active)
    stmt = stmt.order_by(CorporateRideTemplate.name)

    result = await db.execute(stmt)
    templates = result.scalars().all()
    return RideTemplateListResponse(
        items=[_to_response(t) for t in templates],
        total=len(templates),
    )


async def update_ride_template(
    db: AsyncSession,
    template_id: int,
    account_id: int,
    data: RideTemplateUpdate,
) -> RideTemplateResponse:
    """Partially update a ride template.

    Only fields explicitly supplied in the request body are written.
    Raises 409 on name collision with another template in the same account.
    """
    template = await _get_template_or_404(db, template_id, account_id)

    update_data = data.model_dump(exclude_unset=True)

    if "name" in update_data and update_data["name"] != template.name:
        await _check_name_conflict(db, account_id, update_data["name"], exclude_id=template_id)

    for field, value in update_data.items():
        setattr(template, field, value)

    await db.commit()
    await db.refresh(template)
    return _to_response(template)


async def deactivate_ride_template(
    db: AsyncSession,
    template_id: int,
    account_id: int,
) -> RideTemplateResponse:
    """Soft-deactivate a ride template.

    Raises 409 if the template is already inactive.
    """
    template = await _get_template_or_404(db, template_id, account_id)
    if not template.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ride template is already inactive.",
        )
    template.is_active = False
    await db.commit()
    await db.refresh(template)
    return _to_response(template)


async def reactivate_ride_template(
    db: AsyncSession,
    template_id: int,
    account_id: int,
) -> RideTemplateResponse:
    """Reactivate an inactive ride template.

    Raises 409 if the template is already active.
    """
    template = await _get_template_or_404(db, template_id, account_id)
    if template.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ride template is already active.",
        )
    template.is_active = True
    await db.commit()
    await db.refresh(template)
    return _to_response(template)


async def delete_ride_template(
    db: AsyncSession,
    template_id: int,
    account_id: int,
) -> None:
    """Hard-delete a ride template.

    Raises 404 if the template does not exist in the account.
    """
    template = await _get_template_or_404(db, template_id, account_id)
    await db.delete(template)
    await db.commit()


async def record_template_use(
    db: AsyncSession,
    template_id: int,
    account_id: int,
) -> RideTemplateResponse:
    """Increment the use_count for a template (called when an employee books from it).

    Raises 404 if the template does not exist.
    Raises 409 if the template is inactive (cannot use an inactive template).
    """
    template = await _get_template_or_404(db, template_id, account_id)
    if not template.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot record use for an inactive ride template.",
        )
    template.use_count = (template.use_count or 0) + 1
    await db.commit()
    await db.refresh(template)
    return _to_response(template)


async def get_popular_templates(
    db: AsyncSession,
    account_id: int,
    limit: int = 10,
) -> RideTemplateListResponse:
    """Return the most-used active templates for the account, ordered by use_count desc."""
    stmt = (
        select(CorporateRideTemplate)
        .where(
            CorporateRideTemplate.account_id == account_id,
            CorporateRideTemplate.is_active == True,  # noqa: E712
        )
        .order_by(CorporateRideTemplate.use_count.desc(), CorporateRideTemplate.name)
        .limit(limit)
    )
    result = await db.execute(stmt)
    templates = result.scalars().all()

    # total = all active templates (not just the page)
    count_result = await db.execute(
        select(func.count()).where(
            CorporateRideTemplate.account_id == account_id,
            CorporateRideTemplate.is_active == True,  # noqa: E712
        )
    )
    total = count_result.scalar_one()

    return RideTemplateListResponse(
        items=[_to_response(t) for t in templates],
        total=total,
    )


async def list_all_platform(
    db: AsyncSession,
    account_id: Optional[int] = None,
) -> RideTemplateListResponse:
    """Platform-admin: list all ride templates, optionally filtered by account."""
    stmt = select(CorporateRideTemplate)
    if account_id is not None:
        stmt = stmt.where(CorporateRideTemplate.account_id == account_id)
    stmt = stmt.order_by(
        CorporateRideTemplate.account_id, CorporateRideTemplate.name
    )
    result = await db.execute(stmt)
    templates = result.scalars().all()
    return RideTemplateListResponse(
        items=[_to_response(t) for t in templates],
        total=len(templates),
    )
