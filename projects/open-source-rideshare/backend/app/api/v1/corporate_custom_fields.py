"""Corporate Custom Ride Field endpoints.

Admins define custom metadata fields that employees fill in on corporate rides.

Member endpoints (read-only — any active account member):
  GET  /corporate/accounts/me/custom-fields                           — list fields
  GET  /corporate/accounts/me/custom-fields/{field_id}                — get field
  GET  /corporate/accounts/me/rides/{ride_id}/custom-fields           — get ride values

Admin endpoints (require ADMIN role within the account):
  POST   /corporate/accounts/me/custom-fields                         — create field
  PUT    /corporate/accounts/me/custom-fields/{field_id}              — update field
  DELETE /corporate/accounts/me/custom-fields/{field_id}/deactivate   — soft-delete
  PUT    /corporate/accounts/me/rides/{ride_id}/custom-fields/{field_id} — set value

Platform-admin endpoints:
  GET /admin/corporate/accounts/{account_id}/custom-fields            — list fields
  GET /admin/corporate/accounts/{account_id}/rides/{ride_id}/custom-fields — ride values
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query, status
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.models.user import User
from app.schemas.corporate_custom_field import (
    CustomFieldCreate,
    CustomFieldListResponse,
    CustomFieldResponse,
    CustomFieldUpdate,
    RideFieldValueSet,
    RideFieldValueResponse,
    RideFieldValuesResponse,
)
from app.services.corporate_account_mgmt import get_user_account
from app.services.corporate_custom_field import (
    create_custom_field,
    deactivate_custom_field,
    get_custom_field,
    get_ride_field_values,
    list_custom_fields,
    set_ride_field_value,
    update_custom_field,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["corporate-custom-fields"])


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------


async def _resolve_account_id(db: AsyncSession, user_id: int) -> int:
    account = await get_user_account(db, user_id)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="You are not a member of any corporate account.",
        )
    return account.id


# ---------------------------------------------------------------------------
# Member: list custom fields
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/custom-fields",
    response_model=CustomFieldListResponse,
    summary="List custom ride fields for the account",
)
async def list_my_custom_fields(
    active_only: bool = Query(True, description="When True, only return active fields."),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return custom ride field definitions for the corporate account.

    Any active account member may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    return await list_custom_fields(db, account_id, active_only=active_only, skip=skip, limit=limit)


# ---------------------------------------------------------------------------
# Member: get a single custom field
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/custom-fields/{field_id}",
    response_model=CustomFieldResponse,
    summary="Get a custom ride field by ID",
)
async def get_my_custom_field(
    field_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return details of a specific custom ride field.

    Any active account member may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    return await get_custom_field(db, account_id, field_id)


# ---------------------------------------------------------------------------
# Member: get all custom field values on a ride
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/rides/{ride_id}/custom-fields",
    response_model=RideFieldValuesResponse,
    summary="Get custom field values recorded on a specific ride",
)
async def get_my_ride_custom_field_values(
    ride_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all custom field values annotated on a specific ride.

    Any active account member may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    return await get_ride_field_values(db, account_id, ride_id)


# ---------------------------------------------------------------------------
# Admin: create custom field
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/accounts/me/custom-fields",
    response_model=CustomFieldResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Admin: create a new custom ride field",
)
async def create_my_custom_field(
    data: CustomFieldCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new custom ride field definition.

    Employees will see this field when annotating corporate rides.
    Requires ADMIN role within the account.
    """
    account_id = await _resolve_account_id(db, user.id)
    result = await create_custom_field(db, account_id, user.id, data)
    await db.commit()
    return result


# ---------------------------------------------------------------------------
# Admin: update custom field
# ---------------------------------------------------------------------------


@router.put(
    "/corporate/accounts/me/custom-fields/{field_id}",
    response_model=CustomFieldResponse,
    summary="Admin: update a custom ride field",
)
async def update_my_custom_field(
    field_id: int,
    data: CustomFieldUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update a custom ride field definition.

    The field_key and field_type are immutable after creation.
    Requires ADMIN role within the account.
    """
    account_id = await _resolve_account_id(db, user.id)
    result = await update_custom_field(db, account_id, field_id, user.id, data)
    await db.commit()
    return result


# ---------------------------------------------------------------------------
# Admin: deactivate custom field
# ---------------------------------------------------------------------------


@router.delete(
    "/corporate/accounts/me/custom-fields/{field_id}/deactivate",
    response_model=CustomFieldResponse,
    summary="Admin: deactivate a custom ride field (soft-delete)",
)
async def deactivate_my_custom_field(
    field_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Soft-delete a custom ride field.

    Deactivated fields are hidden from employees but their values are preserved.
    Requires ADMIN role within the account.
    """
    account_id = await _resolve_account_id(db, user.id)
    result = await deactivate_custom_field(db, account_id, field_id, user.id)
    await db.commit()
    return result


# ---------------------------------------------------------------------------
# Admin/Member: set a custom field value on a ride
# ---------------------------------------------------------------------------


@router.put(
    "/corporate/accounts/me/rides/{ride_id}/custom-fields/{field_id}",
    response_model=RideFieldValueResponse,
    summary="Set a custom field value on a ride",
)
async def set_my_ride_custom_field_value(
    ride_id: int,
    field_id: int,
    data: RideFieldValueSet,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Set or update a custom field value on a corporate ride.

    Any active account member may annotate rides with custom field values.
    The value is validated against the field schema (type, options, length).
    """
    account_id = await _resolve_account_id(db, user.id)
    result = await set_ride_field_value(db, account_id, ride_id, field_id, user.id, data)
    await db.commit()
    return result


# ---------------------------------------------------------------------------
# Platform-admin: list custom fields for any account
# ---------------------------------------------------------------------------


@router.get(
    "/admin/corporate/accounts/{account_id}/custom-fields",
    response_model=CustomFieldListResponse,
    summary="Platform admin: list custom fields for any corporate account",
)
async def platform_admin_list_custom_fields(
    account_id: int,
    active_only: bool = Query(False),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return custom field definitions for any corporate account.

    Requires platform-level admin role.
    """
    return await list_custom_fields(db, account_id, active_only=active_only, skip=skip, limit=limit)


# ---------------------------------------------------------------------------
# Platform-admin: get ride field values for any account
# ---------------------------------------------------------------------------


@router.get(
    "/admin/corporate/accounts/{account_id}/rides/{ride_id}/custom-fields",
    response_model=RideFieldValuesResponse,
    summary="Platform admin: get custom field values on a ride for any corporate account",
)
async def platform_admin_get_ride_custom_field_values(
    account_id: int,
    ride_id: int,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return custom field values on a specific ride for any corporate account.

    Requires platform-level admin role.
    """
    return await get_ride_field_values(db, account_id, ride_id)
