"""Tests for the driver earnings P&L summary feature.

Service unit tests (AsyncMock DB — no live DB required):
  1.  _aggregate_rides — gross_fares sums actual_fare values
  2.  _aggregate_rides — falls back to estimated_fare when actual_fare is None
  3.  _aggregate_rides — platform_fees summed from fees_by_ride map
  4.  _aggregate_rides — tips summed from tips_by_ride map
  5.  _aggregate_rides — net_ride_earnings = gross - fees + tips
  6.  _aggregate_rides — rides_completed equals len(rides)
  7.  _aggregate_rides — all zeros when rides list is empty
  8.  _aggregate_rides — rounds to 2 decimal places
  9.  _aggregate_expenses — grand_total sums all amounts
  10. _aggregate_expenses — deductible_total excludes non-deductible items
  11. _aggregate_expenses — categories list contains correct categories
  12. _aggregate_expenses — per-category count is correct
  13. _aggregate_expenses — per-category total_amount is correct
  14. _aggregate_expenses — empty list returns zeros and empty categories
  15. _week_ranges — single week entirely within range
  16. _week_ranges — range spanning multiple weeks
  17. _week_ranges — single-day range returns one window
  18. _week_ranges — first window starts on start_date, last ends on end_date
  19. _month_ranges — single month entirely within range
  20. _month_ranges — range spanning multiple months
  21. _month_ranges — first window starts on start_date, last ends on end_date
  22. _month_ranges — single-day range returns one window
  23. _rides_in_window — includes rides completed on start_date
  24. _rides_in_window — includes rides completed on end_date
  25. _rides_in_window — excludes rides completed before start_date
  26. _rides_in_window — excludes rides completed after end_date
  27. _rides_in_window — excludes rides with completed_at=None
  28. _expenses_in_window — includes expenses on boundary dates
  29. _expenses_in_window — excludes expenses outside range
  30. _period_label — same start/end returns single date string
  31. _period_label — different start/end returns dash-separated range
  32. get_driver_earnings_summary — net_profit = net_ride_earnings - total_expenses
  33. get_driver_earnings_summary — no periods when breakdown=none
  34. get_driver_earnings_summary — periods populated when breakdown=weekly
  35. get_driver_earnings_summary — periods populated when breakdown=monthly
  36. get_driver_earnings_summary — period_start and period_end reflected
  37. get_driver_earnings_summary — driver_id reflected in response
  38. get_driver_earnings_summary — breakdown field reflected in response
  39. get_driver_earnings_summary — zero net_profit when earnings match expenses
  40. get_driver_earnings_summary — negative net_profit when expenses exceed earnings
  41. get_driver_earnings_summary — weekly periods ordered oldest-to-newest
  42. get_driver_earnings_summary — monthly periods ordered oldest-to-newest
  43. get_driver_earnings_summary — period net_profit = period_net_ride_earnings - period_expenses

API integration tests (in-transaction test DB via conftest):
  44. GET /api/v1/drivers/me/earnings-summary — 401 with no auth
  45. GET /api/v1/drivers/me/earnings-summary — 403 with rider token
  46. GET /api/v1/drivers/me/earnings-summary — 200 with driver token
  47. GET /api/v1/drivers/me/earnings-summary — response matches schema
  48. GET /api/v1/drivers/me/earnings-summary — defaults: breakdown=none, current month
  49. GET /api/v1/drivers/me/earnings-summary — explicit start_date + end_date accepted
  50. GET /api/v1/drivers/me/earnings-summary — breakdown=weekly returns periods list
  51. GET /api/v1/drivers/me/earnings-summary — breakdown=monthly returns periods list
  52. GET /api/v1/drivers/me/earnings-summary — 422 when start_date > end_date
  53. GET /api/v1/drivers/me/earnings-summary — 422 when breakdown is invalid
  54. GET /api/v1/drivers/me/earnings-summary — periods ordered oldest-to-newest
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.driver_expense import DriverExpense, ExpenseCategory
from app.models.ride import Ride, RideStatus
from app.schemas.driver_earnings_summary import BreakdownInterval
from app.services.driver_earnings_summary import (
    _aggregate_expenses,
    _aggregate_rides,
    _expenses_in_window,
    _month_ranges,
    _period_label,
    _rides_in_window,
    _week_ranges,
    get_driver_earnings_summary,
)

# ---------------------------------------------------------------------------
# Shared constants and factory helpers
# ---------------------------------------------------------------------------

TODAY = date(2026, 4, 14)
DRIVER_ID = 42


def _dt(d: date) -> datetime:
    """Return midnight UTC for the given date."""
    return datetime(d.year, d.month, d.day, 12, 0, 0, tzinfo=timezone.utc)


def _make_ride(
    ride_id: int = 1,
    driver_id: int = DRIVER_ID,
    actual_fare: float | None = 20.00,
    estimated_fare: float = 18.00,
    completed_at: datetime | None = None,
) -> MagicMock:
    ride = MagicMock(spec=Ride)
    ride.id = ride_id
    ride.driver_id = driver_id
    ride.actual_fare = actual_fare
    ride.estimated_fare = estimated_fare
    ride.status = RideStatus.COMPLETED
    ride.completed_at = completed_at or _dt(TODAY)
    return ride


def _make_expense(
    exp_id: int = 1,
    driver_id: int = DRIVER_ID,
    category: ExpenseCategory = ExpenseCategory.FUEL,
    amount: float = 50.00,
    is_deductible: bool = True,
    expense_date: date = TODAY,
) -> MagicMock:
    exp = MagicMock(spec=DriverExpense)
    exp.id = exp_id
    exp.driver_id = driver_id
    exp.category = category
    exp.amount = amount
    exp.is_deductible = is_deductible
    exp.expense_date = expense_date
    return exp


def _scalars_list(items: list) -> MagicMock:
    scalars = MagicMock()
    scalars.all.return_value = list(items)
    result = MagicMock()
    result.scalars.return_value = scalars
    return result


def _db_multi_execute(*results) -> AsyncMock:
    """DB mock that returns successive results on each execute() call."""
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=list(results))
    return db


# ---------------------------------------------------------------------------
# Service unit tests — _aggregate_rides
# ---------------------------------------------------------------------------


class TestAggregateRides:
    def test_gross_fares_sums_actual_fare(self):
        rides = [_make_ride(ride_id=1, actual_fare=20.0), _make_ride(ride_id=2, actual_fare=30.0)]
        result = _aggregate_rides(rides, {}, {})
        assert result.gross_fares == 50.0

    def test_falls_back_to_estimated_fare(self):
        ride = _make_ride(ride_id=1, actual_fare=None, estimated_fare=22.0)
        result = _aggregate_rides([ride], {}, {})
        assert result.gross_fares == 22.0

    def test_platform_fees_from_map(self):
        ride = _make_ride(ride_id=1, actual_fare=20.0)
        result = _aggregate_rides([ride], tips_by_ride={}, fees_by_ride={1: 2.40})
        assert result.platform_fees == 2.40

    def test_tips_from_map(self):
        ride = _make_ride(ride_id=1, actual_fare=20.0)
        result = _aggregate_rides([ride], tips_by_ride={1: 3.00}, fees_by_ride={})
        assert result.tips == 3.00

    def test_net_ride_earnings_formula(self):
        ride = _make_ride(ride_id=1, actual_fare=20.0)
        result = _aggregate_rides([ride], tips_by_ride={1: 2.0}, fees_by_ride={1: 2.0})
        # 20 - 2 + 2 = 20
        assert result.net_ride_earnings == 20.0

    def test_rides_completed_count(self):
        rides = [_make_ride(ride_id=i) for i in range(5)]
        result = _aggregate_rides(rides, {}, {})
        assert result.rides_completed == 5

    def test_empty_rides_all_zeros(self):
        result = _aggregate_rides([], {}, {})
        assert result.gross_fares == 0.0
        assert result.platform_fees == 0.0
        assert result.tips == 0.0
        assert result.net_ride_earnings == 0.0
        assert result.rides_completed == 0

    def test_rounds_to_two_decimal_places(self):
        ride = _make_ride(ride_id=1, actual_fare=10.001)
        result = _aggregate_rides([ride], {}, {1: 1.001})
        assert result.gross_fares == 10.0  # rounds 10.001 to 10.0
        assert result.platform_fees == 1.0  # rounds 1.001 to 1.0


# ---------------------------------------------------------------------------
# Service unit tests — _aggregate_expenses
# ---------------------------------------------------------------------------


class TestAggregateExpenses:
    def test_grand_total_sums_all(self):
        expenses = [_make_expense(amount=50.0), _make_expense(exp_id=2, amount=30.0)]
        result = _aggregate_expenses(expenses)
        assert result.total_expenses == 80.0

    def test_deductible_excludes_non_deductible(self):
        expenses = [
            _make_expense(exp_id=1, amount=50.0, is_deductible=True),
            _make_expense(exp_id=2, amount=20.0, is_deductible=False),
        ]
        result = _aggregate_expenses(expenses)
        assert result.deductible_total == 50.0

    def test_categories_present(self):
        expenses = [
            _make_expense(exp_id=1, category=ExpenseCategory.FUEL, amount=50.0),
            _make_expense(exp_id=2, category=ExpenseCategory.TOLLS, amount=10.0),
        ]
        result = _aggregate_expenses(expenses)
        cats = {c.category for c in result.categories}
        assert ExpenseCategory.FUEL in cats
        assert ExpenseCategory.TOLLS in cats

    def test_per_category_count(self):
        expenses = [
            _make_expense(exp_id=1, category=ExpenseCategory.FUEL, amount=50.0),
            _make_expense(exp_id=2, category=ExpenseCategory.FUEL, amount=30.0),
        ]
        result = _aggregate_expenses(expenses)
        fuel = next(c for c in result.categories if c.category == ExpenseCategory.FUEL)
        assert fuel.count == 2

    def test_per_category_total_amount(self):
        expenses = [
            _make_expense(exp_id=1, category=ExpenseCategory.FUEL, amount=50.0),
            _make_expense(exp_id=2, category=ExpenseCategory.FUEL, amount=30.0),
        ]
        result = _aggregate_expenses(expenses)
        fuel = next(c for c in result.categories if c.category == ExpenseCategory.FUEL)
        assert fuel.total_amount == 80.0

    def test_empty_returns_zeros(self):
        result = _aggregate_expenses([])
        assert result.total_expenses == 0.0
        assert result.deductible_total == 0.0
        assert result.categories == []


# ---------------------------------------------------------------------------
# Service unit tests — _week_ranges and _month_ranges
# ---------------------------------------------------------------------------


class TestWeekRanges:
    def test_single_week(self):
        # Monday to Sunday = 1 window
        monday = date(2026, 4, 13)  # Monday
        sunday = date(2026, 4, 19)  # Sunday
        ranges = _week_ranges(monday, sunday)
        assert len(ranges) == 1
        assert ranges[0] == (monday, sunday)

    def test_spanning_two_weeks(self):
        start = date(2026, 4, 13)  # Monday
        end = date(2026, 4, 20)    # Monday next week
        ranges = _week_ranges(start, end)
        assert len(ranges) == 2

    def test_single_day(self):
        d = date(2026, 4, 14)
        ranges = _week_ranges(d, d)
        assert len(ranges) == 1
        assert ranges[0][0] == d
        assert ranges[0][1] == d

    def test_first_window_starts_on_start_date(self):
        start = date(2026, 4, 14)  # Tuesday
        end = date(2026, 4, 28)
        ranges = _week_ranges(start, end)
        assert ranges[0][0] == start

    def test_last_window_ends_on_end_date(self):
        start = date(2026, 4, 14)
        end = date(2026, 4, 28)
        ranges = _week_ranges(start, end)
        assert ranges[-1][1] == end


class TestMonthRanges:
    def test_single_month(self):
        start = date(2026, 4, 1)
        end = date(2026, 4, 30)
        ranges = _month_ranges(start, end)
        assert len(ranges) == 1
        assert ranges[0] == (start, end)

    def test_spanning_two_months(self):
        start = date(2026, 3, 15)
        end = date(2026, 4, 14)
        ranges = _month_ranges(start, end)
        assert len(ranges) == 2

    def test_first_window_starts_on_start_date(self):
        start = date(2026, 4, 5)
        end = date(2026, 5, 10)
        ranges = _month_ranges(start, end)
        assert ranges[0][0] == start

    def test_last_window_ends_on_end_date(self):
        start = date(2026, 4, 5)
        end = date(2026, 5, 10)
        ranges = _month_ranges(start, end)
        assert ranges[-1][1] == end

    def test_single_day(self):
        d = date(2026, 4, 14)
        ranges = _month_ranges(d, d)
        assert len(ranges) == 1
        assert ranges[0] == (d, d)


# ---------------------------------------------------------------------------
# Service unit tests — _rides_in_window and _expenses_in_window
# ---------------------------------------------------------------------------


class TestRidesInWindow:
    def test_includes_ride_on_start_date(self):
        ride = _make_ride(completed_at=datetime(2026, 4, 1, 10, 0, 0, tzinfo=timezone.utc))
        result = _rides_in_window([ride], date(2026, 4, 1), date(2026, 4, 30))
        assert ride in result

    def test_includes_ride_on_end_date(self):
        ride = _make_ride(completed_at=datetime(2026, 4, 30, 23, 0, 0, tzinfo=timezone.utc))
        result = _rides_in_window([ride], date(2026, 4, 1), date(2026, 4, 30))
        assert ride in result

    def test_excludes_ride_before_start(self):
        ride = _make_ride(completed_at=datetime(2026, 3, 31, 23, 59, 59, tzinfo=timezone.utc))
        result = _rides_in_window([ride], date(2026, 4, 1), date(2026, 4, 30))
        assert ride not in result

    def test_excludes_ride_after_end(self):
        ride = _make_ride(completed_at=datetime(2026, 5, 1, 0, 0, 1, tzinfo=timezone.utc))
        result = _rides_in_window([ride], date(2026, 4, 1), date(2026, 4, 30))
        assert ride not in result

    def test_excludes_ride_with_no_completed_at(self):
        ride = _make_ride()
        ride.completed_at = None
        result = _rides_in_window([ride], date(2026, 4, 1), date(2026, 4, 30))
        assert ride not in result


class TestExpensesInWindow:
    def test_includes_on_boundaries(self):
        exp1 = _make_expense(exp_id=1, expense_date=date(2026, 4, 1))
        exp2 = _make_expense(exp_id=2, expense_date=date(2026, 4, 30))
        result = _expenses_in_window([exp1, exp2], date(2026, 4, 1), date(2026, 4, 30))
        assert exp1 in result
        assert exp2 in result

    def test_excludes_outside_range(self):
        exp = _make_expense(expense_date=date(2026, 3, 31))
        result = _expenses_in_window([exp], date(2026, 4, 1), date(2026, 4, 30))
        assert exp not in result


# ---------------------------------------------------------------------------
# Service unit tests — _period_label
# ---------------------------------------------------------------------------


class TestPeriodLabel:
    def test_same_date_returns_single(self):
        d = date(2026, 4, 14)
        assert _period_label(d, d) == "2026-04-14"

    def test_range_returns_dash_separated(self):
        assert _period_label(date(2026, 4, 1), date(2026, 4, 7)) == "2026-04-01 – 2026-04-07"


# ---------------------------------------------------------------------------
# Service integration-style unit tests — get_driver_earnings_summary
# ---------------------------------------------------------------------------


class TestGetDriverEarningsSummary:
    """Unit tests using fully mocked DB."""

    def _make_db(self, rides, tips, fees, expenses) -> AsyncMock:
        """DB mock for four sequential execute() calls."""
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _scalars_list(rides),   # _fetch_completed_rides
                _scalars_list(tips),    # _fetch_tips
                _scalars_list(fees),    # _fetch_platform_fees
                _scalars_list(expenses),  # _fetch_expenses
            ]
        )
        return db

    @pytest.mark.anyio
    async def test_net_profit_calculation(self):
        ride = _make_ride(ride_id=1, actual_fare=100.0)
        tip = MagicMock()
        tip.ride_id = 1
        tip.driver_id = DRIVER_ID
        tip.amount_cents = 1000  # $10
        fee = MagicMock()
        fee.ride_id = 1
        fee.platform_fee = 12.0
        expense = _make_expense(amount=20.0)

        db = self._make_db([ride], [tip], [fee], [expense])
        result = await get_driver_earnings_summary(
            db, DRIVER_ID, date(2026, 4, 1), date(2026, 4, 14)
        )
        # net_ride = 100 - 12 + 10 = 98; net_profit = 98 - 20 = 78
        assert result.net_profit == 78.0

    @pytest.mark.anyio
    async def test_no_periods_when_breakdown_none(self):
        db = self._make_db([], [], [], [])
        result = await get_driver_earnings_summary(
            db, DRIVER_ID, date(2026, 4, 1), date(2026, 4, 14),
            breakdown=BreakdownInterval.NONE,
        )
        assert result.periods == []

    @pytest.mark.anyio
    async def test_periods_populated_weekly(self):
        db = self._make_db([], [], [], [])
        # 14-day range → 2 weeks
        result = await get_driver_earnings_summary(
            db, DRIVER_ID, date(2026, 4, 1), date(2026, 4, 14),
            breakdown=BreakdownInterval.WEEKLY,
        )
        assert len(result.periods) >= 2

    @pytest.mark.anyio
    async def test_periods_populated_monthly(self):
        db = self._make_db([], [], [], [])
        # Mar 15 – Apr 14 → 2 months
        result = await get_driver_earnings_summary(
            db, DRIVER_ID, date(2026, 3, 15), date(2026, 4, 14),
            breakdown=BreakdownInterval.MONTHLY,
        )
        assert len(result.periods) == 2

    @pytest.mark.anyio
    async def test_period_start_end_reflected(self):
        db = self._make_db([], [], [], [])
        result = await get_driver_earnings_summary(
            db, DRIVER_ID, date(2026, 4, 1), date(2026, 4, 14)
        )
        assert result.period_start == date(2026, 4, 1)
        assert result.period_end == date(2026, 4, 14)

    @pytest.mark.anyio
    async def test_driver_id_reflected(self):
        db = self._make_db([], [], [], [])
        result = await get_driver_earnings_summary(
            db, DRIVER_ID, date(2026, 4, 1), date(2026, 4, 14)
        )
        assert result.driver_id == DRIVER_ID

    @pytest.mark.anyio
    async def test_breakdown_field_reflected(self):
        db = self._make_db([], [], [], [])
        result = await get_driver_earnings_summary(
            db, DRIVER_ID, date(2026, 4, 1), date(2026, 4, 14),
            breakdown=BreakdownInterval.MONTHLY,
        )
        assert result.breakdown == BreakdownInterval.MONTHLY

    @pytest.mark.anyio
    async def test_zero_net_profit_when_balanced(self):
        ride = _make_ride(ride_id=1, actual_fare=50.0)
        expense = _make_expense(amount=50.0)
        db = self._make_db([ride], [], [], [expense])
        result = await get_driver_earnings_summary(
            db, DRIVER_ID, date(2026, 4, 1), date(2026, 4, 14)
        )
        assert result.net_profit == 0.0

    @pytest.mark.anyio
    async def test_negative_net_profit_when_expenses_exceed_earnings(self):
        ride = _make_ride(ride_id=1, actual_fare=30.0)
        expense = _make_expense(amount=50.0)
        db = self._make_db([ride], [], [], [expense])
        result = await get_driver_earnings_summary(
            db, DRIVER_ID, date(2026, 4, 1), date(2026, 4, 14)
        )
        assert result.net_profit == -20.0

    @pytest.mark.anyio
    async def test_weekly_periods_ordered_oldest_first(self):
        db = self._make_db([], [], [], [])
        result = await get_driver_earnings_summary(
            db, DRIVER_ID, date(2026, 4, 1), date(2026, 4, 21),
            breakdown=BreakdownInterval.WEEKLY,
        )
        starts = [p.period_start for p in result.periods]
        assert starts == sorted(starts)

    @pytest.mark.anyio
    async def test_monthly_periods_ordered_oldest_first(self):
        db = self._make_db([], [], [], [])
        result = await get_driver_earnings_summary(
            db, DRIVER_ID, date(2026, 2, 1), date(2026, 4, 14),
            breakdown=BreakdownInterval.MONTHLY,
        )
        starts = [p.period_start for p in result.periods]
        assert starts == sorted(starts)

    @pytest.mark.anyio
    async def test_period_net_profit_formula(self):
        """Period net_profit = net_ride_earnings - total_expenses for that sub-period."""
        ride = _make_ride(
            ride_id=1,
            actual_fare=100.0,
            completed_at=datetime(2026, 4, 5, 12, 0, 0, tzinfo=timezone.utc),
        )
        expense = _make_expense(amount=20.0, expense_date=date(2026, 4, 5))
        db = self._make_db([ride], [], [], [expense])
        result = await get_driver_earnings_summary(
            db, DRIVER_ID, date(2026, 4, 1), date(2026, 4, 14),
            breakdown=BreakdownInterval.MONTHLY,
        )
        assert len(result.periods) == 1
        period = result.periods[0]
        assert period.net_profit == period.net_ride_earnings - period.total_expenses


# ---------------------------------------------------------------------------
# API integration tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_earnings_summary_no_auth(client):
    resp = await client.get("/api/v1/drivers/me/earnings-summary")
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_earnings_summary_rider_forbidden(client, rider_token):
    resp = await client.get(
        "/api/v1/drivers/me/earnings-summary",
        headers={"Authorization": f"Bearer {rider_token}"},
    )
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_earnings_summary_driver_ok(client, driver_token):
    resp = await client.get(
        "/api/v1/drivers/me/earnings-summary",
        headers={"Authorization": f"Bearer {driver_token}"},
    )
    assert resp.status_code == 200


@pytest.mark.anyio
async def test_earnings_summary_schema(client, driver_token):
    resp = await client.get(
        "/api/v1/drivers/me/earnings-summary",
        headers={"Authorization": f"Bearer {driver_token}"},
    )
    body = resp.json()
    assert "driver_id" in body
    assert "period_start" in body
    assert "period_end" in body
    assert "breakdown" in body
    assert "income" in body
    assert "expenses" in body
    assert "net_profit" in body
    assert "periods" in body


@pytest.mark.anyio
async def test_earnings_summary_defaults(client, driver_token):
    resp = await client.get(
        "/api/v1/drivers/me/earnings-summary",
        headers={"Authorization": f"Bearer {driver_token}"},
    )
    body = resp.json()
    assert body["breakdown"] == "none"
    assert body["periods"] == []


@pytest.mark.anyio
async def test_earnings_summary_explicit_dates(client, driver_token):
    resp = await client.get(
        "/api/v1/drivers/me/earnings-summary",
        params={"start_date": "2026-01-01", "end_date": "2026-04-14"},
        headers={"Authorization": f"Bearer {driver_token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["period_start"] == "2026-01-01"
    assert body["period_end"] == "2026-04-14"


@pytest.mark.anyio
async def test_earnings_summary_weekly_breakdown(client, driver_token):
    resp = await client.get(
        "/api/v1/drivers/me/earnings-summary",
        params={
            "start_date": "2026-04-01",
            "end_date": "2026-04-14",
            "breakdown": "weekly",
        },
        headers={"Authorization": f"Bearer {driver_token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["periods"]) >= 2


@pytest.mark.anyio
async def test_earnings_summary_monthly_breakdown(client, driver_token):
    resp = await client.get(
        "/api/v1/drivers/me/earnings-summary",
        params={
            "start_date": "2026-03-01",
            "end_date": "2026-04-14",
            "breakdown": "monthly",
        },
        headers={"Authorization": f"Bearer {driver_token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["periods"]) == 2


@pytest.mark.anyio
async def test_earnings_summary_invalid_date_range(client, driver_token):
    resp = await client.get(
        "/api/v1/drivers/me/earnings-summary",
        params={"start_date": "2026-04-14", "end_date": "2026-04-01"},
        headers={"Authorization": f"Bearer {driver_token}"},
    )
    assert resp.status_code == 422


@pytest.mark.anyio
async def test_earnings_summary_invalid_breakdown(client, driver_token):
    resp = await client.get(
        "/api/v1/drivers/me/earnings-summary",
        params={"breakdown": "quarterly"},
        headers={"Authorization": f"Bearer {driver_token}"},
    )
    assert resp.status_code == 422


@pytest.mark.anyio
async def test_earnings_summary_periods_ordered(client, driver_token):
    resp = await client.get(
        "/api/v1/drivers/me/earnings-summary",
        params={
            "start_date": "2026-02-01",
            "end_date": "2026-04-14",
            "breakdown": "monthly",
        },
        headers={"Authorization": f"Bearer {driver_token}"},
    )
    assert resp.status_code == 200
    periods = resp.json()["periods"]
    starts = [p["period_start"] for p in periods]
    assert starts == sorted(starts)
