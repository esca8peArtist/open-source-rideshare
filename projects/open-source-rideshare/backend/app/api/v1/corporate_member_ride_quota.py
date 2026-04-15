"""Corporate Member Ride Quota endpoints.

Member endpoints (authenticated corporate account member):
  GET  /corporate/accounts/me/ride-quotas/check?period=daily  — own quota + usage
  GET  /corporate/accounts/me/ride-quotas                     — list own active quotas

Account-admin endpoints (require_account_admin):
  POST   /corporate/accounts/{account_id}/ride-quotas              — set quota
  GET    /corporate/accounts/{account_id}/ride-quotas              — list quotas
  GET    /corporate/accounts/{account_id}/ride-quotas/summary      — list with usage
  GET    /corporate/accounts/{account_id}/ride-quotas/{quota_id}   — get one
  PUT    /corporate/accounts/{account_id}/ride-quotas/{quota_id}   — update
  DELETE /corporate/accounts/{account_id}/ride-quotas/{quota_id}   — hard delete

Platform-admin endpoints (require_admin):
  GET  /admin/corporate/accounts/{account_id}/ride-quotas          — list quotas
  POST /admin/corporate/accounts/{account_id}/ride-quotas          — set quota
  GET  /admin/corporate/ride-quotas/exceeded                       — cross-account exceeded
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.models.user import User
from app.schemas.corporate_member_ride_quota import (
    QuotaCheckResponse,
    QuotaCreate,
    QuotaListResponse,
    QuotaPeriod,
    QuotaResponse,
    QuotaUpdate,
    QuotaWithUsageResponse,
)
from app.services.corporate_account_mgmt import (
    _require_account_admin,
    get_user_account,
)
from app.services.corporate_member_ride_quota import (
    deactivate_quota,
    delete_quota,
    get_account_quota_summary,
    get_quota,
    get_quota_usage,
    list_member_quotas,
    set_quota,
    update_quota,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["corporate-member-ride-quotas"])


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
    "/corporate/accounts/me/ride-quotas/check",
    response_model=QuotaCheckResponse,
    summary="Check your own ride quota and current usage for a period",
)
async def member_check_quota(
    period: QuotaPeriod = Query(..., description="Time period to check: daily, weekly, or monthly"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the authenticated member's quota and current usage for a period.

    When no active quota is set for this period, ``quota_active`` will be
    False and numeric fields will be 0 (meaning rides are unrestricted).

    Returns HTTP 404 when the user is not a member of any corporate account.
    """
    account_id = await _resolve_member_account(db, user.id)
    return await get_quota_usage(db, account_id=account_id, member_id=user.id, period=period.value)


@router.get(
    "/corporate/accounts/me/ride-quotas",
    response_model=list[QuotaWithUsageResponse],
    summary="List your own active ride quotas with current usage",
)
async def member_list_quotas(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all active quotas for the authenticated member, enriched with
    current usage statistics for each period.

    Returns HTTP 404 when the user is not a member of any corporate account.
    """
    account_id = await _resolve_member_account(db, user.id)
    # Fetch all active quotas for this member and enrich with usage
    quotas = await list_member_quotas(db, account_id=account_id, member_id=user.id, active_only=True)
    enriched = []
    from app.services.corporate_member_ride_quota import (
        _count_rides_in_period,
        _period_start,
    )
    for q in quotas:
        ps = _period_start(q.period)
        current_rides = await _count_rides_in_period(db, user.id, account_id, ps)
        remaining = max(0, q.max_rides - current_rides)
        enriched.append(
            QuotaWithUsageResponse(
                id=q.id,
                account_id=q.account_id,
                member_id=q.member_id,
                period=q.period,
                max_rides=q.max_rides,
                is_active=q.is_active,
                created_by_id=q.created_by_id,
                created_at=q.created_at,
                updated_at=q.updated_at,
                current_period_rides=current_rides,
                remaining_rides=remaining,
                quota_exceeded=current_rides >= q.max_rides,
            )
        )
    return enriched


# ===========================================================================
# Account-admin endpoints
# ===========================================================================


@router.post(
    "/corporate/accounts/{account_id}/ride-quotas",
    response_model=QuotaResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Admin: set a ride quota for a corporate member",
)
async def admin_set_quota(
    account_id: int,
    payload: QuotaCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Set a per-member ride count limit for a corporate account member.

    Returns HTTP 409 when an active quota for the same (member, period)
    already exists on the account.

    Account admin only.
    """
    await _require_account_admin(db, account_id=account_id, user_id=user.id)
    return await set_quota(
        db,
        account_id=account_id,
        member_id=payload.member_id,
        period=payload.period.value,
        max_rides=payload.max_rides,
        created_by_id=user.id,
    )


@router.get(
    "/corporate/accounts/{account_id}/ride-quotas/summary",
    response_model=list[QuotaWithUsageResponse],
    summary="Admin: list all active quotas with current usage",
)
async def admin_quota_summary(
    account_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all active quotas on the account, each enriched with current
    period usage data.

    Sorted by member_id then period.

    Account admin only.
    """
    await _require_account_admin(db, account_id=account_id, user_id=user.id)
    return await get_account_quota_summary(db, account_id=account_id)


@router.get(
    "/corporate/accounts/{account_id}/ride-quotas",
    response_model=QuotaListResponse,
    summary="Admin: list ride quotas on a corporate account",
)
async def admin_list_quotas(
    account_id: int,
    member_id: Optional[int] = Query(None, description="Filter by member user ID"),
    period: Optional[QuotaPeriod] = Query(None, description="Filter by time period"),
    active_only: bool = Query(True, description="Return only active quotas"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List ride quotas on a corporate account.

    Optionally filtered by member_id, period, or active status.

    Account admin only.
    """
    await _require_account_admin(db, account_id=account_id, user_id=user.id)
    quotas = await list_member_quotas(
        db,
        account_id=account_id,
        member_id=member_id,
        period=period.value if period else None,
        active_only=active_only,
    )
    return QuotaListResponse(quotas=quotas, total=len(quotas))


@router.get(
    "/corporate/accounts/{account_id}/ride-quotas/{quota_id}",
    response_model=QuotaResponse,
    summary="Admin: get a single ride quota",
)
async def admin_get_quota(
    account_id: int,
    quota_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a single quota record by ID.

    Returns HTTP 404 when the quota does not exist or belongs to a different
    account.

    Account admin only.
    """
    await _require_account_admin(db, account_id=account_id, user_id=user.id)
    return await get_quota(db, quota_id=quota_id, account_id=account_id)


@router.put(
    "/corporate/accounts/{account_id}/ride-quotas/{quota_id}",
    response_model=QuotaResponse,
    summary="Admin: update a ride quota",
)
async def admin_update_quota(
    account_id: int,
    quota_id: int,
    payload: QuotaUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Partially update a quota's max_rides or is_active flag.

    Only supplied fields are applied.  Returns HTTP 404 when the quota does
    not exist or belongs to a different account.

    Account admin only.
    """
    await _require_account_admin(db, account_id=account_id, user_id=user.id)
    return await update_quota(db, quota_id=quota_id, account_id=account_id, payload=payload)


@router.delete(
    "/corporate/accounts/{account_id}/ride-quotas/{quota_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Admin: hard-delete a ride quota",
)
async def admin_delete_quota(
    account_id: int,
    quota_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Permanently remove a quota row.

    Returns HTTP 404 when the quota does not exist or belongs to a different
    account.  To keep the audit trail consider using the deactivate endpoint
    (PUT with is_active=false) instead.

    Account admin only.
    """
    await _require_account_admin(db, account_id=account_id, user_id=user.id)
    await delete_quota(db, quota_id=quota_id, account_id=account_id)


# ===========================================================================
# Platform-admin endpoints
# ===========================================================================


@router.get(
    "/admin/corporate/accounts/{account_id}/ride-quotas",
    response_model=QuotaListResponse,
    summary="Platform admin: list all ride quotas for an account",
)
async def platform_admin_list_quotas(
    account_id: int,
    member_id: Optional[int] = Query(None, description="Filter by member user ID"),
    period: Optional[QuotaPeriod] = Query(None, description="Filter by time period"),
    active_only: bool = Query(False, description="Filter by active status"),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """List all quota records for a corporate account.

    Platform admin only — returns all quotas including inactive ones by
    default (use active_only=true to restrict).
    """
    quotas = await list_member_quotas(
        db,
        account_id=account_id,
        member_id=member_id,
        period=period.value if period else None,
        active_only=active_only,
    )
    return QuotaListResponse(quotas=quotas, total=len(quotas))


@router.post(
    "/admin/corporate/accounts/{account_id}/ride-quotas",
    response_model=QuotaResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Platform admin: set a ride quota on any account",
)
async def platform_admin_set_quota(
    account_id: int,
    payload: QuotaCreate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Set a per-member ride count limit on any corporate account.

    Returns HTTP 409 when an active quota for the same (member, period)
    already exists on the account.

    Platform admin only.
    """
    return await set_quota(
        db,
        account_id=account_id,
        member_id=payload.member_id,
        period=payload.period.value,
        max_rides=payload.max_rides,
        created_by_id=admin.id,
    )


@router.get(
    "/admin/corporate/ride-quotas/exceeded",
    response_model=list[QuotaWithUsageResponse],
    summary="Platform admin: list all exceeded quotas across all accounts",
)
async def platform_admin_exceeded_quotas(
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return all active quotas across every corporate account where the
    member has equalled or exceeded their ride limit this period.

    Results are sorted by account_id, then member_id, then period.

    Platform admin only.
    """
    from sqlalchemy import select as sa_select

    from app.models.corporate_member_ride_quota import CorporateMemberRideQuota
    from app.services.corporate_member_ride_quota import (
        _count_rides_in_period,
        _period_start,
    )

    result = await db.execute(
        sa_select(CorporateMemberRideQuota)
        .where(CorporateMemberRideQuota.is_active.is_(True))
        .order_by(
            CorporateMemberRideQuota.account_id,
            CorporateMemberRideQuota.member_id,
            CorporateMemberRideQuota.period,
        )
    )
    all_quotas = result.scalars().all()

    exceeded: list[QuotaWithUsageResponse] = []
    for row in all_quotas:
        ps = _period_start(row.period)
        current_rides = await _count_rides_in_period(db, row.member_id, row.account_id, ps)
        if current_rides >= row.max_rides:
            remaining = max(0, row.max_rides - current_rides)
            exceeded.append(
                QuotaWithUsageResponse(
                    id=row.id,
                    account_id=row.account_id,
                    member_id=row.member_id,
                    period=row.period,
                    max_rides=row.max_rides,
                    is_active=row.is_active,
                    created_by_id=row.created_by_id,
                    created_at=row.created_at,
                    updated_at=row.updated_at,
                    current_period_rides=current_rides,
                    remaining_rides=remaining,
                    quota_exceeded=True,
                )
            )
    return exceeded
