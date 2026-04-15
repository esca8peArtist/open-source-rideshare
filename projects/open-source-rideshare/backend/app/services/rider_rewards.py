"""Service layer for the rider loyalty rewards programme.

All public functions accept an AsyncSession and are awaitable.
No commits are issued here — callers are responsible for committing.

Earn flow
---------
1. Ride completes → rides service calls ``award_points_for_ride``.
2. points_delta = floor(fare_usd × POINTS_PER_DOLLAR)
3. Account balance + lifetime_earned are incremented; a transaction row is written.

Redeem flow
-----------
1. Rider calls POST /riders/me/rewards/redeem with points count.
2. Service validates: balance >= points, points >= MIN_REDEMPTION_POINTS.
3. Balance is decremented; lifetime_redeemed incremented; transaction written.
4. Returns dollar value of the redeemed points (caller applies to next fare).

Admin adjust flow
-----------------
Admin credits or debits a rider's balance directly (for goodwill credits,
corrections, etc.).  Negative deltas are capped so balance cannot go below 0.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.rider_reward import (
    MAX_REDEMPTION_PCT,
    MIN_REDEMPTION_POINTS,
    POINT_VALUE_CENTS,
    POINTS_PER_DOLLAR,
    RewardTransactionType,
    RiderRewardAccount,
    RiderRewardTransaction,
)

# ---------------------------------------------------------------------------
# Pagination defaults
# ---------------------------------------------------------------------------

DEFAULT_PAGE_SIZE: int = 20
MAX_PAGE_SIZE: int = 100


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def points_to_usd(points: int) -> float:
    """Convert a point count to its equivalent dollar value."""
    return round(points * POINT_VALUE_CENTS / 100, 2)


def usd_to_points(usd: float) -> int:
    """Convert a dollar amount to the number of points it would earn."""
    return math.floor(usd * POINTS_PER_DOLLAR)


# ---------------------------------------------------------------------------
# Account management
# ---------------------------------------------------------------------------


async def get_or_create_account(rider_id: int, db: AsyncSession) -> RiderRewardAccount:
    """Return the rider's reward account, creating one if it does not exist."""
    result = await db.execute(
        select(RiderRewardAccount).where(RiderRewardAccount.rider_id == rider_id)
    )
    account = result.scalar_one_or_none()
    if account is None:
        account = RiderRewardAccount(
            rider_id=rider_id,
            points_balance=0,
            lifetime_earned=0,
            lifetime_redeemed=0,
        )
        db.add(account)
        await db.flush()   # populate account.id before we write transactions
    return account


# ---------------------------------------------------------------------------
# Earning points
# ---------------------------------------------------------------------------


async def award_points_for_ride(
    rider_id: int,
    fare_usd: float,
    db: AsyncSession,
    ride_id: int | None = None,
) -> RiderRewardTransaction | None:
    """Award points to a rider after a completed ride.

    Points = floor(fare_usd × POINTS_PER_DOLLAR).
    Returns None if fare_usd <= 0 or points_delta == 0 (e.g., free ride).
    """
    if fare_usd <= 0:
        return None

    points_delta = usd_to_points(fare_usd)
    if points_delta <= 0:
        return None

    account = await get_or_create_account(rider_id, db)
    account.points_balance += points_delta
    account.lifetime_earned += points_delta

    txn = RiderRewardTransaction(
        rider_id=rider_id,
        account_id=account.id,
        ride_id=ride_id,
        transaction_type=RewardTransactionType.earn,
        points_delta=points_delta,
        balance_after=account.points_balance,
        description=f"Earned {points_delta} pts for ${fare_usd:.2f} fare",
    )
    db.add(txn)
    await db.flush()
    return txn


# ---------------------------------------------------------------------------
# Redeeming points
# ---------------------------------------------------------------------------


async def redeem_points(
    rider_id: int,
    points: int,
    db: AsyncSession,
    ride_id: int | None = None,
) -> RiderRewardTransaction:
    """Burn `points` from the rider's balance and return the transaction.

    Raises:
        ValueError: if balance is insufficient, points < MIN_REDEMPTION_POINTS,
                    or points is not a positive integer.
    """
    if points <= 0:
        raise ValueError("points must be a positive integer")
    if points < MIN_REDEMPTION_POINTS:
        raise ValueError(
            f"Minimum redemption is {MIN_REDEMPTION_POINTS} points "
            f"(= ${points_to_usd(MIN_REDEMPTION_POINTS):.2f})"
        )

    account = await get_or_create_account(rider_id, db)
    if account.points_balance < points:
        raise ValueError(
            f"Insufficient points balance: have {account.points_balance}, "
            f"requested {points}"
        )

    discount_usd = points_to_usd(points)
    account.points_balance -= points
    account.lifetime_redeemed += points

    txn = RiderRewardTransaction(
        rider_id=rider_id,
        account_id=account.id,
        ride_id=ride_id,
        transaction_type=RewardTransactionType.redeem,
        points_delta=-points,
        balance_after=account.points_balance,
        description=f"Redeemed {points} pts for ${discount_usd:.2f} discount",
    )
    db.add(txn)
    await db.flush()
    return txn


# ---------------------------------------------------------------------------
# Transaction history
# ---------------------------------------------------------------------------


async def get_transaction_history(
    rider_id: int,
    db: AsyncSession,
    offset: int = 0,
    limit: int = DEFAULT_PAGE_SIZE,
) -> tuple[list[RiderRewardTransaction], int]:
    """Return a paginated list of transactions and the total count.

    Returns: (transactions, total_count)
    """
    limit = min(limit, MAX_PAGE_SIZE)

    count_result = await db.execute(
        select(func.count()).where(
            RiderRewardTransaction.rider_id == rider_id
        ).select_from(RiderRewardTransaction)
    )
    total = count_result.scalar_one()

    result = await db.execute(
        select(RiderRewardTransaction)
        .where(RiderRewardTransaction.rider_id == rider_id)
        .order_by(RiderRewardTransaction.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    transactions = list(result.scalars().all())
    return transactions, total


# ---------------------------------------------------------------------------
# Admin: manual adjustments
# ---------------------------------------------------------------------------


async def admin_adjust_points(
    rider_id: int,
    points_delta: int,
    db: AsyncSession,
    description: str | None = None,
) -> RiderRewardTransaction:
    """Manually credit or debit a rider's point balance.

    Negative adjustments are capped so balance cannot go below 0.
    Raises ValueError if points_delta == 0.
    """
    if points_delta == 0:
        raise ValueError("points_delta cannot be zero")

    account = await get_or_create_account(rider_id, db)

    # Cap negative adjustments at current balance.
    if points_delta < 0 and account.points_balance + points_delta < 0:
        points_delta = -account.points_balance

    if points_delta == 0:
        raise ValueError("Rider balance is already 0; cannot debit further")

    account.points_balance += points_delta
    if points_delta > 0:
        account.lifetime_earned += points_delta
    else:
        account.lifetime_redeemed += abs(points_delta)

    txn = RiderRewardTransaction(
        rider_id=rider_id,
        account_id=account.id,
        ride_id=None,
        transaction_type=RewardTransactionType.admin_adjust,
        points_delta=points_delta,
        balance_after=account.points_balance,
        description=description or f"Admin adjustment: {points_delta:+d} pts",
    )
    db.add(txn)
    await db.flush()
    return txn


# ---------------------------------------------------------------------------
# Admin: platform-wide stats
# ---------------------------------------------------------------------------


async def get_platform_stats(db: AsyncSession) -> dict:
    """Aggregate reward stats across all rider accounts."""
    result = await db.execute(
        select(
            func.count(RiderRewardAccount.id).label("total_accounts"),
            func.coalesce(func.sum(RiderRewardAccount.points_balance), 0).label(
                "total_outstanding_points"
            ),
            func.coalesce(func.sum(RiderRewardAccount.lifetime_earned), 0).label(
                "total_lifetime_earned"
            ),
            func.coalesce(func.sum(RiderRewardAccount.lifetime_redeemed), 0).label(
                "total_lifetime_redeemed"
            ),
        )
    )
    row = result.one()

    total_accounts: int = row.total_accounts
    total_outstanding: int = row.total_outstanding_points
    lifetime_earned: int = row.total_lifetime_earned
    lifetime_redeemed: int = row.total_lifetime_redeemed

    return {
        "total_accounts": total_accounts,
        "total_outstanding_points": total_outstanding,
        "outstanding_liability_usd": points_to_usd(total_outstanding),
        "total_lifetime_earned": lifetime_earned,
        "total_lifetime_redeemed": lifetime_redeemed,
        "total_lifetime_earned_usd": points_to_usd(lifetime_earned),
        "total_lifetime_redeemed_usd": points_to_usd(lifetime_redeemed),
    }
