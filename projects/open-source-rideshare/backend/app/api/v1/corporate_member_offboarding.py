"""Corporate Member Offboarding endpoints.

Structured workflow for offboarding employees from a corporate account.
Tracks ten cleanup steps with audit timestamps and affected record counts.

Admin endpoints (account admins only):
  POST   /corporate/admin/offboarding                             — create (201)
  GET    /corporate/admin/offboarding                             — list all
  GET    /corporate/admin/offboarding/overview                    — overview with step counts
  GET    /corporate/admin/offboarding/{offboarding_id}            — get detail
  PUT    /corporate/admin/offboarding/{offboarding_id}            — update reason/last_day/notes
  POST   /corporate/admin/offboarding/{offboarding_id}/execute-step   — execute a step
  POST   /corporate/admin/offboarding/{offboarding_id}/complete       — mark complete
  POST   /corporate/admin/offboarding/{offboarding_id}/cancel         — cancel
  GET    /corporate/admin/offboarding/{offboarding_id}/summary        — step summary
  GET    /corporate/admin/offboarding/{offboarding_id}/pending-steps  — pending steps list
  GET    /corporate/admin/members/{member_id}/offboarding             — offboarding for member

Platform-admin endpoints:
  GET  /corporate/platform-admin/offboarding                                — all offboardings
  GET  /corporate/platform-admin/offboarding/{offboarding_id}               — get any
  GET  /corporate/platform-admin/accounts/{account_id}/offboarding          — all for account
"""

from __future__ import annotations

import logging
import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.models.corporate_member_offboarding import (
    CorporateMemberOffboarding,
    OffboardingStatus,
)
from app.models.user import User
from app.schemas.corporate_member_offboarding import (
    CancelOffboardingRequest,
    ExecuteStepRequest,
    OffboardingCreate,
    OffboardingListResponse,
    OffboardingOverviewResponse,
    OffboardingResponse,
    OffboardingSummaryResponse,
    OffboardingUpdate,
)
from app.services.corporate_account_mgmt import get_user_account
from app.services.corporate_member_offboarding import (
    cancel_offboarding,
    complete_offboarding,
    create_offboarding,
    execute_step,
    get_offboarding,
    get_offboarding_summary,
    list_account_offboardings_with_status,
    list_all_platform,
    list_offboardings,
    list_pending_steps,
    update_offboarding,
)
from app.services.corporate_trip_purpose import _require_account_admin

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Corporate Member Offboarding"])


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
# Admin endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/admin/offboarding",
    response_model=OffboardingResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Admin: initiate member offboarding",
)
async def admin_create_offboarding(
    data: OffboardingCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Initiate an offboarding workflow for a corporate account member.

    Returns 404 if the member is not in this account.
    Returns 409 if an active offboarding already exists for this member.
    Restricted to account admins.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    return await create_offboarding(
        db,
        account_id=account_id,
        member_id=data.member_id,
        initiated_by_id=user.id,
        reason=data.reason,
        last_day=data.last_day,
        notes=data.notes,
    )


@router.get(
    "/corporate/admin/offboarding/overview",
    response_model=OffboardingOverviewResponse,
    summary="Admin: list all offboardings with step counts",
)
async def admin_offboarding_overview(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all offboarding records for the account with step completion counts.

    Restricted to account admins.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    return await list_account_offboardings_with_status(db, account_id)


@router.get(
    "/corporate/admin/offboarding",
    response_model=OffboardingListResponse,
    summary="Admin: list offboardings",
)
async def admin_list_offboardings(
    status: Optional[OffboardingStatus] = Query(
        None, description="Filter by status"
    ),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all offboarding records for the admin's account.

    Optionally filter by status.  Restricted to account admins.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    return await list_offboardings(db, account_id, status_filter=status)


@router.get(
    "/corporate/admin/members/{member_id}/offboarding",
    response_model=OffboardingResponse,
    summary="Admin: get current or most recent offboarding for a member",
)
async def admin_get_member_offboarding(
    member_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the current active or most recent offboarding for a specific member.

    Returns 404 if no offboarding exists for this member.
    Restricted to account admins.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)

    # Prefer active offboarding, fall back to most recent
    result = await db.execute(
        select(CorporateMemberOffboarding)
        .where(
            CorporateMemberOffboarding.account_id == account_id,
            CorporateMemberOffboarding.member_id == member_id,
        )
        .order_by(
            CorporateMemberOffboarding.is_active.desc(),
            CorporateMemberOffboarding.created_at.desc(),
        )
        .limit(1)
    )
    ob = result.scalar_one_or_none()
    if ob is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No offboarding found for this member.",
        )
    from app.services.corporate_member_offboarding import _offboarding_to_response

    return _offboarding_to_response(ob)


@router.get(
    "/corporate/admin/offboarding/{offboarding_id}",
    response_model=OffboardingResponse,
    summary="Admin: get offboarding detail",
)
async def admin_get_offboarding(
    offboarding_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a single offboarding record by ID.

    Returns 404 if not found.  Restricted to account admins.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    return await get_offboarding(db, offboarding_id, account_id)


@router.put(
    "/corporate/admin/offboarding/{offboarding_id}",
    response_model=OffboardingResponse,
    summary="Admin: update offboarding fields",
)
async def admin_update_offboarding(
    offboarding_id: uuid.UUID,
    data: OffboardingUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update reason, last_day, and/or notes for an offboarding record.

    Returns 404 if not found.  Restricted to account admins.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    return await update_offboarding(db, offboarding_id, account_id, data)


@router.post(
    "/corporate/admin/offboarding/{offboarding_id}/execute-step",
    response_model=OffboardingResponse,
    summary="Admin: execute an offboarding cleanup step",
)
async def admin_execute_step(
    offboarding_id: uuid.UUID,
    data: ExecuteStepRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Execute a single offboarding cleanup step and record the results.

    Returns 404 if not found.
    Returns 422 if step_name is invalid.
    Returns 409 if step already completed or offboarding is terminal.
    Restricted to account admins.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    return await execute_step(
        db, offboarding_id, account_id, data.step_name, executed_by_id=user.id
    )


@router.post(
    "/corporate/admin/offboarding/{offboarding_id}/complete",
    response_model=OffboardingResponse,
    summary="Admin: mark offboarding as complete",
)
async def admin_complete_offboarding(
    offboarding_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Mark an offboarding workflow as completed.

    Returns 404 if not found.  Returns 409 if already completed/cancelled.
    Restricted to account admins.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    return await complete_offboarding(db, offboarding_id, account_id, user.id)


@router.post(
    "/corporate/admin/offboarding/{offboarding_id}/cancel",
    response_model=OffboardingResponse,
    summary="Admin: cancel an offboarding",
)
async def admin_cancel_offboarding(
    offboarding_id: uuid.UUID,
    data: CancelOffboardingRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Cancel an offboarding workflow.

    Returns 404 if not found.  Returns 409 if already completed/cancelled.
    Restricted to account admins.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    return await cancel_offboarding(
        db, offboarding_id, account_id, user.id, notes=data.notes
    )


@router.get(
    "/corporate/admin/offboarding/{offboarding_id}/summary",
    response_model=OffboardingSummaryResponse,
    summary="Admin: get offboarding step summary",
)
async def admin_offboarding_summary(
    offboarding_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a detailed step completion summary for an offboarding.

    Returns 404 if not found.  Restricted to account admins.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    return await get_offboarding_summary(db, offboarding_id, account_id)


@router.get(
    "/corporate/admin/offboarding/{offboarding_id}/pending-steps",
    response_model=List[str],
    summary="Admin: list pending offboarding steps",
)
async def admin_list_pending_steps(
    offboarding_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the list of step names not yet completed for this offboarding.

    Returns 404 if not found.  Restricted to account admins.
    """
    account_id = await _resolve_account_id(db, user.id)
    await _require_account_admin(db, account_id, user.id)
    return await list_pending_steps(db, offboarding_id, account_id)


# ---------------------------------------------------------------------------
# Platform-admin endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/platform-admin/offboarding",
    response_model=OffboardingListResponse,
    summary="Platform admin: list all offboardings",
)
async def platform_list_all_offboardings(
    account_id: Optional[int] = Query(
        None, description="Filter by corporate account ID"
    ),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return all offboarding records across all accounts.

    Optionally filter by account_id.  Platform admin only.
    """
    return await list_all_platform(db, account_id_filter=account_id)


@router.get(
    "/corporate/platform-admin/offboarding/{offboarding_id}",
    response_model=OffboardingResponse,
    summary="Platform admin: get any offboarding record",
)
async def platform_get_offboarding(
    offboarding_id: uuid.UUID,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return any offboarding record by ID regardless of account.

    Returns 404 if not found.  Platform admin only.
    """
    result = await db.execute(
        select(CorporateMemberOffboarding).where(
            CorporateMemberOffboarding.id == offboarding_id
        )
    )
    ob = result.scalar_one_or_none()
    if ob is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Offboarding record not found.",
        )
    from app.services.corporate_member_offboarding import _offboarding_to_response

    return _offboarding_to_response(ob)


@router.get(
    "/corporate/platform-admin/accounts/{account_id}/offboarding",
    response_model=OffboardingListResponse,
    summary="Platform admin: list all offboardings for a specific account",
)
async def platform_list_offboardings_for_account(
    account_id: int,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return all offboarding records for a specific corporate account.

    Platform admin only.
    """
    return await list_all_platform(db, account_id_filter=account_id)
