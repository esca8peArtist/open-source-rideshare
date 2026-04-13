"""API endpoints for driver incentive / bonus programs.

Driver endpoints allow drivers to view active programs and their progress.
Admin endpoints allow managing program definitions.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_admin, require_driver
from app.db.database import get_db
from app.models.incentive import DriverIncentiveProgress, IncentiveProgram, ProgressStatus
from app.models.user import User
from app.schemas.incentive import (
    DriverIncentiveSummary,
    DriverProgressResponse,
    IncentiveProgramCreate,
    IncentiveProgramResponse,
    IncentiveProgramUpdate,
)
from app.services.incentives import (
    create_or_get_progress,
    get_active_programs,
    get_driver_progress,
    get_driver_summary,
    mark_bonuses_paid,
)

router = APIRouter(prefix="/incentives", tags=["incentives"])
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Driver endpoints
# ---------------------------------------------------------------------------


@router.get("/", response_model=list[DriverIncentiveSummary])
async def list_active_programs(
    current_user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    """List all active programs along with the current driver's progress on each."""
    summary_dicts = await get_driver_summary(db, current_user.id)
    return [
        DriverIncentiveSummary(
            program=IncentiveProgramResponse.model_validate(item["program"]),
            progress=(
                DriverProgressResponse.model_validate(item["progress"])
                if item["progress"] is not None
                else None
            ),
            trips_remaining=item["trips_remaining"],
            potential_bonus=item["potential_bonus"],
        )
        for item in summary_dicts
    ]


@router.get("/earnings/pending")
async def pending_earnings(
    current_user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    """Return total unpaid (completed but not yet paid) bonus earnings for the driver."""
    result = await db.execute(
        select(func.coalesce(func.sum(DriverIncentiveProgress.bonus_earned), 0.0)).where(
            DriverIncentiveProgress.driver_id == current_user.id,
            DriverIncentiveProgress.status == ProgressStatus.COMPLETED.value,
        )
    )
    total = result.scalar() or 0.0
    return {"pending_bonus": round(float(total), 2)}


@router.get("/{program_id}/progress", response_model=DriverProgressResponse)
async def get_program_progress(
    program_id: int,
    current_user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    """Get the current driver's progress on a specific program (today's period)."""
    from datetime import date
    progress = await get_driver_progress(db, current_user.id, program_id, date.today())
    if progress is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No progress record found")
    return DriverProgressResponse.model_validate(progress)


# ---------------------------------------------------------------------------
# Admin endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/admin/programs",
    response_model=IncentiveProgramResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_program(
    payload: IncentiveProgramCreate,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Create a new incentive program."""
    program = IncentiveProgram(**payload.model_dump())
    db.add(program)
    await db.flush()
    logger.info("Admin %d created incentive program %d (%s)", current_user.id, program.id, program.name)
    return IncentiveProgramResponse.model_validate(program)


@router.get("/admin/programs", response_model=list[IncentiveProgramResponse])
async def list_all_programs(
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """List all incentive programs (active and inactive)."""
    result = await db.execute(select(IncentiveProgram).order_by(IncentiveProgram.id))
    return [IncentiveProgramResponse.model_validate(p) for p in result.scalars().all()]


@router.put("/admin/programs/{program_id}", response_model=IncentiveProgramResponse)
async def update_program(
    program_id: int,
    payload: IncentiveProgramUpdate,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Update an existing incentive program."""
    result = await db.execute(select(IncentiveProgram).where(IncentiveProgram.id == program_id))
    program = result.scalar_one_or_none()
    if program is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Program not found")

    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(program, field, value)

    await db.flush()
    return IncentiveProgramResponse.model_validate(program)


@router.delete("/admin/programs/{program_id}")
async def deactivate_program(
    program_id: int,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Soft-delete an incentive program by setting is_active=False."""
    result = await db.execute(select(IncentiveProgram).where(IncentiveProgram.id == program_id))
    program = result.scalar_one_or_none()
    if program is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Program not found")

    program.is_active = False
    await db.flush()
    return {"status": "deactivated", "program_id": program_id}


@router.get("/admin/programs/{program_id}/leaderboard")
async def program_leaderboard(
    program_id: int,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Top 20 drivers by trips_completed for a given program."""
    result = await db.execute(select(IncentiveProgram).where(IncentiveProgram.id == program_id))
    program = result.scalar_one_or_none()
    if program is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Program not found")

    leaderboard_result = await db.execute(
        select(DriverIncentiveProgress)
        .where(DriverIncentiveProgress.program_id == program_id)
        .order_by(DriverIncentiveProgress.trips_completed.desc())
        .limit(20)
    )
    records = leaderboard_result.scalars().all()
    return [
        {
            "driver_id": r.driver_id,
            "trips_completed": r.trips_completed,
            "bonus_earned": r.bonus_earned,
            "status": r.status,
        }
        for r in records
    ]
