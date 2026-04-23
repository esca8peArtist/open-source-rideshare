"""Admin driver earnings aggregation report service.

Returns per-driver earnings aggregated over a date range, paginated and
sortable.  Unlike the top-earners endpoint (which shows only the top N
drivers), this report includes ALL drivers who had at least one completed
ride in the period.

Platform fee arithmetic (mirrors driver_earnings_summary.py):
    gross    = actual_fare  (fallback: estimated_fare)
    net      = gross / (1 + platform_fee_pct / 100)
    fee      = gross - net

pending_payout_usd:
    Sum of net_earnings for rides whose completed_at date is NOT covered by
    any COMPLETED DriverPayout for that driver (i.e. not within any
    [period_start, period_end] of a completed payout record).
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.payout import DriverPayout, PayoutStatus
from app.models.ride import Ride, RideStatus
from app.models.user import User
from app.schemas.admin_driver_earnings_report import (
    AdminDriverEarningsReport,
    DriverEarningsRow,
    PlatformTotals,
)

SortField = Literal["net_earnings", "gross_earnings", "rides_completed", "tips"]
SortDir = Literal["asc", "desc"]


def _date_to_utc_start(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=timezone.utc)


def _date_to_utc_end(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=timezone.utc)


def _sort_key(row: DriverEarningsRow, sort_by: SortField) -> float:
    if sort_by == "gross_earnings":
        return row.gross_earnings_usd
    if sort_by == "rides_completed":
        return float(row.rides_completed)
    if sort_by == "tips":
        return row.tips_usd
    # default: net_earnings
    return row.net_earnings_usd


async def get_driver_earnings_report(
    db: AsyncSession,
    start_date: date,
    end_date: date,
    sort_by: SortField,
    sort_dir: SortDir,
    page: int,
    page_size: int,
    platform_fee_pct: float,
) -> AdminDriverEarningsReport:
    """Build and return the admin driver earnings report.

    Args:
        db: Async SQLAlchemy session.
        start_date: Inclusive start of the reporting period.
        end_date: Inclusive end of the reporting period.
        sort_by: Field to sort drivers by (net_earnings, gross_earnings,
                 rides_completed, tips).
        sort_dir: Sort direction ('asc' or 'desc').
        page: 1-based page number.
        page_size: Number of driver rows per page (max 100).
        platform_fee_pct: Platform fee percentage, e.g. 20.0 means 20%.

    Returns:
        AdminDriverEarningsReport with full platform totals and paginated
        per-driver breakdown.
    """
    start = _date_to_utc_start(start_date)
    end = _date_to_utc_end(end_date)

    # Fetch all completed rides in the period
    rides_result = await db.execute(
        select(Ride).where(
            Ride.status == RideStatus.COMPLETED,
            Ride.completed_at >= start,
            Ride.completed_at <= end,
            Ride.driver_id.is_not(None),
        )
    )
    all_rides: list[Ride] = list(rides_result.scalars().all())

    if not all_rides:
        return AdminDriverEarningsReport(
            period_start=start_date.isoformat(),
            period_end=end_date.isoformat(),
            total_active_drivers=0,
            platform_totals=PlatformTotals(
                total_rides=0,
                gross_earnings_usd=0.0,
                platform_fees_usd=0.0,
                net_earnings_usd=0.0,
                tips_usd=0.0,
            ),
            drivers=[],
            page=page,
            page_size=page_size,
            total_count=0,
        )

    # Group rides by driver_id
    rides_by_driver: dict[int, list[Ride]] = {}
    for ride in all_rides:
        driver_id = ride.driver_id  # type: ignore[assignment]
        rides_by_driver.setdefault(driver_id, []).append(ride)

    # Fetch User records for all active drivers in one query
    driver_ids = list(rides_by_driver.keys())
    users_result = await db.execute(
        select(User).where(User.id.in_(driver_ids))
    )
    users_by_id: dict[int, User] = {u.id: u for u in users_result.scalars().all()}

    # Fetch ALL completed payout records for these drivers (any period)
    payouts_result = await db.execute(
        select(DriverPayout).where(
            DriverPayout.driver_id.in_(driver_ids),
            DriverPayout.status == PayoutStatus.COMPLETED,
        )
    )
    all_payouts: list[DriverPayout] = list(payouts_result.scalars().all())

    # Index payout intervals per driver: list of (period_start, period_end) date pairs
    payout_intervals: dict[int, list[tuple[date, date]]] = {}
    for payout in all_payouts:
        payout_intervals.setdefault(payout.driver_id, []).append(
            (payout.period_start, payout.period_end)
        )

    # Platform fee divisor
    divisor = 1.0 + platform_fee_pct / 100.0 if platform_fee_pct > 0 else 1.0

    def _ride_net(fare: float) -> float:
        return fare / divisor if platform_fee_pct > 0 else fare

    def _is_covered(ride: Ride, intervals: list[tuple[date, date]]) -> bool:
        """Return True if this ride's completed_at date falls within any payout interval."""
        if not ride.completed_at:
            return False
        completed_date = ride.completed_at.date()
        for ps, pe in intervals:
            if ps <= completed_date <= pe:
                return True
        return False

    # Build per-driver rows
    driver_rows: list[DriverEarningsRow] = []
    for driver_id, rides in rides_by_driver.items():
        gross_total = 0.0
        net_total = 0.0
        tips_total = 0.0
        pending_net = 0.0
        intervals = payout_intervals.get(driver_id, [])

        for ride in rides:
            fare = float(ride.actual_fare if ride.actual_fare is not None else ride.estimated_fare)
            tip = float(ride.tip_amount or 0.0)
            net = _ride_net(fare)

            gross_total += fare
            net_total += net
            tips_total += tip

            if not _is_covered(ride, intervals):
                pending_net += net

        gross_total = round(gross_total, 2)
        net_total = round(net_total, 2)
        platform_fee_total = round(gross_total - net_total, 2)
        tips_total = round(tips_total, 2)
        pending_net = round(pending_net, 2)

        user = users_by_id.get(driver_id)
        driver_name = user.name if user else "Unknown"
        driver_phone = user.phone if user else ""

        driver_rows.append(
            DriverEarningsRow(
                driver_id=driver_id,
                driver_name=driver_name,
                driver_phone=driver_phone,
                rides_completed=len(rides),
                gross_earnings_usd=gross_total,
                platform_fee_usd=platform_fee_total,
                net_earnings_usd=net_total,
                tips_usd=tips_total,
                total_take_home_usd=round(net_total + tips_total, 2),
                pending_payout_usd=pending_net,
            )
        )

    # Sort
    reverse = sort_dir == "desc"
    driver_rows.sort(key=lambda r: _sort_key(r, sort_by), reverse=reverse)

    total_count = len(driver_rows)

    # Paginate
    offset = (page - 1) * page_size
    page_rows = driver_rows[offset: offset + page_size]

    # Platform totals (across ALL drivers, not just current page)
    total_rides = sum(len(rides) for rides in rides_by_driver.values())
    total_gross = round(sum(r.gross_earnings_usd for r in driver_rows), 2)
    total_fees = round(sum(r.platform_fee_usd for r in driver_rows), 2)
    total_net = round(sum(r.net_earnings_usd for r in driver_rows), 2)
    total_tips = round(sum(r.tips_usd for r in driver_rows), 2)

    return AdminDriverEarningsReport(
        period_start=start_date.isoformat(),
        period_end=end_date.isoformat(),
        total_active_drivers=total_count,
        platform_totals=PlatformTotals(
            total_rides=total_rides,
            gross_earnings_usd=total_gross,
            platform_fees_usd=total_fees,
            net_earnings_usd=total_net,
            tips_usd=total_tips,
        ),
        drivers=page_rows,
        page=page,
        page_size=page_size,
        total_count=total_count,
    )
