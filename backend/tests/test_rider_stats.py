"""Tests for rider lifetime stats endpoint.

Covers:
Service unit tests (AsyncMock DB):
  1.  get_rider_stats — no rides returns all zeros
  2.  get_rider_stats — total_rides counts all status types
  3.  get_rider_stats — completed_rides counts only COMPLETED
  4.  get_rider_stats — cancelled_rides counts only CANCELLED
  5.  get_rider_stats — completion_rate_pct is 0.0 when no rides
  6.  get_rider_stats — completion_rate_pct calculated correctly
  7.  get_rider_stats — total_spent_dollars sums actual_fare for completed rides
  8.  get_rider_stats — falls back to estimated_fare when actual_fare is None
  9.  get_rider_stats — avg_fare_dollars is 0.0 when no completed rides
  10. get_rider_stats — total_distance_km sums completed rides only
  11. get_rider_stats — total_distance_km excludes rides with None distance
  12. get_rider_stats — avg_rating_given is None when no ratings
  13. get_rider_stats — avg_rating_given averages driver_rating values
  14. get_rider_stats — tips_given_count counts tip records
  15. get_rider_stats — total_tips_given_dollars converts cents to dollars
  16. get_rider_stats — member_since passed through unchanged

API integration tests (real in-transaction test DB):
  17. GET /analytics/rider/stats — 401 without auth
  18. GET /analytics/rider/stats — 200 with any authenticated user
  19. GET /analytics/rider/stats — response has all required fields
  20. GET /analytics/rider/stats — total_rides is 0 for new rider
  21. GET /analytics/rider/stats — completed_rides=0 when no rides completed
  22. GET /analytics/rider/stats — completion_rate_pct=0.0 for no rides
  23. GET /analytics/rider/stats — member_since is not null
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.ride import Ride, RideStatus
from app.models.tip import TipRecord
from app.services.analytics import get_rider_stats


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


def _make_ride(
    ride_id: int = 1,
    rider_id: int = 10,
    status: RideStatus = RideStatus.COMPLETED,
    actual_fare: float | None = 12.50,
    estimated_fare: float = 11.00,
    distance_km: float | None = 5.0,
    driver_rating: int | None = None,
) -> MagicMock:
    ride = MagicMock(spec=Ride)
    ride.id = ride_id
    ride.rider_id = rider_id
    ride.status = status
    ride.actual_fare = actual_fare
    ride.estimated_fare = estimated_fare
    ride.distance_km = distance_km
    ride.driver_rating = driver_rating
    return ride


def _make_tip(tip_id: int = 1, rider_id: int = 10, amount_cents: int = 300) -> MagicMock:
    tip = MagicMock(spec=TipRecord)
    tip.id = tip_id
    tip.rider_id = rider_id
    tip.amount_cents = amount_cents
    return tip


def _make_db_two_results(rides: list, tips: list) -> AsyncMock:
    """Mock DB with two sequential execute calls: first returns rides, second tips."""
    db = AsyncMock()
    results = []
    for items in [rides, tips]:
        mock_result = MagicMock()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = items
        mock_result.scalars.return_value = scalars_mock
        results.append(mock_result)
    db.execute = AsyncMock(side_effect=results)
    return db


# ---------------------------------------------------------------------------
# Unit tests — get_rider_stats
# ---------------------------------------------------------------------------


class TestGetRiderStats:
    @pytest.mark.asyncio
    async def test_no_rides_returns_zeros(self):
        db = _make_db_two_results([], [])
        result = await get_rider_stats(db, rider_id=10, member_since=None)
        assert result["total_rides"] == 0
        assert result["completed_rides"] == 0
        assert result["cancelled_rides"] == 0
        assert result["total_spent_dollars"] == 0.0
        assert result["total_distance_km"] == 0.0
        assert result["tips_given_count"] == 0

    @pytest.mark.asyncio
    async def test_total_rides_counts_all_statuses(self):
        rides = [
            _make_ride(ride_id=1, status=RideStatus.COMPLETED),
            _make_ride(ride_id=2, status=RideStatus.CANCELLED),
            _make_ride(ride_id=3, status=RideStatus.REQUESTED),
        ]
        db = _make_db_two_results(rides, [])
        result = await get_rider_stats(db, rider_id=10)
        assert result["total_rides"] == 3

    @pytest.mark.asyncio
    async def test_completed_rides_counts_only_completed(self):
        rides = [
            _make_ride(ride_id=1, status=RideStatus.COMPLETED),
            _make_ride(ride_id=2, status=RideStatus.COMPLETED),
            _make_ride(ride_id=3, status=RideStatus.CANCELLED),
        ]
        db = _make_db_two_results(rides, [])
        result = await get_rider_stats(db, rider_id=10)
        assert result["completed_rides"] == 2

    @pytest.mark.asyncio
    async def test_cancelled_rides_counts_only_cancelled(self):
        rides = [
            _make_ride(ride_id=1, status=RideStatus.COMPLETED),
            _make_ride(ride_id=2, status=RideStatus.CANCELLED),
            _make_ride(ride_id=3, status=RideStatus.CANCELLED),
        ]
        db = _make_db_two_results(rides, [])
        result = await get_rider_stats(db, rider_id=10)
        assert result["cancelled_rides"] == 2

    @pytest.mark.asyncio
    async def test_completion_rate_zero_when_no_rides(self):
        db = _make_db_two_results([], [])
        result = await get_rider_stats(db, rider_id=10)
        assert result["completion_rate_pct"] == 0.0

    @pytest.mark.asyncio
    async def test_completion_rate_calculated_correctly(self):
        rides = [
            _make_ride(ride_id=1, status=RideStatus.COMPLETED),
            _make_ride(ride_id=2, status=RideStatus.COMPLETED),
            _make_ride(ride_id=3, status=RideStatus.CANCELLED),
            _make_ride(ride_id=4, status=RideStatus.CANCELLED),
        ]
        db = _make_db_two_results(rides, [])
        result = await get_rider_stats(db, rider_id=10)
        assert result["completion_rate_pct"] == 50.0

    @pytest.mark.asyncio
    async def test_total_spent_sums_actual_fare_for_completed(self):
        rides = [
            _make_ride(ride_id=1, status=RideStatus.COMPLETED, actual_fare=10.0),
            _make_ride(ride_id=2, status=RideStatus.COMPLETED, actual_fare=15.0),
            _make_ride(ride_id=3, status=RideStatus.CANCELLED, actual_fare=8.0),
        ]
        db = _make_db_two_results(rides, [])
        result = await get_rider_stats(db, rider_id=10)
        assert result["total_spent_dollars"] == 25.0

    @pytest.mark.asyncio
    async def test_falls_back_to_estimated_fare(self):
        rides = [_make_ride(ride_id=1, status=RideStatus.COMPLETED, actual_fare=None, estimated_fare=12.0)]
        db = _make_db_two_results(rides, [])
        result = await get_rider_stats(db, rider_id=10)
        assert result["total_spent_dollars"] == 12.0

    @pytest.mark.asyncio
    async def test_avg_fare_zero_when_no_completed_rides(self):
        rides = [_make_ride(ride_id=1, status=RideStatus.CANCELLED)]
        db = _make_db_two_results(rides, [])
        result = await get_rider_stats(db, rider_id=10)
        assert result["avg_fare_dollars"] == 0.0

    @pytest.mark.asyncio
    async def test_total_distance_sums_completed_rides_only(self):
        rides = [
            _make_ride(ride_id=1, status=RideStatus.COMPLETED, distance_km=10.0),
            _make_ride(ride_id=2, status=RideStatus.COMPLETED, distance_km=5.0),
            _make_ride(ride_id=3, status=RideStatus.CANCELLED, distance_km=7.0),
        ]
        db = _make_db_two_results(rides, [])
        result = await get_rider_stats(db, rider_id=10)
        assert result["total_distance_km"] == 15.0

    @pytest.mark.asyncio
    async def test_total_distance_excludes_none_distances(self):
        rides = [
            _make_ride(ride_id=1, status=RideStatus.COMPLETED, distance_km=8.0),
            _make_ride(ride_id=2, status=RideStatus.COMPLETED, distance_km=None),
        ]
        db = _make_db_two_results(rides, [])
        result = await get_rider_stats(db, rider_id=10)
        assert result["total_distance_km"] == 8.0

    @pytest.mark.asyncio
    async def test_avg_rating_given_none_when_no_ratings(self):
        rides = [_make_ride(ride_id=1, driver_rating=None)]
        db = _make_db_two_results(rides, [])
        result = await get_rider_stats(db, rider_id=10)
        assert result["avg_rating_given"] is None

    @pytest.mark.asyncio
    async def test_avg_rating_given_averages_values(self):
        rides = [
            _make_ride(ride_id=1, driver_rating=4),
            _make_ride(ride_id=2, driver_rating=5),
            _make_ride(ride_id=3, driver_rating=5),
        ]
        db = _make_db_two_results(rides, [])
        result = await get_rider_stats(db, rider_id=10)
        assert result["avg_rating_given"] == pytest.approx(4.67, abs=0.01)

    @pytest.mark.asyncio
    async def test_tips_given_count(self):
        tips = [_make_tip(tip_id=1), _make_tip(tip_id=2), _make_tip(tip_id=3)]
        db = _make_db_two_results([], tips)
        result = await get_rider_stats(db, rider_id=10)
        assert result["tips_given_count"] == 3

    @pytest.mark.asyncio
    async def test_total_tips_given_converts_cents_to_dollars(self):
        tips = [_make_tip(tip_id=1, amount_cents=300), _make_tip(tip_id=2, amount_cents=500)]
        db = _make_db_two_results([], tips)
        result = await get_rider_stats(db, rider_id=10)
        assert result["total_tips_given_dollars"] == 8.0

    @pytest.mark.asyncio
    async def test_member_since_passed_through(self):
        ts = datetime(2024, 6, 15, tzinfo=timezone.utc)
        db = _make_db_two_results([], [])
        result = await get_rider_stats(db, rider_id=10, member_since=ts)
        assert result["member_since"] == ts


# ---------------------------------------------------------------------------
# API integration tests
# ---------------------------------------------------------------------------

pytestmark = pytest.mark.anyio


class TestRiderStatsEndpoint:
    async def test_requires_auth(self, client):
        resp = await client.get("/analytics/rider/stats")
        assert resp.status_code == 401

    async def test_200_with_auth(self, client, rider_token):
        from tests.conftest import auth_header
        resp = await client.get("/analytics/rider/stats", headers=auth_header(rider_token))
        assert resp.status_code == 200

    async def test_driver_also_gets_200(self, client, driver_token):
        from tests.conftest import auth_header
        resp = await client.get("/analytics/rider/stats", headers=auth_header(driver_token))
        assert resp.status_code == 200

    async def test_response_has_required_fields(self, client, rider_token):
        from tests.conftest import auth_header
        resp = await client.get("/analytics/rider/stats", headers=auth_header(rider_token))
        data = resp.json()
        for field in [
            "total_rides", "completed_rides", "cancelled_rides",
            "completion_rate_pct", "total_spent_dollars", "avg_fare_dollars",
            "total_distance_km", "avg_rating_given", "tips_given_count",
            "total_tips_given_dollars", "member_since",
        ]:
            assert field in data, f"Missing field: {field}"

    async def test_zero_total_rides_for_new_rider(self, client, rider_token):
        from tests.conftest import auth_header
        resp = await client.get("/analytics/rider/stats", headers=auth_header(rider_token))
        assert resp.json()["total_rides"] == 0

    async def test_completed_rides_zero(self, client, rider_token):
        from tests.conftest import auth_header
        resp = await client.get("/analytics/rider/stats", headers=auth_header(rider_token))
        assert resp.json()["completed_rides"] == 0

    async def test_completion_rate_zero_for_no_rides(self, client, rider_token):
        from tests.conftest import auth_header
        resp = await client.get("/analytics/rider/stats", headers=auth_header(rider_token))
        assert resp.json()["completion_rate_pct"] == 0.0

    async def test_member_since_is_not_null(self, client, rider_token):
        from tests.conftest import auth_header
        resp = await client.get("/analytics/rider/stats", headers=auth_header(rider_token))
        assert resp.json()["member_since"] is not None
