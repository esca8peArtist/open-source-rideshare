"""Driver earnings P&L summary service.

Combines actual ride earnings with logged expenses to produce a true
profit/loss picture for a driver over a flexible date range.

Public API:
  get_driver_earnings_summary(db, driver_id, start_date, end_date, breakdown)
      → EarningsSummaryResponse

Data sources:
  - Ride (completed rides, actual_fare / estimated_fare)
  - Payment (platform_fee per ride)
  - TipRecord (tip amounts paid to the driver)
  - DriverExpense (logged business expenses)

All queries are scoped to the authenticated driver; no cross-driver data
is exposed.
"""
from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
from itertools import groupby

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.driver_expense import DriverExpense, ExpenseCategory
from app.models.payment import Payment, PaymentStatus
from app.models.ride import Ride, RideStatus
from app.models.tip import TipRecord, TipStatus
from app.schemas.driver_earnings_summary import (
    BreakdownInterval,
    EarningsSummaryResponse,
    ExpenseCategoryBreakdown,
    ExpenseSummary,
    IncomeBreakdown,
    PeriodBreakdown,
)


# ---------------------------------------------------------------------------
# Internal helpers — date utilities
# ---------------------------------------------------------------------------


def _start_of_month(d: date) -> date:
    """Return the first day of the month containing *d*."""
    return d.replace(day=1)


def _end_of_month(d: date) -> date:
    """Return the last day of the month containing *d*."""
    _, last = monthrange(d.year, d.month)
    return d.replace(day=last)


def _to_utc_start(d: date) -> datetime:
    """Convert a date to midnight UTC (start of day)."""
    return datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=timezone.utc)


def _to_utc_end(d: date) -> datetime:
    """Convert a date to 23:59:59 UTC (end of day)."""
    return datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=timezone.utc)


def _week_ranges(start: date, end: date) -> list[tuple[date, date]]:
    """Return a list of (week_start, week_end) tuples covering [start, end].

    Each window aligns to calendar weeks (Monday–Sunday). The first window
    starts on *start* (not necessarily Monday); the last window ends on *end*.
    """
    ranges: list[tuple[date, date]] = []
    cursor = start
    while cursor <= end:
        # Find the Sunday ending this week
        days_until_sunday = 6 - cursor.weekday() if cursor.weekday() != 6 else 0
        week_end = min(cursor + timedelta(days=days_until_sunday), end)
        ranges.append((cursor, week_end))
        cursor = week_end + timedelta(days=1)
    return ranges


def _month_ranges(start: date, end: date) -> list[tuple[date, date]]:
    """Return a list of (month_start, month_end) tuples covering [start, end].

    The first window starts on *start*; the last ends on *end*.
    """
    ranges: list[tuple[date, date]] = []
    cursor = start
    while cursor <= end:
        month_end = min(_end_of_month(cursor), end)
        ranges.append((cursor, month_end))
        # Advance to the first day of the next month
        cursor = month_end + timedelta(days=1)
    return ranges


def _period_label(start: date, end: date) -> str:
    """Return a human-readable label for a date range."""
    if start == end:
        return start.isoformat()
    return f"{start.isoformat()} – {end.isoformat()}"


# ---------------------------------------------------------------------------
# Internal helpers — aggregation
# ---------------------------------------------------------------------------


def _aggregate_rides(
    rides: list[Ride],
    tips_by_ride: dict[int, float],
    fees_by_ride: dict[int, float],
) -> IncomeBreakdown:
    """Build an IncomeBreakdown from a list of rides and lookup maps."""
    if not rides:
        return IncomeBreakdown(
            gross_fares=0.0,
            platform_fees=0.0,
            tips=0.0,
            net_ride_earnings=0.0,
            rides_completed=0,
        )

    gross = sum(r.actual_fare or r.estimated_fare or 0.0 for r in rides)
    fees = sum(fees_by_ride.get(r.id, 0.0) for r in rides)
    tips = sum(tips_by_ride.get(r.id, 0.0) for r in rides)
    net = gross - fees + tips

    return IncomeBreakdown(
        gross_fares=round(gross, 2),
        platform_fees=round(fees, 2),
        tips=round(tips, 2),
        net_ride_earnings=round(net, 2),
        rides_completed=len(rides),
    )


def _aggregate_expenses(expenses: list[DriverExpense]) -> ExpenseSummary:
    """Build an ExpenseSummary from a list of DriverExpense records."""
    cat_totals: dict[ExpenseCategory, dict] = {}
    grand_total = 0.0
    deductible_total = 0.0

    for exp in expenses:
        amount = float(exp.amount)
        grand_total += amount
        if exp.is_deductible:
            deductible_total += amount

        if exp.category not in cat_totals:
            cat_totals[exp.category] = {"total_amount": 0.0, "count": 0}
        cat_totals[exp.category]["total_amount"] += amount
        cat_totals[exp.category]["count"] += 1

    categories = [
        ExpenseCategoryBreakdown(
            category=cat,
            total_amount=round(data["total_amount"], 2),
            count=data["count"],
        )
        for cat, data in cat_totals.items()
    ]

    return ExpenseSummary(
        total_expenses=round(grand_total, 2),
        deductible_total=round(deductible_total, 2),
        categories=categories,
    )


def _rides_in_window(rides: list[Ride], start: date, end: date) -> list[Ride]:
    """Filter rides whose completed_at date falls within [start, end]."""
    start_dt = _to_utc_start(start)
    end_dt = _to_utc_end(end)
    return [
        r for r in rides
        if r.completed_at is not None and start_dt <= r.completed_at <= end_dt
    ]


def _expenses_in_window(expenses: list[DriverExpense], start: date, end: date) -> list[DriverExpense]:
    """Filter expenses whose expense_date falls within [start, end]."""
    return [e for e in expenses if start <= e.expense_date <= end]


# ---------------------------------------------------------------------------
# Database fetch helpers
# ---------------------------------------------------------------------------


async def _fetch_completed_rides(
    db: AsyncSession,
    driver_id: int,
    start: date,
    end: date,
) -> list[Ride]:
    """Fetch completed rides for a driver within the date range."""
    result = await db.execute(
        select(Ride).where(
            Ride.driver_id == driver_id,
            Ride.status == RideStatus.COMPLETED,
            Ride.completed_at >= _to_utc_start(start),
            Ride.completed_at <= _to_utc_end(end),
        )
    )
    return list(result.scalars().all())


async def _fetch_tips(
    db: AsyncSession,
    driver_id: int,
    ride_ids: list[int],
) -> dict[int, float]:
    """Return ride_id → tip_amount mapping for the given rides."""
    if not ride_ids:
        return {}
    result = await db.execute(
        select(TipRecord).where(
            TipRecord.ride_id.in_(ride_ids),
            TipRecord.driver_id == driver_id,
            TipRecord.status == TipStatus.COMPLETED,
        )
    )
    return {t.ride_id: t.amount_cents / 100.0 for t in result.scalars().all()}


async def _fetch_platform_fees(
    db: AsyncSession,
    ride_ids: list[int],
) -> dict[int, float]:
    """Return ride_id → platform_fee mapping for the given rides."""
    if not ride_ids:
        return {}
    result = await db.execute(
        select(Payment).where(
            Payment.ride_id.in_(ride_ids),
            Payment.status == PaymentStatus.COMPLETED,
        )
    )
    return {p.ride_id: float(p.platform_fee) for p in result.scalars().all()}


async def _fetch_expenses(
    db: AsyncSession,
    driver_id: int,
    start: date,
    end: date,
) -> list[DriverExpense]:
    """Fetch all expense records for a driver within the date range."""
    result = await db.execute(
        select(DriverExpense).where(
            DriverExpense.driver_id == driver_id,
            DriverExpense.expense_date >= start,
            DriverExpense.expense_date <= end,
        )
    )
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def get_driver_earnings_summary(
    db: AsyncSession,
    driver_id: int,
    start_date: date,
    end_date: date,
    breakdown: BreakdownInterval = BreakdownInterval.NONE,
) -> EarningsSummaryResponse:
    """Return a P&L earnings summary for the given driver and date range.

    Combines actual ride earnings (gross fares minus platform fees plus tips)
    with logged business expenses to show the driver's true net profit for the
    period.

    Args:
        db:         Async database session.
        driver_id:  Authenticated driver's user ID.
        start_date: Inclusive start of the summary period.
        end_date:   Inclusive end of the summary period.
        breakdown:  Granularity for the optional per-period breakdown.
                    NONE (default) → no ``periods`` list returned.
                    WEEKLY         → one entry per calendar week.
                    MONTHLY        → one entry per calendar month.

    Returns:
        EarningsSummaryResponse with top-level totals and optional sub-period
        breakdowns.
    """
    # Single bulk fetch for the full period — avoids N+1 in the breakdown path
    rides = await _fetch_completed_rides(db, driver_id=driver_id, start=start_date, end=end_date)
    ride_ids = [r.id for r in rides]
    tips_by_ride = await _fetch_tips(db, driver_id=driver_id, ride_ids=ride_ids)
    fees_by_ride = await _fetch_platform_fees(db, ride_ids=ride_ids)
    expenses = await _fetch_expenses(db, driver_id=driver_id, start=start_date, end=end_date)

    # Top-level aggregates
    income = _aggregate_rides(rides, tips_by_ride, fees_by_ride)
    expense_summary = _aggregate_expenses(expenses)
    net_profit = round(income.net_ride_earnings - expense_summary.total_expenses, 2)

    # Optional period breakdown
    periods: list[PeriodBreakdown] = []
    if breakdown != BreakdownInterval.NONE:
        if breakdown == BreakdownInterval.WEEKLY:
            windows = _week_ranges(start_date, end_date)
        else:  # MONTHLY
            windows = _month_ranges(start_date, end_date)

        for win_start, win_end in windows:
            win_rides = _rides_in_window(rides, win_start, win_end)
            win_expenses = _expenses_in_window(expenses, win_start, win_end)
            win_income = _aggregate_rides(win_rides, tips_by_ride, fees_by_ride)
            win_exp_total = sum(float(e.amount) for e in win_expenses)
            win_net = round(win_income.net_ride_earnings - win_exp_total, 2)

            periods.append(
                PeriodBreakdown(
                    period_label=_period_label(win_start, win_end),
                    period_start=win_start,
                    period_end=win_end,
                    gross_fares=win_income.gross_fares,
                    platform_fees=win_income.platform_fees,
                    tips=win_income.tips,
                    net_ride_earnings=win_income.net_ride_earnings,
                    rides_completed=win_income.rides_completed,
                    total_expenses=round(win_exp_total, 2),
                    net_profit=win_net,
                )
            )

    return EarningsSummaryResponse(
        driver_id=driver_id,
        period_start=start_date,
        period_end=end_date,
        breakdown=breakdown,
        income=income,
        expenses=expense_summary,
        net_profit=net_profit,
        periods=periods,
    )
