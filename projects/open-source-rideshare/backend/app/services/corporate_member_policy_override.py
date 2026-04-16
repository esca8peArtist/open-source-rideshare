"""Service layer for Corporate Member Policy Overrides.

Admins define per-member exceptions to the account-level CorporateRidePolicy.
Override fields that are NULL mean "inherit from account policy"; only
specified fields are overridden.

The ``get_effective_policy`` function merges account policy + member override
into a single EffectivePolicyResponse that callers (e.g. the booking engine)
can use without knowing about the two-layer structure.

Public surface
--------------
create_member_override(db, account_id, data, requesting_user_id)
    -> CorporateMemberPolicyOverride
get_member_override(db, account_id, member_id)
    -> CorporateMemberPolicyOverride | None
update_member_override(db, account_id, member_id, data, requesting_user_id)
    -> CorporateMemberPolicyOverride
deactivate_member_override(db, account_id, member_id, requesting_user_id)
    -> CorporateMemberPolicyOverride
delete_member_override(db, account_id, member_id, requesting_user_id)
    -> None
get_effective_policy(db, account_id, member_id)
    -> EffectivePolicyResponse
list_member_overrides(db, account_id, is_active)
    -> list[CorporateMemberPolicyOverride]
list_all_overrides_platform(db)
    -> list[CorporateMemberPolicyOverride]
get_members_with_overrides(db, account_id)
    -> list[int]
"""

from __future__ import annotations

from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.corporate import (
    BusinessAccount,
    BusinessAccountMember,
    CorporateAccountStatus,
    MemberRole,
)
from app.models.corporate_member_policy_override import CorporateMemberPolicyOverride
from app.models.corporate_ride_policy import CorporateRidePolicy
from app.schemas.corporate_member_policy_override import (
    EffectivePolicyResponse,
    MemberPolicyOverrideCreate,
    MemberPolicyOverrideUpdate,
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

    Pass ``requesting_user_id=-1`` from platform-admin endpoints to bypass
    this check.
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
            detail="Only account admins may manage member policy overrides.",
        )


async def _get_member_or_404(
    db: AsyncSession, account_id: int, member_id: int
) -> BusinessAccountMember:
    """Verify the member belongs to the account; raise HTTP 404 otherwise."""
    result = await db.execute(
        select(BusinessAccountMember).where(
            BusinessAccountMember.id == member_id,
            BusinessAccountMember.account_id == account_id,
        )
    )
    member = result.scalar_one_or_none()
    if member is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Member {member_id} not found in account {account_id}.",
        )
    return member


async def _get_override_or_404(
    db: AsyncSession, account_id: int, member_id: int
) -> CorporateMemberPolicyOverride:
    """Fetch an override row or raise HTTP 404."""
    row = await get_member_override(db, account_id, member_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No policy override found for member {member_id} in account {account_id}.",
        )
    return row


# ---------------------------------------------------------------------------
# Public service functions
# ---------------------------------------------------------------------------


async def create_member_override(
    db: AsyncSession,
    account_id: int,
    data: MemberPolicyOverrideCreate,
    requesting_user_id: int,
) -> CorporateMemberPolicyOverride:
    """Create a per-member policy override.

    Args:
        account_id:          Corporate account to scope the override to.
        data:                Override fields and metadata.
        requesting_user_id:  The admin creating the override.

    Raises:
        HTTP 404 if the account or member does not exist.
        HTTP 409 if an override row already exists for this member
                  (use ``update_member_override`` to change it).
    """
    await _get_account_or_404(db, account_id)
    await _require_account_admin(db, account_id, requesting_user_id)
    await _get_member_or_404(db, account_id, data.member_id)

    # Reject if any override row already exists (active or inactive)
    existing = await get_member_override(db, account_id, data.member_id)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"An override already exists for member {data.member_id}. "
                "Use PUT to update or DELETE to remove it first."
            ),
        )

    row = CorporateMemberPolicyOverride(
        account_id=account_id,
        member_id=data.member_id,
        overridden_by_id=requesting_user_id,
        allowed_vehicle_categories=data.allowed_vehicle_categories,
        max_per_ride_usd=data.max_per_ride_usd,
        require_purpose=data.require_purpose,
        approved_purposes=data.approved_purposes,
        business_hours_only=data.business_hours_only,
        reason=data.reason,
        custom_notes=data.custom_notes,
        valid_until=data.valid_until,
        is_active=True,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def get_member_override(
    db: AsyncSession,
    account_id: int,
    member_id: int,
) -> CorporateMemberPolicyOverride | None:
    """Fetch the override row for a member, or ``None`` if it does not exist.

    Callers are responsible for raising HTTP 404 when appropriate.
    """
    result = await db.execute(
        select(CorporateMemberPolicyOverride).where(
            CorporateMemberPolicyOverride.account_id == account_id,
            CorporateMemberPolicyOverride.member_id == member_id,
        )
    )
    return result.scalar_one_or_none()


async def update_member_override(
    db: AsyncSession,
    account_id: int,
    member_id: int,
    data: MemberPolicyOverrideUpdate,
    requesting_user_id: int,
) -> CorporateMemberPolicyOverride:
    """Update an existing per-member policy override.

    Only fields supplied in ``data`` (i.e. not ``None``) are written.

    Args:
        account_id:          Corporate account to scope the lookup to.
        member_id:           The member whose override is being updated.
        data:                Fields to update.
        requesting_user_id:  The admin making the change.

    Raises:
        HTTP 404 if no override row exists for this member.
    """
    await _require_account_admin(db, account_id, requesting_user_id)
    row = await _get_override_or_404(db, account_id, member_id)

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
    if data.reason is not None:
        row.reason = data.reason
    if data.custom_notes is not None:
        row.custom_notes = data.custom_notes
    if data.valid_until is not None:
        row.valid_until = data.valid_until
    if data.is_active is not None:
        row.is_active = data.is_active

    row.overridden_by_id = requesting_user_id
    await db.commit()
    await db.refresh(row)
    return row


async def deactivate_member_override(
    db: AsyncSession,
    account_id: int,
    member_id: int,
    requesting_user_id: int,
) -> CorporateMemberPolicyOverride:
    """Soft-deactivate a per-member policy override.

    Raises:
        HTTP 404 if no override row exists.
        HTTP 409 if the override is already inactive.
    """
    await _require_account_admin(db, account_id, requesting_user_id)
    row = await _get_override_or_404(db, account_id, member_id)
    if not row.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Override for member {member_id} is already inactive.",
        )
    row.is_active = False
    row.overridden_by_id = requesting_user_id
    await db.commit()
    await db.refresh(row)
    return row


async def delete_member_override(
    db: AsyncSession,
    account_id: int,
    member_id: int,
    requesting_user_id: int,
) -> None:
    """Hard-delete a per-member policy override.

    Raises:
        HTTP 404 if no override row exists.
    """
    await _require_account_admin(db, account_id, requesting_user_id)
    row = await _get_override_or_404(db, account_id, member_id)
    await db.delete(row)
    await db.commit()


async def get_effective_policy(
    db: AsyncSession,
    account_id: int,
    member_id: int,
) -> EffectivePolicyResponse:
    """Compute the effective ride policy for a member.

    Merges the account-level ``CorporateRidePolicy`` with any
    ``CorporateMemberPolicyOverride`` for this member.  Override fields
    take precedence when:
      - an override row exists, AND
      - ``override.is_active`` is ``True``, AND
      - the override field is not ``None``.

    ``max_per_member_monthly_usd`` is always sourced from the account policy
    (not overridable at per-member level).

    Returns:
        EffectivePolicyResponse with merged values and metadata about whether
        an override exists and whether it is active.
    """
    # Fetch account-level policy (may be None — no restrictions)
    policy_result = await db.execute(
        select(CorporateRidePolicy).where(
            CorporateRidePolicy.account_id == account_id
        )
    )
    account_policy = policy_result.scalar_one_or_none()

    # Fetch member override (may be None)
    override = await get_member_override(db, account_id, member_id)

    has_override = override is not None
    override_is_active = override.is_active if override is not None else None
    apply_override = has_override and override_is_active is True

    # Base values from account policy (defaults when no policy exists)
    allowed_vehicle_categories = (
        account_policy.allowed_vehicle_categories if account_policy else None
    )
    max_per_ride_usd = account_policy.max_per_ride_usd if account_policy else None
    max_per_member_monthly_usd = (
        account_policy.max_per_member_monthly_usd if account_policy else None
    )
    require_purpose = account_policy.require_purpose if account_policy else False
    approved_purposes = account_policy.approved_purposes if account_policy else None
    business_hours_only = account_policy.business_hours_only if account_policy else False

    # Apply override where set
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

    return EffectivePolicyResponse(
        member_id=member_id,
        account_id=account_id,
        has_override=has_override,
        override_is_active=override_is_active,
        allowed_vehicle_categories=allowed_vehicle_categories,
        max_per_ride_usd=max_per_ride_usd,
        max_per_member_monthly_usd=max_per_member_monthly_usd,
        require_purpose=require_purpose,
        approved_purposes=approved_purposes,
        business_hours_only=business_hours_only,
    )


async def list_member_overrides(
    db: AsyncSession,
    account_id: int,
    is_active: Optional[bool] = None,
) -> list[CorporateMemberPolicyOverride]:
    """List all per-member overrides for an account.

    Args:
        account_id: Corporate account to scope results to.
        is_active:  When provided, filter by active/inactive status.

    Returns:
        List of overrides ordered by created_at descending.
    """
    q = select(CorporateMemberPolicyOverride).where(
        CorporateMemberPolicyOverride.account_id == account_id
    )
    if is_active is not None:
        q = q.where(CorporateMemberPolicyOverride.is_active.is_(is_active))
    q = q.order_by(CorporateMemberPolicyOverride.created_at.desc())
    result = await db.execute(q)
    return list(result.scalars().all())


async def list_all_overrides_platform(
    db: AsyncSession,
) -> list[CorporateMemberPolicyOverride]:
    """Platform-admin: list all per-member overrides across all accounts.

    Ordered newest-first.  Intended for platform support and auditing.
    """
    result = await db.execute(
        select(CorporateMemberPolicyOverride).order_by(
            CorporateMemberPolicyOverride.created_at.desc()
        )
    )
    return list(result.scalars().all())


async def get_members_with_overrides(
    db: AsyncSession,
    account_id: int,
) -> list[int]:
    """Return the ``member_id`` values that have an active override for an account.

    Useful for quickly determining which members have exceptional policies
    without loading full override rows.

    Returns:
        Sorted list of member IDs.
    """
    result = await db.execute(
        select(CorporateMemberPolicyOverride.member_id).where(
            CorporateMemberPolicyOverride.account_id == account_id,
            CorporateMemberPolicyOverride.is_active.is_(True),
        )
    )
    return sorted(result.scalars().all())
