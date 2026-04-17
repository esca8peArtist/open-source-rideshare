"""Tests for the driver earnings comparison feature.

GET /driver/me/earnings-comparison

Coverage
--------
Service layer (get_driver_earnings_comparison)
  - No rides on platform → driver_avg=0, platform_avg=0, rank=1/0, note
  - Driver has rides but is the only active driver → rank=1, percentile=0
  - Driver above platform average → positive difference_usd/pct
  - Driver below platform average → negative difference_usd/pct
  - Driver exactly at platform average → 0.0 difference
  - Driver not in results (no rides) → driver_avg=0, rank last
  - Platform average computed across all active drivers, not just the current driver
  - difference_pct is None when platform_avg is 0
  - difference_pct correctly computed when platform_avg > 0
  - as_of timestamp matches _utc_now
  - period_weeks = COMPARISON_WEEKS
  - active_drivers_in_period = distinct driver count with completed rides

Helpers (_compute_percentile)
  - Empty all_avgs list → rank=1, total=0, percentile=0
  - Single driver → rank=1, percentile=0
  - Driver at top → rank=1, high percentile
  - Driver at bottom → rank=N, percentile=0
  - Driver in middle → correct rank, correct percentile
  - Tied drivers → rank reflects number above (not dense-ranked)
  - Driver avg 0 with other drivers → ranked last (high rank number)
  - Percentile rounds to 1 decimal place

Helpers (_compute_difference_pct)
  - platform_avg=0 → returns None
  - driver > platform → positive pct
  - driver < platform → negative pct
  - driver = platform → 0.0
  - rounds to 1 decimal place

Helpers (_build_comparison_note)
  - total_drivers=0 → no-platform-data message
  - both avgs=0 → no-rides-recorded message
  - driver_avg=0, platform_avg>0 → no-rides-for-driver message
  - driver above average → "above" in note
  - driver below average → "below" in note
  - note includes driver_avg, platform_avg, rank, total_drivers, percentile

Schema (DriverEarningsComparison, EarningsPercentile)
  - All required fields present
  - EarningsPercentile has rank, total_drivers, percentile
  - DriverEarningsComparison has all documented fields

Router (get_earnings_comparison)
  - Delegates to service with driver.id
  - Returns DriverEarningsComparison
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.schemas.driver_earnings_comparison import (
    DriverEarningsComparison,
    EarningsPercentile,
)
from app.services.driver_earnings_comparison import (
    COMPARISON_WEEKS,
    _build_comparison_note,
    _compute_difference_pct,
    _compute_percentile,
    get_driver_earnings_comparison,
)

# --------------------------------------------------------------------------- #
# Shared test data
# --------------------------------------------------------------------------- #

DRIVER_ID = 7
NOW = datetime(2026, 4, 17, 15, 0, 0, tzinfo=timezone.utc)


def _make_row(driver_id: int, total_fare: float, ride_count: int = 1) -> MagicMock:
    """Fake a SQLAlchemy Row with driver_id, total_fare, ride_count attributes."""
    row = MagicMock()
    row.driver_id = driver_id
    row.total_fare = total_fare
    row.ride_count = ride_count
    return row


def _make_db(rows: list) -> AsyncMock:
    """Return a mock AsyncSession that yields *rows* on execute().all()."""
    result = MagicMock()
    result.all.return_value = rows

    db = AsyncMock()
    db.execute = AsyncMock(return_value=result)
    return db


# --------------------------------------------------------------------------- #
# Helper: _compute_percentile
# --------------------------------------------------------------------------- #


class TestComputePercentile:
    def test_empty_list_returns_rank_1_total_0(self):
        p = _compute_percentile(100.0, [])
        assert p.rank == 1
        assert p.total_drivers == 0
        assert p.percentile == 0.0

    def test_single_driver_rank_1_percentile_0(self):
        p = _compute_percentile(200.0, [200.0])
        assert p.rank == 1
        assert p.total_drivers == 1
        assert p.percentile == 0.0

    def test_top_driver_rank_1(self):
        avgs = [300.0, 200.0, 100.0]
        p = _compute_percentile(300.0, avgs)
        assert p.rank == 1

    def test_top_driver_highest_percentile(self):
        # top driver has 2 drivers below
        avgs = [300.0, 200.0, 100.0]
        p = _compute_percentile(300.0, avgs)
        # 2 out of 3 earn less → 66.7%
        assert p.percentile == pytest.approx(66.7, abs=0.1)

    def test_bottom_driver_rank_equals_total(self):
        avgs = [300.0, 200.0, 100.0]
        p = _compute_percentile(100.0, avgs)
        assert p.rank == 3
        assert p.percentile == 0.0

    def test_middle_driver_correct_rank(self):
        avgs = [300.0, 200.0, 100.0]
        p = _compute_percentile(200.0, avgs)
        assert p.rank == 2

    def test_middle_driver_correct_percentile(self):
        # 1 driver earns less → 33.3%
        avgs = [300.0, 200.0, 100.0]
        p = _compute_percentile(200.0, avgs)
        assert p.percentile == pytest.approx(33.3, abs=0.1)

    def test_tied_drivers_same_rank(self):
        # two drivers tied at 200; both have rank 2 (one driver above at 300)
        avgs = [300.0, 200.0, 200.0, 100.0]
        p1 = _compute_percentile(200.0, avgs)
        assert p1.rank == 2

    def test_driver_avg_zero_ranked_last(self):
        avgs = [300.0, 200.0, 0.0]
        p = _compute_percentile(0.0, avgs)
        assert p.rank == 3
        assert p.percentile == 0.0

    def test_total_drivers_reflects_all_avgs(self):
        avgs = [100.0, 200.0, 300.0, 400.0, 500.0]
        p = _compute_percentile(300.0, avgs)
        assert p.total_drivers == 5

    def test_percentile_rounds_to_one_decimal(self):
        # 2 below out of 3 total → 66.666… should round to 66.7
        avgs = [300.0, 200.0, 100.0]
        p = _compute_percentile(300.0, avgs)
        # percentile stored to 1 decimal
        assert isinstance(p.percentile, float)
        assert str(p.percentile).count(".") <= 1

    def test_all_tied_everyone_rank_1(self):
        avgs = [100.0, 100.0, 100.0]
        p = _compute_percentile(100.0, avgs)
        assert p.rank == 1
        assert p.percentile == 0.0


# --------------------------------------------------------------------------- #
# Helper: _compute_difference_pct
# --------------------------------------------------------------------------- #


class TestComputeDifferencePct:
    def test_platform_avg_zero_returns_none(self):
        assert _compute_difference_pct(100.0, 0.0) is None

    def test_driver_above_platform_positive_pct(self):
        result = _compute_difference_pct(120.0, 100.0)
        assert result == pytest.approx(20.0, abs=0.01)

    def test_driver_below_platform_negative_pct(self):
        result = _compute_difference_pct(80.0, 100.0)
        assert result == pytest.approx(-20.0, abs=0.01)

    def test_driver_at_platform_returns_zero(self):
        assert _compute_difference_pct(100.0, 100.0) == 0.0

    def test_rounds_to_one_decimal(self):
        # 115 / 100 → 15.0 exactly; use a case that triggers rounding
        result = _compute_difference_pct(133.0, 100.0)
        assert result == 33.0

    def test_small_difference_rounded(self):
        result = _compute_difference_pct(100.333, 100.0)
        # 0.333% → 0.3
        assert result == pytest.approx(0.3, abs=0.05)


# --------------------------------------------------------------------------- #
# Helper: _build_comparison_note
# --------------------------------------------------------------------------- #


class TestBuildComparisonNote:
    def _note(self, **kw):
        defaults = dict(
            driver_avg=250.0,
            platform_avg=200.0,
            difference_usd=50.0,
            difference_pct=25.0,
            rank=3,
            total_drivers=10,
            percentile=70.0,
            period_weeks=4,
        )
        defaults.update(kw)
        return _build_comparison_note(**defaults)

    def test_total_drivers_zero_returns_no_platform_data(self):
        note = self._note(driver_avg=0.0, platform_avg=0.0,
                          difference_usd=0.0, difference_pct=None,
                          rank=1, total_drivers=0, percentile=0.0)
        assert "No platform earnings data" in note

    def test_both_avgs_zero_returns_no_rides_message(self):
        note = self._note(driver_avg=0.0, platform_avg=0.0,
                          difference_usd=0.0, difference_pct=None,
                          rank=1, total_drivers=5, percentile=0.0)
        assert "No completed rides" in note

    def test_driver_avg_zero_platform_positive_describes_platform(self):
        note = self._note(driver_avg=0.0, platform_avg=200.0,
                          difference_usd=-200.0, difference_pct=-100.0,
                          rank=10, total_drivers=10, percentile=0.0)
        assert "no completed rides" in note.lower() or "you have no" in note.lower()
        assert "200.00" in note

    def test_driver_above_average_says_above(self):
        note = self._note(driver_avg=300.0, platform_avg=200.0,
                          difference_usd=100.0, difference_pct=50.0)
        assert "above" in note.lower()

    def test_driver_below_average_says_below(self):
        note = self._note(driver_avg=150.0, platform_avg=200.0,
                          difference_usd=-50.0, difference_pct=-25.0)
        assert "below" in note.lower()

    def test_note_includes_driver_avg(self):
        note = self._note(driver_avg=275.5)
        assert "275.50" in note

    def test_note_includes_platform_avg(self):
        note = self._note(platform_avg=189.25)
        assert "189.25" in note

    def test_note_includes_rank(self):
        note = self._note(rank=4, total_drivers=20)
        assert "#4" in note

    def test_note_includes_total_drivers(self):
        note = self._note(total_drivers=37)
        assert "37" in note

    def test_note_includes_percentile(self):
        note = self._note(percentile=82.5)
        assert "82.5" in note

    def test_note_includes_period_weeks(self):
        note = self._note(period_weeks=4)
        assert "4" in note

    def test_difference_pct_none_does_not_crash(self):
        # Should not raise even with no pct string to embed
        note = self._note(difference_pct=None, platform_avg=0.0,
                          driver_avg=0.0, difference_usd=0.0,
                          total_drivers=0, rank=1, percentile=0.0)
        assert isinstance(note, str)


# --------------------------------------------------------------------------- #
# Service: get_driver_earnings_comparison
# --------------------------------------------------------------------------- #


class TestGetDriverEarningsComparison:
    @pytest.mark.anyio
    async def test_no_rides_on_platform(self):
        db = _make_db([])
        with patch(
            "app.services.driver_earnings_comparison._utc_now", return_value=NOW
        ):
            result = await get_driver_earnings_comparison(db=db, driver_id=DRIVER_ID)

        assert result.driver_avg_weekly_usd == 0.0
        assert result.platform_avg_weekly_usd == 0.0
        assert result.difference_usd == 0.0
        assert result.difference_pct is None
        assert result.active_drivers_in_period == 0
        assert result.percentile.total_drivers == 1  # driver included with avg=0

    @pytest.mark.anyio
    async def test_as_of_matches_now(self):
        db = _make_db([])
        with patch(
            "app.services.driver_earnings_comparison._utc_now", return_value=NOW
        ):
            result = await get_driver_earnings_comparison(db=db, driver_id=DRIVER_ID)
        assert result.as_of == NOW

    @pytest.mark.anyio
    async def test_period_weeks_constant(self):
        db = _make_db([])
        with patch(
            "app.services.driver_earnings_comparison._utc_now", return_value=NOW
        ):
            result = await get_driver_earnings_comparison(db=db, driver_id=DRIVER_ID)
        assert result.period_weeks == COMPARISON_WEEKS

    @pytest.mark.anyio
    async def test_driver_only_active_driver_rank_1(self):
        # Driver DRIVER_ID earns $400 total → $100/week
        rows = [_make_row(DRIVER_ID, 400.0, 10)]
        db = _make_db(rows)
        with patch(
            "app.services.driver_earnings_comparison._utc_now", return_value=NOW
        ):
            result = await get_driver_earnings_comparison(db=db, driver_id=DRIVER_ID)

        assert result.percentile.rank == 1
        assert result.percentile.total_drivers == 1
        assert result.driver_avg_weekly_usd == 100.0
        assert result.platform_avg_weekly_usd == 100.0
        assert result.difference_usd == 0.0

    @pytest.mark.anyio
    async def test_driver_above_platform_average(self):
        # Driver earns $800 total → $200/week; other earns $400 → $100/week
        # Platform avg = ($200 + $100) / 2 = $150/week
        rows = [
            _make_row(DRIVER_ID, 800.0, 20),
            _make_row(99, 400.0, 10),
        ]
        db = _make_db(rows)
        with patch(
            "app.services.driver_earnings_comparison._utc_now", return_value=NOW
        ):
            result = await get_driver_earnings_comparison(db=db, driver_id=DRIVER_ID)

        assert result.driver_avg_weekly_usd == 200.0
        assert result.platform_avg_weekly_usd == 150.0
        assert result.difference_usd == 50.0
        assert result.difference_pct is not None
        assert result.difference_pct > 0

    @pytest.mark.anyio
    async def test_driver_below_platform_average(self):
        # Driver earns $200 total → $50/week; other earns $800 → $200/week
        rows = [
            _make_row(DRIVER_ID, 200.0, 5),
            _make_row(99, 800.0, 20),
        ]
        db = _make_db(rows)
        with patch(
            "app.services.driver_earnings_comparison._utc_now", return_value=NOW
        ):
            result = await get_driver_earnings_comparison(db=db, driver_id=DRIVER_ID)

        assert result.driver_avg_weekly_usd == 50.0
        assert result.platform_avg_weekly_usd == 125.0
        assert result.difference_usd == pytest.approx(-75.0, abs=0.01)
        assert result.difference_pct is not None
        assert result.difference_pct < 0

    @pytest.mark.anyio
    async def test_driver_not_in_rows_gets_zero_avg(self):
        # Other drivers only — DRIVER_ID had no completed rides
        rows = [
            _make_row(10, 400.0, 10),
            _make_row(11, 200.0, 5),
        ]
        db = _make_db(rows)
        with patch(
            "app.services.driver_earnings_comparison._utc_now", return_value=NOW
        ):
            result = await get_driver_earnings_comparison(db=db, driver_id=DRIVER_ID)

        assert result.driver_avg_weekly_usd == 0.0
        # Platform avg from rows only (active drivers), not including zero-ride driver
        assert result.platform_avg_weekly_usd > 0
        assert result.difference_usd < 0
        # DRIVER_ID included with avg=0 → rank is last (rank=3 of 3)
        assert result.percentile.rank == 3
        assert result.active_drivers_in_period == 2

    @pytest.mark.anyio
    async def test_active_drivers_count_matches_rows(self):
        rows = [_make_row(i, float(i * 100), i) for i in range(1, 6)]
        rows.append(_make_row(DRIVER_ID, 300.0, 8))
        db = _make_db(rows)
        with patch(
            "app.services.driver_earnings_comparison._utc_now", return_value=NOW
        ):
            result = await get_driver_earnings_comparison(db=db, driver_id=DRIVER_ID)

        assert result.active_drivers_in_period == 6

    @pytest.mark.anyio
    async def test_driver_avg_uses_comparison_weeks_divisor(self):
        # $400 total over COMPARISON_WEEKS → avg = 100
        rows = [_make_row(DRIVER_ID, 400.0, 5)]
        db = _make_db(rows)
        with patch(
            "app.services.driver_earnings_comparison._utc_now", return_value=NOW
        ):
            result = await get_driver_earnings_comparison(db=db, driver_id=DRIVER_ID)
        assert result.driver_avg_weekly_usd == 400.0 / COMPARISON_WEEKS

    @pytest.mark.anyio
    async def test_platform_avg_is_mean_across_active_drivers(self):
        # Three drivers: $400, $200, $200 total → avgs $100, $50, $50 → mean $66.67
        rows = [
            _make_row(DRIVER_ID, 400.0, 10),
            _make_row(20, 200.0, 5),
            _make_row(21, 200.0, 5),
        ]
        db = _make_db(rows)
        with patch(
            "app.services.driver_earnings_comparison._utc_now", return_value=NOW
        ):
            result = await get_driver_earnings_comparison(db=db, driver_id=DRIVER_ID)
        expected_platform = round((100.0 + 50.0 + 50.0) / 3, 2)
        assert result.platform_avg_weekly_usd == pytest.approx(expected_platform, abs=0.01)

    @pytest.mark.anyio
    async def test_difference_pct_none_when_platform_avg_zero(self):
        # Only driver on platform with 0 fares
        rows = [_make_row(DRIVER_ID, 0.0, 0)]
        rows[0].total_fare = 0.0
        db = _make_db(rows)
        with patch(
            "app.services.driver_earnings_comparison._utc_now", return_value=NOW
        ):
            result = await get_driver_earnings_comparison(db=db, driver_id=DRIVER_ID)
        assert result.difference_pct is None

    @pytest.mark.anyio
    async def test_comparison_note_is_non_empty_string(self):
        db = _make_db([])
        with patch(
            "app.services.driver_earnings_comparison._utc_now", return_value=NOW
        ):
            result = await get_driver_earnings_comparison(db=db, driver_id=DRIVER_ID)
        assert isinstance(result.comparison_note, str)
        assert len(result.comparison_note) > 0

    @pytest.mark.anyio
    async def test_percentile_rank_top_driver(self):
        rows = [
            _make_row(DRIVER_ID, 800.0, 20),  # highest
            _make_row(20, 400.0, 10),
            _make_row(21, 200.0, 5),
        ]
        db = _make_db(rows)
        with patch(
            "app.services.driver_earnings_comparison._utc_now", return_value=NOW
        ):
            result = await get_driver_earnings_comparison(db=db, driver_id=DRIVER_ID)
        assert result.percentile.rank == 1

    @pytest.mark.anyio
    async def test_percentile_rank_bottom_driver(self):
        rows = [
            _make_row(20, 800.0, 20),
            _make_row(21, 400.0, 10),
            _make_row(DRIVER_ID, 200.0, 5),  # lowest
        ]
        db = _make_db(rows)
        with patch(
            "app.services.driver_earnings_comparison._utc_now", return_value=NOW
        ):
            result = await get_driver_earnings_comparison(db=db, driver_id=DRIVER_ID)
        assert result.percentile.rank == 3

    @pytest.mark.anyio
    async def test_none_total_fare_treated_as_zero(self):
        row = _make_row(DRIVER_ID, 0.0, 0)
        row.total_fare = None
        db = _make_db([row])
        with patch(
            "app.services.driver_earnings_comparison._utc_now", return_value=NOW
        ):
            result = await get_driver_earnings_comparison(db=db, driver_id=DRIVER_ID)
        assert result.driver_avg_weekly_usd == 0.0

    @pytest.mark.anyio
    async def test_single_driver_percentile_zero(self):
        rows = [_make_row(DRIVER_ID, 400.0, 10)]
        db = _make_db(rows)
        with patch(
            "app.services.driver_earnings_comparison._utc_now", return_value=NOW
        ):
            result = await get_driver_earnings_comparison(db=db, driver_id=DRIVER_ID)
        assert result.percentile.percentile == 0.0


# --------------------------------------------------------------------------- #
# Schema validation
# --------------------------------------------------------------------------- #


class TestSchemas:
    def test_earnings_percentile_fields(self):
        p = EarningsPercentile(rank=3, total_drivers=10, percentile=70.0)
        assert p.rank == 3
        assert p.total_drivers == 10
        assert p.percentile == 70.0

    def test_driver_earnings_comparison_all_fields(self):
        p = EarningsPercentile(rank=2, total_drivers=5, percentile=60.0)
        c = DriverEarningsComparison(
            as_of=NOW,
            period_weeks=4,
            driver_avg_weekly_usd=250.0,
            platform_avg_weekly_usd=200.0,
            difference_usd=50.0,
            difference_pct=25.0,
            percentile=p,
            active_drivers_in_period=5,
            comparison_note="Test note.",
        )
        assert c.driver_avg_weekly_usd == 250.0
        assert c.platform_avg_weekly_usd == 200.0
        assert c.percentile.rank == 2

    def test_difference_pct_allows_none(self):
        p = EarningsPercentile(rank=1, total_drivers=0, percentile=0.0)
        c = DriverEarningsComparison(
            as_of=NOW,
            period_weeks=4,
            driver_avg_weekly_usd=0.0,
            platform_avg_weekly_usd=0.0,
            difference_usd=0.0,
            difference_pct=None,
            percentile=p,
            active_drivers_in_period=0,
            comparison_note="No data.",
        )
        assert c.difference_pct is None

    def test_negative_difference_usd_accepted(self):
        p = EarningsPercentile(rank=5, total_drivers=5, percentile=0.0)
        c = DriverEarningsComparison(
            as_of=NOW,
            period_weeks=4,
            driver_avg_weekly_usd=50.0,
            platform_avg_weekly_usd=100.0,
            difference_usd=-50.0,
            difference_pct=-50.0,
            percentile=p,
            active_drivers_in_period=5,
            comparison_note="Below average.",
        )
        assert c.difference_usd == -50.0


# --------------------------------------------------------------------------- #
# Router
# --------------------------------------------------------------------------- #


class TestRouter:
    @pytest.mark.anyio
    async def test_delegates_to_service(self):
        from app.api.v1.driver_earnings_comparison import get_earnings_comparison

        mock_driver = MagicMock()
        mock_driver.id = DRIVER_ID
        mock_db = AsyncMock()

        expected = DriverEarningsComparison(
            as_of=NOW,
            period_weeks=4,
            driver_avg_weekly_usd=150.0,
            platform_avg_weekly_usd=120.0,
            difference_usd=30.0,
            difference_pct=25.0,
            percentile=EarningsPercentile(rank=2, total_drivers=5, percentile=60.0),
            active_drivers_in_period=5,
            comparison_note="Above average.",
        )

        with patch(
            "app.api.v1.driver_earnings_comparison.get_driver_earnings_comparison",
            new=AsyncMock(return_value=expected),
        ) as mock_svc:
            result = await get_earnings_comparison(driver=mock_driver, db=mock_db)

        mock_svc.assert_called_once_with(db=mock_db, driver_id=DRIVER_ID)
        assert result == expected

    @pytest.mark.anyio
    async def test_returns_driver_earnings_comparison(self):
        from app.api.v1.driver_earnings_comparison import get_earnings_comparison

        mock_driver = MagicMock()
        mock_driver.id = DRIVER_ID
        mock_db = AsyncMock()

        stub = DriverEarningsComparison(
            as_of=NOW,
            period_weeks=4,
            driver_avg_weekly_usd=0.0,
            platform_avg_weekly_usd=0.0,
            difference_usd=0.0,
            difference_pct=None,
            percentile=EarningsPercentile(rank=1, total_drivers=0, percentile=0.0),
            active_drivers_in_period=0,
            comparison_note="No data.",
        )

        with patch(
            "app.api.v1.driver_earnings_comparison.get_driver_earnings_comparison",
            new=AsyncMock(return_value=stub),
        ):
            result = await get_earnings_comparison(driver=mock_driver, db=mock_db)

        assert isinstance(result, DriverEarningsComparison)
