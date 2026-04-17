"""Background check expiry admin endpoints.

Admin endpoints:
  GET  /admin/background-checks/expiring
      Paginated list of CLEAR background checks expiring within `days_ahead` days
      (or already expired within the last day).

  POST /admin/background-checks/expiry-scan
      Trigger an expiry scan — records alert rows for checks needing notification
      and returns a count summary.  Safe to call on a schedule (idempotent per
      alert type per check).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin
from app.db.database import get_db
from app.models.user import User
from app.schemas.background_check_expiry import (
    BackgroundCheckExpiryScanResponse,
    ExpiringBackgroundChecksResponse,
)
from app.services.background_check_expiry import (
    get_expiring_background_checks,
    run_expiry_scan,
)

router = APIRouter(tags=["background-check-expiry"])


@router.get(
    "/admin/background-checks/expiring",
    response_model=ExpiringBackgroundChecksResponse,
    summary="List CLEAR background checks expiring soon (admin)",
)
async def admin_expiring_background_checks(
    days_ahead: int = Query(
        60,
        ge=1,
        le=365,
        description="Look-ahead window in days (max 365)",
    ),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ExpiringBackgroundChecksResponse:
    """Return CLEAR background checks that expire within *days_ahead* days or
    have expired within the last day.

    Results are sorted: already-expired first, then soonest expiry.
    """
    rows = await get_expiring_background_checks(db, days_ahead=days_ahead)
    paginated = rows[offset: offset + limit]
    return ExpiringBackgroundChecksResponse(items=paginated, total=len(rows))


@router.post(
    "/admin/background-checks/expiry-scan",
    response_model=BackgroundCheckExpiryScanResponse,
    summary="Trigger background check expiry alert scan (admin)",
)
async def admin_background_check_expiry_scan(
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> BackgroundCheckExpiryScanResponse:
    """Scan all CLEAR background checks and record alert notifications for any
    that have crossed a 60/30/7-day or expired threshold.

    Each alert type is recorded at most once per check (idempotent).  Returns
    the count of new alerts created, broken down by alert type.
    """
    summary = await run_expiry_scan(db)
    return BackgroundCheckExpiryScanResponse(
        alerts_sent=summary["alerts_sent"],
        by_type=summary["by_type"],
    )
