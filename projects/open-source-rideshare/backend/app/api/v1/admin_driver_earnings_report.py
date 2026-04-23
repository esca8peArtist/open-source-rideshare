"""Admin driver earnings report API.

GET /admin/drivers/earnings-report
  Returns per-driver earnings aggregated over a date range, paginated and
  sortable.  Unlike the top-earners endpoint (which shows only the top N
  drivers), this report includes ALL drivers who had at least one completed
  ride in the period.

  Requires admin authentication.
"""

from __future__ import annotations

import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin
from app.db.database import get_db
from app.models.user import User
from app.schemas.admin_driver_earnings_report import AdminDriverEarningsReport
from app.services.admin_driver_earnings_report import get_driver_earnings_report
from app.services.pricing import get_pricing_params

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/admin/drivers",
    tags=["admin-driver-earnings"],
)

_VALID_SORT_FIELDS = {"net_earnings", "gross_earnings", "rides_completed", "tips"}
_VALID_SORT_DIRS = {"asc", "desc"}


def _parse_date(value: str | None, param_name: str) -> date:
    """Parse an ISO date string; raise 422 on bad format or missing value."""
    if value is None:
        raise HTTPException(
            status_code=422,
            detail=f"Query parameter '{param_name}' is required (ISO date: YYYY-MM-DD)",
        )
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Invalid date format for '{param_name}'. "
                f"Expected YYYY-MM-DD, got: {value!r}"
            ),
        )


@router.get(
    "/earnings-report",
    response_model=AdminDriverEarningsReport,
    summary="Admin driver earnings aggregation report",
    description=(
        "Returns per-driver earnings aggregated over a date range. "
        "Includes all drivers with at least one completed ride in the period — "
        "unlike the top-earners endpoint, no driver is excluded. "
        "Results are paginated and sortable by net_earnings, gross_earnings, "
        "rides_completed, or tips. "
        "Requires admin authentication."
    ),
)
async def driver_earnings_report(
    start_date: str = Query(..., description="Inclusive start date (YYYY-MM-DD)"),
    end_date: str = Query(..., description="Inclusive end date (YYYY-MM-DD)"),
    sort_by: str = Query(
        "net_earnings",
        description="Sort field: net_earnings | gross_earnings | rides_completed | tips",
    ),
    sort_dir: str = Query("desc", description="Sort direction: asc | desc"),
    page: int = Query(1, ge=1, description="Page number (1-based)"),
    page_size: int = Query(25, ge=1, le=100, description="Results per page (max 100)"),
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminDriverEarningsReport:
    """Paginated admin report of per-driver earnings for a date range."""
    start = _parse_date(start_date, "start_date")
    end = _parse_date(end_date, "end_date")

    if end < start:
        raise HTTPException(
            status_code=422,
            detail="end_date must be on or after start_date",
        )

    if sort_by not in _VALID_SORT_FIELDS:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Invalid sort_by '{sort_by}'. "
                f"Must be one of: {', '.join(sorted(_VALID_SORT_FIELDS))}"
            ),
        )

    if sort_dir not in _VALID_SORT_DIRS:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid sort_dir '{sort_dir}'. Must be 'asc' or 'desc'.",
        )

    params = get_pricing_params()
    return await get_driver_earnings_report(
        db=db,
        start_date=start,
        end_date=end,
        sort_by=sort_by,  # type: ignore[arg-type]
        sort_dir=sort_dir,  # type: ignore[arg-type]
        page=page,
        page_size=page_size,
        platform_fee_pct=params["platform_fee_percent"],
    )
