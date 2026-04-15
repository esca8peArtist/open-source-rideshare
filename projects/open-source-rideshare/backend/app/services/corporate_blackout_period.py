"""Service layer for the Corporate Blackout Periods feature.

Admins define named date ranges (one-time or recurring) during which
corporate bookings are restricted.  The check function evaluates whether
a proposed booking datetime falls inside any active blackout window.

Public surface
--------------
create_blackout_period(db, account_id, data, created_by_id)
get_blackout_period(db, account_id, period_id)
list_blackout_periods(db, account_id, *, active_only, from_dt, to_dt, skip, limit)
update_blackout_period(db, account_id, period_id, data)
delete_blackout_period(db, account_id, period_id)
check_booking_blackout(db, account_id, dt)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Sequence

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.corporate_blackout_period import (
    BlackoutRecurrence,
    CorporateBlackoutPeriod,
)
from app.schemas.corporate_blackout_period import (
    BlackoutPeriodCreate,
    BlackoutPeriodUpdate,
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _get_period(
    db: AsyncSession, account_id: int, period_id: uuid.UUID
) -> CorporateBlackoutPeriod:
    """Fetch a blackout period; raise 404 if not found or account mismatch."""
    result = await db.execute(
        select(CorporateBlackoutPeriod).where(
            CorporateBlackoutPeriod.id == period_id,
            CorporateBlackoutPeriod.corporate_account_id == account_id,
        )
    )
    period = result.scalar_one_or_none()
    if period is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Blackout period not found.",
        )
    return period


def _period_covers(period: CorporateBlackoutPeriod, dt: datetime) -> bool:
    """Return True if period covers the given datetime.

    For ``none`` recurrence: simple range check.
    For ``annual`` recurrence: the month/day range repeats every year;
        year component of start/end is replaced with dt's year.
    For ``weekly`` recurrence: checks if dt.weekday() is in affected_days
        and dt's time-of-day falls within start/end times.
    """
    # Normalise dt to UTC-aware if it lacks tzinfo, for safe comparison
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    s = period.start_datetime
    e = period.end_datetime
    if s.tzinfo is None:
        s = s.replace(tzinfo=timezone.utc)
    if e.tzinfo is None:
        e = e.replace(tzinfo=timezone.utc)

    if period.recurrence == BlackoutRecurrence.none:
        return s <= dt <= e

    elif period.recurrence == BlackoutRecurrence.annual:
        try:
            s_this = s.replace(year=dt.year)
            e_this = e.replace(year=dt.year)
        except ValueError:
            # e.g. Feb 29 in a non-leap year — skip
            return False

        if s_this <= e_this:
            return s_this <= dt <= e_this
        else:
            # Cross-year wrap (e.g. Dec 26 → Jan 2): check both halves
            try:
                e_next = e.replace(year=dt.year + 1)
                s_prev = s.replace(year=dt.year - 1)
            except ValueError:
                return False
            return dt >= s_this or dt <= e_this or (dt >= s_prev and dt <= e_next)

    elif period.recurrence == BlackoutRecurrence.weekly:
        days = period.affected_days or []
        if dt.weekday() not in days:
            return False
        # Time-of-day comparison (strip timezone for time comparison)
        dt_time = dt.replace(tzinfo=None).time()
        s_time = s.replace(tzinfo=None).time()
        e_time = e.replace(tzinfo=None).time()
        return s_time <= dt_time <= e_time

    return False


# ---------------------------------------------------------------------------
# Public service functions
# ---------------------------------------------------------------------------


async def create_blackout_period(
    db: AsyncSession,
    account_id: int,
    data: BlackoutPeriodCreate,
    created_by_id: int | None = None,
) -> CorporateBlackoutPeriod:
    """Create a new blackout period for the given corporate account.

    Raises:
        400: If end_datetime <= start_datetime (also enforced by schema).
    """
    if data.end_datetime <= data.start_datetime:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="end_datetime must be after start_datetime.",
        )

    period = CorporateBlackoutPeriod(
        corporate_account_id=account_id,
        name=data.name,
        start_datetime=data.start_datetime,
        end_datetime=data.end_datetime,
        recurrence=BlackoutRecurrence(data.recurrence),
        affected_days=data.affected_days,
        override_allowed=data.override_allowed,
        override_requires_approval=data.override_requires_approval,
        reason=data.reason,
        is_active=True,
        created_by_id=created_by_id,
    )
    db.add(period)
    await db.commit()
    await db.refresh(period)
    return period


async def get_blackout_period(
    db: AsyncSession,
    account_id: int,
    period_id: uuid.UUID,
) -> CorporateBlackoutPeriod:
    """Fetch a single blackout period by ID, scoped to account_id."""
    return await _get_period(db, account_id, period_id)


async def list_blackout_periods(
    db: AsyncSession,
    account_id: int,
    *,
    active_only: bool = False,
    from_dt: datetime | None = None,
    to_dt: datetime | None = None,
    skip: int = 0,
    limit: int = 50,
) -> tuple[Sequence[CorporateBlackoutPeriod], int]:
    """Return paginated blackout periods for an account.

    Filters:
        active_only: If True, only return periods with is_active=True.
        from_dt: If set, only return periods whose end_datetime >= from_dt.
        to_dt: If set, only return periods whose start_datetime <= to_dt.
    """
    query = select(CorporateBlackoutPeriod).where(
        CorporateBlackoutPeriod.corporate_account_id == account_id
    )

    if active_only:
        query = query.where(CorporateBlackoutPeriod.is_active.is_(True))
    if from_dt is not None:
        query = query.where(CorporateBlackoutPeriod.end_datetime >= from_dt)
    if to_dt is not None:
        query = query.where(CorporateBlackoutPeriod.start_datetime <= to_dt)

    total_result = await db.execute(query)
    total = len(total_result.scalars().all())

    paged_result = await db.execute(
        query.order_by(CorporateBlackoutPeriod.start_datetime)
        .offset(skip)
        .limit(limit)
    )
    items = paged_result.scalars().all()
    return items, total


async def update_blackout_period(
    db: AsyncSession,
    account_id: int,
    period_id: uuid.UUID,
    data: BlackoutPeriodUpdate,
) -> CorporateBlackoutPeriod:
    """Partially update a blackout period.

    Raises:
        404: Period not found.
        400: If end_datetime <= start_datetime after applying updates.
    """
    period = await _get_period(db, account_id, period_id)

    update_fields = data.model_dump(exclude_unset=True)
    for field, value in update_fields.items():
        if field == "recurrence" and value is not None:
            value = BlackoutRecurrence(value)
        setattr(period, field, value)

    # Re-validate after applying
    if period.end_datetime <= period.start_datetime:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="end_datetime must be after start_datetime.",
        )

    await db.commit()
    await db.refresh(period)
    return period


async def delete_blackout_period(
    db: AsyncSession,
    account_id: int,
    period_id: uuid.UUID,
) -> None:
    """Hard-delete a blackout period.

    Raises:
        404: Period not found.
    """
    period = await _get_period(db, account_id, period_id)
    await db.delete(period)
    await db.commit()


async def check_booking_blackout(
    db: AsyncSession,
    account_id: int,
    dt: datetime,
) -> list[CorporateBlackoutPeriod]:
    """Return all active blackout periods that cover the given datetime.

    An empty list means the booking datetime is not blacked out.
    Inactive periods are always excluded.
    """
    result = await db.execute(
        select(CorporateBlackoutPeriod).where(
            CorporateBlackoutPeriod.corporate_account_id == account_id,
            CorporateBlackoutPeriod.is_active.is_(True),
        )
    )
    periods = result.scalars().all()
    return [p for p in periods if p.is_active and _period_covers(p, dt)]
