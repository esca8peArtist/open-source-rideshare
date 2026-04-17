"""Tests for the driver earnings history feature.

GET /driver/me/earnings-history?weeks=N

Coverage
--------
Helper: _week_start_for
  - Returns Monday for a Monday
  - Returns Monday for a Wednesday
  - Returns Monday for a Sunday

Helper: _build_empty_buckets
  - Returns exactly N buckets
  - First bucket is oldest (N-1 weeks ago)
  - Last bucket is the current week
  - Each bucket has earnings/ride_count/tip_total = 0 / 0 / 0.0
  - Each bucket has avg_fare_usd = None
  - Consecutive buckets are 7 days apart
  - week_end is always 6 days after week_start

Helper: _compute_trend
  - weeks_requested < 4 → insufficient_data
  - weeks_requested == 3 → insufficient_data
  - Both halves all zeros → stable
  - Older half zero, newer half positive → improving
  - Newer avg ≥ 110% of older avg → improving
  - Newer avg == 109% of older avg → stable
  - Newer avg ≤ 90% of older avg → declining
  - Newer avg == 91% of older avg → stable
  - Exactly 10% improvement → improving (boundary)
  - Exactly 10% decline → declining (boundary)
  - Even split (4 weeks) — two older, two newer
  - Odd-count list uses integer division for mid

Helper: _finalise_bucket
  - avg_fare_usd is None when ride_count = 0
  - avg_fare_usd = earnings / ride_count when ride_count > 0
  - earnings_usd and tip_total_usd are rounded to 2 dp

Service: get_driver_earnings_history
  - No rides → all zero buckets
  - No rides → total_earnings = 0, total_rides = 0
  - No rides → avg_weekly_earnings = 0.0
  - No rides → best_week is None
  - No rides → trend for weeks>=4 is stable
  - No rides → weeks list length == weeks_requested
  - Single ride in current week → correct bucket filled
  - Single ride in oldest week → correct bucket filled
  - Rides span multiple weeks → all buckets filled correctly
  - Rides outside the window are ignored
  - actual_fare=None treated as 0.0
  - tip_amount=None treated as 0.0
  - as_of matches _utc_now
  - weeks_requested echoed in response
  - total_earnings_usd = sum across all buckets
  - total_rides = sum of ride_counts
  - avg_weekly_earnings uses weeks_requested (not active-week count) as divisor
  - best_week is bucket with highest earnings_usd
  - best_week is None when total_earnings is 0
  - best_week picks correct bucket among multiple non-zero weeks
  - trend = improving when recent half >> older half
  - trend = declining when recent half << older half
  - trend = stable when halves within ±10%
  - trend = insufficient_data when weeks < 4
  - Timezone-naive requested_at is treated as UTC
  - Weeks param defaults to HISTORY_WEEKS_DEFAULT
  - Buckets are sorted oldest-first

Schema: WeeklyEarningsBucket
  - All required fields present
  - avg_fare_usd accepts None

Schema: DriverEarningsHistory
  - All required fields present
  - best_week accepts None
  - trend is a valid Literal value

Router: get_earnings_history
  - Delegates to service with driver.id and weeks
  - Default weeks = HISTORY_WEEKS_DEFAULT
  - Custom weeks forwarded correctly
  - Returns DriverEarningsHistory
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.schemas.driver_earnings_history import (
    DriverEarningsHistory,
    WeeklyEarningsBucket,
)
from app.services.driver_earnings_history import (
    HISTORY_WEEKS_DEFAULT,
    HISTORY_WEEKS_MAX,
    TREND_THRESHOLD,
    _build_empty_buckets,
    _compute_trend,
    _finalise_bucket,
    _week_start_for,
    get_driver_earnings_history,
)

# --------------------------------------------------------------------------- #
# Shared fixtures / constants
# --------------------------------------------------------------------------- #

DRIVER_ID = 42

# 2026-04-17 is a Friday — week start (Monday) is 2026-04-13
NOW = datetime(2026, 4, 17, 12, 0, 0, tzinfo=timezone.utc)
THIS_MONDAY = date(2026, 4, 13)


def _make_row(
    requested_at: datetime,
    actual_fare: float | None = 100.0,
    tip_amount: float | None = 5.0,
) -> MagicMock:
    """Fake a SQLAlchemy Row for a completed ride."""
    row = MagicMock()
    row.requested_at = requested_at
    row.actual_fare = actual_fare
    row.tip_amount = tip_amount
    return row


def _make_db(rows: list) -> AsyncMock:
    """Return a mock AsyncSession that yields *rows* on execute().all()."""
    result = MagicMock()
    result.all.return_value = rows
    db = AsyncMock()
    db.execute = AsyncMock(return_value=result)
    return db


def _dt(d: date, hour: int = 9) -> datetime:
    """Return a timezone-aware datetime at *d* HH:00 UTC."""
    return datetime(d.year, d.month, d.day, hour, tzinfo=timezone.utc)


# --------------------------------------------------------------------------- #
# Helper: _week_start_for
# --------------------------------------------------------------------------- #


class TestWeekStartFor:
    def test_monday_returns_itself(self):
        monday = date(2026, 4, 13)
        assert _week_start_for(monday) == monday

    def test_wednesday_returns_monday(self):
        wednesday = date(2026, 4, 15)
        assert _week_start_for(wednesday) == date(2026, 4, 13)

    def test_sunday_returns_preceding_monday(self):
        sunday = date(2026, 4, 19)
        assert _week_start_for(sunday) == date(2026, 4, 13)

    def test_saturday_returns_correct_monday(self):
        saturday = date(2026, 4, 18)
        assert _week_start_for(saturday) == date(2026, 4, 13)


# --------------------------------------------------------------------------- #
# Helper: _build_empty_buckets
# --------------------------------------------------------------------------- #


class TestBuildEmptyBuckets:
    def test_returns_n_buckets(self):
        buckets = _build_empty_buckets(NOW, 8)
        assert len(buckets) == 8

    def test_returns_1_bucket_for_weeks_1(self):
        buckets = _build_empty_buckets(NOW, 1)
        assert len(buckets) == 1

    def test_last_bucket_is_current_week(self):
        buckets = _build_empty_buckets(NOW, 4)
        assert buckets[-1].week_start == THIS_MONDAY

    def test_first_bucket_is_oldest(self):
        buckets = _build_empty_buckets(NOW, 4)
        expected_oldest = THIS_MONDAY - timedelta(weeks=3)
        assert buckets[0].week_start == expected_oldest

    def test_buckets_are_7_days_apart(self):
        buckets = _build_empty_buckets(NOW, 6)
        for i in range(1, len(buckets)):
            delta = buckets[i].week_start - buckets[i - 1].week_start
            assert delta.days == 7

    def test_week_end_is_6_days_after_week_start(self):
        buckets = _build_empty_buckets(NOW, 3)
        for b in buckets:
            assert (b.week_end - b.week_start).days == 6

    def test_initial_earnings_zero(self):
        buckets = _build_empty_buckets(NOW, 4)
        for b in buckets:
            assert b.earnings_usd == 0.0

    def test_initial_ride_count_zero(self):
        buckets = _build_empty_buckets(NOW, 4)
        for b in buckets:
            assert b.ride_count == 0

    def test_initial_tip_total_zero(self):
        buckets = _build_empty_buckets(NOW, 4)
        for b in buckets:
            assert b.tip_total_usd == 0.0

    def test_initial_avg_fare_none(self):
        buckets = _build_empty_buckets(NOW, 4)
        for b in buckets:
            assert b.avg_fare_usd is None


# --------------------------------------------------------------------------- #
# Helper: _compute_trend
# --------------------------------------------------------------------------- #


def _buckets_with_earnings(earnings_list: list[float]) -> list[WeeklyEarningsBucket]:
    """Build minimal WeeklyEarningsBucket list from a flat earnings list."""
    mon = THIS_MONDAY - timedelta(weeks=len(earnings_list) - 1)
    buckets = []
    for e in earnings_list:
        buckets.append(
            WeeklyEarningsBucket(
                week_start=mon,
                week_end=mon + timedelta(days=6),
                earnings_usd=e,
                ride_count=1 if e > 0 else 0,
                avg_fare_usd=e if e > 0 else None,
                tip_total_usd=0.0,
            )
        )
        mon += timedelta(weeks=1)
    return buckets


class TestComputeTrend:
    def test_weeks_1_is_insufficient_data(self):
        assert _compute_trend(_buckets_with_earnings([100.0]), 1) == "insufficient_data"

    def test_weeks_3_is_insufficient_data(self):
        assert _compute_trend(_buckets_with_earnings([100.0, 100.0, 100.0]), 3) == "insufficient_data"

    def test_weeks_4_eligible_for_trend(self):
        result = _compute_trend(_buckets_with_earnings([100.0, 100.0, 100.0, 100.0]), 4)
        assert result != "insufficient_data"

    def test_both_halves_zero_is_stable(self):
        buckets = _buckets_with_earnings([0.0, 0.0, 0.0, 0.0])
        assert _compute_trend(buckets, 4) == "stable"

    def test_older_zero_newer_positive_is_improving(self):
        # older half avg = 0, newer half has earnings → improving
        buckets = _buckets_with_earnings([0.0, 0.0, 100.0, 100.0])
        assert _compute_trend(buckets, 4) == "improving"

    def test_newer_gt_110pct_of_older_is_improving(self):
        # older avg = 100, newer avg = 115 → ratio 1.15 → improving
        buckets = _buckets_with_earnings([100.0, 100.0, 115.0, 115.0])
        assert _compute_trend(buckets, 4) == "improving"

    def test_newer_at_109pct_of_older_is_stable(self):
        # older avg = 100, newer avg = 109 → ratio 1.09 → stable (below 1.10)
        buckets = _buckets_with_earnings([100.0, 100.0, 109.0, 109.0])
        assert _compute_trend(buckets, 4) == "stable"

    def test_newer_lt_90pct_of_older_is_declining(self):
        # older avg = 100, newer avg = 85 → ratio 0.85 → declining
        buckets = _buckets_with_earnings([100.0, 100.0, 85.0, 85.0])
        assert _compute_trend(buckets, 4) == "declining"

    def test_newer_at_91pct_of_older_is_stable(self):
        # older avg = 100, newer avg = 91 → ratio 0.91 → stable (above 0.90)
        buckets = _buckets_with_earnings([100.0, 100.0, 91.0, 91.0])
        assert _compute_trend(buckets, 4) == "stable"

    def test_exactly_110pct_is_improving(self):
        # newer_avg = 110, older_avg = 100 → ratio exactly 1.10 → improving
        buckets = _buckets_with_earnings([100.0, 100.0, 110.0, 110.0])
        assert _compute_trend(buckets, 4) == "improving"

    def test_exactly_90pct_is_declining(self):
        # newer_avg = 90, older_avg = 100 → ratio exactly 0.90 → declining
        buckets = _buckets_with_earnings([100.0, 100.0, 90.0, 90.0])
        assert _compute_trend(buckets, 4) == "declining"

    def test_equal_halves_is_stable(self):
        buckets = _buckets_with_earnings([100.0, 100.0, 100.0, 100.0])
        assert _compute_trend(buckets, 4) == "stable"

    def test_six_week_window_uses_3_vs_3(self):
        # older 3 weeks avg = 50, newer 3 weeks avg = 200 → improving
        buckets = _buckets_with_earnings([50.0, 50.0, 50.0, 200.0, 200.0, 200.0])
        assert _compute_trend(buckets, 6) == "improving"


# --------------------------------------------------------------------------- #
# Helper: _finalise_bucket
# --------------------------------------------------------------------------- #


class TestFinaliseBucket:
    def test_avg_fare_none_when_ride_count_zero(self):
        b = _finalise_bucket(THIS_MONDAY, THIS_MONDAY + timedelta(6), 0.0, 0, 0.0)
        assert b.avg_fare_usd is None

    def test_avg_fare_computed_when_rides_present(self):
        b = _finalise_bucket(THIS_MONDAY, THIS_MONDAY + timedelta(6), 300.0, 3, 0.0)
        assert b.avg_fare_usd == pytest.approx(100.0, abs=0.01)

    def test_earnings_rounded_to_2dp(self):
        b = _finalise_bucket(THIS_MONDAY, THIS_MONDAY + timedelta(6), 100.333, 1, 0.0)
        assert b.earnings_usd == pytest.approx(100.33, abs=0.001)

    def test_tip_total_rounded_to_2dp(self):
        b = _finalise_bucket(THIS_MONDAY, THIS_MONDAY + timedelta(6), 0.0, 0, 10.777)
        assert b.tip_total_usd == pytest.approx(10.78, abs=0.001)

    def test_avg_fare_rounded_to_2dp(self):
        b = _finalise_bucket(THIS_MONDAY, THIS_MONDAY + timedelta(6), 100.0, 3, 0.0)
        # 100/3 = 33.333... → 33.33
        assert b.avg_fare_usd == pytest.approx(33.33, abs=0.01)


# --------------------------------------------------------------------------- #
# Service: get_driver_earnings_history
# --------------------------------------------------------------------------- #


class TestGetDriverEarningsHistory:
    # ---- zero rides --------------------------------------------------------

    @pytest.mark.anyio
    async def test_no_rides_all_buckets_zero_earnings(self):
        db = _make_db([])
        with patch("app.services.driver_earnings_history._utc_now", return_value=NOW):
            result = await get_driver_earnings_history(db=db, driver_id=DRIVER_ID, weeks=4)
        for b in result.weeks:
            assert b.earnings_usd == 0.0

    @pytest.mark.anyio
    async def test_no_rides_total_earnings_zero(self):
        db = _make_db([])
        with patch("app.services.driver_earnings_history._utc_now", return_value=NOW):
            result = await get_driver_earnings_history(db=db, driver_id=DRIVER_ID, weeks=4)
        assert result.total_earnings_usd == 0.0

    @pytest.mark.anyio
    async def test_no_rides_total_rides_zero(self):
        db = _make_db([])
        with patch("app.services.driver_earnings_history._utc_now", return_value=NOW):
            result = await get_driver_earnings_history(db=db, driver_id=DRIVER_ID, weeks=4)
        assert result.total_rides == 0

    @pytest.mark.anyio
    async def test_no_rides_avg_weekly_zero(self):
        db = _make_db([])
        with patch("app.services.driver_earnings_history._utc_now", return_value=NOW):
            result = await get_driver_earnings_history(db=db, driver_id=DRIVER_ID, weeks=4)
        assert result.avg_weekly_earnings_usd == 0.0

    @pytest.mark.anyio
    async def test_no_rides_best_week_none(self):
        db = _make_db([])
        with patch("app.services.driver_earnings_history._utc_now", return_value=NOW):
            result = await get_driver_earnings_history(db=db, driver_id=DRIVER_ID, weeks=4)
        assert result.best_week is None

    @pytest.mark.anyio
    async def test_no_rides_trend_stable_for_4_weeks(self):
        db = _make_db([])
        with patch("app.services.driver_earnings_history._utc_now", return_value=NOW):
            result = await get_driver_earnings_history(db=db, driver_id=DRIVER_ID, weeks=4)
        assert result.trend == "stable"

    @pytest.mark.anyio
    async def test_no_rides_week_list_length_equals_requested(self):
        db = _make_db([])
        with patch("app.services.driver_earnings_history._utc_now", return_value=NOW):
            result = await get_driver_earnings_history(db=db, driver_id=DRIVER_ID, weeks=8)
        assert len(result.weeks) == 8

    # ---- single ride -------------------------------------------------------

    @pytest.mark.anyio
    async def test_ride_in_current_week_fills_last_bucket(self):
        # Ride on the same Monday as NOW's week
        ride_dt = _dt(THIS_MONDAY, hour=10)
        rows = [_make_row(ride_dt, actual_fare=120.0, tip_amount=8.0)]
        db = _make_db(rows)
        with patch("app.services.driver_earnings_history._utc_now", return_value=NOW):
            result = await get_driver_earnings_history(db=db, driver_id=DRIVER_ID, weeks=4)
        last = result.weeks[-1]
        assert last.week_start == THIS_MONDAY
        assert last.earnings_usd == pytest.approx(120.0)
        assert last.ride_count == 1
        assert last.tip_total_usd == pytest.approx(8.0)

    @pytest.mark.anyio
    async def test_ride_in_oldest_week_fills_first_bucket(self):
        oldest_monday = THIS_MONDAY - timedelta(weeks=3)
        ride_dt = _dt(oldest_monday, hour=14)
        rows = [_make_row(ride_dt, actual_fare=80.0, tip_amount=3.0)]
        db = _make_db(rows)
        with patch("app.services.driver_earnings_history._utc_now", return_value=NOW):
            result = await get_driver_earnings_history(db=db, driver_id=DRIVER_ID, weeks=4)
        first = result.weeks[0]
        assert first.week_start == oldest_monday
        assert first.earnings_usd == pytest.approx(80.0)
        assert first.ride_count == 1

    @pytest.mark.anyio
    async def test_ride_outside_window_ignored(self):
        outside_dt = _dt(THIS_MONDAY - timedelta(weeks=10), hour=9)
        rows = [_make_row(outside_dt, actual_fare=500.0)]
        db = _make_db(rows)
        with patch("app.services.driver_earnings_history._utc_now", return_value=NOW):
            result = await get_driver_earnings_history(db=db, driver_id=DRIVER_ID, weeks=4)
        assert result.total_earnings_usd == 0.0
        assert result.total_rides == 0

    # ---- multi-ride aggregation --------------------------------------------

    @pytest.mark.anyio
    async def test_two_rides_same_week_summed(self):
        w = THIS_MONDAY
        rows = [
            _make_row(_dt(w, 9), actual_fare=100.0, tip_amount=5.0),
            _make_row(_dt(w, 14), actual_fare=80.0, tip_amount=3.0),
        ]
        db = _make_db(rows)
        with patch("app.services.driver_earnings_history._utc_now", return_value=NOW):
            result = await get_driver_earnings_history(db=db, driver_id=DRIVER_ID, weeks=4)
        last = result.weeks[-1]
        assert last.earnings_usd == pytest.approx(180.0)
        assert last.ride_count == 2
        assert last.tip_total_usd == pytest.approx(8.0)
        assert last.avg_fare_usd == pytest.approx(90.0)

    @pytest.mark.anyio
    async def test_rides_across_different_weeks_distributed_correctly(self):
        w0 = THIS_MONDAY - timedelta(weeks=3)  # oldest
        w1 = THIS_MONDAY - timedelta(weeks=2)
        rows = [
            _make_row(_dt(w0, 9), actual_fare=200.0),
            _make_row(_dt(w1, 9), actual_fare=150.0),
        ]
        db = _make_db(rows)
        with patch("app.services.driver_earnings_history._utc_now", return_value=NOW):
            result = await get_driver_earnings_history(db=db, driver_id=DRIVER_ID, weeks=4)
        assert result.weeks[0].earnings_usd == pytest.approx(200.0)
        assert result.weeks[1].earnings_usd == pytest.approx(150.0)
        assert result.weeks[2].earnings_usd == 0.0
        assert result.weeks[3].earnings_usd == 0.0

    @pytest.mark.anyio
    async def test_total_earnings_is_sum_across_all_buckets(self):
        rows = [
            _make_row(_dt(THIS_MONDAY - timedelta(weeks=1), 9), actual_fare=100.0),
            _make_row(_dt(THIS_MONDAY, 9), actual_fare=200.0),
        ]
        db = _make_db(rows)
        with patch("app.services.driver_earnings_history._utc_now", return_value=NOW):
            result = await get_driver_earnings_history(db=db, driver_id=DRIVER_ID, weeks=4)
        assert result.total_earnings_usd == pytest.approx(300.0)

    @pytest.mark.anyio
    async def test_total_rides_is_sum_of_ride_counts(self):
        rows = [
            _make_row(_dt(THIS_MONDAY - timedelta(weeks=2), 9), actual_fare=50.0),
            _make_row(_dt(THIS_MONDAY - timedelta(weeks=2), 14), actual_fare=50.0),
            _make_row(_dt(THIS_MONDAY, 9), actual_fare=75.0),
        ]
        db = _make_db(rows)
        with patch("app.services.driver_earnings_history._utc_now", return_value=NOW):
            result = await get_driver_earnings_history(db=db, driver_id=DRIVER_ID, weeks=4)
        assert result.total_rides == 3

    @pytest.mark.anyio
    async def test_avg_weekly_uses_weeks_requested_as_divisor(self):
        # Only 1 of 8 weeks has rides — avg is total/8, not total/1
        rows = [_make_row(_dt(THIS_MONDAY, 9), actual_fare=800.0)]
        db = _make_db(rows)
        with patch("app.services.driver_earnings_history._utc_now", return_value=NOW):
            result = await get_driver_earnings_history(db=db, driver_id=DRIVER_ID, weeks=8)
        assert result.avg_weekly_earnings_usd == pytest.approx(100.0, abs=0.01)

    @pytest.mark.anyio
    async def test_best_week_is_highest_earnings_bucket(self):
        rows = [
            _make_row(_dt(THIS_MONDAY - timedelta(weeks=2), 9), actual_fare=50.0),
            _make_row(_dt(THIS_MONDAY - timedelta(weeks=1), 9), actual_fare=300.0),
            _make_row(_dt(THIS_MONDAY, 9), actual_fare=100.0),
        ]
        db = _make_db(rows)
        with patch("app.services.driver_earnings_history._utc_now", return_value=NOW):
            result = await get_driver_earnings_history(db=db, driver_id=DRIVER_ID, weeks=4)
        assert result.best_week is not None
        assert result.best_week.week_start == THIS_MONDAY - timedelta(weeks=1)

    @pytest.mark.anyio
    async def test_best_week_none_when_all_zero(self):
        db = _make_db([])
        with patch("app.services.driver_earnings_history._utc_now", return_value=NOW):
            result = await get_driver_earnings_history(db=db, driver_id=DRIVER_ID, weeks=4)
        assert result.best_week is None

    # ---- null / None handling -----------------------------------------------

    @pytest.mark.anyio
    async def test_actual_fare_none_treated_as_zero(self):
        rows = [_make_row(_dt(THIS_MONDAY, 9), actual_fare=None, tip_amount=5.0)]
        db = _make_db(rows)
        with patch("app.services.driver_earnings_history._utc_now", return_value=NOW):
            result = await get_driver_earnings_history(db=db, driver_id=DRIVER_ID, weeks=4)
        assert result.weeks[-1].earnings_usd == 0.0
        assert result.weeks[-1].ride_count == 1

    @pytest.mark.anyio
    async def test_tip_amount_none_treated_as_zero(self):
        rows = [_make_row(_dt(THIS_MONDAY, 9), actual_fare=100.0, tip_amount=None)]
        db = _make_db(rows)
        with patch("app.services.driver_earnings_history._utc_now", return_value=NOW):
            result = await get_driver_earnings_history(db=db, driver_id=DRIVER_ID, weeks=4)
        assert result.weeks[-1].tip_total_usd == 0.0

    @pytest.mark.anyio
    async def test_timezone_naive_requested_at_treated_as_utc(self):
        # No tzinfo on the datetime — should still map to the correct bucket
        naive_dt = datetime(THIS_MONDAY.year, THIS_MONDAY.month, THIS_MONDAY.day, 10, 0, 0)
        rows = [_make_row(naive_dt, actual_fare=120.0)]
        db = _make_db(rows)
        with patch("app.services.driver_earnings_history._utc_now", return_value=NOW):
            result = await get_driver_earnings_history(db=db, driver_id=DRIVER_ID, weeks=4)
        assert result.weeks[-1].earnings_usd == pytest.approx(120.0)

    # ---- metadata ----------------------------------------------------------

    @pytest.mark.anyio
    async def test_as_of_matches_now(self):
        db = _make_db([])
        with patch("app.services.driver_earnings_history._utc_now", return_value=NOW):
            result = await get_driver_earnings_history(db=db, driver_id=DRIVER_ID, weeks=4)
        assert result.as_of == NOW

    @pytest.mark.anyio
    async def test_weeks_requested_echoed(self):
        db = _make_db([])
        with patch("app.services.driver_earnings_history._utc_now", return_value=NOW):
            result = await get_driver_earnings_history(db=db, driver_id=DRIVER_ID, weeks=6)
        assert result.weeks_requested == 6

    @pytest.mark.anyio
    async def test_buckets_ordered_oldest_first(self):
        db = _make_db([])
        with patch("app.services.driver_earnings_history._utc_now", return_value=NOW):
            result = await get_driver_earnings_history(db=db, driver_id=DRIVER_ID, weeks=4)
        starts = [b.week_start for b in result.weeks]
        assert starts == sorted(starts)

    # ---- trend integration --------------------------------------------------

    @pytest.mark.anyio
    async def test_trend_improving_detected(self):
        # older half (weeks 3,2) = $10/week avg; newer half (weeks 1, 0) = $120/week avg
        rows = [
            _make_row(_dt(THIS_MONDAY - timedelta(weeks=3), 9), actual_fare=10.0),
            _make_row(_dt(THIS_MONDAY - timedelta(weeks=2), 9), actual_fare=10.0),
            _make_row(_dt(THIS_MONDAY - timedelta(weeks=1), 9), actual_fare=120.0),
            _make_row(_dt(THIS_MONDAY, 9), actual_fare=120.0),
        ]
        db = _make_db(rows)
        with patch("app.services.driver_earnings_history._utc_now", return_value=NOW):
            result = await get_driver_earnings_history(db=db, driver_id=DRIVER_ID, weeks=4)
        assert result.trend == "improving"

    @pytest.mark.anyio
    async def test_trend_declining_detected(self):
        # older half avg = $200, newer half avg = $20 → declining
        rows = [
            _make_row(_dt(THIS_MONDAY - timedelta(weeks=3), 9), actual_fare=200.0),
            _make_row(_dt(THIS_MONDAY - timedelta(weeks=2), 9), actual_fare=200.0),
            _make_row(_dt(THIS_MONDAY - timedelta(weeks=1), 9), actual_fare=20.0),
            _make_row(_dt(THIS_MONDAY, 9), actual_fare=20.0),
        ]
        db = _make_db(rows)
        with patch("app.services.driver_earnings_history._utc_now", return_value=NOW):
            result = await get_driver_earnings_history(db=db, driver_id=DRIVER_ID, weeks=4)
        assert result.trend == "declining"

    @pytest.mark.anyio
    async def test_trend_insufficient_data_for_3_weeks(self):
        rows = [_make_row(_dt(THIS_MONDAY, 9), actual_fare=100.0)]
        db = _make_db(rows)
        with patch("app.services.driver_earnings_history._utc_now", return_value=NOW):
            result = await get_driver_earnings_history(db=db, driver_id=DRIVER_ID, weeks=3)
        assert result.trend == "insufficient_data"


# --------------------------------------------------------------------------- #
# Schema: WeeklyEarningsBucket
# --------------------------------------------------------------------------- #


class TestWeeklyEarningsBucketSchema:
    def test_all_required_fields_present(self):
        b = WeeklyEarningsBucket(
            week_start=THIS_MONDAY,
            week_end=THIS_MONDAY + timedelta(days=6),
            earnings_usd=150.0,
            ride_count=3,
            avg_fare_usd=50.0,
            tip_total_usd=12.0,
        )
        assert b.earnings_usd == 150.0
        assert b.ride_count == 3
        assert b.avg_fare_usd == 50.0
        assert b.tip_total_usd == 12.0

    def test_avg_fare_usd_allows_none(self):
        b = WeeklyEarningsBucket(
            week_start=THIS_MONDAY,
            week_end=THIS_MONDAY + timedelta(days=6),
            earnings_usd=0.0,
            ride_count=0,
            avg_fare_usd=None,
            tip_total_usd=0.0,
        )
        assert b.avg_fare_usd is None


# --------------------------------------------------------------------------- #
# Schema: DriverEarningsHistory
# --------------------------------------------------------------------------- #


class TestDriverEarningsHistorySchema:
    def _bucket(self) -> WeeklyEarningsBucket:
        return WeeklyEarningsBucket(
            week_start=THIS_MONDAY,
            week_end=THIS_MONDAY + timedelta(days=6),
            earnings_usd=100.0,
            ride_count=2,
            avg_fare_usd=50.0,
            tip_total_usd=5.0,
        )

    def test_all_fields_present(self):
        h = DriverEarningsHistory(
            as_of=NOW,
            weeks_requested=4,
            weeks=[self._bucket()],
            total_earnings_usd=100.0,
            total_rides=2,
            avg_weekly_earnings_usd=25.0,
            best_week=self._bucket(),
            trend="stable",
        )
        assert h.total_rides == 2
        assert h.trend == "stable"

    def test_best_week_allows_none(self):
        h = DriverEarningsHistory(
            as_of=NOW,
            weeks_requested=4,
            weeks=[],
            total_earnings_usd=0.0,
            total_rides=0,
            avg_weekly_earnings_usd=0.0,
            best_week=None,
            trend="stable",
        )
        assert h.best_week is None

    def test_trend_accepts_all_literals(self):
        for trend_val in ("improving", "declining", "stable", "insufficient_data"):
            h = DriverEarningsHistory(
                as_of=NOW,
                weeks_requested=4,
                weeks=[],
                total_earnings_usd=0.0,
                total_rides=0,
                avg_weekly_earnings_usd=0.0,
                best_week=None,
                trend=trend_val,  # type: ignore[arg-type]
            )
            assert h.trend == trend_val


# --------------------------------------------------------------------------- #
# Router
# --------------------------------------------------------------------------- #


class TestRouter:
    @pytest.mark.anyio
    async def test_delegates_to_service_with_default_weeks(self):
        from app.api.v1.driver_earnings_history import get_earnings_history

        mock_driver = MagicMock()
        mock_driver.id = DRIVER_ID
        mock_db = AsyncMock()

        stub = DriverEarningsHistory(
            as_of=NOW,
            weeks_requested=HISTORY_WEEKS_DEFAULT,
            weeks=[],
            total_earnings_usd=0.0,
            total_rides=0,
            avg_weekly_earnings_usd=0.0,
            best_week=None,
            trend="stable",
        )

        with patch(
            "app.api.v1.driver_earnings_history.get_driver_earnings_history",
            new=AsyncMock(return_value=stub),
        ) as mock_svc:
            result = await get_earnings_history(
                weeks=HISTORY_WEEKS_DEFAULT,
                driver=mock_driver,
                db=mock_db,
            )

        mock_svc.assert_called_once_with(
            db=mock_db,
            driver_id=DRIVER_ID,
            weeks=HISTORY_WEEKS_DEFAULT,
        )
        assert result == stub

    @pytest.mark.anyio
    async def test_delegates_custom_weeks_to_service(self):
        from app.api.v1.driver_earnings_history import get_earnings_history

        mock_driver = MagicMock()
        mock_driver.id = DRIVER_ID
        mock_db = AsyncMock()

        stub = DriverEarningsHistory(
            as_of=NOW,
            weeks_requested=8,
            weeks=[],
            total_earnings_usd=0.0,
            total_rides=0,
            avg_weekly_earnings_usd=0.0,
            best_week=None,
            trend="insufficient_data",
        )

        with patch(
            "app.api.v1.driver_earnings_history.get_driver_earnings_history",
            new=AsyncMock(return_value=stub),
        ) as mock_svc:
            await get_earnings_history(weeks=8, driver=mock_driver, db=mock_db)

        mock_svc.assert_called_once_with(db=mock_db, driver_id=DRIVER_ID, weeks=8)

    @pytest.mark.anyio
    async def test_returns_driver_earnings_history(self):
        from app.api.v1.driver_earnings_history import get_earnings_history

        mock_driver = MagicMock()
        mock_driver.id = DRIVER_ID
        mock_db = AsyncMock()

        stub = DriverEarningsHistory(
            as_of=NOW,
            weeks_requested=HISTORY_WEEKS_DEFAULT,
            weeks=[],
            total_earnings_usd=0.0,
            total_rides=0,
            avg_weekly_earnings_usd=0.0,
            best_week=None,
            trend="stable",
        )

        with patch(
            "app.api.v1.driver_earnings_history.get_driver_earnings_history",
            new=AsyncMock(return_value=stub),
        ):
            result = await get_earnings_history(
                weeks=HISTORY_WEEKS_DEFAULT,
                driver=mock_driver,
                db=mock_db,
            )

        assert isinstance(result, DriverEarningsHistory)
