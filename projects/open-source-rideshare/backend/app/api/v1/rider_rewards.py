"""Rider loyalty rewards API endpoints.

Rider-facing:
  GET  /riders/me/rewards                  — account balance + lifetime stats
  GET  /riders/me/rewards/history          — transaction history (paginated)
  POST /riders/me/rewards/redeem           — redeem points for a discount

Admin-facing:
  GET  /admin/rewards/stats                — platform-wide aggregate stats
  POST /admin/rewards/adjust               — manually credit or debit a rider's balance
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_admin
from app.db.database import get_db
from app.models.rider_reward import POINT_VALUE_CENTS, POINTS_PER_DOLLAR
from app.models.user import User
from app.schemas.rider_reward import (
    AdminAdjustPointsRequest,
    RedeemPointsRequest,
    RedeemPointsResponse,
    RewardAccountResponse,
    RewardPlatformStats,
    RewardTransactionPage,
    RewardTransactionResponse,
)
from app.services.rider_rewards import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    admin_adjust_points,
    get_or_create_account,
    get_platform_stats,
    get_transaction_history,
    points_to_usd,
    redeem_points,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["rider-rewards"])


# ---------------------------------------------------------------------------
# Rider endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/riders/me/rewards",
    response_model=RewardAccountResponse,
    summary="Get my reward account balance and lifetime stats",
)
async def get_my_rewards(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the authenticated rider's loyalty reward account.

    Creates the account lazily if it does not yet exist (returns zero balances).
    """
    account = await get_or_create_account(user.id, db)
    await db.commit()
    await db.refresh(account)

    return RewardAccountResponse(
        points_balance=account.points_balance,
        lifetime_earned=account.lifetime_earned,
        lifetime_redeemed=account.lifetime_redeemed,
        balance_value_usd=points_to_usd(account.points_balance),
        created_at=account.created_at,
        updated_at=account.updated_at,
    )


@router.get(
    "/riders/me/rewards/history",
    response_model=RewardTransactionPage,
    summary="Get my reward transaction history",
)
async def get_my_reward_history(
    offset: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a paginated list of the rider's points earn/redeem events."""
    transactions, total = await get_transaction_history(user.id, db, offset, limit)
    return RewardTransactionPage(
        items=[
            RewardTransactionResponse(
                id=t.id,
                transaction_type=t.transaction_type,
                points_delta=t.points_delta,
                balance_after=t.balance_after,
                description=t.description,
                ride_id=t.ride_id,
                created_at=t.created_at,
            )
            for t in transactions
        ],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.post(
    "/riders/me/rewards/redeem",
    response_model=RedeemPointsResponse,
    summary="Redeem points for a ride discount",
)
async def redeem_my_points(
    req: RedeemPointsRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Burn `points` from the rider's balance and return the dollar discount.

    Rules:
    - Minimum redemption: MIN_REDEMPTION_POINTS points
    - Balance must be >= points requested
    - Each point is worth POINT_VALUE_CENTS cents
    """
    try:
        txn = await redeem_points(
            rider_id=user.id,
            points=req.points,
            db=db,
            ride_id=req.ride_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    await db.commit()
    await db.refresh(txn)

    return RedeemPointsResponse(
        points_redeemed=req.points,
        discount_value_usd=points_to_usd(req.points),
        new_balance=txn.balance_after,
        transaction_id=txn.id,
    )


# ---------------------------------------------------------------------------
# Admin endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/admin/rewards/stats",
    response_model=RewardPlatformStats,
    summary="Platform-wide reward programme statistics (admin only)",
    dependencies=[Depends(require_admin)],
)
async def admin_rewards_stats(
    db: AsyncSession = Depends(get_db),
):
    """Return aggregate reward stats across all rider accounts."""
    stats = await get_platform_stats(db)
    return RewardPlatformStats(**stats)


@router.post(
    "/admin/rewards/adjust",
    response_model=RewardTransactionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Manually credit or debit a rider's reward balance (admin only)",
    dependencies=[Depends(require_admin)],
)
async def admin_adjust_rider_points(
    req: AdminAdjustPointsRequest,
    db: AsyncSession = Depends(get_db),
):
    """Credit (positive) or debit (negative) a rider's points balance.

    Debit is capped at the rider's current balance — balance cannot go below 0.
    """
    try:
        txn = await admin_adjust_points(
            rider_id=req.rider_id,
            points_delta=req.points_delta,
            db=db,
            description=req.description,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    await db.commit()
    await db.refresh(txn)

    return RewardTransactionResponse(
        id=txn.id,
        transaction_type=txn.transaction_type,
        points_delta=txn.points_delta,
        balance_after=txn.balance_after,
        description=txn.description,
        ride_id=txn.ride_id,
        created_at=txn.created_at,
    )
