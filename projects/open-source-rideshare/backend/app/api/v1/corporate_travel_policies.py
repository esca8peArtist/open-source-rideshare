"""Corporate Travel Policy & Acknowledgement endpoints.

Admins create versioned travel policy documents for their corporate account.
Employees acknowledge the active policy before booking corporate rides.
One policy may be active per account at any time; activating a new one
automatically deactivates the previous active policy.

Member endpoints (any account member):
  GET    /corporate/accounts/me/travel-policy                      — active policy
  GET    /corporate/accounts/me/travel-policy/my-status            — own ack status
  POST   /corporate/accounts/me/travel-policy/{policy_id}/acknowledge
                                                                   — acknowledge

Admin endpoints (account admins only):
  POST   /corporate/accounts/me/travel-policies                    — create draft
  GET    /corporate/accounts/me/travel-policies                    — list all versions
  GET    /corporate/accounts/me/travel-policies/{policy_id}        — get by ID
  PUT    /corporate/accounts/me/travel-policies/{policy_id}        — update draft
  POST   /corporate/accounts/me/travel-policies/{policy_id}/activate
                                                                   — activate
  POST   /corporate/accounts/me/travel-policies/{policy_id}/deactivate
                                                                   — deactivate
  DELETE /corporate/accounts/me/travel-policies/{policy_id}        — delete draft
  GET    /corporate/accounts/me/travel-policies/{policy_id}/acknowledgements
                                                                   — ack summary

Platform-admin endpoints:
  GET    /platform/corporate/travel-policies                       — all accounts
  GET    /platform/corporate/accounts/{account_id}/travel-policies — by account
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.models.user import User
from app.schemas.corporate_travel_policy import (
    AcknowledgementResponse,
    AcknowledgementSummary,
    MemberAcknowledgementStatus,
    TravelPolicyCreate,
    TravelPolicyListResponse,
    TravelPolicyResponse,
    TravelPolicyUpdate,
)
from app.services.corporate_account_mgmt import get_user_account
from app.services.corporate_travel_policy import (
    acknowledge_policy,
    activate_policy,
    create_policy,
    deactivate_policy,
    delete_policy,
    get_acknowledgement_summary,
    get_active_policy,
    get_member_acknowledgement_status,
    get_policy,
    list_all_platform,
    list_policies,
    update_policy,
)
from app.services.corporate_trip_purpose import _require_account_admin

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Corporate Travel Policies"])


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
# Member: get active policy
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/travel-policy",
    response_model=Optional[TravelPolicyResponse],
    summary="Get the active travel policy for the account",
)
async def get_active_travel_policy(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the active travel policy for the account.

    Returns ``null`` (HTTP 200) if no policy is currently active.
    Any active corporate account member may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    return await get_active_policy(db, account_id)


# ---------------------------------------------------------------------------
# Member: acknowledgement status
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/travel-policy/my-status",
    response_model=MemberAcknowledgementStatus,
    summary="Get own acknowledgement status for the active policy",
)
async def get_my_acknowledgement_status(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the authenticated employee's acknowledgement status.

    Reports whether they have acknowledged the current active policy,
    the timestamp of acknowledgement, and whether acknowledgement is
    required.  Any active corporate account member may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    return await get_member_acknowledgement_status(db, account_id, user.id)


# ---------------------------------------------------------------------------
# Member: acknowledge a policy
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/accounts/me/travel-policy/{policy_id}/acknowledge",
    response_model=AcknowledgementResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Acknowledge the active travel policy",
)
async def acknowledge_travel_policy(
    policy_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Record the authenticated employee's acknowledgement of a travel policy.

    The policy must be active.  Returns 409 if the member has already
    acknowledged this policy version.  Any active corporate account member
    may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    return await acknowledge_policy(db, account_id, user.id, policy_id)


# ---------------------------------------------------------------------------
# Admin: create draft policy
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/accounts/me/travel-policies",
    response_model=TravelPolicyResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new (draft) travel policy (admin only)",
)
async def create_travel_policy(
    data: TravelPolicyCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new draft travel policy for the account.

    The policy is initially inactive.  Admins must activate it separately.
    Only account admins may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    return await create_policy(db, account_id, user.id, data)


# ---------------------------------------------------------------------------
# Admin: list all policy versions
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/travel-policies",
    response_model=TravelPolicyListResponse,
    summary="List all travel policy versions (admin only)",
)
async def list_travel_policies(
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all travel policy versions for the account, newest first.

    Only account admins may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    return await list_policies(db, account_id, is_active=is_active)


# ---------------------------------------------------------------------------
# Admin: get specific policy  (must precede activate/deactivate/ack routes)
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/travel-policies/{policy_id}",
    response_model=TravelPolicyResponse,
    summary="Get a specific travel policy version (admin only)",
)
async def get_travel_policy(
    policy_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a specific travel policy by ID.

    Only account admins may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    return await get_policy(db, account_id, policy_id)


# ---------------------------------------------------------------------------
# Admin: update draft policy
# ---------------------------------------------------------------------------


@router.put(
    "/corporate/accounts/me/travel-policies/{policy_id}",
    response_model=TravelPolicyResponse,
    summary="Update a draft travel policy (admin only)",
)
async def update_travel_policy(
    policy_id: int,
    data: TravelPolicyUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Partially update a draft (inactive) travel policy.

    Returns 409 if the policy is currently active — deactivate first.
    Only account admins may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    return await update_policy(db, account_id, policy_id, data)


# ---------------------------------------------------------------------------
# Admin: activate policy
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/accounts/me/travel-policies/{policy_id}/activate",
    response_model=TravelPolicyResponse,
    summary="Activate a travel policy (admin only)",
)
async def activate_travel_policy(
    policy_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Activate a travel policy, deactivating any currently active policy.

    Returns 409 if the policy is already active.
    Only account admins may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    return await activate_policy(db, account_id, policy_id)


# ---------------------------------------------------------------------------
# Admin: deactivate policy
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/accounts/me/travel-policies/{policy_id}/deactivate",
    response_model=TravelPolicyResponse,
    summary="Deactivate a travel policy (admin only)",
)
async def deactivate_travel_policy(
    policy_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Deactivate a travel policy (returns it to draft state).

    Returns 409 if the policy is already inactive.
    Only account admins may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    return await deactivate_policy(db, account_id, policy_id)


# ---------------------------------------------------------------------------
# Admin: delete draft policy
# ---------------------------------------------------------------------------


@router.delete(
    "/corporate/accounts/me/travel-policies/{policy_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a draft travel policy (admin only)",
)
async def delete_travel_policy(
    policy_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Hard-delete a travel policy.

    Returns 409 if the policy is active — deactivate it first.
    Only account admins may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    await delete_policy(db, account_id, policy_id)


# ---------------------------------------------------------------------------
# Admin: acknowledgement summary for a policy
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/travel-policies/{policy_id}/acknowledgements",
    response_model=AcknowledgementSummary,
    summary="Get acknowledgement summary for a policy (admin only)",
)
async def get_policy_acknowledgements(
    policy_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all acknowledgement records for a specific policy.

    Includes a total count and per-member acknowledgement details.
    Only account admins may call this endpoint.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    return await get_acknowledgement_summary(db, account_id, policy_id)


# ---------------------------------------------------------------------------
# Platform-admin: list all policies
# ---------------------------------------------------------------------------


@router.get(
    "/platform/corporate/travel-policies",
    response_model=TravelPolicyListResponse,
    summary="Platform admin: list all travel policies",
)
async def admin_list_all_travel_policies(
    account_id: Optional[int] = Query(None, description="Filter by account ID"),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return all travel policies across all accounts.

    Optionally filter by ``account_id``.  Platform admin only.
    """
    return await list_all_platform(db, account_id=account_id)


# ---------------------------------------------------------------------------
# Platform-admin: list policies for a specific account
# ---------------------------------------------------------------------------


@router.get(
    "/platform/corporate/accounts/{account_id}/travel-policies",
    response_model=TravelPolicyListResponse,
    summary="Platform admin: list travel policies for a specific account",
)
async def admin_list_account_travel_policies(
    account_id: int,
    is_active: Optional[bool] = Query(None),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return all travel policies for any corporate account.

    Platform admin only.
    """
    return await list_policies(db, account_id, is_active=is_active)
