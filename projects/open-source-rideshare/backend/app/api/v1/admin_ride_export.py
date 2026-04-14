"""Admin ride export API.

Provides a CSV download of ride data for compliance reporting, auditing,
and operational analysis.

Endpoint:
  GET /admin/rides/export — download rides as CSV, filterable by date range,
                            status, and driver
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin
from app.db.database import get_db
from app.models.ride import RideStatus
from app.models.user import User
from app.services.admin_ride_export import export_rides_csv

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/admin/rides",
    tags=["admin-ride-export"],
)

_VALID_FORMATS = {"csv"}
_VALID_STATUSES = {s.value for s in RideStatus}


def _parse_optional_date(value: str | None, param_name: str) -> date | None:
    """Parse an optional ISO date string; raise 422 on bad format."""
    if value is None:
        return None
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
    "/export",
    summary="Export ride data as CSV for compliance and auditing",
    description=(
        "Returns a CSV file of ride records, optionally filtered by date range, "
        "ride status, or driver. Columns include ride metadata, participant names, "
        "fare, payment status, and vehicle type. "
        "Requires admin authentication."
    ),
)
async def export_rides(
    start_date: str | None = Query(
        None,
        description=(
            "Inclusive start date (YYYY-MM-DD). "
            "Filters rides where created_at >= start_date."
        ),
    ),
    end_date: str | None = Query(
        None,
        description=(
            "Inclusive end date (YYYY-MM-DD). "
            "Filters rides where created_at <= end_date."
        ),
    ),
    status: str | None = Query(
        None,
        description=(
            "Filter by ride status. Valid values: "
            + ", ".join(sorted(_VALID_STATUSES))
        ),
    ),
    driver_id: int | None = Query(
        None,
        description="Filter rides by a specific driver (user ID).",
    ),
    format: str = Query(
        "csv",
        description="Export format. Only 'csv' is supported.",
    ),
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Download ride data as a CSV file.

    All query parameters are optional — omitting them returns all rides.
    An empty result set returns a CSV with the header row only (not 404).
    """
    start = _parse_optional_date(start_date, "start_date")
    end = _parse_optional_date(end_date, "end_date")

    if start is not None and end is not None and end < start:
        raise HTTPException(
            status_code=422,
            detail="end_date must be on or after start_date",
        )

    if status is not None and status not in _VALID_STATUSES:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Invalid status '{status}'. "
                f"Must be one of: {', '.join(sorted(_VALID_STATUSES))}"
            ),
        )

    if format not in _VALID_FORMATS:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported format '{format}'. Only 'csv' is supported.",
        )

    csv_content = await export_rides_csv(
        db,
        start_date=start,
        end_date=end,
        status=status,
        driver_id=driver_id,
    )

    timestamp = datetime.now(tz=timezone.utc).strftime("%Y%m%d")
    filename = f"rides_export_{timestamp}.csv"

    return StreamingResponse(
        iter([csv_content]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
