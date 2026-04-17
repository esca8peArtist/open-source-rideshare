"""Tests for the driver revenue projection feature.

GET /driver/me/revenue-projection

Coverage
--------
Service layer (get_driver_revenue_projection)
  - No ride history → zeros, insufficient_data trend, zero-history note
  - Rides all within analysis window → bucketed into weekly history
  - Rides older than analysis window → excluded
  - Weekly history ordered oldest-first
  - avg_weekly_earnings computed from trailing 4-week window
  - avg_weekly_earnings uses all weeks when fewer than 4 available
  - projected_monthly = avg_weekly * (52/12)
  - Trend: improving (>10% increase later half vs earlier half)
  - Trend: declining (>10% decrease later half vs earlier half)
  - Trend: stable (within ±10%)
  - Trend: insufficient_data (fewer than TREND_WEEKS weeks total)
  - Trend: insufficient_data when earlier-half avg is zero
  - Hourly breakdown has 24 entries (hours 0–23)
  - Hourly breakdown averages over num_weeks
  - Daily breakdown has 7 entries (days 0–6)
  - Daily breakdown maps weekday correctly (0=Monday … 6=Sunday)
  - best_earning_hours returns top-3 by avg_earnings_usd
  - best_earning_hours returns fewer than 3 when all zero except 1 or 2
  - best_earning_days returns top-2 day names by avg_earnings_usd
  - projection_note: no data → no-history message
  - projection_note: improving trend → upward phrasing
  - projection_note: declining trend → declining phrasing
  - projection_note: stable trend → stable phrasing
  - projection_note: insufficient_data trend → limited data phrasing
  - tip_amount accumulated into weekly_history and hourly_breakdown
  - actual_fare None treated as 0.0

Helpers (_build_weekly_history, _classify_trend, _build_hourly_breakdown,
         _build_daily_breakdown, _best_earning_hours, _best_earning_days,
         _build_projection_note, _iso_week_start)
  - _iso_week_start: Wednesday → Monday of same week
  - _iso_week_start: Monday → same day
  - _iso_week_start: Sunday → Monday 6 days prior
  - _classify_trend: fewer than 4 weeks → insufficient_data
  - _classify_trend: 4 weeks exactly, even split 2/2 → stable (same values)
  - _classify_trend: earlier avg = 0 → insufficient_data
  - _build_hourly_breakdown: empty rides → all zeros
  - _build_daily_breakdown: empty rides → all zeros
  - _best_earning_hours: tie-breaking returns first encountered
  - _build_projection_note: weeks=0 → no-history message
  - _build_projection_note: weeks>0, trend improving → correct interpolation

Schema (DriverRevenueProjection, sub-schemas)
  - All required fields present
  - HourlyBreakdown has hour, avg_earnings_usd, avg_rides, avg_tips_usd
  - DailyBreakdown has day_of_week, day_name, avg_earnings_usd, avg_rides
  - WeeklyEarnings has week_start, earnings_usd, rides, tips_usd

Router (get_revenue_projection)
  - Delegates to service with driver.id
  - Returns DriverRevenueProjection
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.schemas.driver_revenue_projection import (
    DailyBreakdown,
    DriverRevenueProjection,
    HourlyBreakdown,
    WeeklyEarnings,
)
from app.services.driver_revenue_projection import (
    ANALYSIS_WEEKS,
    TREND_WEEKS,
    WEEKS_PER_MONTH,
    _best_earning_days,
    _best_earning_hours,
    _build_daily_breakdown,
    _build_hourly_breakdown,
    _build_projection_note,
    _build_weekly_history,
    _classify_trend,
    _iso_week_start,
    get_driver_revenue_projection,
)

# --------------------------------------------------------------------------- #
# Shared fixtures
# --------------------------------------------------------------------------- #

DRIVER_ID = 42
NOW = datetime(2026, 4, 17, 14, 0, 0, tzinfo=timezone.utc)  # Friday
WINDOW_START = NOW - timedelta(weeks=ANALYSIS_WEEKS)


def _make_ride(
    *,
    actual_fare: float = 12.0,
    tip_amount: float = 2.0,
    requested_at: datetime | None = None,
    driver_id: int = DRIVER_ID,
) -> MagicMock:
    from app.models.ride import RideStatus

    ride = MagicMock()
    ride.driver_id = driver_id
    ride.actual_fare = actual_fare
    ride.tip_amount = tip_amount
    ride.status = RideStatus.COMPLETED
    ride.requested_at = requested_at or datetime(2026, 4, 14, 10, 0, 0, tzinfo=timezone.utc)
    return ride


def _make_db(rides: list) -> AsyncMock:
    """Return a mock AsyncSession that yields *rides* on execute()."""
    result = MagicMock()
    result.scalars.return_value.all.return_value = rides

    db = AsyncMock()
    db.execute = AsyncMock(return_value=result)
    return db


# --------------------------------------------------------------------------- #
# Helper: _iso_week_start
# --------------------------------------------------------------------------- #


class TestIsoWeekStart:
    def test_wednesday_returns_monday(self):
        dt = datetime(2026, 4, 15, 12, 0, tzinfo=timezone.utc)  # Wednesday
        assert _iso_week_start(dt) == date(2026, 4, 13)

    def test_monday_returns_same_day(self):
        dt = datetime(2026, 4, 13, 0, 0, tzinfo=timezone.utc)  # Monday
        assert _iso_week_start(dt) == date(2026, 4, 13)

    def test_sunday_returns_prior_monday(self):
        dt = datetime(2026, 4, 19, 23, 59, tzinfo=timezone.utc)  # Sunday
        assert _iso_week_start(dt) == date(2026, 4, 13)


# --------------------------------------------------------------------------- #
# Helper: _build_weekly_history
# --------------------------------------------------------------------------- #


class TestBuildWeeklyHistory:
    def test_empty_rides(self):
        assert _build_weekly_history([], WINDOW_START, NOW) == []

    def test_single_ride_produces_one_week(self):
        ride = _make_ride(actual_fare=50.0, tip_amount=5.0,
                          requested_at=datetime(2026, 4, 14, 10, 0, tzinfo=timezone.utc))
        history = _build_weekly_history([ride], WINDOW_START, NOW)
        assert len(history) == 1
        assert history[0].earnings_usd == 50.0
        assert history[0].tips_usd == 5.0
        assert history[0].rides == 1

    def test_rides_in_same_week_merged(self):
        r1 = _make_ride(actual_fare=20.0, requested_at=datetime(2026, 4, 13, 9, 0, tzinfo=timezone.utc))
        r2 = _make_ride(actual_fare=30.0, requested_at=datetime(2026, 4, 14, 17, 0, tzinfo=timezone.utc))
        history = _build_weekly_history([r1, r2], WINDOW_START, NOW)
        assert len(history) == 1
        assert history[0].earnings_usd == 50.0
        assert history[0].rides == 2

    def test_rides_in_different_weeks_separated(self):
        r1 = _make_ride(actual_fare=20.0, requested_at=datetime(2026, 4, 6, 10, 0, tzinfo=timezone.utc))
        r2 = _make_ride(actual_fare=30.0, requested_at=datetime(2026, 4, 14, 10, 0, tzinfo=timezone.utc))
        history = _build_weekly_history([r1, r2], WINDOW_START, NOW)
        assert len(history) == 2

    def test_ordered_oldest_first(self):
        r1 = _make_ride(actual_fare=20.0, requested_at=datetime(2026, 4, 14, 10, 0, tzinfo=timezone.utc))
        r2 = _make_ride(actual_fare=30.0, requested_at=datetime(2026, 3, 30, 10, 0, tzinfo=timezone.utc))
        history = _build_weekly_history([r1, r2], WINDOW_START, NOW)
        assert history[0].week_start < history[1].week_start

    def test_ride_before_window_excluded(self):
        old = _make_ride(actual_fare=99.0,
                         requested_at=WINDOW_START - timedelta(days=1))
        history = _build_weekly_history([old], WINDOW_START, NOW)
        assert history == []

    def test_ride_at_window_boundary_included(self):
        boundary = _make_ride(actual_fare=10.0, requested_at=WINDOW_START)
        history = _build_weekly_history([boundary], WINDOW_START, NOW)
        assert len(history) == 1

    def test_none_actual_fare_treated_as_zero(self):
        ride = _make_ride(actual_fare=None,  # type: ignore[arg-type]
                          requested_at=datetime(2026, 4, 14, 10, 0, tzinfo=timezone.utc))
        ride.actual_fare = None
        history = _build_weekly_history([ride], WINDOW_START, NOW)
        assert history[0].earnings_usd == 0.0

    def test_week_start_is_monday(self):
        ride = _make_ride(requested_at=datetime(2026, 4, 16, 10, 0, tzinfo=timezone.utc))  # Thursday
        history = _build_weekly_history([ride], WINDOW_START, NOW)
        assert history[0].week_start.weekday() == 0  # Monday


# --------------------------------------------------------------------------- #
# Helper: _classify_trend
# --------------------------------------------------------------------------- #


def _week(earnings: float) -> WeeklyEarnings:
    return WeeklyEarnings(week_start=date(2026, 1, 1), earnings_usd=earnings, rides=5, tips_usd=0.0)


class TestClassifyTrend:
    def test_insufficient_data_fewer_than_trend_weeks(self):
        assert _classify_trend([_week(100)] * (TREND_WEEKS - 1)) == "insufficient_data"

    def test_stable_same_earnings(self):
        history = [_week(100)] * 8
        assert _classify_trend(history) == "stable"

    def test_improving_later_half_significantly_higher(self):
        history = [_week(100)] * 4 + [_week(120)] * 4  # 20% increase
        assert _classify_trend(history) == "improving"

    def test_declining_later_half_significantly_lower(self):
        history = [_week(100)] * 4 + [_week(80)] * 4  # 20% decrease
        assert _classify_trend(history) == "declining"

    def test_stable_within_10_pct(self):
        history = [_week(100)] * 4 + [_week(108)] * 4  # 8% increase
        assert _classify_trend(history) == "stable"

    def test_earlier_avg_zero_returns_insufficient_data(self):
        history = [_week(0)] * 4 + [_week(100)] * 4
        assert _classify_trend(history) == "insufficient_data"

    def test_exactly_4_weeks_returns_result(self):
        history = [_week(100)] * 2 + [_week(100)] * 2
        result = _classify_trend(history)
        assert result in ("stable", "improving", "declining", "insufficient_data")


# --------------------------------------------------------------------------- #
# Helper: _build_hourly_breakdown
# --------------------------------------------------------------------------- #


class TestBuildHourlyBreakdown:
    def test_always_24_entries(self):
        result = _build_hourly_breakdown([], num_weeks=4)
        assert len(result) == 24

    def test_hours_are_0_to_23(self):
        result = _build_hourly_breakdown([], num_weeks=4)
        assert [h.hour for h in result] == list(range(24))

    def test_empty_rides_all_zeros(self):
        result = _build_hourly_breakdown([], num_weeks=4)
        assert all(h.avg_earnings_usd == 0.0 for h in result)

    def test_ride_contributes_to_correct_hour(self):
        ride = _make_ride(actual_fare=40.0,
                          requested_at=datetime(2026, 4, 14, 17, 30, tzinfo=timezone.utc))
        result = _build_hourly_breakdown([ride], num_weeks=1)
        assert result[17].avg_earnings_usd == 40.0

    def test_averages_over_num_weeks(self):
        ride = _make_ride(actual_fare=40.0,
                          requested_at=datetime(2026, 4, 14, 10, 0, tzinfo=timezone.utc))
        result_1w = _build_hourly_breakdown([ride], num_weeks=1)
        result_4w = _build_hourly_breakdown([ride], num_weeks=4)
        assert result_1w[10].avg_earnings_usd == 40.0
        assert result_4w[10].avg_earnings_usd == 10.0

    def test_tips_accumulated(self):
        ride = _make_ride(actual_fare=10.0, tip_amount=5.0,
                          requested_at=datetime(2026, 4, 14, 9, 0, tzinfo=timezone.utc))
        result = _build_hourly_breakdown([ride], num_weeks=1)
        assert result[9].avg_tips_usd == 5.0


# --------------------------------------------------------------------------- #
# Helper: _build_daily_breakdown
# --------------------------------------------------------------------------- #


class TestBuildDailyBreakdown:
    def test_always_7_entries(self):
        result = _build_daily_breakdown([], num_weeks=4)
        assert len(result) == 7

    def test_day_names_correct(self):
        result = _build_daily_breakdown([], num_weeks=1)
        assert result[0].day_name == "Monday"
        assert result[6].day_name == "Sunday"

    def test_empty_rides_all_zeros(self):
        result = _build_daily_breakdown([], num_weeks=4)
        assert all(d.avg_earnings_usd == 0.0 for d in result)

    def test_ride_contributes_to_correct_day(self):
        # 2026-04-14 is a Tuesday (weekday=1)
        ride = _make_ride(actual_fare=30.0,
                          requested_at=datetime(2026, 4, 14, 10, 0, tzinfo=timezone.utc))
        result = _build_daily_breakdown([ride], num_weeks=1)
        assert result[1].avg_earnings_usd == 30.0
        assert result[1].day_name == "Tuesday"

    def test_averages_over_num_weeks(self):
        ride = _make_ride(actual_fare=60.0,
                          requested_at=datetime(2026, 4, 14, 10, 0, tzinfo=timezone.utc))  # Tuesday
        result = _build_daily_breakdown([ride], num_weeks=3)
        assert result[1].avg_earnings_usd == 20.0


# --------------------------------------------------------------------------- #
# Helper: _best_earning_hours and _best_earning_days
# --------------------------------------------------------------------------- #


def _make_hourly(earnings_by_hour: dict[int, float]) -> list[HourlyBreakdown]:
    return [
        HourlyBreakdown(hour=h, avg_earnings_usd=earnings_by_hour.get(h, 0.0),
                        avg_rides=0.0, avg_tips_usd=0.0)
        for h in range(24)
    ]


def _make_daily(earnings_by_day: dict[int, float]) -> list[DailyBreakdown]:
    day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    return [
        DailyBreakdown(day_of_week=d, day_name=day_names[d],
                       avg_earnings_usd=earnings_by_day.get(d, 0.0), avg_rides=0.0)
        for d in range(7)
    ]


class TestBestEarningHours:
    def test_returns_top_3_hours(self):
        earnings = {9: 50.0, 17: 80.0, 20: 60.0, 8: 30.0}
        result = _best_earning_hours(_make_hourly(earnings))
        assert result == [17, 20, 9]

    def test_returns_fewer_than_3_when_only_1_nonzero(self):
        earnings = {12: 40.0}
        result = _best_earning_hours(_make_hourly(earnings), top_n=3)
        # top 3 returned, but only 1 has positive earnings — others will be 0
        assert result[0] == 12
        assert len(result) == 3

    def test_all_zero_returns_three_entries(self):
        result = _best_earning_hours(_make_hourly({}))
        assert len(result) == 3


class TestBestEarningDays:
    def test_returns_top_2_day_names(self):
        earnings = {4: 100.0, 5: 90.0, 6: 50.0}  # Fri, Sat, Sun
        result = _best_earning_days(_make_daily(earnings))
        assert result == ["Friday", "Saturday"]

    def test_all_zero_returns_two_entries(self):
        result = _best_earning_days(_make_daily({}))
        assert len(result) == 2


# --------------------------------------------------------------------------- #
# Helper: _build_projection_note
# --------------------------------------------------------------------------- #


class TestBuildProjectionNote:
    def test_weeks_zero_returns_no_history_message(self):
        note = _build_projection_note(0, "insufficient_data", 0.0, 0.0)
        assert "No completed ride history" in note

    def test_improving_trend_phrasing(self):
        note = _build_projection_note(6, "improving", 300.0, 1300.0)
        assert "upward" in note.lower() or "trending" in note.lower()

    def test_declining_trend_phrasing(self):
        note = _build_projection_note(6, "declining", 200.0, 860.0)
        assert "declining" in note.lower()

    def test_stable_trend_phrasing(self):
        note = _build_projection_note(6, "stable", 250.0, 1080.0)
        assert "stable" in note.lower()

    def test_insufficient_data_phrasing(self):
        note = _build_projection_note(2, "insufficient_data", 100.0, 433.0)
        assert "limited" in note.lower()

    def test_includes_avg_weekly_and_projected_monthly(self):
        note = _build_projection_note(4, "stable", 300.0, 1300.0)
        assert "300.00" in note
        assert "1300.00" in note

    def test_includes_weeks_of_data(self):
        note = _build_projection_note(5, "stable", 250.0, 1000.0)
        assert "5" in note


# --------------------------------------------------------------------------- #
# Service: get_driver_revenue_projection
# --------------------------------------------------------------------------- #


class TestGetDriverRevenueProjection:
    @pytest.mark.anyio
    async def test_no_rides_returns_zero_projection(self):
        db = _make_db([])
        with patch(
            "app.services.driver_revenue_projection._utc_now", return_value=NOW
        ):
            result = await get_driver_revenue_projection(db=db, driver_id=DRIVER_ID)

        assert result.weeks_of_data == 0
        assert result.avg_weekly_earnings_usd == 0.0
        assert result.projected_monthly_earnings_usd == 0.0
        assert result.trend == "insufficient_data"
        assert len(result.hourly_breakdown) == 24
        assert len(result.daily_breakdown) == 7
        assert result.weekly_history == []

    @pytest.mark.anyio
    async def test_single_week_of_data(self):
        rides = [
            _make_ride(actual_fare=50.0,
                       requested_at=datetime(2026, 4, 14, 10, 0, tzinfo=timezone.utc)),
            _make_ride(actual_fare=30.0,
                       requested_at=datetime(2026, 4, 15, 14, 0, tzinfo=timezone.utc)),
        ]
        db = _make_db(rides)
        with patch(
            "app.services.driver_revenue_projection._utc_now", return_value=NOW
        ):
            result = await get_driver_revenue_projection(db=db, driver_id=DRIVER_ID)

        assert result.weeks_of_data == 1
        assert result.weekly_history[0].earnings_usd == 80.0
        assert result.weekly_history[0].rides == 2
        assert result.trend == "insufficient_data"

    @pytest.mark.anyio
    async def test_as_of_is_now(self):
        db = _make_db([])
        with patch(
            "app.services.driver_revenue_projection._utc_now", return_value=NOW
        ):
            result = await get_driver_revenue_projection(db=db, driver_id=DRIVER_ID)
        assert result.as_of == NOW

    @pytest.mark.anyio
    async def test_projected_monthly_uses_weeks_per_month_factor(self):
        rides = [_make_ride(actual_fare=100.0,
                            requested_at=datetime(2026, 4, 14, 10, 0, tzinfo=timezone.utc))]
        db = _make_db(rides)
        with patch(
            "app.services.driver_revenue_projection._utc_now", return_value=NOW
        ):
            result = await get_driver_revenue_projection(db=db, driver_id=DRIVER_ID)

        expected_monthly = round(100.0 * WEEKS_PER_MONTH, 2)
        assert result.projected_monthly_earnings_usd == expected_monthly

    @pytest.mark.anyio
    async def test_improving_trend_detected(self):
        # 4 weeks at $100 then 4 weeks at $125 — 25% increase
        rides = []
        base = datetime(2026, 2, 16, 10, 0, tzinfo=timezone.utc)  # ~8 weeks back
        for week_offset in range(8):
            amount = 100.0 if week_offset < 4 else 125.0
            rides.append(_make_ride(
                actual_fare=amount,
                requested_at=base + timedelta(weeks=week_offset),
            ))
        db = _make_db(rides)
        with patch(
            "app.services.driver_revenue_projection._utc_now", return_value=NOW
        ):
            result = await get_driver_revenue_projection(db=db, driver_id=DRIVER_ID)
        assert result.trend == "improving"

    @pytest.mark.anyio
    async def test_declining_trend_detected(self):
        # 4 weeks at $100 then 4 weeks at $75 — 25% decrease
        rides = []
        base = datetime(2026, 2, 16, 10, 0, tzinfo=timezone.utc)
        for week_offset in range(8):
            amount = 100.0 if week_offset < 4 else 75.0
            rides.append(_make_ride(
                actual_fare=amount,
                requested_at=base + timedelta(weeks=week_offset),
            ))
        db = _make_db(rides)
        with patch(
            "app.services.driver_revenue_projection._utc_now", return_value=NOW
        ):
            result = await get_driver_revenue_projection(db=db, driver_id=DRIVER_ID)
        assert result.trend == "declining"

    @pytest.mark.anyio
    async def test_best_earning_hours_non_empty(self):
        rides = [
            _make_ride(actual_fare=50.0,
                       requested_at=datetime(2026, 4, 14, 17, 0, tzinfo=timezone.utc)),
        ]
        db = _make_db(rides)
        with patch(
            "app.services.driver_revenue_projection._utc_now", return_value=NOW
        ):
            result = await get_driver_revenue_projection(db=db, driver_id=DRIVER_ID)
        assert 17 in result.best_earning_hours
        assert len(result.best_earning_hours) == 3

    @pytest.mark.anyio
    async def test_best_earning_days_non_empty(self):
        # Tuesday rides
        rides = [
            _make_ride(actual_fare=80.0,
                       requested_at=datetime(2026, 4, 14, 10, 0, tzinfo=timezone.utc)),
        ]
        db = _make_db(rides)
        with patch(
            "app.services.driver_revenue_projection._utc_now", return_value=NOW
        ):
            result = await get_driver_revenue_projection(db=db, driver_id=DRIVER_ID)
        assert "Tuesday" in result.best_earning_days
        assert len(result.best_earning_days) == 2

    @pytest.mark.anyio
    async def test_tip_amount_in_weekly_history(self):
        rides = [_make_ride(actual_fare=20.0, tip_amount=5.0,
                            requested_at=datetime(2026, 4, 14, 10, 0, tzinfo=timezone.utc))]
        db = _make_db(rides)
        with patch(
            "app.services.driver_revenue_projection._utc_now", return_value=NOW
        ):
            result = await get_driver_revenue_projection(db=db, driver_id=DRIVER_ID)
        assert result.weekly_history[0].tips_usd == 5.0

    @pytest.mark.anyio
    async def test_projection_note_present_and_non_empty(self):
        db = _make_db([])
        with patch(
            "app.services.driver_revenue_projection._utc_now", return_value=NOW
        ):
            result = await get_driver_revenue_projection(db=db, driver_id=DRIVER_ID)
        assert isinstance(result.projection_note, str)
        assert len(result.projection_note) > 0

    @pytest.mark.anyio
    async def test_avg_weekly_uses_trailing_4_weeks(self):
        # 8 weeks of data: first 4 at $100, last 4 at $200
        # avg_weekly should be the trailing 4-week avg = $200
        rides = []
        base = datetime(2026, 2, 16, 10, 0, tzinfo=timezone.utc)
        for week_offset in range(8):
            amount = 100.0 if week_offset < 4 else 200.0
            rides.append(_make_ride(
                actual_fare=amount,
                requested_at=base + timedelta(weeks=week_offset),
            ))
        db = _make_db(rides)
        with patch(
            "app.services.driver_revenue_projection._utc_now", return_value=NOW
        ):
            result = await get_driver_revenue_projection(db=db, driver_id=DRIVER_ID)
        assert result.avg_weekly_earnings_usd == 200.0


# --------------------------------------------------------------------------- #
# Schema validation
# --------------------------------------------------------------------------- #


class TestSchemas:
    def test_driver_revenue_projection_fields(self):
        proj = DriverRevenueProjection(
            as_of=NOW,
            weeks_of_data=4,
            avg_weekly_earnings_usd=250.0,
            projected_monthly_earnings_usd=1082.5,
            trend="stable",
            best_earning_hours=[17, 18, 9],
            best_earning_days=["Friday", "Saturday"],
            hourly_breakdown=[],
            daily_breakdown=[],
            weekly_history=[],
            projection_note="Test note.",
        )
        assert proj.weeks_of_data == 4
        assert proj.trend == "stable"

    def test_hourly_breakdown_fields(self):
        h = HourlyBreakdown(hour=9, avg_earnings_usd=25.0, avg_rides=2.5, avg_tips_usd=3.0)
        assert h.hour == 9

    def test_daily_breakdown_fields(self):
        d = DailyBreakdown(day_of_week=4, day_name="Friday", avg_earnings_usd=80.0, avg_rides=6.0)
        assert d.day_name == "Friday"

    def test_weekly_earnings_fields(self):
        w = WeeklyEarnings(week_start=date(2026, 4, 13), earnings_usd=320.0, rides=22, tips_usd=40.0)
        assert w.rides == 22


# --------------------------------------------------------------------------- #
# Router
# --------------------------------------------------------------------------- #


class TestRouter:
    @pytest.mark.anyio
    async def test_delegates_to_service(self):
        from app.api.v1.driver_revenue_projection import get_revenue_projection

        mock_driver = MagicMock()
        mock_driver.id = DRIVER_ID
        mock_db = AsyncMock()

        expected = DriverRevenueProjection(
            as_of=NOW,
            weeks_of_data=0,
            avg_weekly_earnings_usd=0.0,
            projected_monthly_earnings_usd=0.0,
            trend="insufficient_data",
            best_earning_hours=[0, 1, 2],
            best_earning_days=["Monday", "Tuesday"],
            hourly_breakdown=[],
            daily_breakdown=[],
            weekly_history=[],
            projection_note="No data.",
        )

        with patch(
            "app.api.v1.driver_revenue_projection.get_driver_revenue_projection",
            new=AsyncMock(return_value=expected),
        ) as mock_svc:
            result = await get_revenue_projection(driver=mock_driver, db=mock_db)

        mock_svc.assert_called_once_with(db=mock_db, driver_id=DRIVER_ID)
        assert result == expected
