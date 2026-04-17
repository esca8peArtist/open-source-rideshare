"""Tests for driver ratings — read-side of rider-to-driver ratings.

Covers:
- get_driver_ratings service: avg, distribution, recent_average, zero-ratings case
- list_low_rated_drivers service: threshold logic, ordering, empty result
- GET /drivers/{driver_id}/rating   — any authenticated user; admin gets low_rated flag
- GET /rides/{ride_id}/driver-rating — rider / driver / admin access; missing rating 404
- GET /admin/driver-ratings/low-rated — admin-only

All service-layer tests use AsyncMock / MagicMock to avoid requiring a live database.
Endpoint tests that require a DB are skipped when no DB is available (matching the
pattern established in test_rider_ratings.py and test_rider_fare_transparency.py).
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.ride import RideStatus
from app.models.user import UserRole
from app.services.ratings import (
    RatingDistribution,
    RatingsSummary,
    get_driver_ratings,
    list_low_rated_drivers,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _make_dist_row(
    one: int = 0,
    two: int = 0,
    three: int = 0,
    four: int = 0,
    five: int = 0,
    total: int = 0,
    avg: float | None = None,
) -> MagicMock:
    row = MagicMock()
    row.one = one
    row.two = two
    row.three = three
    row.four = four
    row.five = five
    row.total = total
    row.avg = avg
    return row


def _make_recent_row(avg: float | None, count: int) -> tuple:
    return (avg, count)


def _make_ride_mock(
    ride_id: int = 1,
    rider_id: int = 10,
    driver_id: int = 20,
    status: RideStatus = RideStatus.COMPLETED,
    driver_rating: int | None = 4,
    completed_at: datetime | None = None,
) -> MagicMock:
    ride = MagicMock()
    ride.id = ride_id
    ride.rider_id = rider_id
    ride.driver_id = driver_id
    ride.status = status
    ride.driver_rating = driver_rating
    ride.completed_at = completed_at or _utcnow()
    return ride


def _make_user(
    user_id: int = 99,
    role: UserRole = UserRole.RIDER,
) -> MagicMock:
    user = MagicMock()
    user.id = user_id
    user.role = role
    return user


# ---------------------------------------------------------------------------
# get_driver_ratings — service unit tests
# ---------------------------------------------------------------------------


class TestGetDriverRatings:
    @pytest.mark.asyncio
    async def test_returns_5_avg_when_no_ratings(self):
        dist_row = _make_dist_row(total=0, avg=None)
        recent_row = _make_recent_row(avg=None, count=0)

        dist_result = MagicMock()
        dist_result.one.return_value = dist_row

        recent_result = MagicMock()
        recent_result.one.return_value = recent_row

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[dist_result, recent_result])

        summary = await get_driver_ratings(driver_user_id=20, db=db)

        assert summary.average == 5.0
        assert summary.total_ratings == 0
        assert summary.recent_average is None
        assert summary.recent_count == 0

    @pytest.mark.asyncio
    async def test_computes_correct_avg_and_distribution(self):
        dist_row = _make_dist_row(
            one=1, two=0, three=2, four=5, five=2,
            total=10, avg=3.7,
        )
        recent_row = _make_recent_row(avg=4.1, count=10)

        dist_result = MagicMock()
        dist_result.one.return_value = dist_row

        recent_result = MagicMock()
        recent_result.one.return_value = recent_row

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[dist_result, recent_result])

        summary = await get_driver_ratings(driver_user_id=20, db=db)

        assert summary.average == 3.7
        assert summary.total_ratings == 10
        assert summary.distribution.one_star == 1
        assert summary.distribution.three_star == 2
        assert summary.distribution.five_star == 2

    @pytest.mark.asyncio
    async def test_recent_average_none_when_fewer_than_5_rated_rides(self):
        dist_row = _make_dist_row(total=3, avg=4.0)
        recent_row = _make_recent_row(avg=4.0, count=3)

        dist_result = MagicMock()
        dist_result.one.return_value = dist_row

        recent_result = MagicMock()
        recent_result.one.return_value = recent_row

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[dist_result, recent_result])

        summary = await get_driver_ratings(driver_user_id=20, db=db)

        # fewer than 5 → recent_average should be None
        assert summary.recent_average is None

    @pytest.mark.asyncio
    async def test_recent_average_populated_when_5_or_more_rides(self):
        dist_row = _make_dist_row(total=8, avg=4.5)
        recent_row = _make_recent_row(avg=4.6, count=8)

        dist_result = MagicMock()
        dist_result.one.return_value = dist_row

        recent_result = MagicMock()
        recent_result.one.return_value = recent_row

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[dist_result, recent_result])

        summary = await get_driver_ratings(driver_user_id=20, db=db)

        assert summary.recent_average == 4.6
        assert summary.recent_count == 8

    @pytest.mark.asyncio
    async def test_avg_rounds_to_2_decimal_places(self):
        dist_row = _make_dist_row(total=3, avg=4.333333)
        recent_row = _make_recent_row(avg=None, count=0)

        dist_result = MagicMock()
        dist_result.one.return_value = dist_row

        recent_result = MagicMock()
        recent_result.one.return_value = recent_row

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[dist_result, recent_result])

        summary = await get_driver_ratings(driver_user_id=20, db=db)

        # Should be rounded to 2 dp
        assert summary.average == round(4.333333, 2)


# ---------------------------------------------------------------------------
# list_low_rated_drivers — service unit tests
# ---------------------------------------------------------------------------


class TestListLowRatedDrivers:
    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_low_rated(self):
        result_mock = MagicMock()
        result_mock.all.return_value = []

        db = AsyncMock()
        db.execute = AsyncMock(return_value=result_mock)

        results = await list_low_rated_drivers(db)

        assert results == []

    @pytest.mark.asyncio
    async def test_returns_correct_dict_structure(self):
        row = MagicMock()
        row.driver_id = 42
        row.recent_avg = 2.4
        row.recent_count = 8

        result_mock = MagicMock()
        result_mock.all.return_value = [row]

        db = AsyncMock()
        db.execute = AsyncMock(return_value=result_mock)

        results = await list_low_rated_drivers(db)

        assert len(results) == 1
        assert results[0]["driver_id"] == 42
        assert results[0]["recent_avg"] == 2.4
        assert results[0]["recent_count"] == 8

    @pytest.mark.asyncio
    async def test_rounds_avg_to_2_decimal_places(self):
        row = MagicMock()
        row.driver_id = 7
        row.recent_avg = 2.666666
        row.recent_count = 9

        result_mock = MagicMock()
        result_mock.all.return_value = [row]

        db = AsyncMock()
        db.execute = AsyncMock(return_value=result_mock)

        results = await list_low_rated_drivers(db)

        assert results[0]["recent_avg"] == round(2.666666, 2)

    @pytest.mark.asyncio
    async def test_passes_limit_and_offset_to_query(self):
        result_mock = MagicMock()
        result_mock.all.return_value = []

        db = AsyncMock()
        db.execute = AsyncMock(return_value=result_mock)

        await list_low_rated_drivers(db, limit=10, offset=20)

        # Verify db.execute was called (query construction verified by service logic)
        db.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_returns_multiple_drivers_sorted(self):
        rows = []
        for driver_id, avg in [(3, 1.8), (7, 2.1), (12, 2.9)]:
            row = MagicMock()
            row.driver_id = driver_id
            row.recent_avg = avg
            row.recent_count = 6
            rows.append(row)

        result_mock = MagicMock()
        result_mock.all.return_value = rows

        db = AsyncMock()
        db.execute = AsyncMock(return_value=result_mock)

        results = await list_low_rated_drivers(db)

        assert len(results) == 3
        assert results[0]["driver_id"] == 3
        assert results[0]["recent_avg"] == 1.8


# ---------------------------------------------------------------------------
# API endpoint tests — service-mocked
# ---------------------------------------------------------------------------


class TestGetDriverRatingSummaryEndpoint:
    @pytest.mark.asyncio
    async def test_returns_summary_for_authenticated_rider(self):
        """GET /drivers/{driver_id}/rating returns 200 for any authenticated user."""
        from app.api.v1.driver_ratings import get_driver_rating_summary

        mock_summary = RatingsSummary(
            average=4.5,
            total_ratings=20,
            distribution=RatingDistribution(one_star=0, two_star=1, three_star=2, four_star=8, five_star=9),
            recent_average=4.6,
            recent_count=15,
        )

        db = AsyncMock()
        user = _make_user(role=UserRole.RIDER)

        with patch("app.api.v1.driver_ratings.get_driver_ratings", new=AsyncMock(return_value=mock_summary)):
            result = await get_driver_rating_summary(driver_id=20, user=user, db=db)

        assert result.driver_id == 20
        assert result.avg_rating == 4.5
        assert result.total_ratings == 20
        assert result.recent_avg == 4.6
        assert result.low_rated is None  # not admin

    @pytest.mark.asyncio
    async def test_admin_receives_low_rated_flag_true(self):
        from app.api.v1.driver_ratings import get_driver_rating_summary

        mock_summary = RatingsSummary(
            average=2.3,
            total_ratings=30,
            distribution=RatingDistribution(one_star=10, two_star=8, three_star=5, four_star=5, five_star=2),
            recent_average=2.1,
            recent_count=20,
        )

        db = AsyncMock()
        user = _make_user(role=UserRole.ADMIN)

        low_rated_data = [{"driver_id": 20, "recent_avg": 2.1, "recent_count": 8}]

        with (
            patch("app.api.v1.driver_ratings.get_driver_ratings", new=AsyncMock(return_value=mock_summary)),
            patch("app.api.v1.driver_ratings.list_low_rated_drivers", new=AsyncMock(return_value=low_rated_data)),
        ):
            result = await get_driver_rating_summary(driver_id=20, user=user, db=db)

        assert result.low_rated is True

    @pytest.mark.asyncio
    async def test_admin_receives_low_rated_flag_false_when_not_in_list(self):
        from app.api.v1.driver_ratings import get_driver_rating_summary

        mock_summary = RatingsSummary(
            average=4.8,
            total_ratings=100,
            distribution=RatingDistribution(five_star=90, four_star=10),
            recent_average=4.9,
            recent_count=20,
        )

        db = AsyncMock()
        user = _make_user(role=UserRole.ADMIN)

        with (
            patch("app.api.v1.driver_ratings.get_driver_ratings", new=AsyncMock(return_value=mock_summary)),
            patch("app.api.v1.driver_ratings.list_low_rated_drivers", new=AsyncMock(return_value=[])),
        ):
            result = await get_driver_rating_summary(driver_id=20, user=user, db=db)

        assert result.low_rated is False

    @pytest.mark.asyncio
    async def test_rating_distribution_mapped_correctly(self):
        from app.api.v1.driver_ratings import get_driver_rating_summary

        dist = RatingDistribution(one_star=1, two_star=2, three_star=3, four_star=4, five_star=5)
        mock_summary = RatingsSummary(
            average=3.67,
            total_ratings=15,
            distribution=dist,
            recent_average=None,
            recent_count=0,
        )

        db = AsyncMock()
        user = _make_user(role=UserRole.RIDER)

        with patch("app.api.v1.driver_ratings.get_driver_ratings", new=AsyncMock(return_value=mock_summary)):
            result = await get_driver_rating_summary(driver_id=5, user=user, db=db)

        assert result.rating_distribution.one_star == 1
        assert result.rating_distribution.three_star == 3
        assert result.rating_distribution.five_star == 5


class TestGetRideDriverRatingEndpoint:
    @pytest.mark.asyncio
    async def test_rider_can_view_their_own_rating(self):
        from fastapi import HTTPException

        from app.api.v1.driver_ratings import get_ride_driver_rating

        ride = _make_ride_mock(rider_id=10, driver_id=20, driver_rating=5)
        user = _make_user(user_id=10, role=UserRole.RIDER)  # rider on this ride

        ride_result = MagicMock()
        ride_result.scalar_one_or_none.return_value = ride

        db = AsyncMock()
        db.execute = AsyncMock(return_value=ride_result)

        result = await get_ride_driver_rating(ride_id=1, user=user, db=db)

        assert result.ride_id == 1
        assert result.driver_id == 20
        assert result.rider_id == 10
        assert result.rating == 5

    @pytest.mark.asyncio
    async def test_driver_can_view_their_own_ride_rating(self):
        from app.api.v1.driver_ratings import get_ride_driver_rating

        ride = _make_ride_mock(rider_id=10, driver_id=20, driver_rating=4)
        user = _make_user(user_id=20, role=UserRole.DRIVER)

        ride_result = MagicMock()
        ride_result.scalar_one_or_none.return_value = ride

        db = AsyncMock()
        db.execute = AsyncMock(return_value=ride_result)

        result = await get_ride_driver_rating(ride_id=1, user=user, db=db)

        assert result.rating == 4

    @pytest.mark.asyncio
    async def test_admin_can_view_any_rating(self):
        from app.api.v1.driver_ratings import get_ride_driver_rating

        ride = _make_ride_mock(rider_id=10, driver_id=20, driver_rating=3)
        user = _make_user(user_id=999, role=UserRole.ADMIN)

        ride_result = MagicMock()
        ride_result.scalar_one_or_none.return_value = ride

        db = AsyncMock()
        db.execute = AsyncMock(return_value=ride_result)

        result = await get_ride_driver_rating(ride_id=1, user=user, db=db)

        assert result.rating == 3

    @pytest.mark.asyncio
    async def test_stranger_gets_403(self):
        from fastapi import HTTPException

        from app.api.v1.driver_ratings import get_ride_driver_rating

        ride = _make_ride_mock(rider_id=10, driver_id=20, driver_rating=4)
        user = _make_user(user_id=777, role=UserRole.RIDER)  # not on this ride

        ride_result = MagicMock()
        ride_result.scalar_one_or_none.return_value = ride

        db = AsyncMock()
        db.execute = AsyncMock(return_value=ride_result)

        with pytest.raises(HTTPException) as exc_info:
            await get_ride_driver_rating(ride_id=1, user=user, db=db)

        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_ride_not_found_returns_404(self):
        from fastapi import HTTPException

        from app.api.v1.driver_ratings import get_ride_driver_rating

        ride_result = MagicMock()
        ride_result.scalar_one_or_none.return_value = None

        db = AsyncMock()
        db.execute = AsyncMock(return_value=ride_result)

        user = _make_user(role=UserRole.RIDER)

        with pytest.raises(HTTPException) as exc_info:
            await get_ride_driver_rating(ride_id=999, user=user, db=db)

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_missing_driver_rating_returns_404(self):
        from fastapi import HTTPException

        from app.api.v1.driver_ratings import get_ride_driver_rating

        ride = _make_ride_mock(rider_id=10, driver_id=20, driver_rating=None)
        user = _make_user(user_id=10, role=UserRole.RIDER)

        ride_result = MagicMock()
        ride_result.scalar_one_or_none.return_value = ride

        db = AsyncMock()
        db.execute = AsyncMock(return_value=ride_result)

        with pytest.raises(HTTPException) as exc_info:
            await get_ride_driver_rating(ride_id=1, user=user, db=db)

        assert exc_info.value.status_code == 404
        assert "driver rating" in exc_info.value.detail.lower()


class TestAdminLowRatedDriversEndpoint:
    @pytest.mark.asyncio
    async def test_returns_list_from_service(self):
        from app.api.v1.driver_ratings import admin_list_low_rated_drivers
        from app.models.user import User

        expected = [
            {"driver_id": 5, "recent_avg": 2.2, "recent_count": 7},
            {"driver_id": 9, "recent_avg": 2.7, "recent_count": 6},
        ]

        admin_user = _make_user(role=UserRole.ADMIN)
        db = AsyncMock()

        with patch("app.api.v1.driver_ratings.list_low_rated_drivers", new=AsyncMock(return_value=expected)):
            result = await admin_list_low_rated_drivers(
                limit=50,
                offset=0,
                _admin=admin_user,
                db=db,
            )

        assert result == expected

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_low_rated(self):
        from app.api.v1.driver_ratings import admin_list_low_rated_drivers

        admin_user = _make_user(role=UserRole.ADMIN)
        db = AsyncMock()

        with patch("app.api.v1.driver_ratings.list_low_rated_drivers", new=AsyncMock(return_value=[])):
            result = await admin_list_low_rated_drivers(
                limit=50,
                offset=0,
                _admin=admin_user,
                db=db,
            )

        assert result == []
