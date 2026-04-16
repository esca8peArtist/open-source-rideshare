"""Service layer for Corporate Department-Level Ride Policies.

Admins configure per-department policy overrides that sit between the
account-level ``CorporateRidePolicy`` and the per-member
``CorporateMemberPolicyOverride``.  NULL fields inherit from the account
policy; only explicitly set fields are overridden.

Policy resolution order (highest → lowest precedence):
  1. CorporateMemberPolicyOverride  (per-member; wins over everything)
  2. CorporateDepartmentRidePolicy  (per-department; merged most-restrictive)
  3. CorporateRidePolicy            (account-level; base defaults)

Public surface
--------------
set_department_policy(db, account_id, department_id, data, requesting_user_id)
    -> CorporateDepartmentRidePolicy   (upsert — create or update)
get_department_policy(db, account_id, department_id)
    -> CorporateDepartmentRidePolicy | None
update_department_policy(db, account_id, department_id, data, requesting_user_id)
    -> CorporateDepartmentRidePolicy
delete_department_policy(db, account_id, department_id, requesting_user_id)
    -> None
activate_department_policy(db, account_id, department_id, requesting_user_id)
    -> CorporateDepartmentRidePolicy
deactivate_department_policy(db, account_id, department_id, requesting_user_id)
    -> CorporateDepartmentRidePolicy
list_department_policies(db, account_id, is_active)
    -> list[CorporateDepartmentRidePolicy]
get_effective_policy_for_member(db, account_id, member_id)
    -> EffectiveDepartmentPolicyResponse
list_all_department_policies_platform(db, skip, limit)
    -> list[CorporateDepartmentRidePolicy]
"""

from __future__ import annotations

from decimal import Decimal
from typing import List, Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.corporate import (
    BusinessAccount,
    BusinessAccountMember,
    MemberRole,
)
from app.models.corporate_department import CorporateDepartment, CorporateDepartmentMember
from app.models.corporate_department_ride_policy import CorporateDepartmentRidePolicy
from app.models.corporate_member_policy_override import CorporateMemberPolicyOverride
from app.models.corporate_ride_policy import CorporateRidePolicy
from app.schemas.corporate_department_ride_policy import (
    DepartmentRidePolicySet,
    DepartmentRidePolicyUpdate,
    EffectiveDepartmentPolicyResponse,
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _get_account_or_404(db: AsyncSession, account_id: int) -> BusinessAccount:
    """Fetch a corporate account by ID or raise HTTP 404."""
    result = await db.execute(
        select(BusinessAccount).where(BusinessAccount.id == account_id)
    )
    account = result.scalar_one_or_none()
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Corporate account not found.",
        )
    return account


async def _require_account_admin(
    db: AsyncSession,
    account_id: int,
    requesting_user_id: int,
) -> None:
    """Raise HTTP 403 if the user is not an active admin of the account.

    Pass ``requesting_user_id=-1`` from platform-admin endpoints to bypass.
    """
    if requesting_user_id == -1:
        return
    result = await db.execute(
        select(BusinessAccountMember).where(
            BusinessAccountMember.account_id == account_id,
            BusinessAccountMember.user_id == requesting_user_id,
            BusinessAccountMember.is_active.is_(True),
            BusinessAccountMember.role == MemberRole.ADMIN,
        )
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only account admins may manage department ride policies.",
        )


async def _get_department_or_404(
    db: AsyncSession, account_id: int, department_id: int
) -> CorporateDepartment:
    """Fetch a department scoped to the account or raise HTTP 404."""
    result = await db.execute(
        select(CorporateDepartment).where(
            CorporateDepartment.id == department_id,
            CorporateDepartment.account_id == account_id,
        )
    )
    dept = result.scalar_one_or_none()
    if dept is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Department {department_id} not found in account {account_id}.",
        )
    return dept


async def _get_policy_or_404(
    db: AsyncSession, account_id: int, department_id: int
) -> CorporateDepartmentRidePolicy:
    """Fetch a department policy row or raise HTTP 404."""
    row = await get_department_policy(db, account_id, department_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"No ride policy found for department {department_id} "
                f"in account {account_id}."
            ),
        )
    return row


# ---------------------------------------------------------------------------
# Public service functions
# ---------------------------------------------------------------------------


async def set_department_policy(
    db: AsyncSession,
    account_id: int,
    department_id: int,
    data: DepartmentRidePolicySet,
    requesting_user_id: int,
) -> CorporateDepartmentRidePolicy:
    """Create or replace the ride policy for a department (upsert).

    If a policy row already exists for this department, it is fully replaced
    with the new values (equivalent to a full PUT).

    Args:
        account_id:          Corporate account to scope the operation to.
        department_id:       Department to set the policy for.
        data:                New policy field values.
        requesting_user_id:  Admin performing the operation.

    Raises:
        HTTP 403 if the caller is not an account admin.
        HTTP 404 if the account or department does not exist.
    """
    await _get_account_or_404(db, account_id)
    await _require_account_admin(db, account_id, requesting_user_id)
    await _get_department_or_404(db, account_id, department_id)

    existing = await get_department_policy(db, account_id, department_id)

    if existing is not None:
        # Full replace
        existing.allowed_vehicle_categories = data.allowed_vehicle_categories
        existing.max_per_ride_usd = data.max_per_ride_usd
        existing.require_purpose = data.require_purpose
        existing.approved_purposes = data.approved_purposes
        existing.business_hours_only = data.business_hours_only
        existing.notes = data.notes
        existing.is_active = data.is_active
        existing.set_by_id = requesting_user_id if requesting_user_id != -1 else None
        await db.commit()
        await db.refresh(existing)
        return existing

    row = CorporateDepartmentRidePolicy(
        account_id=account_id,
        department_id=department_id,
        set_by_id=requesting_user_id if requesting_user_id != -1 else None,
        allowed_vehicle_categories=data.allowed_vehicle_categories,
        max_per_ride_usd=data.max_per_ride_usd,
        require_purpose=data.require_purpose,
        approved_purposes=data.approved_purposes,
        business_hours_only=data.business_hours_only,
        notes=data.notes,
        is_active=data.is_active,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def get_department_policy(
    db: AsyncSession,
    account_id: int,
    department_id: int,
) -> CorporateDepartmentRidePolicy | None:
    """Fetch the policy row for a department, or ``None`` if not set."""
    result = await db.execute(
        select(CorporateDepartmentRidePolicy).where(
            CorporateDepartmentRidePolicy.account_id == account_id,
            CorporateDepartmentRidePolicy.department_id == department_id,
        )
    )
    return result.scalar_one_or_none()


async def update_department_policy(
    db: AsyncSession,
    account_id: int,
    department_id: int,
    data: DepartmentRidePolicyUpdate,
    requesting_user_id: int,
) -> CorporateDepartmentRidePolicy:
    """Partially update an existing department ride policy.

    Only fields supplied in ``data`` (i.e. not ``None``) are written.

    Raises:
        HTTP 404 if no policy exists for the department.
    """
    await _require_account_admin(db, account_id, requesting_user_id)
    row = await _get_policy_or_404(db, account_id, department_id)

    if data.allowed_vehicle_categories is not None:
        row.allowed_vehicle_categories = data.allowed_vehicle_categories
    if data.max_per_ride_usd is not None:
        row.max_per_ride_usd = data.max_per_ride_usd
    if data.require_purpose is not None:
        row.require_purpose = data.require_purpose
    if data.approved_purposes is not None:
        row.approved_purposes = data.approved_purposes
    if data.business_hours_only is not None:
        row.business_hours_only = data.business_hours_only
    if data.notes is not None:
        row.notes = data.notes
    if data.is_active is not None:
        row.is_active = data.is_active

    row.set_by_id = requesting_user_id if requesting_user_id != -1 else None
    await db.commit()
    await db.refresh(row)
    return row


async def delete_department_policy(
    db: AsyncSession,
    account_id: int,
    department_id: int,
    requesting_user_id: int,
) -> None:
    """Hard-delete a department ride policy.

    Raises:
        HTTP 404 if no policy exists for the department.
    """
    await _require_account_admin(db, account_id, requesting_user_id)
    row = await _get_policy_or_404(db, account_id, department_id)
    await db.delete(row)
    await db.commit()


async def activate_department_policy(
    db: AsyncSession,
    account_id: int,
    department_id: int,
    requesting_user_id: int,
) -> CorporateDepartmentRidePolicy:
    """Activate a department ride policy.

    Raises:
        HTTP 404 if no policy row exists.
        HTTP 409 if the policy is already active.
    """
    await _require_account_admin(db, account_id, requesting_user_id)
    row = await _get_policy_or_404(db, account_id, department_id)
    if row.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Department {department_id} policy is already active.",
        )
    row.is_active = True
    row.set_by_id = requesting_user_id if requesting_user_id != -1 else None
    await db.commit()
    await db.refresh(row)
    return row


async def deactivate_department_policy(
    db: AsyncSession,
    account_id: int,
    department_id: int,
    requesting_user_id: int,
) -> CorporateDepartmentRidePolicy:
    """Deactivate a department ride policy (soft-disable).

    Raises:
        HTTP 404 if no policy row exists.
        HTTP 409 if the policy is already inactive.
    """
    await _require_account_admin(db, account_id, requesting_user_id)
    row = await _get_policy_or_404(db, account_id, department_id)
    if not row.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Department {department_id} policy is already inactive.",
        )
    row.is_active = False
    row.set_by_id = requesting_user_id if requesting_user_id != -1 else None
    await db.commit()
    await db.refresh(row)
    return row


async def list_department_policies(
    db: AsyncSession,
    account_id: int,
    is_active: Optional[bool] = None,
) -> list[CorporateDepartmentRidePolicy]:
    """List all department ride policies for a corporate account.

    Args:
        account_id: Corporate account to scope results to.
        is_active:  When provided, filter by active/inactive status.

    Returns:
        Policies ordered by department_id ascending.
    """
    q = select(CorporateDepartmentRidePolicy).where(
        CorporateDepartmentRidePolicy.account_id == account_id
    )
    if is_active is not None:
        q = q.where(CorporateDepartmentRidePolicy.is_active.is_(is_active))
    q = q.order_by(CorporateDepartmentRidePolicy.department_id.asc())
    result = await db.execute(q)
    return list(result.scalars().all())


async def get_effective_policy_for_member(
    db: AsyncSession,
    account_id: int,
    member_id: int,
) -> EffectiveDepartmentPolicyResponse:
    """Compute the effective ride policy for a member across all three layers.

    Resolution order (highest → lowest precedence):
      1. CorporateMemberPolicyOverride (active only)
      2. CorporateDepartmentRidePolicy (most restrictive across departments)
      3. CorporateRidePolicy           (account-level defaults)

    "Most restrictive" for department policies:
      - ``require_purpose`` / ``business_hours_only``: True wins.
      - ``max_per_ride_usd``: minimum value wins (lower cap is tighter).
      - ``allowed_vehicle_categories``: intersection of all lists.
      - ``approved_purposes``: intersection of all approved purpose lists.

    Args:
        account_id: Corporate account to scope the lookup to.
        member_id:  The ``BusinessAccountMember.id`` (not user_id).

    Raises:
        HTTP 404 if the member does not exist in the account.
    """
    # --- Fetch member record ---
    member_result = await db.execute(
        select(BusinessAccountMember).where(
            BusinessAccountMember.id == member_id,
            BusinessAccountMember.account_id == account_id,
        )
    )
    member = member_result.scalar_one_or_none()
    if member is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Member {member_id} not found in account {account_id}.",
        )

    # --- Fetch account-level policy (base) ---
    policy_result = await db.execute(
        select(CorporateRidePolicy).where(
            CorporateRidePolicy.account_id == account_id
        )
    )
    account_policy = policy_result.scalar_one_or_none()

    # --- Fetch member's department memberships ---
    dept_member_result = await db.execute(
        select(CorporateDepartmentMember).where(
            CorporateDepartmentMember.user_id == member.user_id,
        )
    )
    dept_memberships = list(dept_member_result.scalars().all())
    dept_ids = [dm.department_id for dm in dept_memberships]

    # --- Fetch active department policies for those departments ---
    dept_policies: list[CorporateDepartmentRidePolicy] = []
    dept_ids_applied: list[int] = []
    if dept_ids:
        dp_result = await db.execute(
            select(CorporateDepartmentRidePolicy).where(
                CorporateDepartmentRidePolicy.account_id == account_id,
                CorporateDepartmentRidePolicy.department_id.in_(dept_ids),
                CorporateDepartmentRidePolicy.is_active.is_(True),
            )
        )
        dept_policies = list(dp_result.scalars().all())
        dept_ids_applied = [dp.department_id for dp in dept_policies]

    # --- Fetch member override ---
    override_result = await db.execute(
        select(CorporateMemberPolicyOverride).where(
            CorporateMemberPolicyOverride.account_id == account_id,
            CorporateMemberPolicyOverride.member_id == member_id,
        )
    )
    override = override_result.scalar_one_or_none()

    has_member_override = override is not None
    override_is_active = override.is_active if override is not None else None
    apply_override = has_member_override and override_is_active is True

    # -----------------------------------------------------------------------
    # Layer 1 — Account base values
    # -----------------------------------------------------------------------
    allowed_vehicle_categories = (
        account_policy.allowed_vehicle_categories if account_policy else None
    )
    max_per_ride_usd = account_policy.max_per_ride_usd if account_policy else None
    max_per_member_monthly_usd = (
        account_policy.max_per_member_monthly_usd if account_policy else None
    )
    require_purpose: bool = account_policy.require_purpose if account_policy else False
    approved_purposes = account_policy.approved_purposes if account_policy else None
    business_hours_only: bool = (
        account_policy.business_hours_only if account_policy else False
    )

    # -----------------------------------------------------------------------
    # Layer 2 — Department policy merge (most restrictive per field)
    # -----------------------------------------------------------------------
    for dp in dept_policies:
        # Boolean fields: True is more restrictive
        if dp.require_purpose is not None:
            require_purpose = require_purpose or dp.require_purpose
        if dp.business_hours_only is not None:
            business_hours_only = business_hours_only or dp.business_hours_only

        # Numeric: lower cap is more restrictive
        if dp.max_per_ride_usd is not None:
            if max_per_ride_usd is None:
                max_per_ride_usd = dp.max_per_ride_usd
            else:
                max_per_ride_usd = min(max_per_ride_usd, dp.max_per_ride_usd)

        # List fields: intersection is most restrictive
        if dp.allowed_vehicle_categories is not None:
            if allowed_vehicle_categories is None:
                # Account has no constraint → start from department's set
                allowed_vehicle_categories = dp.allowed_vehicle_categories
            else:
                # Intersect: only types allowed by both account and dept
                dept_set = set(dp.allowed_vehicle_categories)
                allowed_vehicle_categories = [
                    v for v in allowed_vehicle_categories if v in dept_set
                ]

        if dp.approved_purposes is not None:
            if approved_purposes is None:
                approved_purposes = dp.approved_purposes
            else:
                dept_purpose_set = set(dp.approved_purposes)
                approved_purposes = [
                    p for p in approved_purposes if p in dept_purpose_set
                ]

    # -----------------------------------------------------------------------
    # Layer 3 — Member override (highest precedence, wins when active and set)
    # -----------------------------------------------------------------------
    if apply_override:
        if override.allowed_vehicle_categories is not None:
            allowed_vehicle_categories = override.allowed_vehicle_categories
        if override.max_per_ride_usd is not None:
            max_per_ride_usd = override.max_per_ride_usd
        if override.require_purpose is not None:
            require_purpose = override.require_purpose
        if override.approved_purposes is not None:
            approved_purposes = override.approved_purposes
        if override.business_hours_only is not None:
            business_hours_only = override.business_hours_only

    return EffectiveDepartmentPolicyResponse(
        member_id=member_id,
        account_id=account_id,
        department_ids_applied=dept_ids_applied,
        has_member_override=has_member_override,
        member_override_is_active=override_is_active,
        allowed_vehicle_categories=allowed_vehicle_categories,
        max_per_ride_usd=max_per_ride_usd,
        max_per_member_monthly_usd=max_per_member_monthly_usd,
        require_purpose=require_purpose,
        approved_purposes=approved_purposes,
        business_hours_only=business_hours_only,
    )


async def list_all_department_policies_platform(
    db: AsyncSession,
    skip: int = 0,
    limit: int = 100,
) -> list[CorporateDepartmentRidePolicy]:
    """Platform-admin: list all department ride policies across all accounts.

    Ordered newest-first.  Intended for platform support and auditing.
    """
    result = await db.execute(
        select(CorporateDepartmentRidePolicy)
        .order_by(CorporateDepartmentRidePolicy.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    return list(result.scalars().all())
