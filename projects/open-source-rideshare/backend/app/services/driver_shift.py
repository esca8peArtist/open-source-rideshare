"""Service layer for driver shift / hours tracking.

All database interactions for shift management live here.  Callers (routers)
pass an AsyncSession and receive plain model instances or raise HTTPException.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.driver_shift import DriverShift, ShiftStatus
from app.schemas.driver_shift import (
    BREAK_AFTER_HOURS,
    MAX_HOURS_PER_DAY,
    MAX_HOURS_PER_WEEK,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _week_start(dt: datetime) -> datetime:
    """Return the Monday 00:00 UTC of the week containing *dt*."""
    monday = dt - timedelta(days=dt.weekday())
    return monday.replace(hour=0, minute=0, second=0, microsecond=0)


def _day_start(dt: datetime) -> datetime:
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


def _minutes_between(start: datetime, end: datetime) -> float:
    delta = end - start
    return delta.total_seconds() / 60.0


# ---------------------------------------------------------------------------
# Core shift operations
# ---------------------------------------------------------------------------

async def start_shift(db: AsyncSession, driver_id: int) -> DriverShift:
    """Start a new shift for *driver_id*.

    Raises 409 if a shift is already active.
    """
    existing = await _get_active_shift(db, driver_id)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You already have an active shift. End it before starting a new one.",
        )
    shift = DriverShift(driver_id=driver_id, status=ShiftStatus.active)
    db.add(shift)
    await db.commit()
    await db.refresh(shift)
    return shift


async def end_shift(db: AsyncSession, driver_id: int) -> DriverShift:
    """End the active shift for *driver_id*.

    Raises 404 if no active shift exists.
    """
    shift = await _get_active_shift(db, driver_id)
    if not shift:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active shift found.",
        )
    now = _now()
    shift.ended_at = now
    shift.status = ShiftStatus.completed
    shift.total_minutes = _minutes_between(shift.started_at, now)
    await db.commit()
    await db.refresh(shift)
    return shift


async def get_active_shift(db: AsyncSession, driver_id: int) -> Optional[DriverShift]:
    """Return the driver's current active shift, or None."""
    return await _get_active_shift(db, driver_id)


async def _get_active_shift(db: AsyncSession, driver_id: int) -> Optional[DriverShift]:
    result = await db.execute(
        select(DriverShift).where(
            and_(
                DriverShift.driver_id == driver_id,
                DriverShift.status == ShiftStatus.active,
            )
        )
    )
    return result.scalars().first()


async def list_driver_shifts(
    db: AsyncSession, driver_id: int, limit: int = 20, offset: int = 0
) -> tuple[list[DriverShift], int]:
    """Return paginated shift history for a driver."""
    base = select(DriverShift).where(DriverShift.driver_id == driver_id)
    count_result = await db.execute(
        select(func.count()).select_from(base.subquery())
    )
    total = count_result.scalar_one()
    shifts_result = await db.execute(
        base.order_by(DriverShift.started_at.desc()).offset(offset).limit(limit)
    )
    return list(shifts_result.scalars().all()), total


# ---------------------------------------------------------------------------
# Hours calculations
# ---------------------------------------------------------------------------

async def _get_day_minutes(db: AsyncSession, driver_id: int, date: datetime) -> float:
    """Total minutes worked on *date* (UTC day)."""
    day_start = _day_start(date)
    day_end = day_start + timedelta(days=1)

    result = await db.execute(
        select(func.coalesce(func.sum(DriverShift.total_minutes), 0.0)).where(
            and_(
                DriverShift.driver_id == driver_id,
                DriverShift.status.in_([ShiftStatus.completed, ShiftStatus.auto_ended]),
                DriverShift.started_at >= day_start,
                DriverShift.started_at < day_end,
            )
        )
    )
    completed_mins = float(result.scalar_one())

    active = await _get_active_shift(db, driver_id)
    active_today: float = 0.0
    if active and active.started_at >= day_start:
        active_today = _minutes_between(active.started_at, _now())

    return completed_mins + active_today


async def _get_week_minutes(db: AsyncSession, driver_id: int) -> float:
    """Total minutes worked since the start of the current week."""
    now = _now()
    week_start = _week_start(now)

    result = await db.execute(
        select(func.coalesce(func.sum(DriverShift.total_minutes), 0.0)).where(
            and_(
                DriverShift.driver_id == driver_id,
                DriverShift.status.in_([ShiftStatus.completed, ShiftStatus.auto_ended]),
                DriverShift.started_at >= week_start,
            )
        )
    )
    completed_mins = float(result.scalar_one())

    active = await _get_active_shift(db, driver_id)
    active_this_week: float = 0.0
    if active and active.started_at >= week_start:
        active_this_week = _minutes_between(active.started_at, _now())

    return completed_mins + active_this_week


async def get_hours_summary(db: AsyncSession, driver_id: int) -> dict:
    """Return daily + weekly hours summary dict for a driver."""
    now = _now()
    day_minutes = await _get_day_minutes(db, driver_id, now)
    week_minutes = await _get_week_minutes(db, driver_id)

    day_hours = day_minutes / 60.0
    week_hours = week_minutes / 60.0
    max_day = MAX_HOURS_PER_DAY
    max_week = MAX_HOURS_PER_WEEK

    day_remaining_min = max(0.0, (max_day - day_hours) * 60.0)
    week_remaining_min = max(0.0, (max_week - week_hours) * 60.0)

    day_start = _day_start(now)
    day_end = day_start + timedelta(days=1)
    week_start = _week_start(now)

    daily_shifts_result = await db.execute(
        select(func.count()).where(
            and_(
                DriverShift.driver_id == driver_id,
                DriverShift.started_at >= day_start,
                DriverShift.started_at < day_end,
            )
        )
    )
    daily_shifts = daily_shifts_result.scalar_one()

    weekly_shifts_result = await db.execute(
        select(func.count()).where(
            and_(
                DriverShift.driver_id == driver_id,
                DriverShift.started_at >= week_start,
            )
        )
    )
    weekly_shifts = weekly_shifts_result.scalar_one()

    active = await _get_active_shift(db, driver_id)

    return {
        "driver_id": driver_id,
        "today": {
            "date": now.strftime("%Y-%m-%d"),
            "hours_worked": round(day_hours, 2),
            "shifts_count": daily_shifts,
            "at_daily_limit": day_hours >= max_day,
            "minutes_until_daily_limit": round(day_remaining_min, 1),
        },
        "week_start": _week_start(now).strftime("%Y-%m-%d"),
        "weekly_hours": round(week_hours, 2),
        "weekly_shifts": weekly_shifts,
        "at_weekly_limit": week_hours >= max_week,
        "minutes_until_weekly_limit": round(week_remaining_min, 1),
        "active_shift": active,
    }


async def get_fatigue_status(db: AsyncSession, driver_id: int) -> dict:
    """Return fatigue status and break recommendation for a driver."""
    now = _now()
    active = await _get_active_shift(db, driver_id)

    shift_minutes: Optional[float] = None
    break_recommended = False
    minutes_until_break: Optional[float] = None

    if active:
        shift_minutes = _minutes_between(active.started_at, now)
        hours_on_shift = shift_minutes / 60.0
        break_recommended = hours_on_shift >= BREAK_AFTER_HOURS
        minutes_until_break = max(0.0, (BREAK_AFTER_HOURS * 60.0) - shift_minutes)

    day_minutes = await _get_day_minutes(db, driver_id, now)
    week_minutes = await _get_week_minutes(db, driver_id)

    daily_remaining = max(0.0, (MAX_HOURS_PER_DAY * 60.0 - day_minutes) / 60.0)
    weekly_remaining = max(0.0, (MAX_HOURS_PER_WEEK * 60.0 - week_minutes) / 60.0)

    return {
        "driver_id": driver_id,
        "has_active_shift": active is not None,
        "shift_minutes_elapsed": round(shift_minutes, 1) if shift_minutes is not None else None,
        "break_recommended": break_recommended,
        "minutes_until_break_due": round(minutes_until_break, 1) if minutes_until_break is not None else None,
        "daily_hours_remaining": round(daily_remaining, 2),
        "weekly_hours_remaining": round(weekly_remaining, 2),
        "max_hours_per_day": MAX_HOURS_PER_DAY,
        "max_hours_per_week": MAX_HOURS_PER_WEEK,
        "break_after_hours": BREAK_AFTER_HOURS,
    }


# ---------------------------------------------------------------------------
# Admin operations
# ---------------------------------------------------------------------------

async def admin_force_end_shift(
    db: AsyncSession, shift_id: int, admin_id: int, admin_note: Optional[str]
) -> DriverShift:
    """Admin force-ends any active shift."""
    result = await db.execute(select(DriverShift).where(DriverShift.id == shift_id))
    shift = result.scalars().first()
    if not shift:
        raise HTTPException(status_code=404, detail="Shift not found.")
    if shift.status != ShiftStatus.active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Shift is not active.",
        )
    now = _now()
    shift.ended_at = now
    shift.status = ShiftStatus.auto_ended
    shift.total_minutes = _minutes_between(shift.started_at, now)
    shift.ended_by_admin_id = admin_id
    shift.admin_note = admin_note
    await db.commit()
    await db.refresh(shift)
    return shift


async def admin_list_shifts(
    db: AsyncSession,
    driver_id: Optional[int] = None,
    shift_status: Optional[ShiftStatus] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[DriverShift], int]:
    """List shifts with optional filters for admin."""
    filters = []
    if driver_id is not None:
        filters.append(DriverShift.driver_id == driver_id)
    if shift_status is not None:
        filters.append(DriverShift.status == shift_status)
    if date_from is not None:
        filters.append(DriverShift.started_at >= date_from)
    if date_to is not None:
        filters.append(DriverShift.started_at <= date_to)

    base = select(DriverShift)
    if filters:
        base = base.where(and_(*filters))

    count_result = await db.execute(
        select(func.count()).select_from(base.subquery())
    )
    total = count_result.scalar_one()
    shifts_result = await db.execute(
        base.order_by(DriverShift.started_at.desc()).offset(offset).limit(limit)
    )
    return list(shifts_result.scalars().all()), total


async def admin_hours_summary(db: AsyncSession) -> dict:
    """Platform-wide driver hours summary for admin dashboard."""
    now = _now()
    day_start = _day_start(now)
    day_end = day_start + timedelta(days=1)
    week_start = _week_start(now)

    active_result = await db.execute(
        select(func.count()).where(DriverShift.status == ShiftStatus.active)
    )
    active_count = active_result.scalar_one()

    drivers_today_result = await db.execute(
        select(DriverShift.driver_id).where(
            and_(
                DriverShift.started_at >= day_start,
                DriverShift.started_at < day_end,
            )
        ).distinct()
    )
    drivers_today = drivers_today_result.scalars().all()

    near_daily = 0
    over_daily = 0
    for did in drivers_today:
        mins = await _get_day_minutes(db, did, now)
        hours = mins / 60.0
        if hours >= MAX_HOURS_PER_DAY:
            over_daily += 1
        elif hours >= MAX_HOURS_PER_DAY - 1.0:
            near_daily += 1

    drivers_week_result = await db.execute(
        select(DriverShift.driver_id).where(
            DriverShift.started_at >= week_start
        ).distinct()
    )
    drivers_week = drivers_week_result.scalars().all()

    near_weekly = 0
    over_weekly = 0
    for did in drivers_week:
        week_mins = await _get_week_minutes(db, did)
        week_h = week_mins / 60.0
        if week_h >= MAX_HOURS_PER_WEEK:
            over_weekly += 1
        elif week_h >= MAX_HOURS_PER_WEEK - 5.0:
            near_weekly += 1

    avg_result = await db.execute(
        select(func.avg(DriverShift.total_minutes)).where(
            and_(
                DriverShift.status.in_([ShiftStatus.completed, ShiftStatus.auto_ended]),
                DriverShift.started_at >= day_start,
                DriverShift.started_at < day_end,
            )
        )
    )
    avg_raw = avg_result.scalar_one()
    avg_hours = round((float(avg_raw) / 60.0) if avg_raw else 0.0, 2)

    return {
        "total_active_shifts": active_count,
        "drivers_near_daily_limit": near_daily,
        "drivers_near_weekly_limit": near_weekly,
        "drivers_over_daily_limit": over_daily,
        "drivers_over_weekly_limit": over_weekly,
        "average_shift_hours_today": avg_hours,
    }
