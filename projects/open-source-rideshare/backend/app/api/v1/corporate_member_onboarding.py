"""Corporate Member Onboarding endpoints.

Structured checklist for onboarding new employees into a corporate account.
Tracks ten setup steps with auto-detection from existing data.

Member endpoints:
  GET  /corporate/me/onboarding                        — own onboarding status

Admin endpoints (account admins only):
  POST   /corporate/admin/onboarding                              — create (201)
  GET    /corporate/admin/onboarding                              — list all
  GET    /corporate/admin/onboarding/overview                     — overview with step counts
  GET    /corporate/admin/onboarding/{onboarding_id}              — get detail
  PUT    /corporate/admin/onboarding/{onboarding_id}              — update notes
  POST   /corporate/admin/onboarding/{onboarding_id}/detect       — auto-detect progress
  POST   /corporate/admin/onboarding/{onboarding_id}/steps        — mark step complete
  POST   /corporate/admin/onboarding/{onboarding_id}/complete     — force complete
  GET    /corporate/admin/onboarding/{onboarding_id}/summary      — step summary
  GET    /corporate/admin/onboarding/{onboarding_id}/pending-steps — pending steps list
  GET    /corporate/admin/members/{member_id}/onboarding          — onboarding for member

Platform-admin endpoints:
  GET  /corporate/platform-admin/onboarding                              — all onboardings
  GET  /corporate/platform-admin/onboarding/{onboarding_id}             — get any
  GET  /corporate/platform-admin/accounts/{account_id}/onboarding       — all for account
"""

from __future__ import annotations

import logging
import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.models.corporate_member_onboarding import OnboardingStatus
from app.models.user import User
from app.schemas.corporate_member_onboarding import (
    AutoDetectResult,
    MarkStepRequest,
    OnboardingCreate,
    OnboardingListResponse,
    OnboardingOverviewResponse,
    OnboardingResponse,
    OnboardingSummaryResponse,
    OnboardingUpdate,
)
from app.services.corporate_account_mgmt import get_user_account
from app.services.corporate_member_onboarding import (
    auto_detect_progress,
    complete_onboarding,
    create_onboarding,
    get_onboarding,
    get_onboarding_for_member,
    get_onboarding_summary,
    list_account_onboardings_with_status,
    list_all_platform,
    list_onboardings,
    list_pending_steps,
    mark_step_complete,
    update_onboarding,
)
from app.services.corporate_trip_purpose import _require_account_admin

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Corporate Member Onboarding"])


# ---------------------------------------------------------------------------
# Internal helpers
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
# Member endpoint
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/me/onboarding",
    response_model=OnboardingResponse,
    summary="Member: get own onboarding status",
)
async def member_get_own_onboarding(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the authenticated member's onboarding tracker.

    Returns 404 if no onboarding record exists for this member.
    """
    account_id = await _resolve_account_id(db, user.id)
    return await get_onboarding_for_member(db, account_id, user.id)


# ---------------------------------------------------------------------------
# Admin endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/admin/onboarding",
    response_model=OnboardingResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Admin: create member onboarding tracker",
)
async def admin_create_onboarding(
    data: OnboardingCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create an onboarding tracker for a corporate account member.

    Returns 404 if the member is not in this account.
    Returns 409 if an active onboarding already exists for this member.
    Restricted to account admins.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    return await create_onboarding(
        db,
        account_id=account_id,
        member_id=data.member_id,
        created_by_id=user.id,
        invitation_id=data.invitation_id,
        notes=data.notes,
    )


@router.get(
    "/corporate/admin/onboarding/overview",
    response_model=OnboardingOverviewResponse,
    summary="Admin: list all onboardings with step counts",
)
async def admin_onboarding_overview(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all onboarding records for the account with step completion counts.

    Restricted to account admins.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    return await list_account_onboardings_with_status(db, account_id)


@router.get(
    "/corporate/admin/onboarding",
    response_model=OnboardingListResponse,
    summary="Admin: list onboardings",
)
async def admin_list_onboardings(
    status: Optional[OnboardingStatus] = Query(
        None, description="Filter by status"
    ),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all onboarding records for the admin's account.

    Optionally filter by status.  Restricted to account admins.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    return await list_onboardings(db, account_id, status_filter=status)


@router.get(
    "/corporate/admin/members/{member_id}/onboarding",
    response_model=OnboardingResponse,
    summary="Admin: get current or most recent onboarding for a member",
)
async def admin_get_member_onboarding(
    member_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the current active or most recent onboarding for a specific member.

    Returns 404 if no onboarding exists for this member.
    Restricted to account admins.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    return await get_onboarding_for_member(db, account_id, member_id)


@router.get(
    "/corporate/admin/onboarding/{onboarding_id}",
    response_model=OnboardingResponse,
    summary="Admin: get onboarding detail",
)
async def admin_get_onboarding(
    onboarding_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a single onboarding record by ID.

    Returns 404 if not found.  Restricted to account admins.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    return await get_onboarding(db, onboarding_id, account_id)


@router.put(
    "/corporate/admin/onboarding/{onboarding_id}",
    response_model=OnboardingResponse,
    summary="Admin: update onboarding notes",
)
async def admin_update_onboarding(
    onboarding_id: uuid.UUID,
    data: OnboardingUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update notes for an onboarding record.

    Returns 404 if not found.  Restricted to account admins.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    return await update_onboarding(db, onboarding_id, account_id, data)


@router.post(
    "/corporate/admin/onboarding/{onboarding_id}/detect",
    response_model=AutoDetectResult,
    summary="Admin: auto-detect onboarding progress",
)
async def admin_auto_detect_progress(
    onboarding_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Scan the member's existing data and auto-mark completed steps.

    Returns 404 if not found.
    Returns 409 if the onboarding is already completed.
    Restricted to account admins.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    return await auto_detect_progress(db, onboarding_id, account_id)


@router.post(
    "/corporate/admin/onboarding/{onboarding_id}/steps",
    response_model=OnboardingResponse,
    summary="Admin: manually mark an onboarding step complete",
)
async def admin_mark_step_complete(
    onboarding_id: uuid.UUID,
    data: MarkStepRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Mark a single onboarding step as complete.

    Returns 404 if not found.
    Returns 422 if step_name is invalid.
    Returns 409 if step already completed or onboarding is completed.
    Restricted to account admins.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    return await mark_step_complete(
        db, onboarding_id, account_id, data.step_name, user.id, notes=data.notes
    )


@router.post(
    "/corporate/admin/onboarding/{onboarding_id}/complete",
    response_model=OnboardingResponse,
    summary="Admin: force-complete an onboarding",
)
async def admin_complete_onboarding(
    onboarding_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Force-complete an onboarding tracker.

    Returns 404 if not found.  Returns 409 if already completed.
    Restricted to account admins.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    return await complete_onboarding(db, onboarding_id, account_id, user.id)


@router.get(
    "/corporate/admin/onboarding/{onboarding_id}/summary",
    response_model=OnboardingSummaryResponse,
    summary="Admin: get onboarding step summary",
)
async def admin_onboarding_summary(
    onboarding_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a detailed step completion summary for an onboarding.

    Returns 404 if not found.  Restricted to account admins.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    return await get_onboarding_summary(db, onboarding_id, account_id)


@router.get(
    "/corporate/admin/onboarding/{onboarding_id}/pending-steps",
    response_model=List[str],
    summary="Admin: list pending onboarding steps",
)
async def admin_list_pending_steps(
    onboarding_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the list of step names not yet completed for this onboarding.

    Returns 404 if not found.  Restricted to account admins.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    return await list_pending_steps(db, onboarding_id, account_id)


# ---------------------------------------------------------------------------
# Platform-admin endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/platform-admin/onboarding",
    response_model=OnboardingListResponse,
    summary="Platform admin: list all onboardings",
)
async def platform_list_all_onboardings(
    account_id: Optional[int] = Query(
        None, description="Filter by corporate account ID"
    ),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return all onboarding records across all accounts.

    Optionally filter by account_id.  Platform admin only.
    """
    return await list_all_platform(db, account_id_filter=account_id)


@router.get(
    "/corporate/platform-admin/onboarding/{onboarding_id}",
    response_model=OnboardingResponse,
    summary="Platform admin: get any onboarding record",
)
async def platform_get_onboarding(
    onboarding_id: uuid.UUID,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return any onboarding record by ID regardless of account.

    Returns 404 if not found.  Platform admin only.
    """
    from sqlalchemy import select
    from app.models.corporate_member_onboarding import CorporateMemberOnboarding
    from app.services.corporate_member_onboarding import _onboarding_to_response

    result = await db.execute(
        select(CorporateMemberOnboarding).where(
            CorporateMemberOnboarding.id == onboarding_id
        )
    )
    ob = result.scalar_one_or_none()
    if ob is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Onboarding record not found.",
        )
    return _onboarding_to_response(ob)


@router.get(
    "/corporate/platform-admin/accounts/{account_id}/onboarding",
    response_model=OnboardingListResponse,
    summary="Platform admin: list all onboardings for a specific account",
)
async def platform_list_onboardings_for_account(
    account_id: int,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return all onboarding records for a specific corporate account.

    Platform admin only.
    """
    return await list_all_platform(db, account_id_filter=account_id)
