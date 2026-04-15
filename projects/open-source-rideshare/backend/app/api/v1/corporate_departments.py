"""Corporate Department Management endpoints.

Member endpoints (any active account member):
  GET  /corporate/accounts/me/departments                       — list
  GET  /corporate/accounts/me/departments/{id}                  — get
  GET  /corporate/accounts/me/departments/{id}/members          — list members
  GET  /corporate/accounts/me/departments/{id}/spend            — spend analytics

Admin endpoints (require ADMIN role within the account):
  POST   /corporate/accounts/me/departments                     — create
  PUT    /corporate/accounts/me/departments/{id}                — update
  DELETE /corporate/accounts/me/departments/{id}/deactivate     — soft-delete
  POST   /corporate/accounts/me/departments/{id}/members        — add member
  DELETE /corporate/accounts/me/departments/{id}/members/{uid}  — remove member

Platform-admin endpoints:
  GET /admin/corporate/accounts/{account_id}/departments                   — list
  GET /admin/corporate/accounts/{account_id}/departments/{id}/spend        — spend
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query, status
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.models.user import User
from app.schemas.corporate_department import (
    AddMemberRequest,
    DepartmentCreate,
    DepartmentListResponse,
    DepartmentMembersResponse,
    DepartmentResponse,
    DepartmentSpendResponse,
    DepartmentUpdate,
    DepartmentMemberResponse,
)
from app.services.corporate_account_mgmt import get_user_account
from app.services.corporate_department import (
    add_department_member,
    create_department,
    deactivate_department,
    get_department,
    get_department_spend,
    list_department_members,
    list_departments,
    remove_department_member,
    update_department,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["corporate-departments"])


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
# Member: list departments
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/departments",
    response_model=DepartmentListResponse,
    summary="List departments in the account",
)
async def list_my_departments(
    active_only: bool = Query(True, description="When True, only return active departments."),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a paginated list of departments in the corporate account.

    Any active account member may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    return await list_departments(db, account_id, active_only=active_only, skip=skip, limit=limit)


# ---------------------------------------------------------------------------
# Admin: create department
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/accounts/me/departments",
    response_model=DepartmentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Admin: create a new department",
)
async def create_my_department(
    data: DepartmentCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new department within the corporate account.

    Requires ADMIN role within the account.
    """
    account_id = await _resolve_account_id(db, user.id)
    result = await create_department(db, account_id, user.id, data)
    await db.commit()
    return result


# ---------------------------------------------------------------------------
# Member/Admin: get a single department
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/departments/{department_id}",
    response_model=DepartmentResponse,
    summary="Get a department by ID",
)
async def get_my_department(
    department_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return details of a specific department.

    Any active account member may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    return await get_department(db, account_id, department_id)


# ---------------------------------------------------------------------------
# Admin: update department
# ---------------------------------------------------------------------------


@router.put(
    "/corporate/accounts/me/departments/{department_id}",
    response_model=DepartmentResponse,
    summary="Admin: update a department",
)
async def update_my_department(
    department_id: int,
    data: DepartmentUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update a department's name, code, description, cost center, or budget.

    Requires ADMIN role within the account.
    """
    account_id = await _resolve_account_id(db, user.id)
    result = await update_department(db, account_id, department_id, user.id, data)
    await db.commit()
    return result


# ---------------------------------------------------------------------------
# Admin: deactivate department
# ---------------------------------------------------------------------------


@router.delete(
    "/corporate/accounts/me/departments/{department_id}/deactivate",
    response_model=DepartmentResponse,
    summary="Admin: deactivate a department (soft-delete)",
)
async def deactivate_my_department(
    department_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Soft-delete a department.  Members are preserved for history.

    Requires ADMIN role within the account.
    """
    account_id = await _resolve_account_id(db, user.id)
    result = await deactivate_department(db, account_id, department_id, user.id)
    await db.commit()
    return result


# ---------------------------------------------------------------------------
# Member: list department members
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/departments/{department_id}/members",
    response_model=DepartmentMembersResponse,
    summary="List members of a department",
)
async def list_my_department_members(
    department_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all members of a department.

    Any active account member may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    return await list_department_members(db, account_id, department_id)


# ---------------------------------------------------------------------------
# Admin: add member to department
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/accounts/me/departments/{department_id}/members",
    response_model=DepartmentMemberResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Admin: add an account member to a department",
)
async def add_my_department_member(
    department_id: int,
    data: AddMemberRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Add an active corporate account member to a department.

    Requires ADMIN role within the account.
    """
    account_id = await _resolve_account_id(db, user.id)
    result = await add_department_member(db, account_id, department_id, user.id, data)
    await db.commit()
    return result


# ---------------------------------------------------------------------------
# Admin: remove member from department
# ---------------------------------------------------------------------------


@router.delete(
    "/corporate/accounts/me/departments/{department_id}/members/{target_user_id}",
    summary="Admin: remove a member from a department",
)
async def remove_my_department_member(
    department_id: int,
    target_user_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove a user from a department.

    Does not remove the user from the corporate account itself.
    Requires ADMIN role within the account.
    """
    account_id = await _resolve_account_id(db, user.id)
    result = await remove_department_member(
        db, account_id, department_id, user.id, target_user_id
    )
    await db.commit()
    return result


# ---------------------------------------------------------------------------
# Member: department spend analytics
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/departments/{department_id}/spend",
    response_model=DepartmentSpendResponse,
    summary="Current-month spend analytics for a department",
)
async def my_department_spend(
    department_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return current-month spend totals for all members of a department.

    Any active account member may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    return await get_department_spend(db, account_id, department_id)


# ---------------------------------------------------------------------------
# Platform-admin: list departments for any account
# ---------------------------------------------------------------------------


@router.get(
    "/admin/corporate/accounts/{account_id}/departments",
    response_model=DepartmentListResponse,
    summary="Platform admin: list all departments for any corporate account",
)
async def platform_admin_list_departments(
    account_id: int,
    active_only: bool = Query(True),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return departments for any corporate account.

    Requires platform-level admin role.
    """
    return await list_departments(db, account_id, active_only=active_only, skip=skip, limit=limit)


# ---------------------------------------------------------------------------
# Platform-admin: spend for a specific department
# ---------------------------------------------------------------------------


@router.get(
    "/admin/corporate/accounts/{account_id}/departments/{department_id}/spend",
    response_model=DepartmentSpendResponse,
    summary="Platform admin: spend analytics for a department in any account",
)
async def platform_admin_department_spend(
    account_id: int,
    department_id: int,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return current-month spend analytics for any corporate department.

    Requires platform-level admin role.
    """
    return await get_department_spend(db, account_id, department_id)
