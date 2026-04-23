"""Tests for the admin driver earnings report feature.

Covers:

Service unit tests (using AsyncMock for DB):
  1.  empty period returns empty drivers list and zero platform totals
  2.  single driver with 1 ride returns correct gross/net/fee/tip breakdown
  3.  platform_fee_percent=20 applies correct divisor
  4.  platform_fee_percent=0 gives net == gross, fee == 0
  5.  actual_fare=None falls back to estimated_fare
  6.  multiple drivers are all returned (not just top N)
  7.  sort_by=net_earnings descending: higher earner first
  8.  sort_by=rides_completed: driver with more rides first
  9.  page=1 returns first page_size items
  10. page=2 returns next slice
  11. total_count reflects all active drivers, not just current page
  12. total_active_drivers matches len of unique drivers with completed rides
  13. platform_totals.total_rides is sum across all drivers
  14. platform_totals.gross_earnings_usd sums all drivers
  15. pending_payout_usd is 0 when all rides covered by completed payouts
  16. pending_payout_usd counts uncovered rides correctly
  17. drivers with zero rides in period are excluded

API integration tests (using conftest fixtures + real DB):
  18. 401 with no auth
  19. 403 with rider token
  20. 403 with driver token
  21. 200 with admin token
  22. missing start_date returns 422
  23. missing end_date returns 422
  24. end_date before start_date returns 422
  25. invalid date format returns 422
  26. response contains platform_totals, drivers, page, page_size, total_count
  27. empty period returns total_active_drivers=0
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.payout import DriverPayout, PayoutStatus
from app.models.ride import Ride, RideStatus
from app.models.user import User, UserRole
from app.services.admin_driver_earnings_report import get_driver_earnings_report

# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------

_START = date(2026, 1, 1)
_END = date(2026, 1, 31)
_DT = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)


def _make_ride(
    ride_id: int = 1,
    driver_id: int = 10,
    rider_id: int = 50,
    actual_fare: float | None = 20.0,
    estimated_fare: float = 18.0,
    tip_amount: float = 2.0,
    completed_at: datetime | None = None,
) -> MagicMock:
    ride = MagicMock(spec=Ride)
    ride.id = ride_id
    ride.driver_id = driver_id
    ride.rider_id = rider_id
    ride.status = RideStatus.COMPLETED
    ride.actual_fare = actual_fare
    ride.estimated_fare = estimated_fare
    ride.tip_amount = tip_amount
    ride.completed_at = completed_at or _DT
    return ride


def _make_user(user_id: int = 10, name: str = "Test Driver", phone: str = "+15555550001") -> MagicMock:
    u = MagicMock(spec=User)
    u.id = user_id
    u.name = name
    u.phone = phone
    return u


def _make_payout(
    payout_id: int = 1,
    driver_id: int = 10,
    period_start: date = date(2026, 1, 1),
    period_end: date = date(2026, 1, 31),
    status: PayoutStatus = PayoutStatus.COMPLETED,
) -> MagicMock:
    dp = MagicMock(spec=DriverPayout)
    dp.id = payout_id
    dp.driver_id = driver_id
    dp.period_start = period_start
    dp.period_end = period_end
    dp.status = status
    return dp


def _make_db(*result_lists) -> AsyncMock:
    """DB mock where each execute() returns the next list via scalars().all()."""
    db = AsyncMock()
    side_effects = []
    for items in result_lists:
        mock_result = MagicMock()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = items
        mock_result.scalars.return_value = scalars_mock
        side_effects.append(mock_result)
    db.execute = AsyncMock(side_effect=side_effects)
    return db


# DB call order (non-empty): rides, users, payouts — 3 execute() calls
# DB call order (empty rides): rides — 1 execute() call (returns early)


# ---------------------------------------------------------------------------
# Service unit tests
# ---------------------------------------------------------------------------


class TestGetDriverEarningsReport:

    @pytest.mark.asyncio
    async def test_empty_period_returns_empty_drivers_and_zero_totals(self):
        """Test 1: empty period returns empty drivers list and zero platform totals."""
        db = _make_db([])
        result = await get_driver_earnings_report(
            db, _START, _END, "net_earnings", "desc", 1, 25, 20.0
        )
        assert result.drivers == []
        assert result.total_active_drivers == 0
        assert result.total_count == 0
        assert result.platform_totals.total_rides == 0
        assert result.platform_totals.gross_earnings_usd == 0.0
        assert result.platform_totals.platform_fees_usd == 0.0
        assert result.platform_totals.net_earnings_usd == 0.0
        assert result.platform_totals.tips_usd == 0.0

    @pytest.mark.asyncio
    async def test_single_driver_single_ride_correct_breakdown(self):
        """Test 2: single driver with 1 ride returns correct gross/net/fee/tip breakdown."""
        # actual_fare=20, platform_fee_pct=20 → net=20/1.2=16.67, fee=3.33
        ride = _make_ride(ride_id=1, driver_id=10, actual_fare=20.0, tip_amount=2.0)
        user = _make_user(user_id=10)
        db = _make_db([ride], [user], [])
        result = await get_driver_earnings_report(
            db, _START, _END, "net_earnings", "desc", 1, 25, 20.0
        )
        assert len(result.drivers) == 1
        row = result.drivers[0]
        assert row.driver_id == 10
        assert row.rides_completed == 1
        assert row.gross_earnings_usd == 20.0
        assert row.platform_fee_usd == round(20.0 - 20.0 / 1.2, 2)
        assert row.net_earnings_usd == round(20.0 / 1.2, 2)
        assert row.tips_usd == 2.0
        assert row.total_take_home_usd == round(row.net_earnings_usd + 2.0, 2)

    @pytest.mark.asyncio
    async def test_platform_fee_pct_20_applies_correct_divisor(self):
        """Test 3: platform_fee_percent=20 applies correct divisor (1.2)."""
        ride = _make_ride(ride_id=1, driver_id=10, actual_fare=12.0, tip_amount=0.0)
        user = _make_user(user_id=10)
        db = _make_db([ride], [user], [])
        result = await get_driver_earnings_report(
            db, _START, _END, "net_earnings", "desc", 1, 25, 20.0
        )
        row = result.drivers[0]
        expected_net = round(12.0 / 1.2, 2)
        expected_fee = round(12.0 - expected_net, 2)
        assert row.net_earnings_usd == expected_net
        assert row.platform_fee_usd == expected_fee

    @pytest.mark.asyncio
    async def test_platform_fee_pct_0_gives_net_equals_gross_fee_zero(self):
        """Test 4: platform_fee_percent=0 gives net == gross, fee == 0."""
        ride = _make_ride(ride_id=1, driver_id=10, actual_fare=15.0, tip_amount=0.0)
        user = _make_user(user_id=10)
        db = _make_db([ride], [user], [])
        result = await get_driver_earnings_report(
            db, _START, _END, "net_earnings", "desc", 1, 25, 0.0
        )
        row = result.drivers[0]
        assert row.gross_earnings_usd == 15.0
        assert row.net_earnings_usd == 15.0
        assert row.platform_fee_usd == 0.0

    @pytest.mark.asyncio
    async def test_actual_fare_none_falls_back_to_estimated_fare(self):
        """Test 5: actual_fare=None falls back to estimated_fare."""
        ride = _make_ride(ride_id=1, driver_id=10, actual_fare=None, estimated_fare=14.0, tip_amount=0.0)
        user = _make_user(user_id=10)
        db = _make_db([ride], [user], [])
        result = await get_driver_earnings_report(
            db, _START, _END, "net_earnings", "desc", 1, 25, 0.0
        )
        row = result.drivers[0]
        assert row.gross_earnings_usd == 14.0

    @pytest.mark.asyncio
    async def test_multiple_drivers_all_returned(self):
        """Test 6: multiple drivers are all returned (not just top N)."""
        rides = [
            _make_ride(ride_id=1, driver_id=10, actual_fare=20.0),
            _make_ride(ride_id=2, driver_id=11, actual_fare=30.0),
            _make_ride(ride_id=3, driver_id=12, actual_fare=25.0),
        ]
        users = [
            _make_user(user_id=10, name="Driver A"),
            _make_user(user_id=11, name="Driver B"),
            _make_user(user_id=12, name="Driver C"),
        ]
        db = _make_db(rides, users, [])
        result = await get_driver_earnings_report(
            db, _START, _END, "net_earnings", "desc", 1, 25, 20.0
        )
        assert result.total_count == 3
        assert len(result.drivers) == 3

    @pytest.mark.asyncio
    async def test_sort_by_net_earnings_descending_higher_earner_first(self):
        """Test 7: sort_by=net_earnings descending: higher earner first."""
        rides = [
            _make_ride(ride_id=1, driver_id=10, actual_fare=10.0, tip_amount=0.0),
            _make_ride(ride_id=2, driver_id=11, actual_fare=50.0, tip_amount=0.0),
        ]
        users = [
            _make_user(user_id=10, name="Low Earner"),
            _make_user(user_id=11, name="High Earner"),
        ]
        db = _make_db(rides, users, [])
        result = await get_driver_earnings_report(
            db, _START, _END, "net_earnings", "desc", 1, 25, 20.0
        )
        assert result.drivers[0].driver_id == 11
        assert result.drivers[1].driver_id == 10

    @pytest.mark.asyncio
    async def test_sort_by_rides_completed_driver_with_more_rides_first(self):
        """Test 8: sort_by=rides_completed: driver with more rides first."""
        rides = [
            _make_ride(ride_id=1, driver_id=10, actual_fare=10.0),
            _make_ride(ride_id=2, driver_id=11, actual_fare=10.0),
            _make_ride(ride_id=3, driver_id=11, actual_fare=10.0),
            _make_ride(ride_id=4, driver_id=11, actual_fare=10.0),
        ]
        users = [
            _make_user(user_id=10, name="Fewer Rides"),
            _make_user(user_id=11, name="More Rides"),
        ]
        db = _make_db(rides, users, [])
        result = await get_driver_earnings_report(
            db, _START, _END, "rides_completed", "desc", 1, 25, 20.0
        )
        assert result.drivers[0].driver_id == 11
        assert result.drivers[0].rides_completed == 3

    @pytest.mark.asyncio
    async def test_page1_returns_first_page_size_items(self):
        """Test 9: page=1 returns first page_size items."""
        rides = [
            _make_ride(ride_id=i, driver_id=i, actual_fare=float(i * 10))
            for i in range(1, 6)
        ]
        users = [_make_user(user_id=i, name=f"Driver {i}") for i in range(1, 6)]
        db = _make_db(rides, users, [])
        result = await get_driver_earnings_report(
            db, _START, _END, "net_earnings", "desc", 1, 3, 20.0
        )
        assert len(result.drivers) == 3
        assert result.page == 1
        assert result.page_size == 3

    @pytest.mark.asyncio
    async def test_page2_returns_next_slice(self):
        """Test 10: page=2 returns next slice."""
        rides = [
            _make_ride(ride_id=i, driver_id=i, actual_fare=float(i * 10))
            for i in range(1, 6)
        ]
        users = [_make_user(user_id=i, name=f"Driver {i}") for i in range(1, 6)]
        db = _make_db(rides, users, [])
        result = await get_driver_earnings_report(
            db, _START, _END, "net_earnings", "desc", 2, 3, 20.0
        )
        # page 2, page_size 3 → 2 remaining drivers
        assert len(result.drivers) == 2
        assert result.page == 2

    @pytest.mark.asyncio
    async def test_total_count_reflects_all_drivers_not_just_page(self):
        """Test 11: total_count reflects all active drivers, not just current page."""
        rides = [
            _make_ride(ride_id=i, driver_id=i, actual_fare=10.0)
            for i in range(1, 6)
        ]
        users = [_make_user(user_id=i) for i in range(1, 6)]
        db = _make_db(rides, users, [])
        result = await get_driver_earnings_report(
            db, _START, _END, "net_earnings", "desc", 1, 3, 20.0
        )
        assert result.total_count == 5
        assert len(result.drivers) == 3

    @pytest.mark.asyncio
    async def test_total_active_drivers_matches_unique_drivers(self):
        """Test 12: total_active_drivers matches unique drivers with completed rides."""
        rides = [
            _make_ride(ride_id=1, driver_id=10),
            _make_ride(ride_id=2, driver_id=10),  # same driver twice
            _make_ride(ride_id=3, driver_id=11),
        ]
        users = [_make_user(user_id=10), _make_user(user_id=11)]
        db = _make_db(rides, users, [])
        result = await get_driver_earnings_report(
            db, _START, _END, "net_earnings", "desc", 1, 25, 20.0
        )
        assert result.total_active_drivers == 2

    @pytest.mark.asyncio
    async def test_platform_totals_total_rides_sums_across_all_drivers(self):
        """Test 13: platform_totals.total_rides is sum across all drivers."""
        rides = [
            _make_ride(ride_id=1, driver_id=10),
            _make_ride(ride_id=2, driver_id=10),
            _make_ride(ride_id=3, driver_id=11),
        ]
        users = [_make_user(user_id=10), _make_user(user_id=11)]
        db = _make_db(rides, users, [])
        result = await get_driver_earnings_report(
            db, _START, _END, "net_earnings", "desc", 1, 25, 20.0
        )
        assert result.platform_totals.total_rides == 3

    @pytest.mark.asyncio
    async def test_platform_totals_gross_earnings_sums_all_drivers(self):
        """Test 14: platform_totals.gross_earnings_usd sums all drivers."""
        rides = [
            _make_ride(ride_id=1, driver_id=10, actual_fare=20.0, tip_amount=0.0),
            _make_ride(ride_id=2, driver_id=11, actual_fare=30.0, tip_amount=0.0),
        ]
        users = [_make_user(user_id=10), _make_user(user_id=11)]
        db = _make_db(rides, users, [])
        result = await get_driver_earnings_report(
            db, _START, _END, "net_earnings", "desc", 1, 25, 0.0
        )
        assert result.platform_totals.gross_earnings_usd == 50.0

    @pytest.mark.asyncio
    async def test_pending_payout_zero_when_all_rides_covered(self):
        """Test 15: pending_payout_usd is 0 when all rides covered by completed payouts."""
        ride_dt = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        ride = _make_ride(ride_id=1, driver_id=10, actual_fare=20.0, tip_amount=0.0, completed_at=ride_dt)
        user = _make_user(user_id=10)
        payout = _make_payout(
            payout_id=1,
            driver_id=10,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
            status=PayoutStatus.COMPLETED,
        )
        db = _make_db([ride], [user], [payout])
        result = await get_driver_earnings_report(
            db, _START, _END, "net_earnings", "desc", 1, 25, 20.0
        )
        assert result.drivers[0].pending_payout_usd == 0.0

    @pytest.mark.asyncio
    async def test_pending_payout_counts_uncovered_rides(self):
        """Test 16: pending_payout_usd counts uncovered rides correctly."""
        # ride1 is covered (Jan 15), ride2 is NOT covered (no payout covers Feb)
        ride1_dt = datetime(2026, 1, 15, tzinfo=timezone.utc)
        ride2_dt = datetime(2026, 1, 25, tzinfo=timezone.utc)
        ride1 = _make_ride(ride_id=1, driver_id=10, actual_fare=20.0, tip_amount=0.0, completed_at=ride1_dt)
        ride2 = _make_ride(ride_id=2, driver_id=10, actual_fare=30.0, tip_amount=0.0, completed_at=ride2_dt)
        user = _make_user(user_id=10)
        # payout only covers Jan 1–14, so ride on Jan 15 is also uncovered... use Jan 1–20 to cover only ride1
        payout = _make_payout(
            payout_id=1,
            driver_id=10,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 20),
            status=PayoutStatus.COMPLETED,
        )
        db = _make_db([ride1, ride2], [user], [payout])
        result = await get_driver_earnings_report(
            db, _START, _END, "net_earnings", "desc", 1, 25, 0.0
        )
        # ride2 (fare=30, pct=0, so net=30) is uncovered
        assert result.drivers[0].pending_payout_usd == 30.0

    @pytest.mark.asyncio
    async def test_drivers_with_zero_rides_in_period_excluded(self):
        """Test 17: drivers with zero rides in period are excluded.

        This is implicitly guaranteed by the query filtering on COMPLETED rides
        in the period. We verify by checking the result has only drivers present
        in the rides result, not any additional driver_ids passed in.
        """
        # Only driver 10 has a ride; driver 11 has none (not in rides list)
        ride = _make_ride(ride_id=1, driver_id=10, actual_fare=20.0)
        user = _make_user(user_id=10)
        db = _make_db([ride], [user], [])
        result = await get_driver_earnings_report(
            db, _START, _END, "net_earnings", "desc", 1, 25, 20.0
        )
        driver_ids_in_result = {r.driver_id for r in result.drivers}
        assert 11 not in driver_ids_in_result
        assert result.total_count == 1


# ---------------------------------------------------------------------------
# API integration tests
# ---------------------------------------------------------------------------

BASE = "/api/v1/admin/drivers/earnings-report"
VALID_DATES = "?start_date=2026-01-01&end_date=2026-01-31"


def auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.anyio
class TestDriverEarningsReportEndpoint:

    async def test_no_auth_returns_401(self, client):
        """Test 18: 401 with no auth."""
        resp = await client.get(f"{BASE}{VALID_DATES}")
        assert resp.status_code == 401

    async def test_rider_token_returns_403(self, client, rider, rider_token):
        """Test 19: 403 with rider token."""
        resp = await client.get(
            f"{BASE}{VALID_DATES}",
            headers=auth_header(rider_token),
        )
        assert resp.status_code == 403

    async def test_driver_token_returns_403(self, client, driver_user, driver_token):
        """Test 20: 403 with driver token."""
        resp = await client.get(
            f"{BASE}{VALID_DATES}",
            headers=auth_header(driver_token),
        )
        assert resp.status_code == 403

    async def test_admin_token_returns_200(self, client, admin_user, admin_token):
        """Test 21: 200 with admin token."""
        resp = await client.get(
            f"{BASE}{VALID_DATES}",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200

    async def test_missing_start_date_returns_422(self, client, admin_user, admin_token):
        """Test 22: missing start_date returns 422."""
        resp = await client.get(
            f"{BASE}?end_date=2026-01-31",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 422

    async def test_missing_end_date_returns_422(self, client, admin_user, admin_token):
        """Test 23: missing end_date returns 422."""
        resp = await client.get(
            f"{BASE}?start_date=2026-01-01",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 422

    async def test_end_date_before_start_date_returns_422(self, client, admin_user, admin_token):
        """Test 24: end_date before start_date returns 422."""
        resp = await client.get(
            f"{BASE}?start_date=2026-01-31&end_date=2026-01-01",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 422

    async def test_invalid_date_format_returns_422(self, client, admin_user, admin_token):
        """Test 25: invalid date format returns 422."""
        resp = await client.get(
            f"{BASE}?start_date=01-01-2026&end_date=01-31-2026",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 422

    async def test_response_contains_required_fields(self, client, admin_user, admin_token):
        """Test 26: response contains platform_totals, drivers, page, page_size, total_count."""
        resp = await client.get(
            f"{BASE}{VALID_DATES}",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "platform_totals" in data
        assert "drivers" in data
        assert "page" in data
        assert "page_size" in data
        assert "total_count" in data
        assert "period_start" in data
        assert "period_end" in data
        assert "total_active_drivers" in data
        # platform_totals sub-fields
        pt = data["platform_totals"]
        assert "total_rides" in pt
        assert "gross_earnings_usd" in pt
        assert "platform_fees_usd" in pt
        assert "net_earnings_usd" in pt
        assert "tips_usd" in pt

    async def test_empty_period_returns_zero_active_drivers(self, client, admin_user, admin_token):
        """Test 27: empty period returns total_active_drivers=0."""
        resp = await client.get(
            f"{BASE}?start_date=2099-01-01&end_date=2099-12-31",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_active_drivers"] == 0
        assert data["drivers"] == []
        assert data["total_count"] == 0
