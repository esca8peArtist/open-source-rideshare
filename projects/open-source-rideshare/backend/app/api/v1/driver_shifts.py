"""Driver shift management endpoints.

POST /driver/me/shifts/start   — start a new shift (409 if already active)
POST /driver/me/shifts/end     — end the active shift, compute duration (404 if none)
GET  /driver/me/shifts/active  — current active shift (404 if none)
GET  /driver/me/shifts         — paginated shift history (?page=1&page_size=20)
"""

from datetime import datetime, timezone
from math import ceil

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_driver
from app.db.database import get_db
from app.models.driver_shift import DriverShift, ShiftStatus
from app.models.user import User
from app.schemas.driver_shift import DriverShiftListResponse, DriverShiftResponse

router = APIRouter(prefix="/driver", tags=["driver"])


@router.post(
    "/me/shifts/start",
    response_model=DriverShiftResponse,
    status_code=status.HTTP_201_CREATED,
)
async def start_shift(
    driver: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
) -> DriverShiftResponse:
    """Start a new driver shift.

    Returns 409 if the driver already has an active shift.
    """
    result = await db.execute(
        select(DriverShift).where(
            DriverShift.driver_id == driver.id,
            DriverShift.status == ShiftStatus.active,
        )
    )
    if result.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Active shift already in progress")

    shift = DriverShift(
        driver_id=driver.id,
        status=ShiftStatus.active,
        started_at=datetime.now(timezone.utc),
    )
    db.add(shift)
    await db.commit()
    await db.refresh(shift)
    return DriverShiftResponse.model_validate(shift)


@router.post("/me/shifts/end", response_model=DriverShiftResponse)
async def end_shift(
    driver: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
) -> DriverShiftResponse:
    """End the driver's active shift and compute total duration.

    Returns 404 if the driver has no active shift.
    """
    result = await db.execute(
        select(DriverShift).where(
            DriverShift.driver_id == driver.id,
            DriverShift.status == ShiftStatus.active,
        )
    )
    shift = result.scalar_one_or_none()
    if not shift:
        raise HTTPException(status_code=404, detail="No active shift found")

    now = datetime.now(timezone.utc)
    shift.ended_at = now
    shift.status = ShiftStatus.completed
    started = shift.started_at
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    shift.total_minutes = (now - started).total_seconds() / 60.0

    await db.commit()
    await db.refresh(shift)
    return DriverShiftResponse.model_validate(shift)


@router.get("/me/shifts/active", response_model=DriverShiftResponse)
async def get_active_shift(
    driver: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
) -> DriverShiftResponse:
    """Return the driver's current active shift (404 if none)."""
    result = await db.execute(
        select(DriverShift).where(
            DriverShift.driver_id == driver.id,
            DriverShift.status == ShiftStatus.active,
        )
    )
    shift = result.scalar_one_or_none()
    if not shift:
        raise HTTPException(status_code=404, detail="No active shift found")
    return DriverShiftResponse.model_validate(shift)


@router.get("/me/shifts", response_model=DriverShiftListResponse)
async def list_shifts(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    driver: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
) -> DriverShiftListResponse:
    """Return a paginated list of the driver's shifts, newest first."""
    offset = (page - 1) * page_size

    count_result = await db.execute(
        select(func.count()).where(DriverShift.driver_id == driver.id)
    )
    total = count_result.scalar_one()

    result = await db.execute(
        select(DriverShift)
        .where(DriverShift.driver_id == driver.id)
        .order_by(DriverShift.started_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    shifts = result.scalars().all()

    return DriverShiftListResponse(
        items=[DriverShiftResponse.model_validate(s) for s in shifts],
        total=total,
        page=page,
        page_size=page_size,
    )
