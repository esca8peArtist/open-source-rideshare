"""Corporate Ride Templates endpoints.

Corporate admins define named, reusable booking configurations — saved routes
with pre-filled pickup/dropoff addresses, preferred vehicle type, and default
cost centre / trip purpose.  Employees browse templates and get pre-filled
booking data, reducing friction for frequent corporate trips (airport runs,
hotel transfers, office-to-client-site routes, etc.).

Member endpoints (any active member):
  GET    /corporate/accounts/me/ride-templates                      — list templates
  GET    /corporate/accounts/me/ride-templates/popular              — popular templates
  GET    /corporate/accounts/me/ride-templates/{template_id}        — get template

Admin endpoints (account admins only):
  POST   /corporate/accounts/me/ride-templates                      — create template
  PATCH  /corporate/accounts/me/ride-templates/{template_id}        — update template
  POST   /corporate/accounts/me/ride-templates/{template_id}/deactivate
  POST   /corporate/accounts/me/ride-templates/{template_id}/reactivate
  DELETE /corporate/accounts/me/ride-templates/{template_id}        — delete template
  POST   /corporate/accounts/me/ride-templates/{template_id}/use    — record use

Platform-admin endpoints:
  GET    /platform/corporate/ride-templates                         — all templates
  GET    /platform/corporate/accounts/{account_id}/ride-templates   — account templates
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.models.user import User
from app.schemas.corporate_ride_template import (
    RideTemplateCreate,
    RideTemplateListResponse,
    RideTemplateResponse,
    RideTemplateUpdate,
)
from app.services.corporate_account_mgmt import get_user_account
from app.services.corporate_ride_template import (
    create_ride_template,
    deactivate_ride_template,
    delete_ride_template,
    get_popular_templates,
    get_ride_template,
    list_all_platform,
    list_ride_templates,
    reactivate_ride_template,
    record_template_use,
    update_ride_template,
)
from app.services.corporate_trip_purpose import _require_account_admin

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Corporate Ride Templates"])


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------


async def _resolve_account_id(db: AsyncSession, user_id: int) -> int:
    """Return the account_id for the authenticated user.

    Raises HTTP 404 if the user is not a member of any corporate account.
    """
    account = await get_user_account(db, user_id)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="You are not a member of any corporate account.",
        )
    return account.id


# ---------------------------------------------------------------------------
# Member: list templates
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/ride-templates",
    response_model=RideTemplateListResponse,
    summary="List corporate ride templates for own account",
)
async def list_my_ride_templates(
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all corporate ride templates for the authenticated user's account.

    Optionally filter by active/inactive status.  Any active member may call
    this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    return await list_ride_templates(db, account_id, is_active=is_active)


# ---------------------------------------------------------------------------
# Member: popular templates (must appear before /{template_id} to avoid conflict)
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/ride-templates/popular",
    response_model=RideTemplateListResponse,
    summary="Get most-used corporate ride templates",
)
async def get_my_popular_templates(
    limit: int = Query(10, ge=1, le=50, description="Maximum templates to return"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the most frequently used active ride templates for the account.

    Ordered by use_count descending.  Any active member may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    return await get_popular_templates(db, account_id, limit=limit)


# ---------------------------------------------------------------------------
# Member: get template
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/ride-templates/{template_id}",
    response_model=RideTemplateResponse,
    summary="Get a corporate ride template",
)
async def get_my_ride_template(
    template_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a single ride template by ID.

    Any active member may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    return await get_ride_template(db, template_id, account_id)


# ---------------------------------------------------------------------------
# Admin: create template
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/accounts/me/ride-templates",
    response_model=RideTemplateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a corporate ride template (admin only)",
)
async def create_my_ride_template(
    data: RideTemplateCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new ride template for the account.

    Returns 409 if a template with the same name already exists.
    Only account admins may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    return await create_ride_template(db, account_id, created_by_id=user.id, data=data)


# ---------------------------------------------------------------------------
# Admin: update template
# ---------------------------------------------------------------------------


@router.patch(
    "/corporate/accounts/me/ride-templates/{template_id}",
    response_model=RideTemplateResponse,
    summary="Update a corporate ride template (admin only)",
)
async def update_my_ride_template(
    template_id: int,
    data: RideTemplateUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Partially update a ride template.

    Only supplied fields are written; unset fields are left unchanged.
    Returns 409 if the new name collides with an existing template.
    Only account admins may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    return await update_ride_template(db, template_id, account_id, data)


# ---------------------------------------------------------------------------
# Admin: deactivate template
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/accounts/me/ride-templates/{template_id}/deactivate",
    response_model=RideTemplateResponse,
    summary="Deactivate a corporate ride template (admin only)",
)
async def deactivate_my_ride_template(
    template_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Soft-deactivate a ride template.

    Returns 409 if the template is already inactive.
    Only account admins may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    return await deactivate_ride_template(db, template_id, account_id)


# ---------------------------------------------------------------------------
# Admin: reactivate template
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/accounts/me/ride-templates/{template_id}/reactivate",
    response_model=RideTemplateResponse,
    summary="Reactivate a corporate ride template (admin only)",
)
async def reactivate_my_ride_template(
    template_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Reactivate a previously deactivated ride template.

    Returns 409 if the template is already active.
    Only account admins may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    return await reactivate_ride_template(db, template_id, account_id)


# ---------------------------------------------------------------------------
# Admin: delete template
# ---------------------------------------------------------------------------


@router.delete(
    "/corporate/accounts/me/ride-templates/{template_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a corporate ride template (admin only)",
)
async def delete_my_ride_template(
    template_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Hard-delete a ride template.

    Returns 404 if the template does not exist.
    Only account admins may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    await delete_ride_template(db, template_id, account_id)


# ---------------------------------------------------------------------------
# Member: record template use
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/accounts/me/ride-templates/{template_id}/use",
    response_model=RideTemplateResponse,
    summary="Record use of a ride template (increments use_count)",
)
async def use_ride_template(
    template_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Increment the use_count for a ride template.

    Called by the client when an employee selects a template to pre-fill a
    booking form.  Returns 409 if the template is inactive.
    Any active member may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    return await record_template_use(db, template_id, account_id)


# ---------------------------------------------------------------------------
# Platform-admin: list all templates
# ---------------------------------------------------------------------------


@router.get(
    "/platform/corporate/ride-templates",
    response_model=RideTemplateListResponse,
    summary="Admin: list all corporate ride templates",
)
async def admin_list_all_ride_templates(
    account_id: Optional[int] = Query(None, description="Filter by account ID"),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return all corporate ride templates across all accounts.

    Optionally filter by account_id.  Platform admin only.
    """
    return await list_all_platform(db, account_id=account_id)


# ---------------------------------------------------------------------------
# Platform-admin: list templates for a specific account
# ---------------------------------------------------------------------------


@router.get(
    "/platform/corporate/accounts/{account_id}/ride-templates",
    response_model=RideTemplateListResponse,
    summary="Admin: list corporate ride templates for a specific account",
)
async def admin_list_account_ride_templates(
    account_id: int,
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return all corporate ride templates for any account.

    Platform admin only.
    """
    return await list_ride_templates(db, account_id, is_active=is_active)
