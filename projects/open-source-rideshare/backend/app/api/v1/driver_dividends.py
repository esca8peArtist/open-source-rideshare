"""Cooperative member dividend / profit-sharing API.

Admin endpoints:
  POST /admin/cooperative/dividends/calculate         — preview distribution (dry run)
  POST /admin/cooperative/dividends                   — declare distribution
  GET  /admin/cooperative/dividends                   — list all distributions
  GET  /admin/cooperative/dividends/{id}              — detail view + driver breakdown
  POST /admin/cooperative/dividends/{id}/approve      — approve for payout
  POST /admin/cooperative/dividends/{id}/distribute   — mark all shares as paid
  POST /admin/cooperative/dividends/{id}/cancel       — cancel pending/approved

Driver endpoints:
  GET  /drivers/me/dividends                          — own share history

Public endpoints:
  GET  /platform/cooperative/dividends                — list past distributions (no per-driver data)
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_admin, require_driver
from app.db.database import get_db
from app.models.driver import DriverProfile
from app.models.user import User
from app.schemas.driver_dividend import (
    ApproveDividendRequest,
    CancelDividendRequest,
    DividendCalculationPreview,
    DividendCalculationRequest,
    DividendDeclarationRequest,
    DividendDetailResponse,
    DividendListResponse,
    DividendResponse,
    DriverDividendHistoryResponse,
    PublicDividendItem,
    PublicDividendListResponse,
)
from app.services.driver_dividend import (
    admin_approve_dividend,
    admin_cancel_dividend,
    admin_distribute_dividend,
    build_dividend_detail,
    calculate_dividend,
    declare_dividend,
    get_dividend,
    get_driver_dividend_history,
    list_dividends,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["cooperative-dividends"])


# ---------------------------------------------------------------------------
# Public
# ---------------------------------------------------------------------------

@router.get("/platform/cooperative/dividends", response_model=PublicDividendListResponse)
async def public_list_dividends(db: AsyncSession = Depends(get_db)):
    """List all published dividend distributions (status only — no per-driver data).

    No authentication required — cooperative financial transparency.
    """
    dividends = await list_dividends(db)
    items = [
        PublicDividendItem(
            id=d.id,
            year=d.year,
            quarter=d.quarter,
            total_platform_surplus_usd=float(d.total_platform_surplus_usd),
            total_qualifying_rides=d.total_qualifying_rides,
            per_ride_payout_usd=float(d.per_ride_payout_usd),
            status=d.status,
            distributed_at=d.distributed_at,
        )
        for d in dividends
    ]
    return PublicDividendListResponse(dividends=items, total=len(items))


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

@router.get("/drivers/me/dividends", response_model=DriverDividendHistoryResponse)
async def my_dividend_history(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_driver),
):
    """Return the authenticated driver's dividend share history.

    Shows qualifying rides, share percentage, amount, and payment status for
    each distribution the driver participated in.
    """
    from sqlalchemy import select

    result = await db.execute(
        select(DriverProfile).where(DriverProfile.user_id == user.id)
    )
    driver = result.scalar_one_or_none()
    if driver is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Driver profile not found",
        )

    history = await get_driver_dividend_history(db, driver.id)
    return DriverDividendHistoryResponse(history=history, total=len(history))


# ---------------------------------------------------------------------------
# Admin — calculation preview (no DB write)
# ---------------------------------------------------------------------------

@router.post(
    "/admin/cooperative/dividends/calculate",
    response_model=DividendCalculationPreview,
)
async def admin_calculate_dividend(
    req: DividendCalculationRequest,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """Preview how a surplus would be distributed among driver-members.

    Dry run — does not create any records. Use this to review the breakdown
    before formally declaring a distribution.
    """
    try:
        preview = await calculate_dividend(
            db,
            year=req.year,
            quarter=req.quarter,
            surplus_usd=req.surplus_usd,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    return DividendCalculationPreview(**preview)


# ---------------------------------------------------------------------------
# Admin — declare
# ---------------------------------------------------------------------------

@router.post(
    "/admin/cooperative/dividends",
    response_model=DividendResponse,
    status_code=status.HTTP_201_CREATED,
)
async def admin_declare_dividend(
    req: DividendDeclarationRequest,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """Declare a cooperative dividend distribution.

    Creates a CooperativeDividend record (status=pending) and individual
    DriverDividendShare records for every driver who completed rides in the
    quarter. The distribution requires explicit admin approval before payout.
    """
    try:
        dividend = await declare_dividend(
            db,
            year=req.year,
            quarter=req.quarter,
            surplus_usd=req.surplus_usd,
            notes=req.notes,
        )
        await db.commit()
        await db.refresh(dividend)
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    logger.info("Dividend declared: Q%d %d — $%.2f", req.quarter, req.year, req.surplus_usd)
    return DividendResponse.model_validate(dividend)


# ---------------------------------------------------------------------------
# Admin — list / detail
# ---------------------------------------------------------------------------

@router.get("/admin/cooperative/dividends", response_model=DividendListResponse)
async def admin_list_dividends(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """List all cooperative dividend distributions, newest first."""
    dividends = await list_dividends(db)
    return DividendListResponse(
        dividends=[DividendResponse.model_validate(d) for d in dividends],
        total=len(dividends),
    )


@router.get(
    "/admin/cooperative/dividends/{dividend_id}",
    response_model=DividendDetailResponse,
)
async def admin_get_dividend(
    dividend_id: int,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """Fetch full dividend detail including per-driver share breakdown."""
    dividend = await get_dividend(db, dividend_id)
    if dividend is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Dividend {dividend_id} not found",
        )

    detail = await build_dividend_detail(db, dividend)
    return DividendDetailResponse(**detail)


# ---------------------------------------------------------------------------
# Admin — state transitions
# ---------------------------------------------------------------------------

@router.post(
    "/admin/cooperative/dividends/{dividend_id}/approve",
    response_model=DividendResponse,
)
async def admin_approve(
    dividend_id: int,
    req: ApproveDividendRequest,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Approve a pending dividend for distribution.

    Once approved, the distribution can be triggered with /distribute.
    """
    try:
        dividend = await admin_approve_dividend(db, dividend_id, admin.id)
        if dividend is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Dividend {dividend_id} not found",
            )
        if req.notes:
            dividend.notes = req.notes
        await db.commit()
        await db.refresh(dividend)
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    logger.info("Dividend %d approved by admin %d", dividend_id, admin.id)
    return DividendResponse.model_validate(dividend)


@router.post(
    "/admin/cooperative/dividends/{dividend_id}/distribute",
    response_model=DividendResponse,
)
async def admin_distribute(
    dividend_id: int,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """Mark a dividend as distributed (all driver shares set to paid).

    The dividend must be in approved status.
    """
    try:
        dividend = await admin_distribute_dividend(db, dividend_id)
        if dividend is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Dividend {dividend_id} not found",
            )
        await db.commit()
        await db.refresh(dividend)
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    logger.info("Dividend %d distributed", dividend_id)
    return DividendResponse.model_validate(dividend)


@router.post(
    "/admin/cooperative/dividends/{dividend_id}/cancel",
    response_model=DividendResponse,
)
async def admin_cancel(
    dividend_id: int,
    req: CancelDividendRequest,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """Cancel a pending or approved dividend.

    Cannot cancel an already-distributed dividend.
    """
    try:
        dividend = await admin_cancel_dividend(db, dividend_id, reason=req.reason)
        if dividend is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Dividend {dividend_id} not found",
            )
        await db.commit()
        await db.refresh(dividend)
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    logger.info("Dividend %d cancelled", dividend_id)
    return DividendResponse.model_validate(dividend)
