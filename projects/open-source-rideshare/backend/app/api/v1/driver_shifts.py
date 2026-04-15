"""Driver shift and hours-tracking endpoints.

Driver endpoints:
  POST /drivers/me/shift/start         — clock in (start a shift)
  POST /drivers/me/shift/end           — clock out (end the active shift)
  GET  /drivers/me/shift/current       — get current active shift (or 404)
  GET  /drivers/me/shifts              — paginated shift history
  GET  /drivers/me/hours/summary       — daily + weekly hours summary
  GET  /drivers/me/shift/fatigue       — fatigue / break recommendation status

Admin endpoints:
  GET  /admin/driver-shifts            — list all shifts (filter: driver_id, status, date range)
  GET  /admin/driver-hours/summary     — platform-wide fatigue dashboard
  POST /admin/driver-shifts/{id}/end   — force-end any active shift
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_admin
from app.db.database import get_db
from app.models.driver_shift import ShiftStatus
from app.models.user import User
from app.schemas.driver_shift import (
    AdminForceEndShift,
    AdminHoursSummaryOut,
    AdminShiftListOut,
    AdminShiftRow,
    DriverShiftListOut,
    DriverShiftOut,
    FatigueStatusOut,
    HoursSummaryOut,
)
from app.services.driver_shift import (
    admin_force_end_shift,
    admin_hours_summary,
    admin_list_shifts,
    end_shift,
    get_active_shift,
    get_fatigue_status,
    get_hours_summary,
    list_driver_shifts,
    start_shift,
)

router = APIRouter(tags=["driver-shifts"])


# ---------------------------------------------------------------------------
# Driver — shift management
# ---------------------------------------------------------------------------


@router.post(
    "/drivers/me/shift/start",
    response_model=DriverShiftOut,
    status_code=status.HTTP_201_CREATED,
)
async def driver_start_shift(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Clock in: start a new shift.

    Only one active shift is allowed at a time.  The shift records the start
    time and tracks rides completed during the window.  Cooperative platforms
    surface this data to protect drivers from fatigue — unlike Uber/Lyft.
    """
    return await start_shift(db, user.id)


@router.post(
    "/drivers/me/shift/end",
    response_model=DriverShiftOut,
)
async def driver_end_shift(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Clock out: end the active shift and record total minutes worked."""
    return await end_shift(db, user.id)


@router.get(
    "/drivers/me/shift/current",
    response_model=DriverShiftOut,
)
async def driver_get_current_shift(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the currently active shift.  Returns 404 if no shift is active."""
    from fastapi import HTTPException

    shift = await get_active_shift(db, user.id)
    if not shift:
        raise HTTPException(status_code=404, detail="No active shift.")
    return shift


@router.get(
    "/drivers/me/shifts",
    response_model=DriverShiftListOut,
)
async def driver_list_shifts(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Paginated shift history for the authenticated driver."""
    shifts, total = await list_driver_shifts(db, user.id, limit=limit, offset=offset)
    return DriverShiftListOut(shifts=shifts, total=total)


@router.get(
    "/drivers/me/hours/summary",
    response_model=HoursSummaryOut,
)
async def driver_hours_summary(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Daily and weekly hours summary.

    Includes today's hours, weekly hours, and whether the driver is
    approaching or at the cooperative safety limits (12 h/day, 60 h/week).
    """
    data = await get_hours_summary(db, user.id)
    return HoursSummaryOut(**data)


@router.get(
    "/drivers/me/shift/fatigue",
    response_model=FatigueStatusOut,
)
async def driver_fatigue_status(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Fatigue check: break recommendation and remaining daily/weekly hours.

    The cooperative recommends a 30-minute break every 4 hours on shift.
    This endpoint surfaces that data to the driver app so it can prompt
    break reminders — a feature deliberately absent from Uber/Lyft.
    """
    data = await get_fatigue_status(db, user.id)
    return FatigueStatusOut(**data)


# ---------------------------------------------------------------------------
# Admin — shift oversight
# ---------------------------------------------------------------------------


@router.get(
    "/admin/driver-shifts",
    response_model=AdminShiftListOut,
    dependencies=[Depends(require_admin)],
)
async def admin_list_driver_shifts(
    driver_id: Optional[int] = Query(None),
    shift_status: Optional[ShiftStatus] = Query(None, alias="status"),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """Admin: list all shifts with optional filters.

    Use *status=active* to see drivers currently on shift.
    Use *driver_id* + *date_from/date_to* for targeted hour audits.
    """
    shifts, total = await admin_list_shifts(
        db,
        driver_id=driver_id,
        shift_status=shift_status,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        offset=offset,
    )
    rows = [
        AdminShiftRow(
            id=s.id,
            driver_id=s.driver_id,
            driver_name=None,  # resolved via driver profile in production
            started_at=s.started_at,
            ended_at=s.ended_at,
            status=s.status,
            rides_completed=s.rides_completed,
            total_minutes=s.total_minutes,
            admin_note=s.admin_note,
        )
        for s in shifts
    ]
    return AdminShiftListOut(shifts=rows, total=total)


@router.get(
    "/admin/driver-hours/summary",
    response_model=AdminHoursSummaryOut,
    dependencies=[Depends(require_admin)],
)
async def admin_platform_hours_summary(
    db: AsyncSession = Depends(get_db),
):
    """Admin: platform-wide fatigue dashboard.

    Shows how many drivers are currently on shift, how many are approaching
    daily/weekly safety limits, and average shift length today.
    """
    data = await admin_hours_summary(db)
    return AdminHoursSummaryOut(**data)


@router.post(
    "/admin/driver-shifts/{shift_id}/end",
    response_model=DriverShiftOut,
    dependencies=[Depends(require_admin)],
)
async def admin_end_driver_shift(
    shift_id: int,
    body: AdminForceEndShift,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Admin: force-end any active shift (marks as auto_ended).

    Use when a driver has exceeded the daily limit or in an emergency.
    Records which admin ended the shift and an optional note.
    """
    return await admin_force_end_shift(db, shift_id, user.id, body.admin_note)
