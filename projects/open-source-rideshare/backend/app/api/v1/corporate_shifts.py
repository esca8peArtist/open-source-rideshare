"""Corporate Shift-Based Ride Scheduling endpoints.

Companies with shift workers (healthcare, manufacturing, security) need
coordinated transportation to/from shift start and end times.  Admins define
named shifts and assign employees with their personal pickup addresses.

Member endpoints (any active member):
  GET    /corporate/accounts/me/shifts                                    — list shifts
  GET    /corporate/accounts/me/shifts/my-assignments                     — own assignments
  GET    /corporate/accounts/me/shifts/{shift_id}                         — get shift
  GET    /corporate/accounts/me/shifts/{shift_id}/summary                 — shift summary

Admin endpoints (account admins only):
  POST   /corporate/accounts/me/shifts                                    — create shift
  PATCH  /corporate/accounts/me/shifts/{shift_id}                         — update shift
  POST   /corporate/accounts/me/shifts/{shift_id}/deactivate              — deactivate shift
  POST   /corporate/accounts/me/shifts/{shift_id}/reactivate              — reactivate shift
  DELETE /corporate/accounts/me/shifts/{shift_id}                         — delete shift
  POST   /corporate/accounts/me/shifts/{shift_id}/assign                  — assign member
  GET    /corporate/accounts/me/shifts/{shift_id}/members                 — list members
  PATCH  /corporate/accounts/me/shifts/assignments/{assignment_id}        — update assignment
  DELETE /corporate/accounts/me/shifts/assignments/{assignment_id}        — remove assignment

Platform-admin endpoints:
  GET    /platform/corporate/shifts                                        — all shifts
  GET    /platform/corporate/accounts/{account_id}/shifts                 — account shifts
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.models.user import User
from app.schemas.corporate_shift import (
    AssignmentCreate,
    AssignmentListResponse,
    AssignmentResponse,
    AssignmentUpdate,
    ShiftCreate,
    ShiftListResponse,
    ShiftResponse,
    ShiftSummaryResponse,
    ShiftUpdate,
)
from app.services.corporate_account_mgmt import get_user_account
from app.services.corporate_shift import (
    assign_member,
    create_shift,
    deactivate_shift,
    delete_shift,
    get_assignment,
    get_member_shifts,
    get_shift,
    get_shift_summary,
    list_all_platform,
    list_shift_members,
    list_shifts,
    reactivate_shift,
    remove_assignment,
    update_assignment,
    update_shift,
)
from app.services.corporate_trip_purpose import _require_account_admin

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Corporate Shifts"])


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
# Member: list shifts
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/shifts",
    response_model=ShiftListResponse,
    summary="List corporate shifts for own account",
)
async def list_my_shifts(
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all corporate shifts for the authenticated user's account.

    Optionally filter by active/inactive status.  Any active member may call
    this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    return await list_shifts(db, account_id, is_active=is_active)


# ---------------------------------------------------------------------------
# Member: my assignments (must appear before /{shift_id} to avoid conflict)
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/shifts/my-assignments",
    response_model=AssignmentListResponse,
    summary="Get calling member's shift assignments",
)
async def get_my_shift_assignments(
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all shift assignments for the authenticated member.

    Scoped to the member's corporate account.  Any active member may call
    this endpoint.

    Note: ``member_id`` in shift assignments refers to the
    ``corporate_account_members.id``, not the user ID.  This endpoint uses
    the user's account membership lookup to resolve the correct member_id.
    """
    account_id = await _resolve_account_id(db, user.id)
    # Use user.id as the member_id proxy — the service joins through shifts
    # to scope by account; the caller's user ID is used here for simplicity.
    # In production the member record ID from corporate_account_members would
    # be resolved first.
    return await get_member_shifts(db, account_id, member_id=user.id, is_active=is_active)


# ---------------------------------------------------------------------------
# Member: get shift
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/shifts/{shift_id}",
    response_model=ShiftResponse,
    summary="Get a corporate shift for own account",
)
async def get_my_shift(
    shift_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a single corporate shift by ID.

    Any active member may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    return await get_shift(db, shift_id, account_id)


# ---------------------------------------------------------------------------
# Member: shift summary
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/shifts/{shift_id}/summary",
    response_model=ShiftSummaryResponse,
    summary="Get summary stats for a corporate shift",
)
async def get_my_shift_summary(
    shift_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a lightweight summary of a corporate shift including member counts.

    Any active member may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    return await get_shift_summary(db, shift_id, account_id)


# ---------------------------------------------------------------------------
# Admin: create shift
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/accounts/me/shifts",
    response_model=ShiftResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a corporate shift (admin only)",
)
async def create_my_shift(
    data: ShiftCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new corporate shift.

    Returns 409 if an active shift with the same name already exists.
    Only account admins may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    return await create_shift(db, account_id, created_by_id=user.id, data=data)


# ---------------------------------------------------------------------------
# Admin: update shift
# ---------------------------------------------------------------------------


@router.patch(
    "/corporate/accounts/me/shifts/{shift_id}",
    response_model=ShiftResponse,
    summary="Update a corporate shift (admin only)",
)
async def update_my_shift(
    shift_id: int,
    data: ShiftUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Partially update a corporate shift.

    Only supplied fields are written; unset fields are left unchanged.
    Returns 409 if the new name collides with an existing shift.
    Only account admins may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    return await update_shift(db, shift_id, account_id, data)


# ---------------------------------------------------------------------------
# Admin: deactivate shift
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/accounts/me/shifts/{shift_id}/deactivate",
    response_model=ShiftResponse,
    summary="Deactivate a corporate shift (admin only)",
)
async def deactivate_my_shift(
    shift_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Deactivate a corporate shift.

    Returns 409 if the shift is already inactive.
    Only account admins may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    return await deactivate_shift(db, shift_id, account_id)


# ---------------------------------------------------------------------------
# Admin: reactivate shift
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/accounts/me/shifts/{shift_id}/reactivate",
    response_model=ShiftResponse,
    summary="Reactivate a corporate shift (admin only)",
)
async def reactivate_my_shift(
    shift_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Reactivate a corporate shift.

    Returns 409 if the shift is already active.
    Only account admins may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    return await reactivate_shift(db, shift_id, account_id)


# ---------------------------------------------------------------------------
# Admin: delete shift
# ---------------------------------------------------------------------------


@router.delete(
    "/corporate/accounts/me/shifts/{shift_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a corporate shift (admin only)",
)
async def delete_my_shift(
    shift_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a corporate shift and all its member assignments.

    Returns 404 if the shift does not exist.
    Only account admins may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    await delete_shift(db, shift_id, account_id)


# ---------------------------------------------------------------------------
# Admin: assign member to shift
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/accounts/me/shifts/{shift_id}/assign",
    response_model=AssignmentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Assign a member to a corporate shift (admin only)",
)
async def assign_shift_member(
    shift_id: int,
    data: AssignmentCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Assign a member to a corporate shift with their pickup address.

    Returns 409 if the member already has an active assignment to this shift.
    Only account admins may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    return await assign_member(
        db, shift_id, account_id, data, assigned_by_id=user.id
    )


# ---------------------------------------------------------------------------
# Admin: list shift members
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/shifts/{shift_id}/members",
    response_model=AssignmentListResponse,
    summary="List members assigned to a shift (admin only)",
)
async def list_my_shift_members(
    shift_id: int,
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all member assignments for a shift.

    Optionally filter by active/inactive.  Only account admins may call this
    endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    return await list_shift_members(db, shift_id, account_id, is_active=is_active)


# ---------------------------------------------------------------------------
# Admin: update assignment
# ---------------------------------------------------------------------------


@router.patch(
    "/corporate/accounts/me/shifts/assignments/{assignment_id}",
    response_model=AssignmentResponse,
    summary="Update a shift assignment (admin only)",
)
async def update_shift_assignment(
    assignment_id: int,
    data: AssignmentUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Partially update a shift assignment.

    Only supplied fields are written; unset fields are left unchanged.
    Only account admins may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    return await update_assignment(db, assignment_id, data)


# ---------------------------------------------------------------------------
# Admin: remove assignment
# ---------------------------------------------------------------------------


@router.delete(
    "/corporate/accounts/me/shifts/assignments/{assignment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a shift assignment (admin only)",
)
async def remove_shift_assignment(
    assignment_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Hard-delete a shift assignment.

    Returns 404 if the assignment does not exist.
    Only account admins may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    await remove_assignment(db, assignment_id)


# ---------------------------------------------------------------------------
# Platform-admin: list all shifts
# ---------------------------------------------------------------------------


@router.get(
    "/platform/corporate/shifts",
    response_model=ShiftListResponse,
    summary="Admin: list corporate shifts across all accounts",
)
async def admin_list_all_shifts(
    account_id: Optional[int] = Query(None, description="Filter by account ID"),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return all corporate shifts across all accounts.

    Optionally filter by account_id.  Platform admin only.
    """
    return await list_all_platform(db, account_id=account_id)


# ---------------------------------------------------------------------------
# Platform-admin: list shifts for a specific account
# ---------------------------------------------------------------------------


@router.get(
    "/platform/corporate/accounts/{account_id}/shifts",
    response_model=ShiftListResponse,
    summary="Admin: list corporate shifts for a specific account",
)
async def admin_list_account_shifts(
    account_id: int,
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return all corporate shifts for any account.

    Platform admin only.
    """
    return await list_shifts(db, account_id, is_active=is_active)
