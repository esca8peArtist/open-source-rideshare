"""Tests for the driver income stability report feature.

GET /drivers/me/income-stability-report

Coverage
--------
Service layer (get_driver_income_stability_report)
  - No rides → all None/zero, insufficient_data tier, period_weeks=12
  - 1 active week → weeks_analyzed=1, std_dev=None, cv=None, insufficient_data tier
  - 2 active weeks → std_dev computed, stability tier computed
  - CV < 0.2 → stability_tier 'high'
  - CV exactly 0.2 → stability_tier 'moderate'
  - CV 0.2–0.4 → stability_tier 'moderate'
  - CV > 0.4 → stability_tier 'low'
  - Weeks with 0 rides → counted in weeks_inactive, excluded from std_dev calc
  - trend_direction 'improving' (last 4 avg > first 4 avg by >10%)
  - trend_direction 'declining' (last 4 avg < first 4 avg by >10%)
  - trend_direction 'stable' (within ±10%)
  - trend_direction 'insufficient_data' (< 12 week entries)
  - best_week_earnings correctly identified
  - worst_nonzero_week correctly identified
  - weekly_breakdown is sorted newest-first
  - weekly_breakdown always has exactly 12 entries
  - Rides older than 12 weeks excluded
  - guarantee_activations counted when guarantee payments exist
  - guarantee_activations = 0 when no guarantee records
  - had_guarantee_payout True for weeks with paid guarantee
  - weeks_analyzed + weeks_inactive == period_weeks (always 12)
  - period_weeks is always 12
  - mean_weekly_earnings computed over active weeks only
  - stability_note generated for each tier/trend combination
  - stability_note for insufficient_data
  - stability_note for high+improving
  - stability_note for high+stable
  - stability_note for high+declining
  - stability_note for moderate+improving
  - stability_note for low+declining
  - all rides have 0 tip → earnings equals fares only
  - tips included in earnings calculation
  - rides with None actual_fare treated as 0

Helpers (_build_week_windows, _stability_tier, _trend_direction, _build_stability_note)
  - _build_week_windows returns exactly n_weeks entries, newest-first
  - _stability_tier: insufficient_data when weeks_analyzed < 2
  - _stability_tier: insufficient_data when cv is None
  - _stability_tier: high, moderate, low thresholds
  - _trend_direction: both windows all-zero → insufficient_data
  - _trend_direction: oldest_avg=0 and recent>0 → improving

Schema (DriverIncomeStabilityReport, WeeklyEarningsEntry)
  - All required fields present in schema
  - Optional fields can be None
  - weekly_breakdown is a list of WeeklyEarningsEntry

Router (get_income_stability_report)
  - Delegates to service with correct driver.id
  - Returns DriverIncomeStabilityReport
  - Unauthenticated call: service not called (auth handled by dependency)
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.schemas.driver_income_stability import (
    DriverIncomeStabilityReport,
    WeeklyEarningsEntry,
)
from app.services.driver_income_stability import (
    _PERIOD_WEEKS,
    _TREND_THRESHOLD_PCT,
    _build_stability_note,
    _build_week_windows,
    _compute_std_dev,
    _iso_week_monday,
    _stability_tier,
    _trend_direction,
    get_driver_income_stability_report,
)

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

DRIVER_ID = 42
# Pin "today" to a known Monday so ISO weeks are predictable.
# 2026-04-13 is a Monday.
TODAY = date(2026, 4, 13)
NOW = datetime(2026, 4, 13, 12, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Helpers — mock builders
# ---------------------------------------------------------------------------


def _make_ride(
    *,
    actual_fare: Optional[float] = 100.0,
    tip_amount: float = 0.0,
    completed_at: Optional[datetime] = None,
) -> MagicMock:
    ride = MagicMock()
    ride.driver_id = DRIVER_ID
    ride.actual_fare = actual_fare
    ride.tip_amount = tip_amount
    ride.completed_at = completed_at or datetime(2026, 4, 13, 10, 0, 0, tzinfo=timezone.utc)
    return ride


def _make_guarantee_row(week_start: date) -> MagicMock:
    """Simulates a row returned from the guarantee query."""
    row = MagicMock()
    row.__getitem__ = lambda self, i: week_start
    return week_start  # we use {row[0] for row in result} pattern


def _mock_db(rides: list, guarantee_week_starts: Optional[list[date]] = None) -> AsyncMock:
    """Return a mock AsyncSession.

    The service makes two db.execute calls in order:
      1. Ride query → rides
      2. WeeklyGuaranteeRecord query → set of week_start dates
    """
    if guarantee_week_starts is None:
        guarantee_week_starts = []

    db = AsyncMock()

    # First execute: rides
    rides_result = MagicMock()
    rides_result.scalars.return_value.all.return_value = rides

    # Second execute: guarantee records — result iterable yields (week_start,) tuples
    guarantee_result = MagicMock()
    guarantee_result.__iter__ = lambda self: iter(
        [(ws,) for ws in guarantee_week_starts]
    )

    db.execute = AsyncMock(side_effect=[rides_result, guarantee_result])
    return db


def _ride_in_week(week_offset: int, fare: float = 100.0, tip: float = 0.0) -> MagicMock:
    """Create a ride whose completed_at falls in the ISO week `week_offset` weeks before TODAY.

    week_offset=0 → current week, 1 → one week ago, etc.
    """
    monday = _iso_week_monday(TODAY) - timedelta(weeks=week_offset)
    completed_at = datetime(monday.year, monday.month, monday.day, 10, 0, 0, tzinfo=timezone.utc)
    return _make_ride(actual_fare=fare, tip_amount=tip, completed_at=completed_at)


# ---------------------------------------------------------------------------
# _build_week_windows — unit tests
# ---------------------------------------------------------------------------


class TestBuildWeekWindows:
    def test_returns_exactly_n_entries(self):
        windows = _build_week_windows(TODAY, 12)
        assert len(windows) == 12

    def test_newest_first_ordering(self):
        windows = _build_week_windows(TODAY, 12)
        # Each entry's week_start should be 1 week later than the next entry's
        for i in range(len(windows) - 1):
            assert windows[i][0] > windows[i + 1][0]

    def test_first_entry_is_current_week(self):
        windows = _build_week_windows(TODAY, 12)
        expected_monday = _iso_week_monday(TODAY)
        assert windows[0][0] == expected_monday

    def test_each_week_spans_7_days(self):
        windows = _build_week_windows(TODAY, 12)
        for start, end in windows:
            assert (end - start).days == 6

    def test_week_end_is_sunday(self):
        windows = _build_week_windows(TODAY, 12)
        for _, end in windows:
            assert end.weekday() == 6  # Sunday


# ---------------------------------------------------------------------------
# _stability_tier — unit tests
# ---------------------------------------------------------------------------


class TestStabilityTier:
    def test_insufficient_data_when_0_weeks(self):
        assert _stability_tier(None, 0) == "insufficient_data"

    def test_insufficient_data_when_1_week(self):
        assert _stability_tier(0.1, 1) == "insufficient_data"

    def test_insufficient_data_when_cv_none(self):
        assert _stability_tier(None, 5) == "insufficient_data"

    def test_high_when_cv_below_02(self):
        assert _stability_tier(0.19, 4) == "high"

    def test_high_at_cv_zero(self):
        assert _stability_tier(0.0, 3) == "high"

    def test_moderate_at_cv_02(self):
        assert _stability_tier(0.2, 3) == "moderate"

    def test_moderate_at_cv_04(self):
        assert _stability_tier(0.4, 3) == "moderate"

    def test_moderate_between_02_and_04(self):
        assert _stability_tier(0.3, 5) == "moderate"

    def test_low_above_04(self):
        assert _stability_tier(0.41, 3) == "low"

    def test_low_at_high_cv(self):
        assert _stability_tier(1.5, 8) == "low"


# ---------------------------------------------------------------------------
# _trend_direction — unit tests
# ---------------------------------------------------------------------------


def _make_breakdown(earnings_by_week: list[float]) -> list[WeeklyEarningsEntry]:
    """Build a fake weekly_breakdown list (newest-first) from a flat list of floats."""
    entries = []
    for i, earn in enumerate(earnings_by_week):
        monday = _iso_week_monday(TODAY) - timedelta(weeks=i)
        entries.append(
            WeeklyEarningsEntry(
                week_start=monday,
                week_end=monday + timedelta(days=6),
                earnings_usd=earn,
                ride_count=1 if earn > 0 else 0,
                had_guarantee_payout=False,
            )
        )
    return entries


class TestTrendDirection:
    def test_insufficient_data_when_fewer_than_12_entries(self):
        breakdown = _make_breakdown([100.0] * 8)
        assert _trend_direction(breakdown) == "insufficient_data"

    def test_improving_when_recent_avg_exceeds_old_by_over_10pct(self):
        # oldest 4 = 100, recent 4 = 120 → 20% improvement
        earnings = [120.0] * 4 + [110.0] * 4 + [100.0] * 4
        assert _trend_direction(_make_breakdown(earnings)) == "improving"

    def test_declining_when_recent_avg_drops_by_over_10pct(self):
        # oldest 4 = 120, recent 4 = 100 → ~16.7% decline
        earnings = [100.0] * 4 + [110.0] * 4 + [120.0] * 4
        assert _trend_direction(_make_breakdown(earnings)) == "declining"

    def test_stable_within_10pct(self):
        # oldest 4 = 100, recent 4 = 105 → 5% — stable
        earnings = [105.0] * 4 + [103.0] * 4 + [100.0] * 4
        assert _trend_direction(_make_breakdown(earnings)) == "stable"

    def test_both_windows_zero_is_insufficient_data(self):
        earnings = [0.0] * 12
        assert _trend_direction(_make_breakdown(earnings)) == "insufficient_data"

    def test_oldest_zero_recent_positive_is_improving(self):
        # Driver was inactive for oldest 4 weeks but active recently
        earnings = [100.0] * 4 + [50.0] * 4 + [0.0] * 4
        assert _trend_direction(_make_breakdown(earnings)) == "improving"

    def test_exactly_10pct_improvement_is_stable(self):
        # oldest 4 = 100, recent 4 = 110 → exactly 10% — not > threshold
        earnings = [110.0] * 4 + [105.0] * 4 + [100.0] * 4
        assert _trend_direction(_make_breakdown(earnings)) == "stable"


# ---------------------------------------------------------------------------
# _build_stability_note — unit tests
# ---------------------------------------------------------------------------


class TestBuildStabilityNote:
    def test_insufficient_data_note(self):
        note = _build_stability_note("insufficient_data", "insufficient_data")
        assert "not yet enough data" in note.lower() or "insufficient" in note.lower()

    def test_high_improving_note(self):
        note = _build_stability_note("high", "improving")
        assert "highly stable" in note.lower()
        assert "upward" in note.lower()

    def test_high_stable_note(self):
        note = _build_stability_note("high", "stable")
        assert "highly stable" in note.lower()
        assert "steady" in note.lower()

    def test_high_declining_note(self):
        note = _build_stability_note("high", "declining")
        assert "highly stable" in note.lower()
        assert "downward" in note.lower()

    def test_moderate_improving_note(self):
        note = _build_stability_note("moderate", "improving")
        assert "moderately stable" in note.lower()
        assert "upward" in note.lower()

    def test_moderate_stable_note(self):
        note = _build_stability_note("moderate", "stable")
        assert "moderately stable" in note.lower()

    def test_low_declining_note(self):
        note = _build_stability_note("low", "declining")
        assert "volatile" in note.lower()
        assert "downward" in note.lower()

    def test_low_improving_note(self):
        note = _build_stability_note("low", "improving")
        assert "volatile" in note.lower()
        assert "upward" in note.lower()

    def test_note_ends_with_period(self):
        note = _build_stability_note("high", "stable")
        assert note.endswith(".")

    def test_insufficient_data_trend_still_produces_note(self):
        note = _build_stability_note("high", "insufficient_data")
        assert isinstance(note, str)
        assert len(note) > 0


# ---------------------------------------------------------------------------
# _compute_std_dev — unit tests
# ---------------------------------------------------------------------------


class TestComputeStdDev:
    def test_returns_none_for_empty_list(self):
        assert _compute_std_dev([]) is None

    def test_returns_none_for_one_value(self):
        assert _compute_std_dev([100.0]) is None

    def test_two_equal_values_std_dev_zero(self):
        result = _compute_std_dev([100.0, 100.0])
        assert result == pytest.approx(0.0)

    def test_population_std_dev(self):
        # [100, 200]: mean=150, variance=2500, std=50
        result = _compute_std_dev([100.0, 200.0])
        assert result == pytest.approx(50.0)


# ---------------------------------------------------------------------------
# get_driver_income_stability_report — service integration tests (mocked DB)
# ---------------------------------------------------------------------------


class TestGetDriverIncomeStabilityReportService:
    @pytest.mark.asyncio
    async def test_no_rides_returns_zeros_and_insufficient_data(self):
        db = _mock_db(rides=[])
        with patch("app.services.driver_income_stability._utc_now", return_value=NOW):
            result = await get_driver_income_stability_report(db, DRIVER_ID)

        assert result.period_weeks == 12
        assert result.weeks_analyzed == 0
        assert result.weeks_inactive == 12
        assert result.mean_weekly_earnings_usd is None
        assert result.std_dev_weekly_earnings_usd is None
        assert result.coefficient_of_variation is None
        assert result.stability_tier == "insufficient_data"
        assert result.best_week_earnings_usd is None
        assert result.worst_nonzero_week_earnings_usd is None
        assert result.guarantee_activations == 0

    @pytest.mark.asyncio
    async def test_no_rides_weekly_breakdown_has_12_entries(self):
        db = _mock_db(rides=[])
        with patch("app.services.driver_income_stability._utc_now", return_value=NOW):
            result = await get_driver_income_stability_report(db, DRIVER_ID)

        assert len(result.weekly_breakdown) == 12

    @pytest.mark.asyncio
    async def test_1_active_week_gives_insufficient_data_tier(self):
        ride = _ride_in_week(0, fare=200.0)
        db = _mock_db(rides=[ride])
        with patch("app.services.driver_income_stability._utc_now", return_value=NOW):
            result = await get_driver_income_stability_report(db, DRIVER_ID)

        assert result.weeks_analyzed == 1
        assert result.std_dev_weekly_earnings_usd is None
        assert result.coefficient_of_variation is None
        assert result.stability_tier == "insufficient_data"

    @pytest.mark.asyncio
    async def test_2_active_weeks_std_dev_computed(self):
        # Two rides in different weeks: week 0 = $100, week 1 = $200
        r0 = _ride_in_week(0, fare=100.0)
        r1 = _ride_in_week(1, fare=200.0)
        db = _mock_db(rides=[r0, r1])
        with patch("app.services.driver_income_stability._utc_now", return_value=NOW):
            result = await get_driver_income_stability_report(db, DRIVER_ID)

        assert result.weeks_analyzed == 2
        assert result.std_dev_weekly_earnings_usd is not None
        # Population std dev of [100, 200] = 50
        assert result.std_dev_weekly_earnings_usd == pytest.approx(50.0)

    @pytest.mark.asyncio
    async def test_cv_below_02_gives_high_tier(self):
        # 12 weeks, very similar earnings (low CV)
        rides = [_ride_in_week(i, fare=100.0 + i * 0.5) for i in range(12)]
        db = _mock_db(rides=rides)
        with patch("app.services.driver_income_stability._utc_now", return_value=NOW):
            result = await get_driver_income_stability_report(db, DRIVER_ID)

        assert result.coefficient_of_variation is not None
        assert result.coefficient_of_variation < 0.2
        assert result.stability_tier == "high"

    @pytest.mark.asyncio
    async def test_cv_between_02_and_04_gives_moderate_tier(self):
        # Earnings that produce CV ~0.3
        # mean ~100, std ~30 → CV = 0.3
        fares = [70.0, 130.0, 70.0, 130.0, 70.0, 130.0, 70.0, 130.0, 70.0, 130.0, 70.0, 130.0]
        rides = [_ride_in_week(i, fare=fares[i]) for i in range(12)]
        db = _mock_db(rides=rides)
        with patch("app.services.driver_income_stability._utc_now", return_value=NOW):
            result = await get_driver_income_stability_report(db, DRIVER_ID)

        assert result.coefficient_of_variation is not None
        assert 0.2 <= result.coefficient_of_variation <= 0.4
        assert result.stability_tier == "moderate"

    @pytest.mark.asyncio
    async def test_cv_above_04_gives_low_tier(self):
        # Very high variance: some weeks $10, some weeks $300
        fares = [10.0, 300.0, 10.0, 300.0, 10.0, 300.0, 10.0, 300.0, 10.0, 300.0, 10.0, 300.0]
        rides = [_ride_in_week(i, fare=fares[i]) for i in range(12)]
        db = _mock_db(rides=rides)
        with patch("app.services.driver_income_stability._utc_now", return_value=NOW):
            result = await get_driver_income_stability_report(db, DRIVER_ID)

        assert result.coefficient_of_variation is not None
        assert result.coefficient_of_variation > 0.4
        assert result.stability_tier == "low"

    @pytest.mark.asyncio
    async def test_inactive_weeks_excluded_from_std_dev(self):
        # Rides only in weeks 0 and 1; weeks 2–11 are empty.
        # std_dev should be computed from only [100, 200], not [100, 200, 0, 0, ...]
        r0 = _ride_in_week(0, fare=100.0)
        r1 = _ride_in_week(1, fare=200.0)
        db = _mock_db(rides=[r0, r1])
        with patch("app.services.driver_income_stability._utc_now", return_value=NOW):
            result = await get_driver_income_stability_report(db, DRIVER_ID)

        assert result.weeks_inactive == 10
        # std dev of [100, 200] = 50.0 (population)
        assert result.std_dev_weekly_earnings_usd == pytest.approx(50.0)

    @pytest.mark.asyncio
    async def test_weeks_analyzed_plus_inactive_equals_12(self):
        rides = [_ride_in_week(i, fare=100.0) for i in range(5)]
        db = _mock_db(rides=rides)
        with patch("app.services.driver_income_stability._utc_now", return_value=NOW):
            result = await get_driver_income_stability_report(db, DRIVER_ID)

        assert result.weeks_analyzed + result.weeks_inactive == 12

    @pytest.mark.asyncio
    async def test_period_weeks_always_12(self):
        db = _mock_db(rides=[])
        with patch("app.services.driver_income_stability._utc_now", return_value=NOW):
            result = await get_driver_income_stability_report(db, DRIVER_ID)

        assert result.period_weeks == 12

    @pytest.mark.asyncio
    async def test_trend_improving(self):
        # oldest 4 weeks (offsets 8–11) = $100, recent 4 weeks (offsets 0–3) = $200
        rides = (
            [_ride_in_week(i, fare=200.0) for i in range(4)]   # recent
            + [_ride_in_week(i, fare=150.0) for i in range(4, 8)]  # middle
            + [_ride_in_week(i, fare=100.0) for i in range(8, 12)]  # oldest
        )
        db = _mock_db(rides=rides)
        with patch("app.services.driver_income_stability._utc_now", return_value=NOW):
            result = await get_driver_income_stability_report(db, DRIVER_ID)

        assert result.trend_direction == "improving"

    @pytest.mark.asyncio
    async def test_trend_declining(self):
        # oldest 4 weeks = $200, recent 4 weeks = $100
        rides = (
            [_ride_in_week(i, fare=100.0) for i in range(4)]   # recent
            + [_ride_in_week(i, fare=150.0) for i in range(4, 8)]
            + [_ride_in_week(i, fare=200.0) for i in range(8, 12)]  # oldest
        )
        db = _mock_db(rides=rides)
        with patch("app.services.driver_income_stability._utc_now", return_value=NOW):
            result = await get_driver_income_stability_report(db, DRIVER_ID)

        assert result.trend_direction == "declining"

    @pytest.mark.asyncio
    async def test_trend_stable(self):
        # All weeks similar earnings → stable
        rides = [_ride_in_week(i, fare=100.0) for i in range(12)]
        db = _mock_db(rides=rides)
        with patch("app.services.driver_income_stability._utc_now", return_value=NOW):
            result = await get_driver_income_stability_report(db, DRIVER_ID)

        assert result.trend_direction == "stable"

    @pytest.mark.asyncio
    async def test_trend_insufficient_data_when_no_rides(self):
        db = _mock_db(rides=[])
        with patch("app.services.driver_income_stability._utc_now", return_value=NOW):
            result = await get_driver_income_stability_report(db, DRIVER_ID)

        assert result.trend_direction == "insufficient_data"

    @pytest.mark.asyncio
    async def test_best_week_correctly_identified(self):
        rides = [_ride_in_week(0, fare=150.0), _ride_in_week(1, fare=300.0), _ride_in_week(2, fare=50.0)]
        db = _mock_db(rides=rides)
        with patch("app.services.driver_income_stability._utc_now", return_value=NOW):
            result = await get_driver_income_stability_report(db, DRIVER_ID)

        assert result.best_week_earnings_usd == pytest.approx(300.0)

    @pytest.mark.asyncio
    async def test_worst_nonzero_week_excludes_inactive_weeks(self):
        # Only weeks 0 and 3 have rides; worst should be min(150, 50) = 50
        rides = [_ride_in_week(0, fare=150.0), _ride_in_week(3, fare=50.0)]
        db = _mock_db(rides=rides)
        with patch("app.services.driver_income_stability._utc_now", return_value=NOW):
            result = await get_driver_income_stability_report(db, DRIVER_ID)

        assert result.worst_nonzero_week_earnings_usd == pytest.approx(50.0)

    @pytest.mark.asyncio
    async def test_weekly_breakdown_is_sorted_newest_first(self):
        rides = [_ride_in_week(0, fare=100.0), _ride_in_week(5, fare=200.0)]
        db = _mock_db(rides=rides)
        with patch("app.services.driver_income_stability._utc_now", return_value=NOW):
            result = await get_driver_income_stability_report(db, DRIVER_ID)

        starts = [e.week_start for e in result.weekly_breakdown]
        assert starts == sorted(starts, reverse=True)

    @pytest.mark.asyncio
    async def test_weekly_breakdown_always_has_12_entries(self):
        rides = [_ride_in_week(i, fare=100.0) for i in range(6)]
        db = _mock_db(rides=rides)
        with patch("app.services.driver_income_stability._utc_now", return_value=NOW):
            result = await get_driver_income_stability_report(db, DRIVER_ID)

        assert len(result.weekly_breakdown) == 12

    @pytest.mark.asyncio
    async def test_rides_older_than_12_weeks_excluded(self):
        # A ride 13 weeks ago should not appear in any week entry
        old_monday = _iso_week_monday(TODAY) - timedelta(weeks=13)
        old_completed_at = datetime(
            old_monday.year, old_monday.month, old_monday.day,
            10, 0, 0, tzinfo=timezone.utc,
        )
        old_ride = _make_ride(actual_fare=500.0, completed_at=old_completed_at)
        db = _mock_db(rides=[old_ride])
        with patch("app.services.driver_income_stability._utc_now", return_value=NOW):
            result = await get_driver_income_stability_report(db, DRIVER_ID)

        assert result.weeks_analyzed == 0
        assert all(e.earnings_usd == 0.0 for e in result.weekly_breakdown)

    @pytest.mark.asyncio
    async def test_guarantee_activations_counted_correctly(self):
        rides = [_ride_in_week(0, fare=80.0), _ride_in_week(1, fare=90.0), _ride_in_week(2, fare=95.0)]
        # Guarantee paid for weeks 0 and 2
        week_0_monday = _iso_week_monday(TODAY)
        week_2_monday = _iso_week_monday(TODAY) - timedelta(weeks=2)
        db = _mock_db(rides=rides, guarantee_week_starts=[week_0_monday, week_2_monday])
        with patch("app.services.driver_income_stability._utc_now", return_value=NOW):
            result = await get_driver_income_stability_report(db, DRIVER_ID)

        assert result.guarantee_activations == 2

    @pytest.mark.asyncio
    async def test_guarantee_activations_zero_when_none(self):
        rides = [_ride_in_week(0, fare=200.0)]
        db = _mock_db(rides=rides, guarantee_week_starts=[])
        with patch("app.services.driver_income_stability._utc_now", return_value=NOW):
            result = await get_driver_income_stability_report(db, DRIVER_ID)

        assert result.guarantee_activations == 0

    @pytest.mark.asyncio
    async def test_had_guarantee_payout_true_in_correct_week(self):
        rides = [_ride_in_week(1, fare=80.0)]
        week_1_monday = _iso_week_monday(TODAY) - timedelta(weeks=1)
        db = _mock_db(rides=rides, guarantee_week_starts=[week_1_monday])
        with patch("app.services.driver_income_stability._utc_now", return_value=NOW):
            result = await get_driver_income_stability_report(db, DRIVER_ID)

        # Find week 1 entry (second newest)
        week_1_entry = next(
            e for e in result.weekly_breakdown if e.week_start == week_1_monday
        )
        assert week_1_entry.had_guarantee_payout is True
        # Week 0 entry should not have had a payout
        week_0_monday = _iso_week_monday(TODAY)
        week_0_entry = next(
            e for e in result.weekly_breakdown if e.week_start == week_0_monday
        )
        assert week_0_entry.had_guarantee_payout is False

    @pytest.mark.asyncio
    async def test_tips_included_in_earnings(self):
        ride = _ride_in_week(0, fare=80.0, tip=20.0)
        db = _mock_db(rides=[ride])
        with patch("app.services.driver_income_stability._utc_now", return_value=NOW):
            result = await get_driver_income_stability_report(db, DRIVER_ID)

        week_0_monday = _iso_week_monday(TODAY)
        week_entry = next(
            e for e in result.weekly_breakdown if e.week_start == week_0_monday
        )
        assert week_entry.earnings_usd == pytest.approx(100.0)

    @pytest.mark.asyncio
    async def test_none_actual_fare_treated_as_zero(self):
        ride = _make_ride(actual_fare=None, tip_amount=5.0)
        db = _mock_db(rides=[ride])
        with patch("app.services.driver_income_stability._utc_now", return_value=NOW):
            result = await get_driver_income_stability_report(db, DRIVER_ID)

        week_0_monday = _iso_week_monday(TODAY)
        week_entry = next(
            e for e in result.weekly_breakdown if e.week_start == week_0_monday
        )
        assert week_entry.earnings_usd == pytest.approx(5.0)

    @pytest.mark.asyncio
    async def test_mean_computed_over_active_weeks_only(self):
        # Rides only in weeks 0 and 1: $100 and $200
        r0 = _ride_in_week(0, fare=100.0)
        r1 = _ride_in_week(1, fare=200.0)
        db = _mock_db(rides=[r0, r1])
        with patch("app.services.driver_income_stability._utc_now", return_value=NOW):
            result = await get_driver_income_stability_report(db, DRIVER_ID)

        # Mean should be 150, not (300 / 12) = 25
        assert result.mean_weekly_earnings_usd == pytest.approx(150.0)

    @pytest.mark.asyncio
    async def test_stability_note_is_non_empty(self):
        db = _mock_db(rides=[])
        with patch("app.services.driver_income_stability._utc_now", return_value=NOW):
            result = await get_driver_income_stability_report(db, DRIVER_ID)

        assert len(result.stability_note) > 0

    @pytest.mark.asyncio
    async def test_stability_note_reflects_high_stable_tier(self):
        # Very uniform earnings → high tier, stable trend
        rides = [_ride_in_week(i, fare=100.0) for i in range(12)]
        db = _mock_db(rides=rides)
        with patch("app.services.driver_income_stability._utc_now", return_value=NOW):
            result = await get_driver_income_stability_report(db, DRIVER_ID)

        assert result.stability_tier == "high"
        assert "highly stable" in result.stability_note.lower()

    @pytest.mark.asyncio
    async def test_stability_note_reflects_insufficient_data(self):
        db = _mock_db(rides=[])
        with patch("app.services.driver_income_stability._utc_now", return_value=NOW):
            result = await get_driver_income_stability_report(db, DRIVER_ID)

        assert result.stability_tier == "insufficient_data"
        # note should mention data insufficiency
        assert any(
            phrase in result.stability_note.lower()
            for phrase in ["not yet enough", "insufficient", "enough data"]
        )

    @pytest.mark.asyncio
    async def test_multiple_rides_same_week_accumulated(self):
        # 3 rides in the same week
        r1 = _ride_in_week(0, fare=50.0)
        r2 = _ride_in_week(0, fare=60.0)
        r3 = _ride_in_week(0, fare=40.0)
        db = _mock_db(rides=[r1, r2, r3])
        with patch("app.services.driver_income_stability._utc_now", return_value=NOW):
            result = await get_driver_income_stability_report(db, DRIVER_ID)

        week_0_monday = _iso_week_monday(TODAY)
        week_entry = next(
            e for e in result.weekly_breakdown if e.week_start == week_0_monday
        )
        assert week_entry.earnings_usd == pytest.approx(150.0)
        assert week_entry.ride_count == 3
        assert result.weeks_analyzed == 1


# ---------------------------------------------------------------------------
# DriverIncomeStabilityReport schema — unit tests
# ---------------------------------------------------------------------------


class TestDriverIncomeStabilityReportSchema:
    def _make_report(self) -> DriverIncomeStabilityReport:
        monday = _iso_week_monday(TODAY)
        entries = [
            WeeklyEarningsEntry(
                week_start=monday - timedelta(weeks=i),
                week_end=monday - timedelta(weeks=i) + timedelta(days=6),
                earnings_usd=100.0 if i < 6 else 0.0,
                ride_count=5 if i < 6 else 0,
                had_guarantee_payout=False,
            )
            for i in range(12)
        ]
        return DriverIncomeStabilityReport(
            period_weeks=12,
            weeks_analyzed=6,
            weeks_inactive=6,
            mean_weekly_earnings_usd=100.0,
            std_dev_weekly_earnings_usd=0.0,
            coefficient_of_variation=0.0,
            stability_tier="high",
            trend_direction="insufficient_data",
            best_week_earnings_usd=100.0,
            worst_nonzero_week_earnings_usd=100.0,
            guarantee_activations=0,
            weekly_breakdown=entries,
            stability_note="Your income is highly stable over the past 12 weeks.",
        )

    def test_all_required_fields_present(self):
        report = self._make_report()
        assert report.period_weeks == 12
        assert report.weeks_analyzed == 6
        assert report.weeks_inactive == 6
        assert report.stability_tier == "high"
        assert report.trend_direction == "insufficient_data"
        assert len(report.weekly_breakdown) == 12
        assert isinstance(report.stability_note, str)

    def test_optional_fields_can_be_none(self):
        monday = _iso_week_monday(TODAY)
        report = DriverIncomeStabilityReport(
            period_weeks=12,
            weeks_analyzed=0,
            weeks_inactive=12,
            mean_weekly_earnings_usd=None,
            std_dev_weekly_earnings_usd=None,
            coefficient_of_variation=None,
            stability_tier="insufficient_data",
            trend_direction="insufficient_data",
            best_week_earnings_usd=None,
            worst_nonzero_week_earnings_usd=None,
            guarantee_activations=0,
            weekly_breakdown=[
                WeeklyEarningsEntry(
                    week_start=monday - timedelta(weeks=i),
                    week_end=monday - timedelta(weeks=i) + timedelta(days=6),
                    earnings_usd=0.0,
                    ride_count=0,
                    had_guarantee_payout=False,
                )
                for i in range(12)
            ],
            stability_note="Not enough data.",
        )
        assert report.mean_weekly_earnings_usd is None
        assert report.std_dev_weekly_earnings_usd is None
        assert report.coefficient_of_variation is None
        assert report.best_week_earnings_usd is None
        assert report.worst_nonzero_week_earnings_usd is None

    def test_weekly_breakdown_is_list_of_entries(self):
        report = self._make_report()
        assert isinstance(report.weekly_breakdown, list)
        assert all(isinstance(e, WeeklyEarningsEntry) for e in report.weekly_breakdown)

    def test_serialises_to_dict(self):
        report = self._make_report()
        d = report.model_dump()
        assert "weekly_breakdown" in d
        assert "stability_tier" in d
        assert "stability_note" in d
        assert isinstance(d["weekly_breakdown"], list)


# ---------------------------------------------------------------------------
# get_income_stability_report — router unit tests
# ---------------------------------------------------------------------------


class TestGetIncomeStabilityReportRouter:
    @pytest.mark.asyncio
    async def test_router_delegates_to_service(self):
        from app.api.v1.driver_income_stability import get_income_stability_report

        mock_driver = MagicMock()
        mock_driver.id = DRIVER_ID
        mock_db = AsyncMock()

        monday = _iso_week_monday(TODAY)
        stub = DriverIncomeStabilityReport(
            period_weeks=12,
            weeks_analyzed=0,
            weeks_inactive=12,
            mean_weekly_earnings_usd=None,
            std_dev_weekly_earnings_usd=None,
            coefficient_of_variation=None,
            stability_tier="insufficient_data",
            trend_direction="insufficient_data",
            best_week_earnings_usd=None,
            worst_nonzero_week_earnings_usd=None,
            guarantee_activations=0,
            weekly_breakdown=[
                WeeklyEarningsEntry(
                    week_start=monday - timedelta(weeks=i),
                    week_end=monday - timedelta(weeks=i) + timedelta(days=6),
                    earnings_usd=0.0,
                    ride_count=0,
                    had_guarantee_payout=False,
                )
                for i in range(12)
            ],
            stability_note="Not enough data yet.",
        )

        with patch(
            "app.api.v1.driver_income_stability.get_driver_income_stability_report",
            new_callable=AsyncMock,
            return_value=stub,
        ) as mock_service:
            result = await get_income_stability_report(driver=mock_driver, db=mock_db)

        mock_service.assert_called_once_with(db=mock_db, driver_id=DRIVER_ID)
        assert result is stub

    @pytest.mark.asyncio
    async def test_router_passes_correct_driver_id(self):
        from app.api.v1.driver_income_stability import get_income_stability_report

        mock_driver = MagicMock()
        mock_driver.id = 999
        mock_db = AsyncMock()

        monday = _iso_week_monday(TODAY)
        stub = DriverIncomeStabilityReport(
            period_weeks=12,
            weeks_analyzed=0,
            weeks_inactive=12,
            mean_weekly_earnings_usd=None,
            std_dev_weekly_earnings_usd=None,
            coefficient_of_variation=None,
            stability_tier="insufficient_data",
            trend_direction="insufficient_data",
            best_week_earnings_usd=None,
            worst_nonzero_week_earnings_usd=None,
            guarantee_activations=0,
            weekly_breakdown=[
                WeeklyEarningsEntry(
                    week_start=monday - timedelta(weeks=i),
                    week_end=monday - timedelta(weeks=i) + timedelta(days=6),
                    earnings_usd=0.0,
                    ride_count=0,
                    had_guarantee_payout=False,
                )
                for i in range(12)
            ],
            stability_note="Not enough data yet.",
        )

        with patch(
            "app.api.v1.driver_income_stability.get_driver_income_stability_report",
            new_callable=AsyncMock,
            return_value=stub,
        ) as mock_service:
            await get_income_stability_report(driver=mock_driver, db=mock_db)

        call_kwargs = mock_service.call_args.kwargs
        assert call_kwargs["driver_id"] == 999
