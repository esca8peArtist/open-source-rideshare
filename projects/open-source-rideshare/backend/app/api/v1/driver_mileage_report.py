"""Driver mileage report endpoint.

GET /driver/me/mileage-report?year=2026
GET /driver/me/mileage-report?year=2026&month=4

Returns total kilometres and miles driven for completed rides in the
requested period, together with an IRS standard mileage deduction estimate.
Drivers can use this for self-employed tax filings (Schedule C / Form 1040).
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_driver
from app.models.user import User
from app.schemas.driver_mileage_report import DriverMileageReport
from app.services.driver_mileage_report import get_driver_mileage_report

router = APIRouter(prefix="/driver", tags=["driver"])


@router.get("/me/mileage-report", response_model=DriverMileageReport)
async def get_mileage_report(
    year: int = Query(..., ge=2000, le=2100, description="Calendar year"),
    month: int | None = Query(None, ge=1, le=12, description="Month (1-12). Omit for full-year view."),
    driver: User = Depends(require_driver),
    db: AsyncSession = Depends(get_db),
) -> DriverMileageReport:
    """Return mileage driven and IRS deduction estimate for the given period.

    When *month* is omitted the response covers the full calendar year and
    includes a per-month breakdown.  When *month* is provided only that month
    is returned and monthly_breakdown is empty.

    Only completed rides with a recorded distance are included.  The IRS
    standard mileage rate shown is an estimate — drivers should verify the
    current rate with a tax professional.
    """
    return await get_driver_mileage_report(db, driver.id, year, month)
