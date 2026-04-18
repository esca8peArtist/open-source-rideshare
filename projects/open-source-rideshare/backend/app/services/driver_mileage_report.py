"""Service layer for the driver mileage report.

Returns total distance driven for completed rides in a given year (or a
specific month within that year), together with an IRS standard mileage
deduction estimate.  Only rides with a non-null distance_km are counted.

IRS standard mileage rate used in deduction estimates.  Update annually.
2025 rate: $0.70/mile.  Drivers should verify the current rate with a tax
professional.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ride import Ride, RideStatus
from app.schemas.driver_mileage_report import DriverMileageReport, MonthlyMileageBreakdown

KM_TO_MILES: float = 0.621371
IRS_MILEAGE_RATE_PER_MILE: float = 0.70


def _utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


async def get_driver_mileage_report(
    db: AsyncSession,
    driver_id: int,
    year: int,
    month: int | None = None,
) -> DriverMileageReport:
    """Build the mileage report for the given driver, year, and optional month.

    When *month* is None the response covers the full calendar year and includes
    a per-month breakdown.  When *month* is provided only that month is covered
    and monthly_breakdown is an empty list.

    Only completed rides with a recorded distance_km are included.
    """
    now = _utc_now()

    if month is not None:
        period_start = datetime(year, month, 1, tzinfo=timezone.utc)
        next_month = month + 1 if month < 12 else 1
        next_year = year if month < 12 else year + 1
        period_end = datetime(next_year, next_month, 1, tzinfo=timezone.utc)
    else:
        period_start = datetime(year, 1, 1, tzinfo=timezone.utc)
        period_end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)

    result = await db.execute(
        select(Ride.distance_km, Ride.completed_at).where(
            Ride.driver_id == driver_id,
            Ride.status == RideStatus.COMPLETED,
            Ride.distance_km.is_not(None),
            Ride.completed_at >= period_start,
            Ride.completed_at < period_end,
        )
    )
    rows = result.all()

    # Collect km per calendar month for the full-year breakdown
    monthly_km: dict[int, list[float]] = {m: [] for m in range(1, 13)}
    for row in rows:
        completed = row.completed_at
        if completed is not None and completed.tzinfo is None:
            completed = completed.replace(tzinfo=timezone.utc)
        km = float(row.distance_km)
        if month is None and completed is not None:
            monthly_km[completed.month].append(km)

    total_km = round(sum(float(r.distance_km) for r in rows), 2)
    total_miles = round(total_km * KM_TO_MILES, 2)

    monthly_breakdown: list[MonthlyMileageBreakdown] = []
    if month is None:
        for m in range(1, 13):
            kms = monthly_km[m]
            m_km = round(sum(kms), 2)
            m_miles = round(m_km * KM_TO_MILES, 2)
            monthly_breakdown.append(
                MonthlyMileageBreakdown(
                    month=m,
                    rides_completed=len(kms),
                    total_km=m_km,
                    total_miles=m_miles,
                    irs_deduction_usd=round(m_miles * IRS_MILEAGE_RATE_PER_MILE, 2),
                )
            )

    return DriverMileageReport(
        driver_id=driver_id,
        year=year,
        month=month,
        as_of=now,
        rides_completed=len(rows),
        total_km=total_km,
        total_miles=total_miles,
        irs_rate_per_mile=IRS_MILEAGE_RATE_PER_MILE,
        irs_deduction_usd=round(total_miles * IRS_MILEAGE_RATE_PER_MILE, 2),
        monthly_breakdown=monthly_breakdown,
    )
