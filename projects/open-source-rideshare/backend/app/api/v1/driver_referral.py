"""API endpoints for the driver-to-driver referral program.

Driver endpoints:
  GET  /drivers/me/referral-code        — get (or auto-create) referral code + stats
  POST /drivers/me/referral-code        — explicitly generate referral code (idempotent)
  POST /drivers/me/referral/apply       — apply another driver's referral code
  GET  /drivers/me/referral/bonuses     — view earned bonuses

Admin endpoints:
  GET  /admin/driver-referrals          — list all referrals
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_admin, require_driver
from app.db.database import get_db
from app.models.driver import DriverProfile
from app.models.driver_referral import DriverReferral
from app.models.user import User
from app.schemas.driver_referral import (
    AdminDriverReferralEntry,
    AdminDriverReferralListResponse,
    DriverReferralApplyRequest,
    DriverReferralBonusEntry,
    DriverReferralCodeResponse,
)
from app.services.driver_referral import (
    apply_driver_referral_code,
    create_or_get_driver_referral_code,
    get_driver_referral_bonuses,
    get_driver_referral_stats,
)

router = APIRouter(tags=["driver-referral"])
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Driver endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/drivers/me/referral-code",
    response_model=DriverReferralCodeResponse,
)
async def get_driver_referral_code(
    current_user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    """Return the driver's referral code and stats. Generates one if none exists."""
    code = await create_or_get_driver_referral_code(current_user.id, db)
    await db.commit()
    stats = await get_driver_referral_stats(current_user.id, db)
    return DriverReferralCodeResponse(referral_code=code, **stats)


@router.post(
    "/drivers/me/referral-code",
    response_model=DriverReferralCodeResponse,
    status_code=status.HTTP_200_OK,
)
async def generate_driver_referral_code_endpoint(
    current_user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    """Idempotent — generate a referral code or return the existing one."""
    try:
        code = await create_or_get_driver_referral_code(current_user.id, db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    await db.commit()
    stats = await get_driver_referral_stats(current_user.id, db)
    return DriverReferralCodeResponse(referral_code=code, **stats)


@router.post(
    "/drivers/me/referral/apply",
    status_code=status.HTTP_200_OK,
)
async def apply_referral_code(
    req: DriverReferralApplyRequest,
    current_user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    """Apply another driver's referral code. Each driver may only apply one code."""
    try:
        referral = await apply_driver_referral_code(req.code, current_user.id, db)
    except ValueError as exc:
        detail = str(exc)
        if "already applied" in detail:
            raise HTTPException(status_code=409, detail=detail)
        raise HTTPException(status_code=400, detail=detail)
    await db.commit()
    return {
        "status": "applied",
        "referrer_driver_id": referral.referrer_driver_id,
        "milestone_rides": referral.milestone_rides,
        "bonus_amount": referral.bonus_amount,
    }


@router.get(
    "/drivers/me/referral/bonuses",
    response_model=list[DriverReferralBonusEntry],
)
async def get_my_driver_referral_bonuses(
    current_user: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
):
    """List all referral bonuses earned (pending, awarded, paid)."""
    bonuses = await get_driver_referral_bonuses(current_user.id, db)
    return [DriverReferralBonusEntry.model_validate(b) for b in bonuses]


# ---------------------------------------------------------------------------
# Admin endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/admin/driver-referrals",
    response_model=AdminDriverReferralListResponse,
    dependencies=[Depends(require_admin)],
)
async def admin_list_driver_referrals(
    referrer_id: int | None = Query(None),
    referee_id: int | None = Query(None),
    status_filter: str | None = Query(None, alias="status"),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """List all driver referrals. Filterable by referrer, referee, or status."""
    query = select(DriverReferral)
    if referrer_id is not None:
        query = query.where(DriverReferral.referrer_driver_id == referrer_id)
    if referee_id is not None:
        query = query.where(DriverReferral.referee_driver_id == referee_id)
    if status_filter is not None:
        query = query.where(DriverReferral.status == status_filter)

    count_result = await db.execute(
        select(func.count()).select_from(query.subquery())
    )
    total = count_result.scalar() or 0

    result = await db.execute(
        query.order_by(DriverReferral.created_at.desc()).offset(offset).limit(limit)
    )
    referrals = result.scalars().all()
    return AdminDriverReferralListResponse(
        total=total,
        referrals=[AdminDriverReferralEntry.model_validate(r) for r in referrals],
    )
