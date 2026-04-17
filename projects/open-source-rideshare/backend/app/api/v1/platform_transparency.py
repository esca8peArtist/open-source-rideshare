"""Platform transparency report API endpoint.

Endpoint:
  GET /platform/transparency-report

Query parameters:
  period  (str, optional) — 'last_7_days' | 'last_30_days' | 'all_time'
                            Default: 'last_30_days'

Authorization: None — this is a fully public, unauthenticated endpoint.

This report is something Uber and Lyft would never voluntarily publish.
OpenRide does so as a matter of cooperative principle, allowing any member
of the public to see the platform's economics in aggregate.

Distinct from:
  GET /pricing/fare-preview            — single pre-booking estimate
  GET /rides/{id}/fare-breakdown       — per-ride breakdown (authenticated)
  GET /riders/me/savings-summary       — rider's personal savings (authenticated)
  GET /drivers/me/earnings-comparison  — driver's personal earnings (authenticated)
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.schemas.platform_transparency import PlatformTransparencyReport
from app.services.platform_transparency import ReportPeriod, get_platform_transparency_report

router = APIRouter(tags=["platform-transparency"])


@router.get(
    "/platform/transparency-report",
    response_model=PlatformTransparencyReport,
    status_code=status.HTTP_200_OK,
    summary="Get public platform transparency report",
    description=(
        "Returns an aggregate transparency report covering platform economics, "
        "driver earnings, rider savings, and service quality for the requested "
        "time period.\n\n"
        "**This endpoint requires no authentication.** It is intentionally public "
        "so that drivers, riders, journalists, researchers, and regulators can "
        "independently verify OpenRide's cooperative model.\n\n"
        "**period** controls the reporting window:\n"
        "- `last_7_days` — the trailing 7 days\n"
        "- `last_30_days` — the trailing 30 days (default)\n"
        "- `all_time` — every completed ride since launch\n\n"
        "When no completed rides exist (e.g. a fresh installation), all numeric "
        "fields are zero and `data_available` is `false` — the endpoint does not "
        "error on an empty database.\n\n"
        "Competitor fare and earnings estimates use 2025 US national average "
        "commission rates for Uber (~26.5%) and Lyft (~22.5%). See "
        "`methodology_note` in the response for full disclosure."
    ),
)
async def get_transparency_report(
    period: ReportPeriod = Query(
        default=ReportPeriod.LAST_30_DAYS,
        description=(
            "Reporting window: 'last_7_days', 'last_30_days' (default), or 'all_time'."
        ),
    ),
    db: AsyncSession = Depends(get_db),
) -> PlatformTransparencyReport:
    return await get_platform_transparency_report(db=db, period=period)
