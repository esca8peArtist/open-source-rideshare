"""Service functions for Corporate Commuter Benefits.

Companies configure a monthly ride subsidy program that gives employees a
per-employee monthly credit for qualifying commute rides.

Public API
----------
create_program             — create the program; 409 if one already exists for account
get_program                — fetch the program for an account; None if absent
update_program             — update program fields; 404 if not found
deactivate_program         — sets is_active=False; 404 if not found
get_or_create_allotment    — get existing or create new monthly allotment;
                             applies rollover from prior month when enabled
list_allotments            — list allotments for a program, with optional filters
get_member_allotment       — convenience: look up program for account then allotment
record_commuter_ride_usage — increment used_usd; 409 if balance exceeded
get_program_stats          — aggregate utilisation statistics for a period
"""

from __future__ import annotations

from decimal import Decimal
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.corporate_commuter_benefit import (
    CorporateCommuterAllotment,
    CorporateCommuterProgram,
)
from app.schemas.corporate_commuter_benefit import (
    CommuterProgramCreate,
    CommuterProgramUpdate,
    CommuterStatsResponse,
)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


async def _get_program_by_account(
    db: AsyncSession, account_id: int
) -> Optional[CorporateCommuterProgram]:
    """Return the program row for *account_id*, or None."""
    result = await db.execute(
        select(CorporateCommuterProgram).where(
            CorporateCommuterProgram.account_id == account_id,
        )
    )
    return result.scalar_one_or_none()


async def _require_program(
    db: AsyncSession, account_id: int
) -> CorporateCommuterProgram:
    """Return the program for *account_id* or raise HTTP 404."""
    program = await _get_program_by_account(db, account_id)
    if program is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Commuter benefit program not found for this account.",
        )
    return program


async def _get_allotment(
    db: AsyncSession,
    program_id: int,
    member_id: int,
    year: int,
    month: int,
) -> Optional[CorporateCommuterAllotment]:
    """Return the allotment row or None."""
    result = await db.execute(
        select(CorporateCommuterAllotment).where(
            CorporateCommuterAllotment.program_id == program_id,
            CorporateCommuterAllotment.member_id == member_id,
            CorporateCommuterAllotment.period_year == year,
            CorporateCommuterAllotment.period_month == month,
        )
    )
    return result.scalar_one_or_none()


def _prev_month(year: int, month: int) -> tuple[int, int]:
    """Return (year, month) for the calendar month prior to the given one."""
    if month == 1:
        return year - 1, 12
    return year, month - 1


# ---------------------------------------------------------------------------
# Public service API
# ---------------------------------------------------------------------------


async def create_program(
    db: AsyncSession,
    account_id: int,
    data: CommuterProgramCreate,
    created_by_id: int,
) -> CorporateCommuterProgram:
    """Create a new commuter benefit program for *account_id*.

    Raises HTTP 409 if a program already exists for the account (one program
    per account is enforced by a unique constraint on account_id).
    """
    existing = await _get_program_by_account(db, account_id)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A commuter benefit program already exists for this account.",
        )

    program = CorporateCommuterProgram(
        account_id=account_id,
        name=data.name,
        description=data.description,
        monthly_allowance_usd=data.monthly_allowance_usd,
        rollover_enabled=data.rollover_enabled,
        max_rollover_usd=data.max_rollover_usd,
        eligible_trip_purpose_ids=data.eligible_trip_purpose_ids,
        eligible_group_ids=data.eligible_group_ids,
        is_active=True,
        valid_from=data.valid_from,
        valid_until=data.valid_until,
        created_by_id=created_by_id,
    )
    db.add(program)
    await db.flush()
    return program


async def get_program(
    db: AsyncSession, account_id: int
) -> Optional[CorporateCommuterProgram]:
    """Return the commuter benefit program for *account_id*, or None."""
    return await _get_program_by_account(db, account_id)


async def update_program(
    db: AsyncSession,
    account_id: int,
    data: CommuterProgramUpdate,
) -> CorporateCommuterProgram:
    """Update fields on an existing commuter benefit program.

    Raises HTTP 404 if no program exists for the account.
    """
    program = await _require_program(db, account_id)

    if data.name is not None:
        program.name = data.name
    if data.description is not None:
        program.description = data.description
    if data.monthly_allowance_usd is not None:
        program.monthly_allowance_usd = data.monthly_allowance_usd
    if data.rollover_enabled is not None:
        program.rollover_enabled = data.rollover_enabled
    if data.max_rollover_usd is not None:
        program.max_rollover_usd = data.max_rollover_usd
    if data.eligible_trip_purpose_ids is not None:
        program.eligible_trip_purpose_ids = data.eligible_trip_purpose_ids
    if data.eligible_group_ids is not None:
        program.eligible_group_ids = data.eligible_group_ids
    if data.is_active is not None:
        program.is_active = data.is_active
    if data.valid_from is not None:
        program.valid_from = data.valid_from
    if data.valid_until is not None:
        program.valid_until = data.valid_until

    await db.flush()
    return program


async def deactivate_program(
    db: AsyncSession, account_id: int
) -> CorporateCommuterProgram:
    """Soft-delete the program by setting is_active=False.

    Raises HTTP 404 if no program exists for the account.
    """
    program = await _require_program(db, account_id)
    program.is_active = False
    await db.flush()
    return program


async def get_or_create_allotment(
    db: AsyncSession,
    program_id: int,
    member_id: int,
    year: int,
    month: int,
) -> CorporateCommuterAllotment:
    """Get the existing monthly allotment or create a new one.

    When creating:
    - ``allotted_usd`` is copied from the program's current
      ``monthly_allowance_usd``.
    - When ``program.rollover_enabled`` is True, the remaining balance from the
      prior month's allotment is carried forward (capped by
      ``program.max_rollover_usd`` when set).

    Does not raise 404 for a missing allotment — it creates it instead.
    Raises HTTP 404 if the program does not exist.
    """
    # Load the program.
    prog_result = await db.execute(
        select(CorporateCommuterProgram).where(
            CorporateCommuterProgram.id == program_id
        )
    )
    program = prog_result.scalar_one_or_none()
    if program is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Commuter benefit program not found.",
        )

    existing = await _get_allotment(db, program_id, member_id, year, month)
    if existing is not None:
        return existing

    # Calculate rollover from previous month.
    rolled_over = Decimal("0")
    if program.rollover_enabled:
        prev_year, prev_month = _prev_month(year, month)
        prior = await _get_allotment(db, program_id, member_id, prev_year, prev_month)
        if prior is not None:
            prior_allotted = Decimal(str(prior.allotted_usd))
            prior_rolled = Decimal(str(prior.rolled_over_usd))
            prior_used = Decimal(str(prior.used_usd))
            remaining = prior_allotted + prior_rolled - prior_used
            if remaining > 0:
                rolled_over = remaining
                if program.max_rollover_usd is not None:
                    cap = Decimal(str(program.max_rollover_usd))
                    rolled_over = min(rolled_over, cap)

    allotment = CorporateCommuterAllotment(
        program_id=program_id,
        member_id=member_id,
        period_year=year,
        period_month=month,
        allotted_usd=program.monthly_allowance_usd,
        used_usd=Decimal("0"),
        rolled_over_usd=rolled_over,
    )
    db.add(allotment)
    await db.flush()
    return allotment


async def list_allotments(
    db: AsyncSession,
    program_id: int,
    year: Optional[int] = None,
    month: Optional[int] = None,
    member_id: Optional[int] = None,
) -> list[CorporateCommuterAllotment]:
    """Return allotments for *program_id*, optionally filtered by period and/or member."""
    query = select(CorporateCommuterAllotment).where(
        CorporateCommuterAllotment.program_id == program_id
    )
    if year is not None:
        query = query.where(CorporateCommuterAllotment.period_year == year)
    if month is not None:
        query = query.where(CorporateCommuterAllotment.period_month == month)
    if member_id is not None:
        query = query.where(CorporateCommuterAllotment.member_id == member_id)

    query = query.order_by(
        CorporateCommuterAllotment.period_year.desc(),
        CorporateCommuterAllotment.period_month.desc(),
    )
    result = await db.execute(query)
    return list(result.scalars().all())


async def get_member_allotment(
    db: AsyncSession,
    account_id: int,
    member_id: int,
    year: int,
    month: int,
) -> Optional[CorporateCommuterAllotment]:
    """Convenience: look up the program for *account_id* then return the allotment.

    Returns None if the account has no program or the allotment does not exist.
    """
    program = await _get_program_by_account(db, account_id)
    if program is None:
        return None
    return await _get_allotment(db, program.id, member_id, year, month)


async def record_commuter_ride_usage(
    db: AsyncSession,
    program_id: int,
    member_id: int,
    year: int,
    month: int,
    amount_usd: float,
) -> CorporateCommuterAllotment:
    """Increment ``used_usd`` on an allotment by *amount_usd*.

    Raises HTTP 409 if the charge would exceed the available balance
    (``allotted_usd + rolled_over_usd``).
    """
    allotment = await _get_allotment(db, program_id, member_id, year, month)
    if allotment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Commuter allotment not found.",
        )

    available = (
        Decimal(str(allotment.allotted_usd))
        + Decimal(str(allotment.rolled_over_usd))
        - Decimal(str(allotment.used_usd))
    )
    charge = Decimal(str(amount_usd))
    if charge > available:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Insufficient commuter benefit balance.",
        )

    allotment.used_usd = Decimal(str(allotment.used_usd)) + charge
    await db.flush()
    return allotment


async def get_program_stats(
    db: AsyncSession,
    account_id: int,
    year: int,
    month: int,
) -> CommuterStatsResponse:
    """Return aggregate utilisation statistics for a program in a given period.

    Returns counts and sums across all allotments for (year, month).
    Raises HTTP 404 if no program exists for the account.
    """
    program = await _require_program(db, account_id)

    result = await db.execute(
        select(
            func.count(CorporateCommuterAllotment.id),
            func.coalesce(func.sum(CorporateCommuterAllotment.allotted_usd), 0),
            func.coalesce(func.sum(CorporateCommuterAllotment.used_usd), 0),
        ).where(
            CorporateCommuterAllotment.program_id == program.id,
            CorporateCommuterAllotment.period_year == year,
            CorporateCommuterAllotment.period_month == month,
        )
    )
    row = result.one()
    total_members = int(row[0])
    total_allotted = float(row[1])
    total_used = float(row[2])
    total_remaining = total_allotted - total_used
    utilization_pct = (
        round((total_used / total_allotted) * 100, 2) if total_allotted > 0 else 0.0
    )

    return CommuterStatsResponse(
        total_members_enrolled=total_members,
        total_allotted=total_allotted,
        total_used=total_used,
        total_remaining=total_remaining,
        utilization_pct=utilization_pct,
    )
