"""Corporate Policy Violation endpoints.

Member endpoints (authenticated corporate account member):
  GET  /corporate/accounts/me/violations            — list own violations

Account-admin endpoints (require_account_admin):
  GET  /corporate/accounts/{account_id}/violations         — list with filters
  GET  /corporate/accounts/{account_id}/violations/summary — aggregate stats
  GET  /corporate/accounts/{account_id}/violations/{violation_id}  — get one
  POST /corporate/accounts/{account_id}/violations/{violation_id}/acknowledge
                                                           — acknowledge one
  POST /corporate/accounts/{account_id}/violations/bulk-acknowledge
                                                           — acknowledge many

Platform-admin endpoints (require_admin):
  GET  /admin/corporate/violations                         — all violations
  POST /admin/corporate/{account_id}/violations            — manually record
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.models.user import User
from app.schemas.corporate_policy_violation import (
    AcknowledgeRequest,
    BulkAcknowledgeRequest,
    ViolationCreate,
    ViolationListResponse,
    ViolationResponse,
    ViolationSummaryResponse,
    ViolationType,
)
from app.services.corporate_account_mgmt import (
    _require_account_admin,
    get_user_account,
)
from app.services.corporate_policy_violation import (
    acknowledge_violation,
    bulk_acknowledge_violations,
    get_violation,
    get_violation_summary,
    list_all_violations,
    list_violations,
    record_violation,
)
from fastapi import HTTPException

logger = logging.getLogger(__name__)

router = APIRouter(tags=["corporate-policy-violations"])


# ---------------------------------------------------------------------------
# Internal helpers
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


# ===========================================================================
# Member endpoints
# ===========================================================================


@router.get(
    "/corporate/accounts/me/violations",
    response_model=ViolationListResponse,
    summary="List your own policy violations",
)
async def member_list_own_violations(
    is_acknowledged: Optional[bool] = Query(
        None, description="Filter by acknowledgement status"
    ),
    limit: int = Query(50, ge=1, le=200, description="Max records to return"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the authenticated member's own policy violations.

    Optionally filter by acknowledgement status.  Sorted newest first.

    Returns HTTP 404 when the user is not a member of any corporate account.
    """
    account_id = await _resolve_member_account(db, user.id)
    violations = await list_violations(
        db,
        account_id=account_id,
        member_id=user.id,
        is_acknowledged=is_acknowledged,
        limit=limit,
        offset=offset,
    )
    return ViolationListResponse(violations=violations, total=len(violations))


# ===========================================================================
# Account-admin endpoints
# ===========================================================================


@router.get(
    "/corporate/accounts/{account_id}/violations/summary",
    response_model=ViolationSummaryResponse,
    summary="Admin: aggregate violation statistics for the account",
)
async def admin_violation_summary(
    account_id: int,
    period_days: int = Query(
        30, ge=1, le=365, description="Number of days back to include"
    ),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return aggregate violation statistics for the account.

    Includes total violations, unacknowledged count, breakdown by type,
    and the top 5 employees with the most violations in the period.

    Account admin only.
    """
    await _require_account_admin(db, account_id=account_id, user_id=user.id)
    return await get_violation_summary(db, account_id=account_id, period_days=period_days)


@router.get(
    "/corporate/accounts/{account_id}/violations",
    response_model=ViolationListResponse,
    summary="Admin: list policy violations on the account",
)
async def admin_list_violations(
    account_id: int,
    member_id: Optional[int] = Query(None, description="Filter by employee user ID"),
    violation_type: Optional[ViolationType] = Query(
        None, description="Filter by violation category"
    ),
    is_acknowledged: Optional[bool] = Query(
        None, description="Filter by acknowledgement status"
    ),
    from_dt: Optional[datetime] = Query(
        None, description="Inclusive lower bound on created_at (ISO 8601)"
    ),
    to_dt: Optional[datetime] = Query(
        None, description="Exclusive upper bound on created_at (ISO 8601)"
    ),
    limit: int = Query(100, ge=1, le=500, description="Max records to return"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List policy violations on the account with optional filters.

    Sorted newest first.  Account admin only.
    """
    await _require_account_admin(db, account_id=account_id, user_id=user.id)
    violations = await list_violations(
        db,
        account_id=account_id,
        member_id=member_id,
        violation_type=violation_type.value if violation_type else None,
        is_acknowledged=is_acknowledged,
        from_dt=from_dt,
        to_dt=to_dt,
        limit=limit,
        offset=offset,
    )
    return ViolationListResponse(violations=violations, total=len(violations))


@router.get(
    "/corporate/accounts/{account_id}/violations/{violation_id}",
    response_model=ViolationResponse,
    summary="Admin: get a single policy violation",
)
async def admin_get_violation(
    account_id: int,
    violation_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a single violation record by ID.

    Returns HTTP 404 when the violation does not exist or belongs to a
    different account.

    Account admin only.
    """
    await _require_account_admin(db, account_id=account_id, user_id=user.id)
    return await get_violation(db, violation_id=violation_id, account_id=account_id)


@router.post(
    "/corporate/accounts/{account_id}/violations/{violation_id}/acknowledge",
    response_model=ViolationResponse,
    summary="Admin: acknowledge a policy violation",
)
async def admin_acknowledge_violation(
    account_id: int,
    violation_id: int,
    payload: AcknowledgeRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Mark a policy violation as reviewed and acknowledged.

    Returns HTTP 404 when the violation does not exist or is not on this account.
    Returns HTTP 409 when the violation is already acknowledged.

    Account admin only.
    """
    await _require_account_admin(db, account_id=account_id, user_id=user.id)
    return await acknowledge_violation(
        db,
        violation_id=violation_id,
        account_id=account_id,
        acknowledged_by_id=user.id,
        note=payload.acknowledgement_note,
    )


@router.post(
    "/corporate/accounts/{account_id}/violations/bulk-acknowledge",
    response_model=ViolationListResponse,
    summary="Admin: bulk-acknowledge multiple policy violations",
)
async def admin_bulk_acknowledge_violations(
    account_id: int,
    payload: BulkAcknowledgeRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Acknowledge multiple violations in a single request.

    Violations already acknowledged or not found on this account are silently
    skipped.  Returns only the violations that were actually changed.

    Account admin only.
    """
    await _require_account_admin(db, account_id=account_id, user_id=user.id)
    acknowledged = await bulk_acknowledge_violations(
        db,
        account_id=account_id,
        violation_ids=payload.violation_ids,
        acknowledged_by_id=user.id,
        note=payload.acknowledgement_note,
    )
    return ViolationListResponse(violations=acknowledged, total=len(acknowledged))


# ===========================================================================
# Platform-admin endpoints
# ===========================================================================


@router.get(
    "/admin/corporate/violations",
    response_model=ViolationListResponse,
    summary="Platform admin: list violations across all accounts",
)
async def platform_admin_list_violations(
    account_id: Optional[int] = Query(None, description="Filter to a single account"),
    violation_type: Optional[ViolationType] = Query(
        None, description="Filter by violation category"
    ),
    is_acknowledged: Optional[bool] = Query(
        None, description="Filter by acknowledgement status"
    ),
    limit: int = Query(200, ge=1, le=500, description="Max records to return"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """List policy violations across all corporate accounts.

    Optionally filter by account, type, or acknowledgement status.

    Platform admin only.
    """
    violations = await list_all_violations(
        db,
        account_id=account_id,
        violation_type=violation_type.value if violation_type else None,
        is_acknowledged=is_acknowledged,
        limit=limit,
        offset=offset,
    )
    return ViolationListResponse(violations=violations, total=len(violations))


@router.post(
    "/admin/corporate/{account_id}/violations",
    response_model=ViolationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Platform admin: manually record a policy violation",
)
async def platform_admin_record_violation(
    account_id: int,
    payload: ViolationCreate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Manually create a policy violation record on any account.

    Primarily for testing, backfills, or cases where the booking engine
    needs to surface a violation through the admin tooling.

    Platform admin only.
    """
    return await record_violation(
        db,
        account_id=account_id,
        member_id=payload.member_id,
        violation_type=payload.violation_type.value,
        violation_details=payload.violation_details,
        ride_id=payload.ride_id,
        policy_snapshot=payload.policy_snapshot,
    )
