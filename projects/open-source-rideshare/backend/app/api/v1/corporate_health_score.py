"""Corporate Account Health Score endpoints.

Member endpoints (authenticated account member):
  GET  /corporate/accounts/me/health-score          — get latest health score
  GET  /corporate/accounts/me/health-score/history  — score history

Admin endpoints (account admin):
  POST /corporate/accounts/me/health-score/refresh  — recompute own account score

Platform-admin endpoints (require_admin):
  GET  /admin/corporate/accounts/{id}/health-score           — get latest score
  POST /admin/corporate/accounts/{id}/health-score/recompute — force recompute
  GET  /admin/corporate/health-scores                        — list all accounts
  GET  /admin/corporate/health-scores/at-risk                — at-risk summary
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.models.corporate_health_score import HealthRiskLevel
from app.models.user import User
from app.schemas.corporate_health_score import (
    AtRiskSummaryResponse,
    HealthScoreListResponse,
    HealthScoreResponse,
)
from app.services.corporate_account_mgmt import (
    get_user_account,
    _require_account_admin,
)
from app.services.corporate_health_score import (
    compute_health_score,
    get_at_risk_summary,
    get_health_score_history,
    get_latest_health_score,
    list_accounts_by_health,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["corporate-health-score"])


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------


async def _resolve_member_account(db: AsyncSession, user_id: int) -> int:
    """Resolve and return the corporate account ID for an authenticated member.

    Raises HTTP 404 when the user is not a member of any corporate account.
    """
    account = await get_user_account(db, user_id)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="You are not a member of any corporate account.",
        )
    return account.id


# ---------------------------------------------------------------------------
# Member: get latest health score
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/health-score",
    response_model=HealthScoreResponse,
    summary="Get the latest health score for your corporate account",
)
async def get_my_health_score(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the most recent health score snapshot for the requesting user's
    corporate account.

    Returns HTTP 404 when no snapshot has been computed yet or the user is not
    a member of any corporate account.
    """
    account_id = await _resolve_member_account(db, user.id)
    score = await get_latest_health_score(db, account_id)
    if score is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No health score has been computed for this account yet.",
        )
    return score


# ---------------------------------------------------------------------------
# Member: get score history
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/health-score/history",
    response_model=HealthScoreListResponse,
    summary="Get health score history for your corporate account",
)
async def get_my_health_score_history(
    limit: int = Query(30, ge=1, le=100, description="Maximum snapshots to return"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return historical health score snapshots for the requesting user's
    corporate account, most recent first.

    Returns an empty list when no snapshots exist yet.
    """
    account_id = await _resolve_member_account(db, user.id)
    scores = await get_health_score_history(db, account_id, limit=limit)
    return HealthScoreListResponse(scores=list(scores), total=len(scores))


# ---------------------------------------------------------------------------
# Admin: refresh own account health score
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/accounts/me/health-score/refresh",
    response_model=HealthScoreResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Recompute health score for your corporate account",
)
async def refresh_my_health_score(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Trigger a health score recomputation for the requesting user's corporate
    account.  The user must be an account admin.

    Creates a new snapshot; previous snapshots are preserved for trend
    analysis.  Returns HTTP 403 when the requester is not an account admin.
    """
    account_id = await _resolve_member_account(db, user.id)
    await _require_account_admin(db, account_id=account_id, user_id=user.id)
    return await compute_health_score(db, account_id=account_id, computed_by_id=user.id)


# ---------------------------------------------------------------------------
# Platform-admin: get latest health score for a specific account
# ---------------------------------------------------------------------------


@router.get(
    "/admin/corporate/accounts/{account_id}/health-score",
    response_model=HealthScoreResponse,
    summary="Admin: get latest health score for a corporate account",
)
async def admin_get_health_score(
    account_id: int,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return the most recent health score snapshot for a specific corporate
    account.

    Returns HTTP 404 when no snapshot has been computed yet.

    Platform admin only.
    """
    score = await get_latest_health_score(db, account_id)
    if score is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No health score has been computed for this account yet.",
        )
    return score


# ---------------------------------------------------------------------------
# Platform-admin: force recompute health score for a specific account
# ---------------------------------------------------------------------------


@router.post(
    "/admin/corporate/accounts/{account_id}/health-score/recompute",
    response_model=HealthScoreResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Admin: force recompute health score for a corporate account",
)
async def admin_recompute_health_score(
    account_id: int,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Force a health score recomputation for a specific corporate account.

    Creates a new snapshot; previous snapshots are preserved for trend
    analysis.

    Platform admin only.
    """
    return await compute_health_score(
        db, account_id=account_id, computed_by_id=admin.id
    )


# ---------------------------------------------------------------------------
# Platform-admin: list all accounts by health score
# ---------------------------------------------------------------------------


@router.get(
    "/admin/corporate/health-scores",
    response_model=HealthScoreListResponse,
    summary="Admin: list corporate accounts by health score",
)
async def admin_list_health_scores(
    risk_level: HealthRiskLevel | None = Query(None, description="Filter by risk level"),
    below_score: int | None = Query(None, ge=0, le=100, description="Filter accounts with score below this value"),
    skip: int = Query(0, ge=0, description="Pagination offset"),
    limit: int = Query(50, ge=1, le=200, description="Maximum records to return"),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return the latest health score per account, sorted by score ascending
    (worst-health accounts first).

    Optionally filter by risk_level or a maximum score threshold.  Returns
    only accounts that have at least one computed snapshot.

    Platform admin only.
    """
    scores = await list_accounts_by_health(
        db,
        risk_level=risk_level,
        below_score=below_score,
        skip=skip,
        limit=limit,
    )
    return HealthScoreListResponse(scores=scores, total=len(scores))


# ---------------------------------------------------------------------------
# Platform-admin: at-risk summary
# ---------------------------------------------------------------------------


@router.get(
    "/admin/corporate/health-scores/at-risk",
    response_model=AtRiskSummaryResponse,
    summary="Admin: platform-level health distribution summary",
)
async def admin_at_risk_summary(
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return a platform-level summary of corporate account health distribution.

    Reports how many accounts fall into each risk category (excellent / good /
    fair / poor / critical) based on the most recent snapshot per account.

    Platform admin only.
    """
    return await get_at_risk_summary(db)
