"""Demand-by-hour analytics service.

Aggregates ride request data by hour of day (UTC) to reveal when demand peaks.
Useful for:
  - Staffing / driver incentive scheduling
  - Surge zone activation windows
  - Rider-facing "busy hours" guidance

All functions are read-only; no data is mutated here.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import case, cast, extract, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.types import Numeric

from app.models.ride import Ride, RideStatus
from app.schemas.demand_heatmap import (
    DemandByHourFilters,
    DemandByHourResponse,
    DemandHourSlot,
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _date_to_utc_start(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=timezone.utc)


def _date_to_utc_end(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=timezone.utc)


def _to_float(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


def _hour_label(hour: int) -> str:
    return f"{hour:02d}:00"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def get_demand_by_hour(
    db,
    start_date: date | None = None,
    end_date: date | None = None,
    day_of_week: int | None = None,
) -> DemandByHourResponse:
    """Compute hourly demand breakdown across all 24 hours of the day.

    Args:
        db: async database session (AsyncSession or compatible AsyncMock)
        start_date: inclusive start date filter on ride.requested_at
        end_date: inclusive end date filter on ride.requested_at
        day_of_week: PostgreSQL DOW (0=Sunday … 6=Saturday); None means all days

    Returns:
        DemandByHourResponse with exactly 24 slots (hours 0–23) sorted by hour.
    """
    # Build the aggregation query
    hour_col = cast(extract("hour", Ride.requested_at), Numeric(4, 0)).label("hour")

    # Minutes between requested_at and matched_at (only where matched_at is set)
    wait_expr = func.extract(
        "epoch",
        Ride.matched_at - Ride.requested_at,
    ) / 60.0

    query = select(
        hour_col,
        func.count(Ride.id).label("total_rides"),
        func.sum(
            case((Ride.status == RideStatus.COMPLETED, 1), else_=0)
        ).label("completed_rides"),
        func.sum(
            case((Ride.status == RideStatus.CANCELLED, 1), else_=0)
        ).label("cancelled_rides"),
        func.avg(
            func.coalesce(Ride.actual_fare, Ride.estimated_fare)
        ).label("avg_fare"),
        func.avg(
            case(
                (Ride.matched_at.isnot(None), wait_expr),
                else_=None,
            )
        ).label("avg_wait_minutes"),
    ).group_by(hour_col).order_by(hour_col)

    # Apply optional filters
    if start_date is not None:
        query = query.where(Ride.requested_at >= _date_to_utc_start(start_date))
    if end_date is not None:
        query = query.where(Ride.requested_at <= _date_to_utc_end(end_date))
    if day_of_week is not None:
        query = query.where(
            cast(extract("dow", Ride.requested_at), Numeric(1, 0)) == day_of_week
        )

    result = await db.execute(query)
    rows = result.fetchall()

    # Build lookup from hour → row
    row_by_hour: dict[int, object] = {}
    for row in rows:
        h = int(row.hour)
        row_by_hour[h] = row

    # Always produce all 24 slots
    slots: list[DemandHourSlot] = []
    for h in range(24):
        row = row_by_hour.get(h)
        if row is not None:
            slot = DemandHourSlot(
                hour=h,
                hour_label=_hour_label(h),
                total_rides=int(row.total_rides),
                completed_rides=int(row.completed_rides),
                cancelled_rides=int(row.cancelled_rides),
                avg_fare=round(_to_float(row.avg_fare), 2)
                if _to_float(row.avg_fare) is not None
                else None,
                avg_wait_minutes=round(_to_float(row.avg_wait_minutes), 2)
                if _to_float(row.avg_wait_minutes) is not None
                else None,
            )
        else:
            slot = DemandHourSlot(
                hour=h,
                hour_label=_hour_label(h),
                total_rides=0,
                completed_rides=0,
                cancelled_rides=0,
                avg_fare=None,
                avg_wait_minutes=None,
            )
        slots.append(slot)

    total_rides = sum(s.total_rides for s in slots)

    # Determine peak hour (highest total_rides; None if all zero)
    peak_hour: int | None = None
    if total_rides > 0:
        peak_hour = max(slots, key=lambda s: s.total_rides).hour

    return DemandByHourResponse(
        slots=slots,
        total_rides=total_rides,
        peak_hour=peak_hour,
        generated_at=datetime.now(timezone.utc),
        filters=DemandByHourFilters(
            start_date=start_date,
            end_date=end_date,
            day_of_week=day_of_week,
        ),
    )
