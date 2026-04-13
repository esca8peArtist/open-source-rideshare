"""Service layer for driver incentive / bonus programs.

Handles program evaluation, trip completion recording, progress tracking,
and bonus payout marking.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.incentive import DriverIncentiveProgress, IncentiveProgram, ProgressStatus, ProgramType
from app.models.ride import Ride, RideStatus

logger = logging.getLogger(__name__)


async def get_active_programs(db: AsyncSession) -> list[IncentiveProgram]:
    """Return all active programs where today falls within start_date..end_date."""
    today = date.today()
    result = await db.execute(
        select(IncentiveProgram).where(
            IncentiveProgram.is_active == True,  # noqa: E712
            IncentiveProgram.start_date <= today,
            # end_date is optional; if None the program runs indefinitely
        )
    )
    programs = result.scalars().all()
    # Filter out expired programs (end_date not None and in the past)
    return [p for p in programs if p.end_date is None or p.end_date >= today]


async def get_driver_progress(
    db: AsyncSession,
    driver_id: int,
    program_id: int,
    period_start: date,
) -> DriverIncentiveProgress | None:
    """Get driver's progress record for a specific program and period."""
    result = await db.execute(
        select(DriverIncentiveProgress).where(
            DriverIncentiveProgress.driver_id == driver_id,
            DriverIncentiveProgress.program_id == program_id,
            DriverIncentiveProgress.period_start == period_start,
        )
    )
    return result.scalar_one_or_none()


async def create_or_get_progress(
    db: AsyncSession,
    driver_id: int,
    program_id: int,
) -> DriverIncentiveProgress:
    """Get or create a progress record for today's period.

    Period logic:
    - All program types use today as the period_start (daily reset).
    """
    today = date.today()
    existing = await get_driver_progress(db, driver_id, program_id, today)
    if existing:
        return existing

    progress = DriverIncentiveProgress(
        driver_id=driver_id,
        program_id=program_id,
        period_start=today,
        trips_completed=0,
        bonus_earned=0.0,
        status=ProgressStatus.ACTIVE.value,
    )
    db.add(progress)
    await db.flush()
    logger.info("Created progress record for driver %d on program %d", driver_id, program_id)
    return progress


def _trip_in_time_window(program: IncentiveProgram, trip_time: datetime) -> bool:
    """Return True if the trip's local time falls within the program's time window.

    If no window is set, all times qualify.
    """
    if program.start_time is None and program.end_time is None:
        return True
    trip_t = trip_time.time()
    if program.start_time is not None and trip_t < program.start_time:
        return False
    if program.end_time is not None and trip_t > program.end_time:
        return False
    return True


def _trip_on_qualifying_day(program: IncentiveProgram, trip_time: datetime) -> bool:
    """Return True if the trip day matches the program's days_of_week filter."""
    if program.days_of_week is None:
        return True
    allowed = {int(d.strip()) for d in program.days_of_week.split(",") if d.strip()}
    return trip_time.weekday() in allowed


async def record_trip_completion(
    db: AsyncSession,
    driver_id: int,
    ride_id: int,
    completed_at: datetime,
) -> list[DriverIncentiveProgress]:
    """Called after a ride completes. Evaluates all active programs and updates progress.

    Returns the list of progress records that were updated.
    """
    programs = await get_active_programs(db)
    updated: list[DriverIncentiveProgress] = []

    for program in programs:
        ptype = program.program_type

        if ptype == ProgramType.QUEST.value:
            if not _trip_in_time_window(program, completed_at):
                continue
            if not _trip_on_qualifying_day(program, completed_at):
                continue

            progress = await create_or_get_progress(db, driver_id, program.id)
            if progress.status != ProgressStatus.ACTIVE.value:
                continue

            progress.trips_completed += 1
            if program.trip_target and progress.trips_completed >= program.trip_target:
                progress.status = ProgressStatus.COMPLETED.value
                progress.bonus_earned = program.bonus_amount
                progress.completed_at = completed_at
                logger.info(
                    "Driver %d completed quest %d — bonus $%.2f",
                    driver_id, program.id, program.bonus_amount,
                )
            updated.append(progress)

        elif ptype == ProgramType.PEAK_HOURS.value:
            if not _trip_in_time_window(program, completed_at):
                continue
            if not _trip_on_qualifying_day(program, completed_at):
                continue

            progress = await create_or_get_progress(db, driver_id, program.id)
            if progress.status not in (ProgressStatus.ACTIVE.value, ProgressStatus.COMPLETED.value):
                continue

            progress.trips_completed += 1
            progress.bonus_earned += program.bonus_amount
            logger.info(
                "Driver %d earned peak-hours bonus $%.2f on program %d",
                driver_id, program.bonus_amount, program.id,
            )
            updated.append(progress)

        elif ptype == ProgramType.STREAK.value:
            # Check for any driver cancellations since period_start; if found, expire the streak.
            progress = await create_or_get_progress(db, driver_id, program.id)
            if progress.status != ProgressStatus.ACTIVE.value:
                continue

            cancel_result = await db.execute(
                select(Ride).where(
                    Ride.driver_id == driver_id,
                    Ride.status == RideStatus.CANCELLED,
                    Ride.updated_at >= datetime.combine(progress.period_start, datetime.min.time()),
                )
            )
            cancellation = cancel_result.scalar_one_or_none()
            if cancellation is not None:
                progress.status = ProgressStatus.EXPIRED.value
                logger.info("Driver %d streak %d expired due to cancellation", driver_id, program.id)
                updated.append(progress)
                continue

            progress.trips_completed += 1
            if program.trip_target and progress.trips_completed >= program.trip_target:
                progress.status = ProgressStatus.COMPLETED.value
                progress.bonus_earned = program.bonus_amount
                progress.completed_at = completed_at
                logger.info(
                    "Driver %d completed streak %d — bonus $%.2f",
                    driver_id, program.id, program.bonus_amount,
                )
            updated.append(progress)

        # earnings_guarantee is evaluated at payout time, not per-trip

    await db.flush()
    return updated


async def get_driver_summary(
    db: AsyncSession,
    driver_id: int,
) -> list[dict]:
    """Return active programs with driver's current progress.

    Each dict contains:
    - program: IncentiveProgram
    - progress: DriverIncentiveProgress | None
    - trips_remaining: int | None
    - potential_bonus: float
    """
    programs = await get_active_programs(db)
    today = date.today()
    summary: list[dict] = []

    for program in programs:
        progress = await get_driver_progress(db, driver_id, program.id, today)

        trips_remaining: int | None = None
        if program.trip_target is not None and program.program_type in (
            ProgramType.QUEST.value,
            ProgramType.STREAK.value,
        ):
            completed = progress.trips_completed if progress else 0
            trips_remaining = max(0, program.trip_target - completed)

        potential_bonus = program.bonus_amount

        summary.append(
            {
                "program": program,
                "progress": progress,
                "trips_remaining": trips_remaining,
                "potential_bonus": potential_bonus,
            }
        )

    return summary


async def mark_bonuses_paid(
    db: AsyncSession,
    driver_id: int,
    program_ids: list[int],
) -> list[DriverIncentiveProgress]:
    """Mark completed bonuses as paid. Called during payout processing."""
    result = await db.execute(
        select(DriverIncentiveProgress).where(
            DriverIncentiveProgress.driver_id == driver_id,
            DriverIncentiveProgress.program_id.in_(program_ids),
            DriverIncentiveProgress.status == ProgressStatus.COMPLETED.value,
        )
    )
    records = list(result.scalars().all())
    now = datetime.now(timezone.utc)
    for record in records:
        record.status = ProgressStatus.PAID.value
        record.paid_at = now

    await db.flush()
    logger.info("Marked %d bonus records as paid for driver %d", len(records), driver_id)
    return records
