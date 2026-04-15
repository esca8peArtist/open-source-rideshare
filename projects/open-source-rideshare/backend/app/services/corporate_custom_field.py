"""Service layer for Corporate Custom Ride Fields.

Enterprise accounts can define custom metadata fields that employees must (or may)
fill in on each corporate ride — project billing codes, client matter numbers, and
similar back-office fields.  Admins manage the field schema; employees set values.

Public surface
--------------
create_custom_field(db, account_id, user_id, data)
get_custom_field(db, account_id, field_id)
list_custom_fields(db, account_id, active_only=True, skip=0, limit=50)
update_custom_field(db, account_id, field_id, user_id, data)
deactivate_custom_field(db, account_id, field_id, user_id)
set_ride_field_value(db, account_id, ride_id, field_id, user_id, data)
get_ride_field_values(db, account_id, ride_id)
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Sequence

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.corporate import BusinessAccountMember, MemberRole
from app.models.corporate_custom_field import (
    CorporateCustomField,
    CorporateRideCustomFieldValue,
    CustomFieldType,
)
from app.schemas.corporate_custom_field import (
    CustomFieldCreate,
    CustomFieldListResponse,
    CustomFieldResponse,
    CustomFieldUpdate,
    RideFieldValueResponse,
    RideFieldValueSet,
    RideFieldValuesResponse,
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _require_admin(
    db: AsyncSession,
    account_id: int,
    user_id: int,
) -> BusinessAccountMember:
    """Return the member row or raise HTTP 403 if the user is not an admin."""
    result = await db.execute(
        select(BusinessAccountMember).where(
            BusinessAccountMember.account_id == account_id,
            BusinessAccountMember.user_id == user_id,
            BusinessAccountMember.role == MemberRole.ADMIN,
            BusinessAccountMember.is_active.is_(True),
        )
    )
    member = result.scalar_one_or_none()
    if member is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have admin access to this corporate account.",
        )
    return member


async def _require_member(
    db: AsyncSession,
    account_id: int,
    user_id: int,
) -> BusinessAccountMember:
    """Return the member row or raise HTTP 403 if the user is not an active member."""
    result = await db.execute(
        select(BusinessAccountMember).where(
            BusinessAccountMember.account_id == account_id,
            BusinessAccountMember.user_id == user_id,
            BusinessAccountMember.is_active.is_(True),
        )
    )
    member = result.scalar_one_or_none()
    if member is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not an active member of this corporate account.",
        )
    return member


async def _get_field(
    db: AsyncSession,
    account_id: int,
    field_id: int,
) -> CorporateCustomField:
    """Return the field or raise HTTP 404 if not found in this account."""
    result = await db.execute(
        select(CorporateCustomField).where(
            CorporateCustomField.id == field_id,
            CorporateCustomField.account_id == account_id,
        )
    )
    field = result.scalar_one_or_none()
    if field is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Custom field not found in this account.",
        )
    return field


def _slugify(label: str) -> str:
    """Convert a label to a lowercase underscore-separated slug."""
    slug = label.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "_", slug)
    slug = slug.strip("_")
    return slug or "field"


def _field_to_response(field: CorporateCustomField) -> CustomFieldResponse:
    now = datetime.now(timezone.utc)
    return CustomFieldResponse(
        id=field.id,
        account_id=field.account_id,
        label=field.label,
        field_key=field.field_key,
        field_type=field.field_type,
        dropdown_options=field.dropdown_options,
        is_required=field.is_required,
        max_length=field.max_length,
        display_order=field.display_order,
        is_active=field.is_active,
        created_by_id=field.created_by_id,
        created_at=field.created_at or now,
        updated_at=field.updated_at or now,
    )


def _value_to_response(
    val: CorporateRideCustomFieldValue,
    field: CorporateCustomField,
) -> RideFieldValueResponse:
    now = datetime.now(timezone.utc)
    return RideFieldValueResponse(
        id=val.id,
        field_id=val.field_id,
        ride_id=val.ride_id,
        field_label=field.label,
        field_key=field.field_key,
        field_type=field.field_type,
        value=val.value,
        set_by_id=val.set_by_id,
        set_at=val.set_at or now,
    )


def _validate_value(field: CorporateCustomField, raw_value: str) -> None:
    """Validate *raw_value* against the field schema.

    Raises HTTP 422 if the value fails validation.
    """
    if field.field_type == CustomFieldType.NUMBER:
        try:
            float(raw_value)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Field '{field.label}' expects a numeric value.",
            )

    if field.field_type == CustomFieldType.CHECKBOX:
        if raw_value.lower() not in ("true", "false", "1", "0", "yes", "no"):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Field '{field.label}' expects a boolean value (true/false).",
            )

    if field.field_type == CustomFieldType.DROPDOWN:
        options = field.dropdown_options or []
        if raw_value not in options:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"Field '{field.label}' value must be one of: "
                    f"{', '.join(options)}."
                ),
            )

    if field.field_type == CustomFieldType.TEXT and field.max_length:
        if len(raw_value) > field.max_length:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"Field '{field.label}' value exceeds maximum length of "
                    f"{field.max_length} characters."
                ),
            )


# ---------------------------------------------------------------------------
# Service functions — field schema management
# ---------------------------------------------------------------------------


async def create_custom_field(
    db: AsyncSession,
    account_id: int,
    user_id: int,
    data: CustomFieldCreate,
) -> CustomFieldResponse:
    """Create a new custom ride field definition (admin only).

    Args:
        db: Database session.
        account_id: Corporate account identifier.
        user_id: ID of the requesting admin.
        data: CustomFieldCreate payload.

    Returns:
        CustomFieldResponse for the newly created field.

    Raises:
        HTTP 403: When the user is not an account admin.
        HTTP 409: When a field with the same field_key already exists in this account.
    """
    await _require_admin(db, account_id, user_id)

    key = data.field_key or _slugify(data.label)

    dup = await db.execute(
        select(CorporateCustomField).where(
            CorporateCustomField.account_id == account_id,
            CorporateCustomField.field_key == key,
        )
    )
    if dup.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A custom field with key '{key}' already exists in this account.",
        )

    field = CorporateCustomField(
        account_id=account_id,
        label=data.label,
        field_key=key,
        field_type=data.field_type,
        dropdown_options=data.dropdown_options,
        is_required=data.is_required,
        max_length=data.max_length,
        display_order=data.display_order,
        is_active=True,
        created_by_id=user_id,
    )
    db.add(field)
    await db.flush()

    return _field_to_response(field)


async def get_custom_field(
    db: AsyncSession,
    account_id: int,
    field_id: int,
) -> CustomFieldResponse:
    """Return a single custom field definition.

    Args:
        db: Database session.
        account_id: Corporate account identifier.
        field_id: Custom field identifier.

    Raises:
        HTTP 404: When the field is not found in this account.
    """
    field = await _get_field(db, account_id, field_id)
    return _field_to_response(field)


async def list_custom_fields(
    db: AsyncSession,
    account_id: int,
    active_only: bool = True,
    skip: int = 0,
    limit: int = 50,
) -> CustomFieldListResponse:
    """Return a paginated list of custom field definitions for the account.

    Results are ordered by display_order ascending, then label.

    Args:
        db: Database session.
        account_id: Corporate account identifier.
        active_only: When True, only return is_active=True fields.
        skip: Pagination offset.
        limit: Maximum rows to return.
    """
    q = select(CorporateCustomField).where(
        CorporateCustomField.account_id == account_id
    )
    if active_only:
        q = q.where(CorporateCustomField.is_active.is_(True))

    total_result = await db.execute(
        select(func.count()).select_from(q.subquery())
    )
    total = total_result.scalar_one() or 0

    page_result = await db.execute(
        q.order_by(CorporateCustomField.display_order, CorporateCustomField.label)
        .offset(skip)
        .limit(limit)
    )
    fields: Sequence[CorporateCustomField] = page_result.scalars().all()

    return CustomFieldListResponse(
        account_id=account_id,
        total=total,
        fields=[_field_to_response(f) for f in fields],
    )


async def update_custom_field(
    db: AsyncSession,
    account_id: int,
    field_id: int,
    user_id: int,
    data: CustomFieldUpdate,
) -> CustomFieldResponse:
    """Update a custom field definition (admin only).

    The field_key and field_type are immutable after creation.

    Raises:
        HTTP 403: When the user is not an account admin.
        HTTP 404: When the field is not found in this account.
        HTTP 422: When dropdown_options is supplied on a non-dropdown field.
    """
    await _require_admin(db, account_id, user_id)
    field = await _get_field(db, account_id, field_id)

    if data.label is not None:
        field.label = data.label
    if data.dropdown_options is not None:
        if field.field_type != CustomFieldType.DROPDOWN:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="dropdown_options can only be set on dropdown-type fields.",
            )
        field.dropdown_options = data.dropdown_options
    if data.is_required is not None:
        field.is_required = data.is_required
    if data.max_length is not None:
        field.max_length = data.max_length
    if data.display_order is not None:
        field.display_order = data.display_order
    if data.is_active is not None:
        field.is_active = data.is_active

    await db.flush()
    return _field_to_response(field)


async def deactivate_custom_field(
    db: AsyncSession,
    account_id: int,
    field_id: int,
    user_id: int,
) -> CustomFieldResponse:
    """Soft-delete a custom field definition (admin only).

    Deactivated fields are hidden from employees, but existing values are preserved.

    Raises:
        HTTP 403: When the user is not an account admin.
        HTTP 404: When the field is not found in this account.
        HTTP 409: When the field is already inactive.
    """
    await _require_admin(db, account_id, user_id)
    field = await _get_field(db, account_id, field_id)

    if not field.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Custom field is already inactive.",
        )

    field.is_active = False
    await db.flush()
    return _field_to_response(field)


# ---------------------------------------------------------------------------
# Service functions — ride field values
# ---------------------------------------------------------------------------


async def set_ride_field_value(
    db: AsyncSession,
    account_id: int,
    ride_id: int,
    field_id: int,
    user_id: int,
    data: RideFieldValueSet,
) -> RideFieldValueResponse:
    """Set (or update) a custom field value on a corporate ride.

    Any active member of the account may set values.  The value is validated
    against the field schema before persisting.  An existing value for the
    same (field_id, ride_id) pair is updated in-place (upsert semantics).

    Args:
        db: Database session.
        account_id: Corporate account identifier (used to verify field ownership).
        ride_id: Ride to annotate.
        field_id: Custom field to set.
        user_id: ID of the user setting the value.
        data: RideFieldValueSet payload.

    Raises:
        HTTP 403: When the user is not an active account member.
        HTTP 404: When the field is not found in this account or is inactive.
        HTTP 422: When the value fails schema validation.
    """
    await _require_member(db, account_id, user_id)

    field = await _get_field(db, account_id, field_id)
    if not field.is_active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Custom field is inactive and cannot be written to.",
        )

    _validate_value(field, data.value)

    # Upsert: update existing value or create new
    existing_result = await db.execute(
        select(CorporateRideCustomFieldValue).where(
            CorporateRideCustomFieldValue.field_id == field_id,
            CorporateRideCustomFieldValue.ride_id == ride_id,
        )
    )
    existing = existing_result.scalar_one_or_none()

    if existing is not None:
        existing.value = data.value
        existing.set_by_id = user_id
        val = existing
    else:
        val = CorporateRideCustomFieldValue(
            field_id=field_id,
            ride_id=ride_id,
            value=data.value,
            set_by_id=user_id,
        )
        db.add(val)

    await db.flush()
    return _value_to_response(val, field)


async def get_ride_field_values(
    db: AsyncSession,
    account_id: int,
    ride_id: int,
) -> RideFieldValuesResponse:
    """Return all custom field values recorded on a specific ride.

    Returns values for all fields belonging to this account on the given ride,
    joined with field metadata for context.

    Args:
        db: Database session.
        account_id: Corporate account identifier.
        ride_id: Ride to query.
    """
    # Fetch all fields for this account to build a lookup map
    fields_result = await db.execute(
        select(CorporateCustomField).where(
            CorporateCustomField.account_id == account_id
        )
    )
    fields_by_id: dict[int, CorporateCustomField] = {
        f.id: f for f in fields_result.scalars().all()
    }

    if not fields_by_id:
        return RideFieldValuesResponse(ride_id=ride_id, values=[])

    values_result = await db.execute(
        select(CorporateRideCustomFieldValue).where(
            CorporateRideCustomFieldValue.ride_id == ride_id,
            CorporateRideCustomFieldValue.field_id.in_(fields_by_id.keys()),
        )
    )
    values: Sequence[CorporateRideCustomFieldValue] = values_result.scalars().all()

    return RideFieldValuesResponse(
        ride_id=ride_id,
        values=[
            _value_to_response(v, fields_by_id[v.field_id])
            for v in values
            if v.field_id in fields_by_id
        ],
    )
