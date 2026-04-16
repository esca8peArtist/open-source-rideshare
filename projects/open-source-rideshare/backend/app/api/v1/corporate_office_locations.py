"""Corporate Office Location endpoints.

Enterprise corporate accounts define named office locations and assign members
to them.  Admins manage the locations; members can read their own assignments.

Member endpoints (any active account member):
  GET  /corporate/offices              — list offices in my account
  GET  /corporate/offices/my-office    — get my primary office
  GET  /corporate/offices/{office_id}  — get a specific office

Admin endpoints (account admins only):
  POST   /corporate/offices                            — create office
  PUT    /corporate/offices/{office_id}                — update office
  POST   /corporate/offices/{office_id}/deactivate     — deactivate
  POST   /corporate/offices/{office_id}/reactivate     — reactivate
  DELETE /corporate/offices/{office_id}                — delete (inactive only)
  POST   /corporate/offices/{office_id}/members        — assign member
  DELETE /corporate/offices/{office_id}/members/{member_id} — remove member
  GET    /corporate/offices/{office_id}/members        — list members
  GET    /corporate/offices/{office_id}/summary        — summary stats

Platform-admin endpoints:
  GET  /platform/corporate/offices                     — all offices (all accounts)
  GET  /platform/corporate/offices/for-account/{account_id}  — by account
"""

from __future__ import annotations

import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.models.user import User
from app.schemas.corporate_office_location import (
    AssignMemberRequest,
    OfficeLocationCreate,
    OfficeLocationListResponse,
    OfficeLocationResponse,
    OfficeLocationUpdate,
    OfficeMembershipListResponse,
    OfficeMembershipResponse,
    OfficeSummaryResponse,
)
from app.services.corporate_account_mgmt import get_user_account
from app.services.corporate_office_location import (
    assign_member,
    create_office,
    deactivate_office,
    delete_office,
    get_member_offices,
    get_office,
    get_office_summary,
    list_all_platform,
    list_office_members,
    list_offices,
    reactivate_office,
    remove_member,
    update_office,
)
from app.services.corporate_trip_purpose import _require_account_admin

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Corporate Office Locations"])


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
# Member: list offices
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/offices",
    response_model=OfficeLocationListResponse,
    summary="List all offices in my corporate account",
)
async def list_my_account_offices(
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all office locations for the authenticated user's account.

    Any active corporate account member may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    return await list_offices(db, account_id, is_active=is_active)


# ---------------------------------------------------------------------------
# Member: get my primary office — must come before /{office_id}
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/offices/my-office",
    response_model=OfficeMembershipResponse,
    summary="Get my primary office assignment",
)
async def get_my_primary_office(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the authenticated member's primary office membership.

    Raises HTTP 404 if the member has no primary office assigned.
    Any active corporate account member may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    result = await get_member_offices(db, user.id, account_id, is_primary=True)
    if result.total == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="You do not have a primary office assigned.",
        )
    return result.items[0]


# ---------------------------------------------------------------------------
# Member: get a specific office
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/offices/{office_id}",
    response_model=OfficeLocationResponse,
    summary="Get a specific office location",
)
async def get_office_endpoint(
    office_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a specific office location by ID.

    Any active corporate account member may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    return await get_office(db, office_id, account_id)


# ---------------------------------------------------------------------------
# Admin: create office
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/offices",
    response_model=OfficeLocationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new office location (admin only)",
)
async def create_office_endpoint(
    data: OfficeLocationCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new office location for the account.

    Returns 409 if an office with the same name already exists.
    Only account admins may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    return await create_office(db, account_id, data, created_by_id=user.id)


# ---------------------------------------------------------------------------
# Admin: update office
# ---------------------------------------------------------------------------


@router.put(
    "/corporate/offices/{office_id}",
    response_model=OfficeLocationResponse,
    summary="Update an office location (admin only)",
)
async def update_office_endpoint(
    office_id: uuid.UUID,
    data: OfficeLocationUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Partially update an office location.

    Returns 409 on duplicate name.  Only account admins may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    return await update_office(db, office_id, account_id, data)


# ---------------------------------------------------------------------------
# Admin: deactivate office
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/offices/{office_id}/deactivate",
    response_model=OfficeLocationResponse,
    summary="Deactivate an office location (admin only)",
)
async def deactivate_office_endpoint(
    office_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Deactivate an active office location.

    Returns 409 if already inactive.  Only account admins may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    return await deactivate_office(db, office_id, account_id)


# ---------------------------------------------------------------------------
# Admin: reactivate office
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/offices/{office_id}/reactivate",
    response_model=OfficeLocationResponse,
    summary="Reactivate an office location (admin only)",
)
async def reactivate_office_endpoint(
    office_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Reactivate an inactive office location.

    Returns 409 if already active.  Only account admins may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    return await reactivate_office(db, office_id, account_id)


# ---------------------------------------------------------------------------
# Admin: delete office
# ---------------------------------------------------------------------------


@router.delete(
    "/corporate/offices/{office_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an office location (admin only)",
)
async def delete_office_endpoint(
    office_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Hard-delete an office location.

    Returns 409 if the office is active — deactivate it first.
    Only account admins may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    await delete_office(db, office_id, account_id)


# ---------------------------------------------------------------------------
# Admin: assign member to office
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/offices/{office_id}/members",
    response_model=OfficeMembershipResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Assign a member to an office (admin only)",
)
async def assign_member_endpoint(
    office_id: uuid.UUID,
    data: AssignMemberRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Assign an account member to an office location.

    Returns 409 if the member is already assigned to this office.
    If ``is_primary=True``, clears the member's previous primary office.
    Only account admins may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    return await assign_member(
        db,
        office_id=office_id,
        account_id=account_id,
        member_id=data.member_id,
        is_primary=data.is_primary,
        assigned_by_id=user.id,
        notes=data.notes,
    )


# ---------------------------------------------------------------------------
# Admin: remove member from office
# ---------------------------------------------------------------------------


@router.delete(
    "/corporate/offices/{office_id}/members/{member_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a member from an office (admin only)",
)
async def remove_member_endpoint(
    office_id: uuid.UUID,
    member_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove a member's assignment from an office location.

    Returns 404 if the member is not assigned to this office.
    Only account admins may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    await remove_member(db, office_id, account_id, member_id)


# ---------------------------------------------------------------------------
# Admin: list office members
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/offices/{office_id}/members",
    response_model=OfficeMembershipListResponse,
    summary="List members assigned to an office (admin only)",
)
async def list_office_members_endpoint(
    office_id: uuid.UUID,
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all member assignments for an office location.

    Only account admins may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    return await list_office_members(db, office_id, account_id, is_active=is_active)


# ---------------------------------------------------------------------------
# Admin: office summary
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/offices/{office_id}/summary",
    response_model=OfficeSummaryResponse,
    summary="Get summary stats for an office (admin only)",
)
async def get_office_summary_endpoint(
    office_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return an office location with total and active member counts.

    Only account admins may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    return await get_office_summary(db, office_id, account_id)


# ---------------------------------------------------------------------------
# Platform-admin: list all offices
# ---------------------------------------------------------------------------


@router.get(
    "/platform/corporate/offices",
    response_model=OfficeLocationListResponse,
    summary="Platform admin: list all office locations",
)
async def admin_list_all_offices(
    account_id: Optional[int] = Query(None, description="Filter by account ID"),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return all office locations across all corporate accounts.

    Optionally filter by ``account_id``.  Platform admin only.
    """
    return await list_all_platform(db, account_id=account_id)


# ---------------------------------------------------------------------------
# Platform-admin: list offices for a specific account
# ---------------------------------------------------------------------------


@router.get(
    "/platform/corporate/offices/for-account/{account_id}",
    response_model=OfficeLocationListResponse,
    summary="Platform admin: list office locations for a specific account",
)
async def admin_list_offices_for_account(
    account_id: int,
    is_active: Optional[bool] = Query(None),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return all office locations for any corporate account.

    Platform admin only.
    """
    return await list_offices(db, account_id, is_active=is_active)
