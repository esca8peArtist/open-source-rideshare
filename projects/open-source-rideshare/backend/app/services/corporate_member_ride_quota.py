"""Service layer for Corporate Member Ride Quotas.

Corporate account admins set per-member ride count limits scoped to a time
period (daily, weekly, monthly).  Service functions are async and require a
SQLAlchemy ``AsyncSession``.

The rides table has a ``corporate_account_id`` column which is used when
counting corporate rides in the current period.  If that value is NULL on a
ride (i.e. the ride was not billed to a corporate account), it is excluded
from the count.

Public surface
--------------
set_quota(db, account_id, member_id, period, max_rides, created_by_id)
    -> QuotaResponse
update_quota(db, quota_id, account_id, payload)      -> QuotaResponse
deactivate_quota(db, quota_id, account_id)           -> QuotaResponse
delete_quota(db, quota_id, account_id)               -> None
get_quota(db, quota_id, account_id)                  -> QuotaResponse
list_member_quotas(db, account_id, member_id, period, active_only)
    -> list[QuotaResponse]
get_quota_usage(db, account_id, member_id, period)   -> QuotaCheckResponse
get_account_quota_summary(db, account_id)            -> list[QuotaWithUsageResponse]
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.corporate_member_ride_quota import CorporateMemberRideQuota
from app.models.ride import Ride, RideStatus
from app.schemas.corporate_member_ride_quota import (
    QuotaCheckResponse,
    QuotaResponse,
    QuotaUpdate,
    QuotaWithUsageResponse,
)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_EXCLUDED_STATUSES = {RideStatus.CANCELLED, "cancelled", "failed"}


def _period_start(period: str) -> datetime:
    """Return the UTC start of the current period.

    Args:
        period: One of "daily", "weekly", or "monthly".

    Returns:
        UTC-aware datetime marking the beginning of the current period.

    Raises:
        ValueError: When an unknown period string is supplied.
    """
    now = datetime.now(tz=timezone.utc)
    if period == "daily":
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "weekly":
        # Monday of the current week
        days_since_monday = now.weekday()  # Mon=0 … Sun=6
        monday = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return monday.replace(day=monday.day - days_since_monday)
    if period == "monthly":
        return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    raise ValueError(f"Unknown period: {period!r}. Must be daily, weekly, or monthly.")


async def _count_rides_in_period(
    db: AsyncSession,
    member_id: int,
    account_id: int,
    period_start: datetime,
) -> int:
    """Count qualifying corporate rides taken by a member since period_start.

    Rides with status "cancelled" or "failed" are excluded.  Only rides
    linked to the given corporate account are counted.

    Args:
        db:           Database session.
        member_id:    Rider user ID.
        account_id:   Corporate account ID to filter on.
        period_start: UTC-aware start of the current period.

    Returns:
        Integer ride count.
    """
    excluded = [RideStatus.CANCELLED]
    # Include string "failed" in case it appears as a raw value
    result = await db.execute(
        select(func.count(Ride.id)).where(
            and_(
                Ride.rider_id == member_id,
                Ride.corporate_account_id == account_id,
                Ride.requested_at >= period_start,
                Ride.status.notin_(excluded),
                Ride.status != "failed",
            )
        )
    )
    count = result.scalar_one()
    return count or 0


async def _get_quota_row(
    db: AsyncSession,
    quota_id: int,
    account_id: int,
) -> CorporateMemberRideQuota:
    """Fetch a quota row by ID scoped to account_id, raising 404 if absent."""
    result = await db.execute(
        select(CorporateMemberRideQuota).where(
            CorporateMemberRideQuota.id == quota_id,
            CorporateMemberRideQuota.account_id == account_id,
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ride quota not found.",
        )
    return row


# ---------------------------------------------------------------------------
# Set (create or reactivate)
# ---------------------------------------------------------------------------


async def set_quota(
    db: AsyncSession,
    account_id: int,
    member_id: int,
    period: str,
    max_rides: int,
    created_by_id: Optional[int],
) -> QuotaResponse:
    """Set a ride quota for a corporate member.

    If an active quota already exists for this (account, member, period)
    combination a 409 Conflict is raised.  If an inactive quota exists for
    the same combination it is reactivated with the new max_rides value
    rather than creating a duplicate row.

    Args:
        db:             Database session.
        account_id:     Corporate account ID.
        member_id:      Employee user ID.
        period:         "daily", "weekly", or "monthly".
        max_rides:      Maximum rides per period.
        created_by_id:  Admin user ID who is setting the quota.

    Returns:
        QuotaResponse for the created or reactivated quota.

    Raises:
        HTTP 409: When an active quota already exists.
    """
    # Check for any existing quota for this (account, member, period)
    result = await db.execute(
        select(CorporateMemberRideQuota).where(
            CorporateMemberRideQuota.account_id == account_id,
            CorporateMemberRideQuota.member_id == member_id,
            CorporateMemberRideQuota.period == period,
        )
    )
    existing = result.scalar_one_or_none()

    if existing is not None:
        if existing.is_active:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"An active {period} quota already exists for this member. "
                    "Update the existing quota or deactivate it first."
                ),
            )
        # Reactivate the inactive quota
        existing.is_active = True
        existing.max_rides = max_rides
        await db.commit()
        await db.refresh(existing)
        return QuotaResponse.model_validate(existing)

    row = CorporateMemberRideQuota(
        account_id=account_id,
        member_id=member_id,
        period=period,
        max_rides=max_rides,
        is_active=True,
        created_by_id=created_by_id,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return QuotaResponse.model_validate(row)


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------


async def update_quota(
    db: AsyncSession,
    quota_id: int,
    account_id: int,
    payload: QuotaUpdate,
) -> QuotaResponse:
    """Partially update a quota's max_rides or is_active flag.

    Args:
        db:         Database session.
        quota_id:   Quota primary key.
        account_id: Corporate account ID (scope check).
        payload:    Fields to update (only supplied fields are applied).

    Returns:
        Updated QuotaResponse.

    Raises:
        HTTP 404: When quota is not found or belongs to a different account.
    """
    row = await _get_quota_row(db, quota_id, account_id)

    if payload.max_rides is not None:
        row.max_rides = payload.max_rides
    if payload.is_active is not None:
        row.is_active = payload.is_active

    await db.commit()
    await db.refresh(row)
    return QuotaResponse.model_validate(row)


# ---------------------------------------------------------------------------
# Deactivate
# ---------------------------------------------------------------------------


async def deactivate_quota(
    db: AsyncSession,
    quota_id: int,
    account_id: int,
) -> QuotaResponse:
    """Set is_active=False on a quota without deleting it.

    Args:
        db:         Database session.
        quota_id:   Quota primary key.
        account_id: Corporate account ID (scope check).

    Returns:
        Updated QuotaResponse with is_active=False.

    Raises:
        HTTP 404: When quota is not found or belongs to a different account.
    """
    row = await _get_quota_row(db, quota_id, account_id)
    row.is_active = False
    await db.commit()
    await db.refresh(row)
    return QuotaResponse.model_validate(row)


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


async def delete_quota(
    db: AsyncSession,
    quota_id: int,
    account_id: int,
) -> None:
    """Hard-delete a quota row.

    Args:
        db:         Database session.
        quota_id:   Quota primary key.
        account_id: Corporate account ID (scope check).

    Raises:
        HTTP 404: When quota is not found or belongs to a different account.
    """
    row = await _get_quota_row(db, quota_id, account_id)
    await db.delete(row)
    await db.commit()


# ---------------------------------------------------------------------------
# Get single
# ---------------------------------------------------------------------------


async def get_quota(
    db: AsyncSession,
    quota_id: int,
    account_id: int,
) -> QuotaResponse:
    """Fetch a single quota by ID.

    Args:
        db:         Database session.
        quota_id:   Quota primary key.
        account_id: Corporate account ID (scope check).

    Returns:
        QuotaResponse.

    Raises:
        HTTP 404: When quota is not found or belongs to a different account.
    """
    row = await _get_quota_row(db, quota_id, account_id)
    return QuotaResponse.model_validate(row)


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------


async def list_member_quotas(
    db: AsyncSession,
    account_id: int,
    member_id: Optional[int] = None,
    period: Optional[str] = None,
    active_only: bool = True,
) -> list[QuotaResponse]:
    """List quotas for a corporate account with optional filtering.

    Args:
        db:          Database session.
        account_id:  Corporate account to query.
        member_id:   If supplied, only return quotas for this member.
        period:      If supplied, only return quotas for this period.
        active_only: When True (default) only return is_active=True rows.

    Returns:
        List of QuotaResponse records sorted by member_id then period.
    """
    conditions = [CorporateMemberRideQuota.account_id == account_id]
    if member_id is not None:
        conditions.append(CorporateMemberRideQuota.member_id == member_id)
    if period is not None:
        conditions.append(CorporateMemberRideQuota.period == period)
    if active_only:
        conditions.append(CorporateMemberRideQuota.is_active.is_(True))

    result = await db.execute(
        select(CorporateMemberRideQuota)
        .where(and_(*conditions))
        .order_by(
            CorporateMemberRideQuota.member_id,
            CorporateMemberRideQuota.period,
        )
    )
    rows = result.scalars().all()
    return [QuotaResponse.model_validate(r) for r in rows]


# ---------------------------------------------------------------------------
# Usage check
# ---------------------------------------------------------------------------


async def get_quota_usage(
    db: AsyncSession,
    account_id: int,
    member_id: int,
    period: str,
) -> QuotaCheckResponse:
    """Return quota status and current usage for a (member, period) combination.

    If no active quota exists for the combination, ``quota_active`` is False
    and all numeric fields are 0.

    Args:
        db:         Database session.
        account_id: Corporate account ID.
        member_id:  Employee user ID.
        period:     "daily", "weekly", or "monthly".

    Returns:
        QuotaCheckResponse with current usage statistics.
    """
    result = await db.execute(
        select(CorporateMemberRideQuota).where(
            CorporateMemberRideQuota.account_id == account_id,
            CorporateMemberRideQuota.member_id == member_id,
            CorporateMemberRideQuota.period == period,
            CorporateMemberRideQuota.is_active.is_(True),
        )
    )
    quota = result.scalar_one_or_none()

    if quota is None:
        return QuotaCheckResponse(
            member_id=member_id,
            period=period,
            max_rides=0,
            current_period_rides=0,
            remaining_rides=0,
            quota_exceeded=False,
            quota_active=False,
        )

    period_start = _period_start(period)
    current_rides = await _count_rides_in_period(db, member_id, account_id, period_start)
    remaining = max(0, quota.max_rides - current_rides)

    return QuotaCheckResponse(
        member_id=member_id,
        period=period,
        max_rides=quota.max_rides,
        current_period_rides=current_rides,
        remaining_rides=remaining,
        quota_exceeded=current_rides >= quota.max_rides,
        quota_active=True,
    )


# ---------------------------------------------------------------------------
# Account summary
# ---------------------------------------------------------------------------


async def get_account_quota_summary(
    db: AsyncSession,
    account_id: int,
) -> list[QuotaWithUsageResponse]:
    """Return all active quotas on an account enriched with current usage.

    Results are sorted by member_id then period.

    Args:
        db:         Database session.
        account_id: Corporate account ID.

    Returns:
        List of QuotaWithUsageResponse records.
    """
    result = await db.execute(
        select(CorporateMemberRideQuota)
        .where(
            CorporateMemberRideQuota.account_id == account_id,
            CorporateMemberRideQuota.is_active.is_(True),
        )
        .order_by(
            CorporateMemberRideQuota.member_id,
            CorporateMemberRideQuota.period,
        )
    )
    rows = result.scalars().all()

    enriched: list[QuotaWithUsageResponse] = []
    for row in rows:
        period_start = _period_start(row.period)
        current_rides = await _count_rides_in_period(
            db, row.member_id, row.account_id, period_start
        )
        remaining = max(0, row.max_rides - current_rides)
        enriched.append(
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
                quota_exceeded=current_rides >= row.max_rides,
            )
        )
    return enriched
