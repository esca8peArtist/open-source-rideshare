"""Unit tests for rider spending summary service and schema.

Tests cover:
  - _compute_period with empty list → zeroed SpendingPeriod
  - _compute_period with rides → correct total_spent, trip_count, avg_fare
  - _compute_period avg_fare rounds correctly with multiple rides
  - get_rider_spending_summary: empty rider → all-zero summary, no route
  - get_rider_spending_summary: lifetime-only ride (old) bucketed correctly
  - get_rider_spending_summary: today's ride appears in all windows
  - get_rider_spending_summary: tips accumulate across lifetime
  - get_rider_spending_summary: promo_discount accumulates across lifetime
  - get_rider_spending_summary: most_frequent_route picks the top pair
  - get_rider_spending_summary: most_frequent_route is None with no rides
  - get_rider_spending_summary: as_of timestamp and rider_id are set
  - Schema round-trip serialisation for SpendingPeriod and RiderSpendingSummary
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.schemas.rider_spending_summary import (
    FrequentRoute,
    RiderSpendingSummary,
    SpendingPeriod,
)
from app.services.rider_spending_summary import (
    _compute_period,
    get_rider_spending_summary,
)

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 4, 16, 15, 0, 0, tzinfo=timezone.utc)  # Thursday


def _make_ride_row(
    fare: float,
    tip: float,
    promo: float,
    pickup: str,
    dropoff: str,
    completed_at: datetime,
):
    """Create a MagicMock mimicking a SQLAlchemy row for the Ride columns queried."""
    row = MagicMock()
    row.actual_fare = fare
    row.tip_amount = tip
    row.promo_discount = promo
    row.pickup_address = pickup
    row.dropoff_address = dropoff
    row.completed_at = completed_at
    return row


def _make_db(ride_rows):
    """Build an AsyncMock db session that returns ride_rows on the first execute call."""
    db = AsyncMock()
    ride_result = MagicMock()
    ride_result.all.return_value = ride_rows
    db.execute.return_value = ride_result
    return db


# ---------------------------------------------------------------------------
# _compute_period — pure function tests (no DB)
# ---------------------------------------------------------------------------


class TestComputePeriodEmpty:
    def test_empty_list_returns_zero_period(self):
        result = _compute_period([])
        assert isinstance(result, SpendingPeriod)
        assert result.trip_count == 0
        assert result.total_spent == 0.0
        assert result.avg_fare == 0.0

    def test_single_ride(self):
        result = _compute_period([15.00])
        assert result.trip_count == 1
        assert result.total_spent == pytest.approx(15.00, abs=0.01)
        assert result.avg_fare == pytest.approx(15.00, abs=0.01)

    def test_multiple_rides_total_and_avg(self):
        # 10 + 20 + 30 = 60; avg = 20
        result = _compute_period([10.00, 20.00, 30.00])
        assert result.trip_count == 3
        assert result.total_spent == pytest.approx(60.00, abs=0.01)
        assert result.avg_fare == pytest.approx(20.00, abs=0.01)

    def test_avg_fare_rounds_to_two_decimals(self):
        # 10 / 3 = 3.333... → should round to 3.33
        result = _compute_period([10.00])
        # 10 / 1 = 10 (exact); test with uneven division via 3 rides summing to 10
        result2 = _compute_period([3.33, 3.33, 3.34])
        assert result2.total_spent == pytest.approx(10.00, abs=0.01)
        assert result2.avg_fare == pytest.approx(10.00 / 3, abs=0.01)


# ---------------------------------------------------------------------------
# Schema round-trip serialisation
# ---------------------------------------------------------------------------


class TestSchemaRoundTrip:
    def test_spending_period_roundtrip(self):
        sp = SpendingPeriod(trip_count=3, total_spent=60.00, avg_fare=20.00)
        restored = SpendingPeriod(**sp.model_dump())
        assert restored == sp

    def test_rider_spending_summary_roundtrip_no_route(self):
        empty = SpendingPeriod(trip_count=0, total_spent=0.0, avg_fare=0.0)
        summary = RiderSpendingSummary(
            rider_id=7,
            as_of=_NOW,
            today=empty,
            this_week=empty,
            this_month=empty,
            lifetime=empty,
            total_tips_given=0.0,
            total_promo_savings=0.0,
            most_frequent_route=None,
        )
        restored = RiderSpendingSummary(**summary.model_dump())
        assert restored == summary

    def test_rider_spending_summary_roundtrip_with_route(self):
        empty = SpendingPeriod(trip_count=0, total_spent=0.0, avg_fare=0.0)
        route = FrequentRoute(pickup="Home", dropoff="Office", count=5)
        summary = RiderSpendingSummary(
            rider_id=3,
            as_of=_NOW,
            today=empty,
            this_week=empty,
            this_month=empty,
            lifetime=empty,
            total_tips_given=12.50,
            total_promo_savings=5.00,
            most_frequent_route=route,
        )
        data = summary.model_dump()
        assert data["most_frequent_route"]["pickup"] == "Home"
        assert data["total_tips_given"] == 12.50


# ---------------------------------------------------------------------------
# get_rider_spending_summary — DB-mocked integration tests
# ---------------------------------------------------------------------------


class TestGetRiderSpendingSummaryEmpty:
    @pytest.mark.asyncio
    async def test_no_rides_returns_zeroed_summary(self):
        db = _make_db(ride_rows=[])
        with patch(
            "app.services.rider_spending_summary._utc_now",
            return_value=_NOW,
        ):
            summary = await get_rider_spending_summary(db, rider_id=1)

        assert summary.rider_id == 1
        assert summary.today.trip_count == 0
        assert summary.this_week.trip_count == 0
        assert summary.this_month.trip_count == 0
        assert summary.lifetime.trip_count == 0
        assert summary.total_tips_given == 0.0
        assert summary.total_promo_savings == 0.0
        assert summary.most_frequent_route is None

    @pytest.mark.asyncio
    async def test_as_of_and_rider_id_set_correctly(self):
        db = _make_db(ride_rows=[])
        with patch("app.services.rider_spending_summary._utc_now", return_value=_NOW):
            summary = await get_rider_spending_summary(db, rider_id=42)

        assert summary.as_of == _NOW
        assert summary.rider_id == 42


class TestGetRiderSpendingSummaryBucketing:
    @pytest.mark.asyncio
    async def test_old_ride_appears_only_in_lifetime(self):
        # A ride 60 days ago: only in lifetime bucket
        old_ts = _NOW - timedelta(days=60)
        rows = [_make_ride_row(20.00, 1.00, 0.00, "A", "B", old_ts)]
        db = _make_db(rows)
        with patch("app.services.rider_spending_summary._utc_now", return_value=_NOW):
            summary = await get_rider_spending_summary(db, rider_id=1)

        assert summary.lifetime.trip_count == 1
        assert summary.this_month.trip_count == 0
        assert summary.this_week.trip_count == 0
        assert summary.today.trip_count == 0

    @pytest.mark.asyncio
    async def test_today_ride_appears_in_all_windows(self):
        # A ride 1 hour ago: today, this_week, this_month, and lifetime
        recent_ts = _NOW - timedelta(hours=1)
        rows = [_make_ride_row(15.00, 2.00, 0.00, "Home", "Office", recent_ts)]
        db = _make_db(rows)
        with patch("app.services.rider_spending_summary._utc_now", return_value=_NOW):
            summary = await get_rider_spending_summary(db, rider_id=1)

        assert summary.today.trip_count == 1
        assert summary.this_week.trip_count == 1
        assert summary.this_month.trip_count == 1
        assert summary.lifetime.trip_count == 1
        assert summary.today.total_spent == pytest.approx(15.00, abs=0.01)
        assert summary.today.avg_fare == pytest.approx(15.00, abs=0.01)

    @pytest.mark.asyncio
    async def test_week_ride_not_in_today(self):
        # A ride 2 days ago: this_week and this_month and lifetime, but not today
        # _NOW is Thursday; 2 days ago is Tuesday — same week
        two_days_ago = _NOW - timedelta(days=2)
        rows = [_make_ride_row(12.00, 0.00, 0.00, "X", "Y", two_days_ago)]
        db = _make_db(rows)
        with patch("app.services.rider_spending_summary._utc_now", return_value=_NOW):
            summary = await get_rider_spending_summary(db, rider_id=1)

        assert summary.today.trip_count == 0
        assert summary.this_week.trip_count == 1
        assert summary.this_month.trip_count == 1
        assert summary.lifetime.trip_count == 1


class TestGetRiderSpendingSummaryTipsAndPromos:
    @pytest.mark.asyncio
    async def test_tips_accumulate_across_lifetime(self):
        ts = _NOW - timedelta(hours=2)
        rows = [
            _make_ride_row(10.00, 1.50, 0.00, "A", "B", ts),
            _make_ride_row(20.00, 3.00, 0.00, "C", "D", ts),
        ]
        db = _make_db(rows)
        with patch("app.services.rider_spending_summary._utc_now", return_value=_NOW):
            summary = await get_rider_spending_summary(db, rider_id=1)

        assert summary.total_tips_given == pytest.approx(4.50, abs=0.01)

    @pytest.mark.asyncio
    async def test_promo_savings_accumulate_across_lifetime(self):
        ts = _NOW - timedelta(hours=2)
        rows = [
            _make_ride_row(10.00, 0.00, 2.00, "A", "B", ts),
            _make_ride_row(20.00, 0.00, 5.00, "C", "D", ts),
        ]
        db = _make_db(rows)
        with patch("app.services.rider_spending_summary._utc_now", return_value=_NOW):
            summary = await get_rider_spending_summary(db, rider_id=1)

        assert summary.total_promo_savings == pytest.approx(7.00, abs=0.01)

    @pytest.mark.asyncio
    async def test_zero_tips_and_promos(self):
        ts = _NOW - timedelta(hours=1)
        rows = [_make_ride_row(15.00, 0.00, 0.00, "Home", "Work", ts)]
        db = _make_db(rows)
        with patch("app.services.rider_spending_summary._utc_now", return_value=_NOW):
            summary = await get_rider_spending_summary(db, rider_id=1)

        assert summary.total_tips_given == 0.0
        assert summary.total_promo_savings == 0.0


class TestGetRiderSpendingSummaryFrequentRoute:
    @pytest.mark.asyncio
    async def test_most_frequent_route_picked_correctly(self):
        ts = _NOW - timedelta(hours=2)
        rows = [
            _make_ride_row(10.00, 0.00, 0.00, "Home", "Office", ts),
            _make_ride_row(10.00, 0.00, 0.00, "Home", "Office", ts),
            _make_ride_row(10.00, 0.00, 0.00, "Home", "Office", ts),
            _make_ride_row(10.00, 0.00, 0.00, "Gym", "Park", ts),
        ]
        db = _make_db(rows)
        with patch("app.services.rider_spending_summary._utc_now", return_value=_NOW):
            summary = await get_rider_spending_summary(db, rider_id=1)

        assert summary.most_frequent_route is not None
        assert summary.most_frequent_route.pickup == "Home"
        assert summary.most_frequent_route.dropoff == "Office"
        assert summary.most_frequent_route.count == 3

    @pytest.mark.asyncio
    async def test_most_frequent_route_none_when_no_rides(self):
        db = _make_db(ride_rows=[])
        with patch("app.services.rider_spending_summary._utc_now", return_value=_NOW):
            summary = await get_rider_spending_summary(db, rider_id=1)

        assert summary.most_frequent_route is None

    @pytest.mark.asyncio
    async def test_most_frequent_route_single_ride(self):
        ts = _NOW - timedelta(hours=1)
        rows = [_make_ride_row(12.00, 0.00, 0.00, "Airport", "Hotel", ts)]
        db = _make_db(rows)
        with patch("app.services.rider_spending_summary._utc_now", return_value=_NOW):
            summary = await get_rider_spending_summary(db, rider_id=1)

        assert summary.most_frequent_route is not None
        assert summary.most_frequent_route.pickup == "Airport"
        assert summary.most_frequent_route.dropoff == "Hotel"
        assert summary.most_frequent_route.count == 1
