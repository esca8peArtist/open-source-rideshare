"""Corporate Commuter Benefits endpoints.

Companies configure a monthly ride subsidy program that gives employees a
monthly credit for qualifying commute rides.  This is distinct from prepaid
credit pools and spend limits.

Member endpoints (employee self-service):
  GET  /api/v1/corporate/{account_id}/commuter-benefits/my-allotment?year=&month=
      — employee's allotment for the given month
  GET  /api/v1/corporate/{account_id}/commuter-benefits/my-allotment/history
      — employee's allotments across all months

Admin endpoints:
  POST   /api/v1/corporate/{account_id}/commuter-benefits/program
      — create program (409 if already exists)
  GET    /api/v1/corporate/{account_id}/commuter-benefits/program
      — get program details
  PATCH  /api/v1/corporate/{account_id}/commuter-benefits/program
      — update program
  POST   /api/v1/corporate/{account_id}/commuter-benefits/program/deactivate
      — deactivate program
  GET    /api/v1/corporate/{account_id}/commuter-benefits/allotments?year=&month=&member_id=
      — list allotments
  GET    /api/v1/corporate/{account_id}/commuter-benefits/program/stats?year=&month=
      — utilisation stats

Platform-admin endpoints:
  GET  /api/v1/platform-admin/corporate-commuter-benefits/
      — list all programs across accounts (paginated)
  GET  /api/v1/platform-admin/corporate-commuter-benefits/{account_id}
      — get program for a specific account
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.models.corporate import BusinessAccountMember
from app.models.user import User
from app.schemas.corporate_commuter_benefit import (
    CommuterAllotmentResponse,
    CommuterProgramCreate,
    CommuterProgramResponse,
    CommuterProgramUpdate,
    CommuterStatsResponse,
)
from app.services.corporate_commuter_benefit import (
    create_program,
    deactivate_program,
    get_member_allotment,
    get_or_create_allotment,
    get_program,
    get_program_stats,
    list_allotments,
    record_commuter_ride_usage,
    update_program,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["corporate-commuter-benefits"])


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _get_member_id_for_user(db: AsyncSession, user_id: int, account_id: int) -> int:
    """Return the BusinessAccountMember.id for *user_id* within *account_id*.

    Raises HTTP 404 if the user is not an active member of the account.
    """
    result = await db.execute(
        select(BusinessAccountMember).where(
            BusinessAccountMember.user_id == user_id,
            BusinessAccountMember.account_id == account_id,
            BusinessAccountMember.is_active.is_(True),
        )
    )
    member = result.scalar_one_or_none()
    if member is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="You are not an active member of this corporate account.",
        )
    return member.id


def _program_response(program) -> CommuterProgramResponse:
    return CommuterProgramResponse.model_validate(program)


def _allotment_response(allotment) -> CommuterAllotmentResponse:
    return CommuterAllotmentResponse.model_validate(allotment)


# ---------------------------------------------------------------------------
# Member: get my allotment for a specific month
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/commuter-benefits/my-allotment",
    response_model=CommuterAllotmentResponse,
    summary="Member: get my commuter benefit allotment for a given month",
)
async def get_my_allotment(
    account_id: int,
    year: int = Query(..., ge=2000, le=2100, description="Period year."),
    month: int = Query(..., ge=1, le=12, description="Period month (1–12)."),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the caller's commuter benefit allotment for the given month.

    Returns HTTP 404 if the account has no commuter program or the employee
    has no allotment for the requested period.
    """
    member_id = await _get_member_id_for_user(db, user.id, account_id)
    allotment = await get_member_allotment(db, account_id=account_id, member_id=member_id, year=year, month=month)
    if allotment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No commuter benefit allotment found for this period.",
        )
    return _allotment_response(allotment)


# ---------------------------------------------------------------------------
# Member: get my allotment history
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/commuter-benefits/my-allotment/history",
    response_model=list[CommuterAllotmentResponse],
    summary="Member: get my commuter benefit allotment history",
)
async def get_my_allotment_history(
    account_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all historical commuter benefit allotments for the calling employee.

    Returns an empty list if no allotments exist.
    """
    member_id = await _get_member_id_for_user(db, user.id, account_id)
    program = await get_program(db, account_id=account_id)
    if program is None:
        return []
    allotments = await list_allotments(db, program_id=program.id, member_id=member_id)
    return [_allotment_response(a) for a in allotments]


# ---------------------------------------------------------------------------
# Admin: create program
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/{account_id}/commuter-benefits/program",
    response_model=CommuterProgramResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Admin: create a commuter benefit program for the account",
)
async def create_commuter_program(
    account_id: int,
    data: CommuterProgramCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new commuter benefit program.

    Returns HTTP 409 if a program already exists for this account.
    Requires ADMIN role within the account.
    """
    program = await create_program(db, account_id=account_id, data=data, created_by_id=user.id)
    await db.commit()
    return _program_response(program)


# ---------------------------------------------------------------------------
# Admin / Member: get program details
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/commuter-benefits/program",
    response_model=CommuterProgramResponse,
    summary="Get commuter benefit program details for the account",
)
async def get_commuter_program(
    account_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the commuter benefit program for the account.

    Returns HTTP 404 if no program exists.
    """
    program = await get_program(db, account_id=account_id)
    if program is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Commuter benefit program not found for this account.",
        )
    return _program_response(program)


# ---------------------------------------------------------------------------
# Admin: update program
# ---------------------------------------------------------------------------


@router.patch(
    "/corporate/{account_id}/commuter-benefits/program",
    response_model=CommuterProgramResponse,
    summary="Admin: update the commuter benefit program",
)
async def update_commuter_program(
    account_id: int,
    data: CommuterProgramUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update fields on the existing commuter benefit program.

    Returns HTTP 404 if no program exists.
    Requires ADMIN role within the account.
    """
    program = await update_program(db, account_id=account_id, data=data)
    await db.commit()
    return _program_response(program)


# ---------------------------------------------------------------------------
# Admin: deactivate program
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/{account_id}/commuter-benefits/program/deactivate",
    response_model=CommuterProgramResponse,
    summary="Admin: deactivate the commuter benefit program",
)
async def deactivate_commuter_program(
    account_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Soft-delete the program by marking it inactive.

    Allotment history is preserved.
    Requires ADMIN role within the account.
    """
    program = await deactivate_program(db, account_id=account_id)
    await db.commit()
    return _program_response(program)


# ---------------------------------------------------------------------------
# Admin: list allotments
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/commuter-benefits/allotments",
    response_model=list[CommuterAllotmentResponse],
    summary="Admin: list commuter benefit allotments",
)
async def list_commuter_allotments(
    account_id: int,
    year: Optional[int] = Query(None, ge=2000, le=2100),
    month: Optional[int] = Query(None, ge=1, le=12),
    member_id: Optional[int] = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List commuter benefit allotments for the account's program.

    Optionally filter by year, month, and/or member_id.
    Returns HTTP 404 if no program exists.
    Requires ADMIN role within the account.
    """
    program = await get_program(db, account_id=account_id)
    if program is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Commuter benefit program not found for this account.",
        )
    allotments = await list_allotments(
        db, program_id=program.id, year=year, month=month, member_id=member_id
    )
    return [_allotment_response(a) for a in allotments]


# ---------------------------------------------------------------------------
# Admin: program stats
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{account_id}/commuter-benefits/program/stats",
    response_model=CommuterStatsResponse,
    summary="Admin: commuter benefit utilisation statistics",
)
async def get_commuter_program_stats(
    account_id: int,
    year: int = Query(..., ge=2000, le=2100),
    month: int = Query(..., ge=1, le=12),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return aggregate utilisation statistics for the program in a given period.

    Returns HTTP 404 if no program exists.
    Requires ADMIN role within the account.
    """
    return await get_program_stats(db, account_id=account_id, year=year, month=month)


# ---------------------------------------------------------------------------
# Platform-admin: list all programs
# ---------------------------------------------------------------------------


@router.get(
    "/platform-admin/corporate-commuter-benefits/",
    response_model=list[CommuterProgramResponse],
    summary="Platform admin: list all commuter benefit programs",
)
async def platform_admin_list_programs(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return all commuter benefit programs across all corporate accounts.

    Requires platform-level admin role.
    """
    from app.models.corporate_commuter_benefit import CorporateCommuterProgram as CCP

    result = await db.execute(
        select(CCP)
        .order_by(CCP.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    programs = list(result.scalars().all())
    return [_program_response(p) for p in programs]


# ---------------------------------------------------------------------------
# Platform-admin: get program for specific account
# ---------------------------------------------------------------------------


@router.get(
    "/platform-admin/corporate-commuter-benefits/{account_id}",
    response_model=CommuterProgramResponse,
    summary="Platform admin: get commuter benefit program for a specific account",
)
async def platform_admin_get_program(
    account_id: int,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return the commuter benefit program for a specific account.

    Returns HTTP 404 if no program exists.
    Requires platform-level admin role.
    """
    program = await get_program(db, account_id=account_id)
    if program is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Commuter benefit program not found for this account.",
        )
    return _program_response(program)
