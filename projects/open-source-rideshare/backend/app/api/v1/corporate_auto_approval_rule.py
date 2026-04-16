"""Corporate Auto-Approval Rule API endpoints.

Corporate account admins configure rules that automatically approve ride
requests when all specified conditions are met.  This reduces admin overhead
for routine, low-risk rides.

Member/admin routes (prefix /api/v1/corporate/accounts/me/auto-approval-rules):
  POST   /                  — admin: create rule
  GET    /                  — member: list rules (optional ?is_active= filter)
  GET    /{rule_id}         — member: get rule
  PUT    /{rule_id}         — admin: update rule
  POST   /{rule_id}/activate   — admin: activate rule
  POST   /{rule_id}/deactivate — admin: deactivate rule
  DELETE /{rule_id}         — admin: hard-delete rule (204)
  POST   /evaluate          — member: evaluate a hypothetical ride

Platform-admin routes (prefix /api/v1/platform/corporate/auto-approval-rules):
  GET /                              — paginated list across all accounts
  GET /accounts/{account_id}         — list rules for a specific account
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.models.user import User
from app.schemas.corporate_auto_approval_rule import (
    AutoApprovalRuleCreate,
    AutoApprovalRuleListResponse,
    AutoApprovalRuleResponse,
    AutoApprovalRuleUpdate,
    EvaluateAutoApprovalRequest,
    EvaluateAutoApprovalResponse,
)
from app.services.corporate_account_mgmt import get_user_account
from app.services.corporate_auto_approval_rule import (
    activate_auto_approval_rule,
    create_auto_approval_rule,
    deactivate_auto_approval_rule,
    delete_auto_approval_rule,
    evaluate_auto_approval,
    get_auto_approval_rule,
    list_all_auto_approval_rules_platform,
    list_auto_approval_rules,
    update_auto_approval_rule,
)
from app.services.corporate_trip_purpose import _require_account_admin

logger = logging.getLogger(__name__)

router = APIRouter(tags=["corporate-auto-approval-rules"])

_BASE = "/corporate/accounts/me/auto-approval-rules"
_PLATFORM_BASE = "/platform/corporate/auto-approval-rules"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _resolve_account(db: AsyncSession, user_id: int):
    """Return the BusinessAccount for an authenticated member.

    Raises HTTP 404 if the user is not a member of any corporate account.
    """
    from fastapi import HTTPException

    account = await get_user_account(db, user_id)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="You are not a member of any corporate account.",
        )
    return account


# ---------------------------------------------------------------------------
# Member / admin routes
# ---------------------------------------------------------------------------


@router.post(
    _BASE,
    response_model=AutoApprovalRuleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an auto-approval rule for your corporate account",
)
async def create_rule(
    data: AutoApprovalRuleCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new auto-approval rule.

    Requires account-admin role.  Returns 409 if an active rule with the
    same name already exists for the account.
    """
    account = await _resolve_account(db, current_user.id)
    await _require_account_admin(db, current_user.id, account.id)
    rule = await create_auto_approval_rule(db, account.id, current_user.id, data)
    return AutoApprovalRuleResponse.model_validate(rule)


@router.get(
    _BASE,
    response_model=AutoApprovalRuleListResponse,
    summary="List auto-approval rules for your corporate account",
)
async def list_rules(
    is_active: Optional[bool] = Query(
        None,
        description="Filter by active status.  Omit for all rules.",
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all auto-approval rules for the caller's account.

    Ordered by priority DESC, created_at ASC.  Optionally filter by
    is_active.
    """
    account = await _resolve_account(db, current_user.id)
    rules = await list_auto_approval_rules(db, account.id, is_active=is_active)
    return AutoApprovalRuleListResponse(
        items=[AutoApprovalRuleResponse.model_validate(r) for r in rules],
        total=len(rules),
    )


@router.get(
    f"{_BASE}/{{rule_id}}",
    response_model=AutoApprovalRuleResponse,
    summary="Get a specific auto-approval rule",
)
async def get_rule(
    rule_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Fetch a single auto-approval rule by ID, scoped to the caller's account."""
    account = await _resolve_account(db, current_user.id)
    rule = await get_auto_approval_rule(db, rule_id, account.id)
    return AutoApprovalRuleResponse.model_validate(rule)


@router.put(
    f"{_BASE}/{{rule_id}}",
    response_model=AutoApprovalRuleResponse,
    summary="Update an auto-approval rule",
)
async def update_rule(
    rule_id: int,
    data: AutoApprovalRuleUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update an existing auto-approval rule.

    Requires account-admin role.  Returns 409 on name collision with a
    different active rule.
    """
    account = await _resolve_account(db, current_user.id)
    await _require_account_admin(db, current_user.id, account.id)
    rule = await update_auto_approval_rule(db, rule_id, account.id, data)
    return AutoApprovalRuleResponse.model_validate(rule)


@router.post(
    f"{_BASE}/{{rule_id}}/activate",
    response_model=AutoApprovalRuleResponse,
    summary="Activate an auto-approval rule",
)
async def activate_rule(
    rule_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Activate an auto-approval rule.

    Requires account-admin role.  Returns 409 if the rule is already active.
    """
    account = await _resolve_account(db, current_user.id)
    await _require_account_admin(db, current_user.id, account.id)
    rule = await activate_auto_approval_rule(db, rule_id, account.id)
    return AutoApprovalRuleResponse.model_validate(rule)


@router.post(
    f"{_BASE}/{{rule_id}}/deactivate",
    response_model=AutoApprovalRuleResponse,
    summary="Deactivate an auto-approval rule",
)
async def deactivate_rule(
    rule_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Deactivate an auto-approval rule.

    Requires account-admin role.  Returns 409 if the rule is already inactive.
    """
    account = await _resolve_account(db, current_user.id)
    await _require_account_admin(db, current_user.id, account.id)
    rule = await deactivate_auto_approval_rule(db, rule_id, account.id)
    return AutoApprovalRuleResponse.model_validate(rule)


@router.delete(
    f"{_BASE}/{{rule_id}}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an auto-approval rule",
)
async def delete_rule(
    rule_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Hard-delete an auto-approval rule.

    Requires account-admin role.  Returns 404 if the rule does not exist.
    """
    account = await _resolve_account(db, current_user.id)
    await _require_account_admin(db, current_user.id, account.id)
    await delete_auto_approval_rule(db, rule_id, account.id)


@router.post(
    f"{_BASE}/evaluate",
    response_model=EvaluateAutoApprovalResponse,
    summary="Evaluate auto-approval for a hypothetical ride",
)
async def evaluate_rule(
    data: EvaluateAutoApprovalRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Check whether a hypothetical ride would be auto-approved.

    Returns the matched rule ID and name when auto-approval fires, or null
    values when no rule matches.
    """
    account = await _resolve_account(db, current_user.id)

    # Resolve the member record for the current user
    from sqlalchemy import select as sa_select
    from app.models.corporate import BusinessAccountMember

    result = await db.execute(
        sa_select(BusinessAccountMember).where(
            BusinessAccountMember.user_id == current_user.id,
            BusinessAccountMember.account_id == account.id,
            BusinessAccountMember.is_active.is_(True),
        )
    )
    membership = result.scalar_one_or_none()
    member_id = membership.id if membership is not None else current_user.id

    approved, matched_rule = await evaluate_auto_approval(
        db,
        account_id=account.id,
        member_id=member_id,
        estimated_cost_usd=data.estimated_cost_usd,
        trip_purpose_id=data.trip_purpose_id,
        cost_center_id=data.cost_center_id,
        ride_dt=data.ride_datetime,
    )
    return EvaluateAutoApprovalResponse(
        auto_approved=approved,
        matched_rule_id=matched_rule.id if matched_rule else None,
        matched_rule_name=matched_rule.name if matched_rule else None,
    )


# ---------------------------------------------------------------------------
# Platform-admin routes
# ---------------------------------------------------------------------------


@router.get(
    _PLATFORM_BASE,
    response_model=AutoApprovalRuleListResponse,
    summary="[Admin] List all auto-approval rules across all accounts",
    dependencies=[Depends(require_admin)],
)
async def platform_list_all_rules(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    """List all auto-approval rules across every corporate account.

    Platform-admin only.  Results are ordered newest-first.
    """
    rules = await list_all_auto_approval_rules_platform(db, skip=skip, limit=limit)
    return AutoApprovalRuleListResponse(
        items=[AutoApprovalRuleResponse.model_validate(r) for r in rules],
        total=len(rules),
    )


@router.get(
    f"{_PLATFORM_BASE}/accounts/{{account_id}}",
    response_model=AutoApprovalRuleListResponse,
    summary="[Admin] List auto-approval rules for a specific account",
    dependencies=[Depends(require_admin)],
)
async def platform_list_account_rules(
    account_id: int,
    is_active: Optional[bool] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """List auto-approval rules for any corporate account.

    Platform-admin only.
    """
    rules = await list_auto_approval_rules(db, account_id, is_active=is_active)
    return AutoApprovalRuleListResponse(
        items=[AutoApprovalRuleResponse.model_validate(r) for r in rules],
        total=len(rules),
    )
