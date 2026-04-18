"""Unit tests for driver earnings summary service and schema.

Tests cover:
  - _compute_period with empty list → zeroed EarningsPeriod
  - _compute_period with rides → correct gross/platform_fee/net/tips/total
  - _compute_period with zero platform fee → gross == net
  - Platform fee arithmetic: net = actual_fare / (1 + pct/100)
  - Round-trip schema serialisation
  - get_driver_earnings_summary via mocked DB (time-window bucketing, pending payout)
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.schemas.driver_earnings_summary import DriverEarningsSummary, EarningsPeriod
from app.services.driver_earnings_summary import (
    _compute_period,
    _next_payout_date,
    get_driver_earnings_summary,
)

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

_FEE_PCT = 20.0  # 20% platform fee used throughout most tests

_NOW = datetime(2026, 4, 16, 15, 0, 0, tzinfo=timezone.utc)  # Thursday


def _period(actual_fare: float, tip: float) -> tuple[float, float]:
    return (actual_fare, tip)


# ---------------------------------------------------------------------------
# _compute_period — pure function tests (no DB)
# ---------------------------------------------------------------------------


class TestComputePeriodEmpty:
    def test_empty_list_returns_zero_period(self):
        result = _compute_period([], _FEE_PCT)
        assert isinstance(result, EarningsPeriod)
        assert result.rides_completed == 0
        assert result.gross_earnings_usd == 0.0
        assert result.platform_fee_usd == 0.0
        assert result.net_earnings_usd == 0.0
        assert result.tips_usd == 0.0
        assert result.total_take_home_usd == 0.0


class TestComputePeriodArithmetic:
    def test_single_ride_20pct_fee(self):
        # actual_fare=15.00, pct=20 → net=12.50, platform_fee=2.50
        result = _compute_period([_period(15.00, 0.0)], 20.0)
        assert result.rides_completed == 1
        assert result.gross_earnings_usd == 15.00
        assert result.net_earnings_usd == pytest.approx(12.50, abs=0.01)
        assert result.platform_fee_usd == pytest.approx(2.50, abs=0.01)
        assert result.tips_usd == 0.0
        assert result.total_take_home_usd == pytest.approx(12.50, abs=0.01)

    def test_single_ride_with_tip(self):
        result = _compute_period([_period(15.00, 3.00)], 20.0)
        assert result.tips_usd == 3.00
        assert result.total_take_home_usd == pytest.approx(12.50 + 3.00, abs=0.01)

    def test_multiple_rides_accumulate(self):
        rides = [_period(10.00, 1.00), _period(20.00, 2.00), _period(30.00, 0.00)]
        result = _compute_period(rides, 20.0)
        assert result.rides_completed == 3
        assert result.gross_earnings_usd == pytest.approx(60.00, abs=0.01)
        assert result.tips_usd == pytest.approx(3.00, abs=0.01)
        # net = 10/1.2 + 20/1.2 + 30/1.2 = 50
        assert result.net_earnings_usd == pytest.approx(50.00, abs=0.02)
        assert result.platform_fee_usd == pytest.approx(10.00, abs=0.02)
        assert result.total_take_home_usd == pytest.approx(53.00, abs=0.02)

    def test_zero_platform_fee_gross_equals_net(self):
        result = _compute_period([_period(15.00, 0.0)], 0.0)
        assert result.gross_earnings_usd == 15.00
        assert result.net_earnings_usd == 15.00
        assert result.platform_fee_usd == 0.0

    def test_platform_fee_gross_minus_net_equals_fee(self):
        result = _compute_period([_period(25.00, 5.00)], 15.0)
        assert round(result.gross_earnings_usd - result.net_earnings_usd, 2) == result.platform_fee_usd

    def test_net_formula_matches_divide_by_divisor(self):
        fare = 18.00
        pct = 25.0
        expected_net = round(fare / (1.0 + pct / 100.0), 2)
        result = _compute_period([_period(fare, 0.0)], pct)
        assert result.net_earnings_usd == pytest.approx(expected_net, abs=0.01)

    def test_total_take_home_is_net_plus_tips(self):
        result = _compute_period([_period(20.00, 4.00)], 20.0)
        assert result.total_take_home_usd == pytest.approx(
            result.net_earnings_usd + result.tips_usd, abs=0.01
        )


# ---------------------------------------------------------------------------
# Schema round-trip serialisation
# ---------------------------------------------------------------------------


class TestSchemaRoundTrip:
    def test_earnings_period_roundtrip(self):
        ep = EarningsPeriod(
            rides_completed=5,
            gross_earnings_usd=75.00,
            platform_fee_usd=12.50,
            net_earnings_usd=62.50,
            tips_usd=10.00,
            total_take_home_usd=72.50,
        )
        restored = EarningsPeriod(**ep.model_dump())
        assert restored == ep

    def test_driver_earnings_summary_roundtrip(self):
        empty_period = EarningsPeriod(
            rides_completed=0,
            gross_earnings_usd=0.0,
            platform_fee_usd=0.0,
            net_earnings_usd=0.0,
            tips_usd=0.0,
            total_take_home_usd=0.0,
        )
        summary = DriverEarningsSummary(
            driver_id=42,
            as_of=_NOW,
            today=empty_period,
            this_week=empty_period,
            this_month=empty_period,
            lifetime=empty_period,
            pending_payout_usd=0.0,
            next_payout_date=None,
        )
        restored = DriverEarningsSummary(**summary.model_dump())
        assert restored == summary

    def test_summary_with_next_payout_date(self):
        empty_period = EarningsPeriod(
            rides_completed=0,
            gross_earnings_usd=0.0,
            platform_fee_usd=0.0,
            net_earnings_usd=0.0,
            tips_usd=0.0,
            total_take_home_usd=0.0,
        )
        summary = DriverEarningsSummary(
            driver_id=1,
            as_of=_NOW,
            today=empty_period,
            this_week=empty_period,
            this_month=empty_period,
            lifetime=empty_period,
            pending_payout_usd=25.00,
            next_payout_date=date(2026, 4, 20),
        )
        data = summary.model_dump()
        assert data["next_payout_date"] == date(2026, 4, 20)
        assert data["pending_payout_usd"] == 25.00


# ---------------------------------------------------------------------------
# _next_payout_date helper
# ---------------------------------------------------------------------------


class TestNextPayoutDate:
    # _NOW is Thursday 2026-04-16
    _today = _NOW.date()  # 2026-04-16 (Thursday)

    def test_daily_is_tomorrow(self):
        from app.models.payout import PayoutFrequency
        result = _next_payout_date(PayoutFrequency.DAILY, self._today)
        assert result == self._today + timedelta(days=1)

    def test_weekly_is_next_monday(self):
        from app.models.payout import PayoutFrequency
        result = _next_payout_date(PayoutFrequency.WEEKLY, self._today)
        # Thursday → next Monday is +4 days = 2026-04-20
        assert result == date(2026, 4, 20)
        assert result.weekday() == 0  # Monday

    def test_biweekly_is_monday_after_next(self):
        from app.models.payout import PayoutFrequency
        result = _next_payout_date(PayoutFrequency.BIWEEKLY, self._today)
        assert result == date(2026, 4, 27)
        assert result.weekday() == 0

    def test_weekly_from_monday_is_next_week_monday(self):
        from app.models.payout import PayoutFrequency
        monday = date(2026, 4, 13)  # confirmed Monday (April 13, 2026)
        result = _next_payout_date(PayoutFrequency.WEEKLY, monday)
        assert result == date(2026, 4, 20)  # following Monday
        assert result.weekday() == 0


# ---------------------------------------------------------------------------
# get_driver_earnings_summary — DB-mocked integration tests
# ---------------------------------------------------------------------------


def _make_ride_row(fare: float, tip: float, completed_at: datetime):
    """Create a MagicMock that mimics a SQLAlchemy row for Ride columns."""
    row = MagicMock()
    row.actual_fare = fare
    row.tip_amount = tip
    row.completed_at = completed_at
    return row


def _make_db(ride_rows, last_payout_period_end=None, bank_frequency=None):
    """Build an AsyncMock db session with configurable query results.

    Calls to db.execute() return different results based on call order:
      1st call → ride rows
      2nd call → last payout period_end (or None)
      3rd call → bank account payout_frequency (or None)
    """
    db = AsyncMock()

    ride_result = MagicMock()
    ride_result.all.return_value = ride_rows

    payout_result = MagicMock()
    payout_result.scalar_one_or_none.return_value = last_payout_period_end

    bank_result = MagicMock()
    bank_result.scalar_one_or_none.return_value = bank_frequency

    db.execute.side_effect = [
        ride_result,
        payout_result,
        bank_result,
    ]
    return db


class TestGetDriverEarningsSummary:
    @pytest.mark.asyncio
    async def test_no_rides_returns_zeroed_summary(self):
        db = _make_db(ride_rows=[])
        with patch(
            "app.services.driver_earnings_summary._utc_now",
            return_value=_NOW,
        ):
            summary = await get_driver_earnings_summary(db, driver_id=1, platform_fee_percent=20.0)

        assert summary.driver_id == 1
        assert summary.today.rides_completed == 0
        assert summary.this_week.rides_completed == 0
        assert summary.this_month.rides_completed == 0
        assert summary.lifetime.rides_completed == 0
        assert summary.pending_payout_usd == 0.0
        assert summary.next_payout_date is None

    @pytest.mark.asyncio
    async def test_lifetime_includes_all_rides(self):
        # Ride from a month ago — only in lifetime
        old_ts = _NOW - timedelta(days=60)
        ride_rows = [_make_ride_row(20.00, 2.00, old_ts)]
        db = _make_db(ride_rows)
        with patch("app.services.driver_earnings_summary._utc_now", return_value=_NOW):
            summary = await get_driver_earnings_summary(db, driver_id=1, platform_fee_percent=20.0)

        assert summary.lifetime.rides_completed == 1
        assert summary.this_month.rides_completed == 0
        assert summary.this_week.rides_completed == 0
        assert summary.today.rides_completed == 0

    @pytest.mark.asyncio
    async def test_today_ride_counts_in_all_windows(self):
        # A ride completed 1 hour ago appears in today, this_week, this_month, lifetime
        recent_ts = _NOW - timedelta(hours=1)
        ride_rows = [_make_ride_row(15.00, 3.00, recent_ts)]
        db = _make_db(ride_rows)
        with patch("app.services.driver_earnings_summary._utc_now", return_value=_NOW):
            summary = await get_driver_earnings_summary(db, driver_id=1, platform_fee_percent=20.0)

        assert summary.today.rides_completed == 1
        assert summary.this_week.rides_completed == 1
        assert summary.this_month.rides_completed == 1
        assert summary.lifetime.rides_completed == 1

    @pytest.mark.asyncio
    async def test_pending_payout_all_rides_when_no_completed_payout(self):
        # No prior completed payout → all rides are pending
        recent_ts = _NOW - timedelta(hours=2)
        ride_rows = [
            _make_ride_row(10.00, 1.00, recent_ts),
            _make_ride_row(20.00, 2.00, recent_ts),
        ]
        db = _make_db(ride_rows, last_payout_period_end=None)
        with patch("app.services.driver_earnings_summary._utc_now", return_value=_NOW):
            summary = await get_driver_earnings_summary(db, driver_id=1, platform_fee_percent=20.0)

        # pending = net(10) + net(20) + tips = 8.33 + 16.67 + 3 = 28.00
        assert summary.pending_payout_usd > 0.0
        assert summary.pending_payout_usd == pytest.approx(
            summary.lifetime.total_take_home_usd, abs=0.01
        )

    @pytest.mark.asyncio
    async def test_pending_payout_excludes_covered_rides(self):
        # Last payout covered through yesterday; only today's ride is pending
        yesterday_end = (_NOW - timedelta(days=1)).date()
        old_ts = _NOW - timedelta(days=5)
        new_ts = _NOW - timedelta(hours=1)
        ride_rows = [
            _make_ride_row(30.00, 0.00, old_ts),   # covered by payout
            _make_ride_row(10.00, 2.00, new_ts),   # pending
        ]
        db = _make_db(ride_rows, last_payout_period_end=yesterday_end)
        with patch("app.services.driver_earnings_summary._utc_now", return_value=_NOW):
            summary = await get_driver_earnings_summary(db, driver_id=1, platform_fee_percent=20.0)

        # Only the 10.00 + tip ride is pending
        expected_net = round(10.00 / 1.2, 2)
        assert summary.pending_payout_usd == pytest.approx(expected_net + 2.00, abs=0.01)

    @pytest.mark.asyncio
    async def test_next_payout_date_none_without_bank_account(self):
        db = _make_db(ride_rows=[], bank_frequency=None)
        with patch("app.services.driver_earnings_summary._utc_now", return_value=_NOW):
            summary = await get_driver_earnings_summary(db, driver_id=1, platform_fee_percent=20.0)

        assert summary.next_payout_date is None

    @pytest.mark.asyncio
    async def test_next_payout_date_weekly(self):
        from app.models.payout import PayoutFrequency
        db = _make_db(ride_rows=[], bank_frequency=PayoutFrequency.WEEKLY)
        with patch("app.services.driver_earnings_summary._utc_now", return_value=_NOW):
            summary = await get_driver_earnings_summary(db, driver_id=1, platform_fee_percent=20.0)

        # _NOW is Thursday 2026-04-16 → next Monday is 2026-04-20
        assert summary.next_payout_date == date(2026, 4, 20)

    @pytest.mark.asyncio
    async def test_summary_as_of_timestamp(self):
        db = _make_db(ride_rows=[])
        with patch("app.services.driver_earnings_summary._utc_now", return_value=_NOW):
            summary = await get_driver_earnings_summary(db, driver_id=7, platform_fee_percent=20.0)

        assert summary.as_of == _NOW
        assert summary.driver_id == 7

    @pytest.mark.asyncio
    async def test_zero_fee_net_equals_gross(self):
        ts = _NOW - timedelta(hours=1)
        ride_rows = [_make_ride_row(15.00, 0.00, ts)]
        db = _make_db(ride_rows)
        with patch("app.services.driver_earnings_summary._utc_now", return_value=_NOW):
            summary = await get_driver_earnings_summary(db, driver_id=1, platform_fee_percent=0.0)

        assert summary.today.net_earnings_usd == pytest.approx(15.00, abs=0.01)
        assert summary.today.platform_fee_usd == pytest.approx(0.0, abs=0.01)
        assert summary.today.gross_earnings_usd == pytest.approx(15.00, abs=0.01)
