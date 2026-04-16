"""Corporate Member Policy Override endpoints.

Admin endpoints (require_admin):
  POST   /corporate/accounts/{account_id}/member-policy-overrides
         — create a per-member policy override
  GET    /corporate/accounts/{account_id}/member-policy-overrides
         — list overrides for an account (optional is_active filter)
  GET    /corporate/accounts/{account_id}/member-policy-overrides/{member_id}
         — fetch the override for a specific member
  PUT    /corporate/accounts/{account_id}/member-policy-overrides/{member_id}
         — update an existing override
  DELETE /corporate/accounts/{account_id}/member-policy-overrides/{member_id}
         — hard-delete an override
  POST   /corporate/accounts/{account_id}/member-policy-overrides/{member_id}/deactivate
         — soft-deactivate an override

Member endpoints (authenticated):
  GET /corporate/accounts/me/effective-policy
      — view the effective (merged) ride policy for the authenticated member

Platform-admin:
  GET /admin/corporate/member-policy-overrides
      — list all overrides across all accounts
  GET /admin/corporate/accounts/{account_id}/member-policy-overrides
      — list overrides for a specific account (platform-admin view)
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.models.user import User
from app.schemas.corporate_member_policy_override import (
    EffectivePolicyResponse,
    MemberPolicyOverrideCreate,
    MemberPolicyOverrideListResponse,
    MemberPolicyOverrideResponse,
    MemberPolicyOverrideUpdate,
)
from app.services.corporate_account_mgmt import get_user_account
from app.services.corporate_member_policy_override import (
    create_member_override,
    deactivate_member_override,
    delete_member_override,
    get_effective_policy,
    get_member_override,
    get_members_with_overrides,
    list_all_overrides_platform,
    list_member_overrides,
    update_member_override,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["corporate-member-policy-overrides"])


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------


async def _resolve_member_account(db: AsyncSession, user_id: int) -> int:
    """Return the corporate account ID for the authenticated member.

    Raises HTTP 404 when the user is not a member of any corporate account.
    """
    account = await get_user_account(db, user_id)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="You are not a member of any corporate account.",
        )
    return account.id


async def _get_member_id_for_user(db: AsyncSession, user_id: int, account_id: int) -> int:
    """Return the corporate_account_members.id for the authenticated user.

    Raises HTTP 404 when the user is not a member of the given account.
    """
    from sqlalchemy import select
    from app.models.corporate import BusinessAccountMember

    result = await db.execute(
        select(BusinessAccountMember.id).where(
            BusinessAccountMember.account_id == account_id,
            BusinessAccountMember.user_id == user_id,
        )
    )
    member_id = result.scalar_one_or_none()
    if member_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="You are not a member of any corporate account.",
        )
    return member_id


# ===========================================================================
# Admin endpoints
# ===========================================================================


@router.post(
    "/corporate/accounts/{account_id}/member-policy-overrides",
    response_model=MemberPolicyOverrideResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Admin: create a per-member policy override",
)
async def admin_create_override(
    account_id: int,
    payload: MemberPolicyOverrideCreate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Grant a per-member exception to the account-level ride policy.

    Specify only the fields that differ from the account policy.  Any
    field left as ``null`` will inherit the account policy value.

    Returns HTTP 404 if the account or member does not exist.
    Returns HTTP 409 if an override already exists for this member.

    Corporate admin only.
    """
    row = await create_member_override(
        db, account_id=account_id, data=payload, requesting_user_id=admin.id
    )
    return MemberPolicyOverrideResponse.model_validate(row)


@router.get(
    "/corporate/accounts/{account_id}/member-policy-overrides",
    response_model=MemberPolicyOverrideListResponse,
    summary="Admin: list per-member policy overrides for an account",
)
async def admin_list_overrides(
    account_id: int,
    is_active: bool | None = Query(None, description="Filter by active status"),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """List all per-member policy overrides for a corporate account.

    Optionally filter by ``is_active``.  Results are ordered newest-first.

    Corporate admin only.
    """
    rows = await list_member_overrides(db, account_id, is_active=is_active)
    return MemberPolicyOverrideListResponse(
        overrides=[MemberPolicyOverrideResponse.model_validate(r) for r in rows],
        total=len(rows),
    )


@router.get(
    "/corporate/accounts/{account_id}/member-policy-overrides/{member_id}",
    response_model=MemberPolicyOverrideResponse,
    summary="Admin: get the policy override for a specific member",
)
async def admin_get_override(
    account_id: int,
    member_id: int,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Fetch the policy override for a specific member.

    Returns HTTP 404 if no override exists for this member.

    Corporate admin only.
    """
    row = await get_member_override(db, account_id=account_id, member_id=member_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No policy override found for member {member_id}.",
        )
    return MemberPolicyOverrideResponse.model_validate(row)


@router.put(
    "/corporate/accounts/{account_id}/member-policy-overrides/{member_id}",
    response_model=MemberPolicyOverrideResponse,
    summary="Admin: update a per-member policy override",
)
async def admin_update_override(
    account_id: int,
    member_id: int,
    payload: MemberPolicyOverrideUpdate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Update an existing per-member policy override.

    All request body fields are optional.  Only supplied (non-null) fields
    are written.

    Returns HTTP 404 if no override exists for this member.

    Corporate admin only.
    """
    row = await update_member_override(
        db,
        account_id=account_id,
        member_id=member_id,
        data=payload,
        requesting_user_id=admin.id,
    )
    return MemberPolicyOverrideResponse.model_validate(row)


@router.delete(
    "/corporate/accounts/{account_id}/member-policy-overrides/{member_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Admin: delete a per-member policy override",
)
async def admin_delete_override(
    account_id: int,
    member_id: int,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Permanently remove a per-member policy override.

    The member will revert to the account-level policy after deletion.
    Returns HTTP 404 if no override exists for this member.

    Corporate admin only.
    """
    await delete_member_override(
        db,
        account_id=account_id,
        member_id=member_id,
        requesting_user_id=admin.id,
    )


@router.post(
    "/corporate/accounts/{account_id}/member-policy-overrides/{member_id}/deactivate",
    response_model=MemberPolicyOverrideResponse,
    summary="Admin: deactivate a per-member policy override",
)
async def admin_deactivate_override(
    account_id: int,
    member_id: int,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Soft-deactivate a per-member policy override.

    The override row is preserved for audit history but will no longer
    affect the member's effective policy.

    Returns HTTP 404 if no override exists for this member.
    Returns HTTP 409 if the override is already inactive.

    Corporate admin only.
    """
    row = await deactivate_member_override(
        db,
        account_id=account_id,
        member_id=member_id,
        requesting_user_id=admin.id,
    )
    return MemberPolicyOverrideResponse.model_validate(row)


# ===========================================================================
# Member endpoints
# ===========================================================================


@router.get(
    "/corporate/accounts/me/effective-policy",
    response_model=EffectivePolicyResponse,
    summary="View your effective ride policy (account policy + any override)",
)
async def member_get_effective_policy(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the effective ride policy for the authenticated member.

    Merges the account-level policy with any active per-member override.
    Override fields take precedence when an active override exists and the
    field is not null in the override row.

    Returns HTTP 404 if the user is not a member of any corporate account.
    """
    account_id = await _resolve_member_account(db, user.id)
    member_id = await _get_member_id_for_user(db, user.id, account_id)
    return await get_effective_policy(db, account_id=account_id, member_id=member_id)


# ===========================================================================
# Platform-admin endpoints
# ===========================================================================


@router.get(
    "/admin/corporate/member-policy-overrides",
    response_model=MemberPolicyOverrideListResponse,
    summary="Platform-admin: list all per-member policy overrides",
)
async def platform_admin_list_all_overrides(
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """List all per-member policy overrides across all corporate accounts.

    Ordered newest-first.  Platform admin only.
    """
    rows = await list_all_overrides_platform(db)
    return MemberPolicyOverrideListResponse(
        overrides=[MemberPolicyOverrideResponse.model_validate(r) for r in rows],
        total=len(rows),
    )


@router.get(
    "/admin/corporate/accounts/{account_id}/member-policy-overrides",
    response_model=MemberPolicyOverrideListResponse,
    summary="Platform-admin: list per-member overrides for a specific account",
)
async def platform_admin_list_account_overrides(
    account_id: int,
    is_active: bool | None = Query(None, description="Filter by active status"),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """List all per-member policy overrides for a specific corporate account.

    Platform support view — bypasses account-admin check.
    Optionally filter by ``is_active``.  Ordered newest-first.

    Platform admin only.
    """
    rows = await list_member_overrides(db, account_id, is_active=is_active)
    return MemberPolicyOverrideListResponse(
        overrides=[MemberPolicyOverrideResponse.model_validate(r) for r in rows],
        total=len(rows),
    )
