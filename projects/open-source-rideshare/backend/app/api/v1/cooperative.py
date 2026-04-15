"""Cooperative transparency and member equity API.

Public (no auth):
  GET  /platform/cooperative/stats                    — live all-time platform aggregate
  GET  /platform/cooperative/reports                  — list all quarterly reports
  GET  /platform/cooperative/reports/{year}/{quarter} — get one quarterly report

Driver (auth required):
  GET  /drivers/me/cooperative-equity                 — driver's own equity profile

Admin:
  POST /admin/cooperative/reports/generate            — generate or refresh a quarterly report
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_admin, require_driver
from app.db.database import get_db
from app.models.driver import DriverProfile
from app.models.user import User
from app.schemas.cooperative import (
    CooperativeReportListResponse,
    CooperativeReportResponse,
    DriverEquityStats,
    GenerateReportRequest,
    PlatformPublicStats,
)
from app.services.cooperative import (
    generate_quarterly_report,
    get_driver_equity_stats,
    get_platform_public_stats,
    get_quarterly_report,
    list_quarterly_reports,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["cooperative"])


# ---------------------------------------------------------------------------
# Public endpoints (no authentication)
# ---------------------------------------------------------------------------

@router.get("/platform/cooperative/stats", response_model=PlatformPublicStats)
async def platform_cooperative_stats(db: AsyncSession = Depends(get_db)):
    """Return live, all-time cooperative performance stats.

    No authentication required — transparency is the point.
    Shows exactly how money flows through the platform: what drivers earn vs.
    what the platform retains.
    """
    stats = await get_platform_public_stats(db)
    return PlatformPublicStats(**stats)


@router.get(
    "/platform/cooperative/reports",
    response_model=CooperativeReportListResponse,
)
async def list_cooperative_reports(db: AsyncSession = Depends(get_db)):
    """List all published quarterly transparency reports (newest first)."""
    reports = await list_quarterly_reports(db)
    return CooperativeReportListResponse(
        reports=[CooperativeReportResponse.model_validate(r) for r in reports],
        total=len(reports),
    )


@router.get(
    "/platform/cooperative/reports/{year}/{quarter}",
    response_model=CooperativeReportResponse,
)
async def get_cooperative_report(
    year: int,
    quarter: int,
    db: AsyncSession = Depends(get_db),
):
    """Fetch a specific quarterly transparency report."""
    if not 1 <= quarter <= 4:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Quarter must be between 1 and 4",
        )
    report = await get_quarterly_report(db, year, quarter)
    if report is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No report found for Q{quarter} {year}",
        )
    return CooperativeReportResponse.model_validate(report)


# ---------------------------------------------------------------------------
# Driver endpoint (auth required)
# ---------------------------------------------------------------------------

@router.get("/drivers/me/cooperative-equity", response_model=DriverEquityStats)
async def my_cooperative_equity(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_driver),
):
    """Return the authenticated driver's cooperative equity profile.

    Shows the driver's contribution to the platform (trips, earnings generated,
    tenure) and their estimated equity share — their portion of the cooperative.
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

    stats = await get_driver_equity_stats(db, driver.id)
    if stats is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Driver profile not found",
        )
    return DriverEquityStats(**stats)


# ---------------------------------------------------------------------------
# Admin endpoint
# ---------------------------------------------------------------------------

@router.post(
    "/admin/cooperative/reports/generate",
    response_model=CooperativeReportResponse,
    status_code=status.HTTP_200_OK,
)
async def admin_generate_cooperative_report(
    req: GenerateReportRequest,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """Generate or refresh a quarterly transparency report.

    Idempotent — safe to call multiple times for the same period (refreshes
    the numbers). Typically run at the end of each quarter.
    """
    if not 1 <= req.quarter <= 4:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Quarter must be between 1 and 4",
        )
    try:
        report = await generate_quarterly_report(
            db, year=req.year, quarter=req.quarter, notes=req.notes
        )
        await db.commit()
        await db.refresh(report)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    logger.info("Cooperative report generated: Q%d %d", req.quarter, req.year)
    return CooperativeReportResponse.model_validate(report)
