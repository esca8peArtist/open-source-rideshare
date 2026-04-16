"""Corporate Department-Level Ride Policy API endpoints.

Corporate account admins configure per-department ride policy overrides.
These sit between the account-level ``CorporateRidePolicy`` and the
per-member ``CorporateMemberPolicyOverride``, completing the three-tier
policy hierarchy.

Member/admin routes (prefix /api/v1/corporate/accounts/me):
  PUT    /departments/{department_id}/ride-policy      — admin: upsert policy
  GET    /departments/{department_id}/ride-policy      — member: get policy
  PATCH  /departments/{department_id}/ride-policy      — admin: partial update
  DELETE /departments/{department_id}/ride-policy      — admin: delete (204)
  POST   /departments/{department_id}/ride-policy/activate   — admin: activate
  POST   /departments/{department_id}/ride-policy/deactivate — admin: deactivate
  GET    /department-ride-policies                     — member: list all for account
  GET    /effective-department-policy                  — member: own effective policy

Platform-admin routes (prefix /api/v1/platform/corporate):
  GET    /department-ride-policies                     — list all across all accounts
  GET    /accounts/{account_id}/department-ride-policies  — list for account
  GET    /accounts/{account_id}/members/{member_id}/effective-department-policy
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select as sa_select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.models.corporate import BusinessAccountMember
from app.models.user import User
from app.schemas.corporate_department_ride_policy import (
    DepartmentRidePolicyListResponse,
    DepartmentRidePolicyResponse,
    DepartmentRidePolicySet,
    DepartmentRidePolicyUpdate,
    EffectiveDepartmentPolicyResponse,
)
from app.services.corporate_account_mgmt import get_user_account
from app.services.corporate_department_ride_policy import (
    activate_department_policy,
    deactivate_department_policy,
    delete_department_policy,
    get_department_policy,
    get_effective_policy_for_member,
    list_all_department_policies_platform,
    list_department_policies,
    set_department_policy,
    update_department_policy,
)
from app.services.corporate_trip_purpose import _require_account_admin

logger = logging.getLogger(__name__)

router = APIRouter(tags=["corporate-department-ride-policies"])

_DEPT_BASE = "/corporate/accounts/me/departments/{department_id}/ride-policy"
_LIST_BASE = "/corporate/accounts/me/department-ride-policies"
_EFFECTIVE_BASE = "/corporate/accounts/me/effective-department-policy"
_PLATFORM_BASE = "/platform/corporate/department-ride-policies"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _resolve_account(db: AsyncSession, user_id: int):
    """Return the BusinessAccount for an authenticated member.

    Raises HTTP 404 if the user is not a member of any corporate account.
    """
    account = await get_user_account(db, user_id)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="You are not a member of any corporate account.",
        )
    return account


async def _resolve_member_id(
    db: AsyncSession, account_id: int, user_id: int
) -> int:
    """Return the BusinessAccountMember.id for a user+account pair.

    Raises HTTP 404 if the membership does not exist.
    """
    result = await db.execute(
        sa_select(BusinessAccountMember).where(
            BusinessAccountMember.user_id == user_id,
            BusinessAccountMember.account_id == account_id,
            BusinessAccountMember.is_active.is_(True),
        )
    )
    membership = result.scalar_one_or_none()
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Active membership not found.",
        )
    return membership.id


# ---------------------------------------------------------------------------
# Member / admin routes — per-department policy CRUD
# ---------------------------------------------------------------------------


@router.put(
    _DEPT_BASE,
    response_model=DepartmentRidePolicyResponse,
    status_code=status.HTTP_200_OK,
    summary="Set (upsert) the ride policy for a department",
)
async def upsert_department_policy(
    department_id: int,
    data: DepartmentRidePolicySet,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create or fully replace the ride policy for a department.

    Requires account-admin role.  Returns 404 if the department does not
    exist or does not belong to the caller's account.
    """
    account = await _resolve_account(db, current_user.id)
    await _require_account_admin(db, current_user.id, account.id)
    policy = await set_department_policy(
        db, account.id, department_id, data, current_user.id
    )
    return DepartmentRidePolicyResponse.model_validate(policy)


@router.get(
    _DEPT_BASE,
    response_model=DepartmentRidePolicyResponse,
    summary="Get the ride policy for a department",
)
async def get_policy_for_department(
    department_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Fetch the ride policy for a specific department.

    Returns 404 if no policy has been set for the department.
    """
    account = await _resolve_account(db, current_user.id)
    policy = await get_department_policy(db, account.id, department_id)
    if policy is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No ride policy found for department {department_id}.",
        )
    return DepartmentRidePolicyResponse.model_validate(policy)


@router.patch(
    _DEPT_BASE,
    response_model=DepartmentRidePolicyResponse,
    summary="Partially update the ride policy for a department",
)
async def patch_department_policy(
    department_id: int,
    data: DepartmentRidePolicyUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Partially update a department ride policy.

    Only supplied fields are written.  Requires account-admin role.
    Returns 404 if no policy exists — use PUT to create one first.
    """
    account = await _resolve_account(db, current_user.id)
    await _require_account_admin(db, current_user.id, account.id)
    policy = await update_department_policy(
        db, account.id, department_id, data, current_user.id
    )
    return DepartmentRidePolicyResponse.model_validate(policy)


@router.delete(
    _DEPT_BASE,
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete the ride policy for a department",
)
async def remove_department_policy(
    department_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Hard-delete the ride policy for a department.

    After deletion the department reverts to the account-level policy.
    Requires account-admin role.  Returns 404 if no policy exists.
    """
    account = await _resolve_account(db, current_user.id)
    await _require_account_admin(db, current_user.id, account.id)
    await delete_department_policy(db, account.id, department_id, current_user.id)


@router.post(
    f"{_DEPT_BASE}/activate",
    response_model=DepartmentRidePolicyResponse,
    summary="Activate the ride policy for a department",
)
async def activate_policy_for_department(
    department_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Activate a department ride policy.

    Requires account-admin role.  Returns 409 if already active.
    """
    account = await _resolve_account(db, current_user.id)
    await _require_account_admin(db, current_user.id, account.id)
    policy = await activate_department_policy(
        db, account.id, department_id, current_user.id
    )
    return DepartmentRidePolicyResponse.model_validate(policy)


@router.post(
    f"{_DEPT_BASE}/deactivate",
    response_model=DepartmentRidePolicyResponse,
    summary="Deactivate the ride policy for a department",
)
async def deactivate_policy_for_department(
    department_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Deactivate a department ride policy (soft-disable).

    Requires account-admin role.  Returns 409 if already inactive.
    """
    account = await _resolve_account(db, current_user.id)
    await _require_account_admin(db, current_user.id, account.id)
    policy = await deactivate_department_policy(
        db, account.id, department_id, current_user.id
    )
    return DepartmentRidePolicyResponse.model_validate(policy)


# ---------------------------------------------------------------------------
# Member / admin routes — account-wide list + effective policy
# ---------------------------------------------------------------------------


@router.get(
    _LIST_BASE,
    response_model=DepartmentRidePolicyListResponse,
    summary="List all department ride policies for your corporate account",
)
async def list_all_policies_for_account(
    is_active: Optional[bool] = Query(
        None,
        description="Filter by active status.  Omit for all.",
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all department ride policies for the caller's account.

    Results are ordered by department_id ascending.
    """
    account = await _resolve_account(db, current_user.id)
    policies = await list_department_policies(db, account.id, is_active=is_active)
    return DepartmentRidePolicyListResponse(
        items=[DepartmentRidePolicyResponse.model_validate(p) for p in policies],
        total=len(policies),
    )


@router.get(
    _EFFECTIVE_BASE,
    response_model=EffectiveDepartmentPolicyResponse,
    summary="Get your effective ride policy (account + departments + override)",
)
async def get_own_effective_policy(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return the caller's fully merged effective ride policy.

    Merges all three layers of the policy hierarchy:
      1. Account-level policy (base defaults)
      2. Active department policies for the caller's departments
         (most restrictive field value wins)
      3. Member-level policy override (wins when active)
    """
    account = await _resolve_account(db, current_user.id)
    member_id = await _resolve_member_id(db, account.id, current_user.id)
    return await get_effective_policy_for_member(db, account.id, member_id)


# ---------------------------------------------------------------------------
# Platform-admin routes
# ---------------------------------------------------------------------------


@router.get(
    _PLATFORM_BASE,
    response_model=DepartmentRidePolicyListResponse,
    summary="[Admin] List all department ride policies across all accounts",
    dependencies=[Depends(require_admin)],
)
async def platform_list_all_policies(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    """List all department ride policies across every corporate account.

    Platform-admin only.  Results are ordered newest-first.
    """
    policies = await list_all_department_policies_platform(db, skip=skip, limit=limit)
    return DepartmentRidePolicyListResponse(
        items=[DepartmentRidePolicyResponse.model_validate(p) for p in policies],
        total=len(policies),
    )


@router.get(
    f"/platform/corporate/accounts/{{account_id}}/department-ride-policies",
    response_model=DepartmentRidePolicyListResponse,
    summary="[Admin] List department ride policies for a specific account",
    dependencies=[Depends(require_admin)],
)
async def platform_list_account_policies(
    account_id: int,
    is_active: Optional[bool] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """List department ride policies for any corporate account.

    Platform-admin only.
    """
    policies = await list_department_policies(db, account_id, is_active=is_active)
    return DepartmentRidePolicyListResponse(
        items=[DepartmentRidePolicyResponse.model_validate(p) for p in policies],
        total=len(policies),
    )


@router.get(
    "/platform/corporate/accounts/{account_id}/members/{member_id}/effective-department-policy",
    response_model=EffectiveDepartmentPolicyResponse,
    summary="[Admin] Get effective department policy for any member",
    dependencies=[Depends(require_admin)],
)
async def platform_get_effective_policy(
    account_id: int,
    member_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Return the fully merged effective policy for any member.

    Platform-admin only.  Merges account + department + member-override layers.
    """
    return await get_effective_policy_for_member(db, account_id, member_id)
