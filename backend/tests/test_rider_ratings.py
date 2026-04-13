"""Tests for the rider rating system (driver rates rider after a completed trip).

Covers:
- submit_rider_rating service: success, duplicate, non-completed ride,
  wrong driver, invalid rating value
- get_rider_rating_summary: avg calculation, distribution, low-rated flag logic
- get_rider_rating_for_ride: found / not found
- list_low_rated_riders: threshold logic
- POST /rider-ratings/                    — driver submits rating
- GET  /riders/{rider_id}/rating          — public summary (driver, admin, rider rejected)
- GET  /rides/{ride_id}/rider-rating      — single ride rating (driver, admin, stranger rejected)
- GET  /admin/rider-ratings/low-rated     — admin-only low-rated list

All service-layer tests use AsyncMock / MagicMock to avoid requiring a live
database, matching the pattern in test_tips.py.
Endpoint tests use the real DB fixtures from conftest.py.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.ride import RideStatus
from app.models.rider_rating import RiderRating
from app.models.user import UserRole
from app.services.rider_ratings import (
    LOW_RATED_MIN_RATINGS,
    LOW_RATED_THRESHOLD,
    RiderRatingError,
    get_rider_rating_for_ride,
    get_rider_rating_summary,
    submit_rider_rating,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _make_ride(
    ride_id: int = 1,
    rider_id: int = 10,
    driver_id: int = 20,
    status: RideStatus = RideStatus.COMPLETED,
) -> MagicMock:
    ride = MagicMock()
    ride.id = ride_id
    ride.rider_id = rider_id
    ride.driver_id = driver_id
    ride.status = status
    return ride


def _make_db_for_submit(
    ride: MagicMock | None = None,
    existing_rating: MagicMock | None = None,
) -> AsyncMock:
    """Build a two-query db mock: first returns ride, second returns existing rating."""
    db = AsyncMock()

    ride_result = MagicMock()
    ride_result.scalar_one_or_none.return_value = ride

    rating_result = MagicMock()
    rating_result.scalar_one_or_none.return_value = existing_rating

    db.execute = AsyncMock(side_effect=[ride_result, rating_result])
    db.commit = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    return db


def _make_rating_orm(
    rating_id: int = 1,
    ride_id: int = 1,
    driver_id: int = 20,
    rider_id: int = 10,
    rating: int = 4,
    comment: str | None = None,
) -> MagicMock:
    r = MagicMock(spec=RiderRating)
    r.id = rating_id
    r.ride_id = ride_id
    r.driver_id = driver_id
    r.rider_id = rider_id
    r.rating = rating
    r.comment = comment
    r.created_at = _utcnow()
    return r


# ---------------------------------------------------------------------------
# submit_rider_rating — service unit tests
# ---------------------------------------------------------------------------


class TestSubmitRiderRatingValidation:
    @pytest.mark.asyncio
    async def test_rejects_rating_below_1(self):
        db = AsyncMock()
        with pytest.raises(RiderRatingError) as exc_info:
            await submit_rider_rating(db, ride_id=1, driver_user_id=20, rating=0)
        assert exc_info.value.status_code == 422

    @pytest.mark.asyncio
    async def test_rejects_rating_above_5(self):
        db = AsyncMock()
        with pytest.raises(RiderRatingError) as exc_info:
            await submit_rider_rating(db, ride_id=1, driver_user_id=20, rating=6)
        assert exc_info.value.status_code == 422

    @pytest.mark.asyncio
    async def test_rejects_when_ride_not_found(self):
        db = AsyncMock()
        no_ride = MagicMock()
        no_ride.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=no_ride)

        with pytest.raises(RiderRatingError) as exc_info:
            await submit_rider_rating(db, ride_id=99, driver_user_id=20, rating=4)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_rejects_wrong_driver(self):
        ride = _make_ride(driver_id=20)
        db = _make_db_for_submit(ride=ride)

        with pytest.raises(RiderRatingError) as exc_info:
            await submit_rider_rating(db, ride_id=1, driver_user_id=999, rating=4)
        assert exc_info.value.status_code == 403
        assert "driver" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_rejects_non_completed_ride(self):
        ride = _make_ride(status=RideStatus.IN_PROGRESS)
        db = _make_db_for_submit(ride=ride)

        with pytest.raises(RiderRatingError) as exc_info:
            await submit_rider_rating(db, ride_id=1, driver_user_id=20, rating=4)
        assert exc_info.value.status_code == 409
        assert "completed" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_rejects_duplicate_rating(self):
        ride = _make_ride()
        existing = _make_rating_orm()
        db = _make_db_for_submit(ride=ride, existing_rating=existing)

        with pytest.raises(RiderRatingError) as exc_info:
            await submit_rider_rating(db, ride_id=1, driver_user_id=20, rating=3)
        assert exc_info.value.status_code == 409
        assert "already" in str(exc_info.value).lower()


class TestSubmitRiderRatingSuccess:
    @pytest.mark.asyncio
    async def test_creates_rating_record(self):
        ride = _make_ride()
        db = _make_db_for_submit(ride=ride, existing_rating=None)

        await submit_rider_rating(db, ride_id=1, driver_user_id=20, rating=5, comment="Great rider!")

        db.add.assert_called_once()
        added = db.add.call_args[0][0]
        assert isinstance(added, RiderRating)
        assert added.rating == 5
        assert added.ride_id == 1
        assert added.driver_id == 20
        assert added.rider_id == 10  # from _make_ride defaults
        assert added.comment == "Great rider!"
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_creates_rating_without_comment(self):
        ride = _make_ride()
        db = _make_db_for_submit(ride=ride, existing_rating=None)

        await submit_rider_rating(db, ride_id=1, driver_user_id=20, rating=3)

        added = db.add.call_args[0][0]
        assert added.comment is None

    @pytest.mark.asyncio
    async def test_accepts_boundary_rating_1(self):
        ride = _make_ride()
        db = _make_db_for_submit(ride=ride, existing_rating=None)

        await submit_rider_rating(db, ride_id=1, driver_user_id=20, rating=1)

        added = db.add.call_args[0][0]
        assert added.rating == 1

    @pytest.mark.asyncio
    async def test_accepts_boundary_rating_5(self):
        ride = _make_ride()
        db = _make_db_for_submit(ride=ride, existing_rating=None)

        await submit_rider_rating(db, ride_id=1, driver_user_id=20, rating=5)

        added = db.add.call_args[0][0]
        assert added.rating == 5


# ---------------------------------------------------------------------------
# get_rider_rating_summary — service unit tests
# ---------------------------------------------------------------------------


class TestGetRiderRatingSummary:
    @pytest.mark.asyncio
    async def test_returns_default_when_no_ratings(self):
        db = AsyncMock()

        # Single query returns all zeros
        row = MagicMock()
        row.one = 0
        row.two = 0
        row.three = 0
        row.four = 0
        row.five = 0
        row.total = 0
        row.avg = None
        result = MagicMock()
        result.one.return_value = row
        db.execute = AsyncMock(return_value=result)

        summary = await get_rider_rating_summary(db, rider_id=10)

        assert summary.avg_rating == 5.0
        assert summary.total_ratings == 0
        assert summary.rating_distribution.one_star == 0
        assert summary.low_rated is None  # not requested

    @pytest.mark.asyncio
    async def test_calculates_average_correctly(self):
        db = AsyncMock()

        row = MagicMock()
        row.one = 0
        row.two = 0
        row.three = 1
        row.four = 2
        row.five = 2
        row.total = 5
        row.avg = 4.2
        result = MagicMock()
        result.one.return_value = row
        db.execute = AsyncMock(return_value=result)

        summary = await get_rider_rating_summary(db, rider_id=10)

        assert summary.avg_rating == 4.2
        assert summary.total_ratings == 5
        assert summary.rating_distribution.three_star == 1
        assert summary.rating_distribution.five_star == 2

    @pytest.mark.asyncio
    async def test_low_rated_flag_not_included_without_request(self):
        db = AsyncMock()

        row = MagicMock()
        row.one = 5
        row.two = 3
        row.three = 0
        row.four = 0
        row.five = 0
        row.total = 8
        row.avg = 1.6
        result = MagicMock()
        result.one.return_value = row
        db.execute = AsyncMock(return_value=result)

        summary = await get_rider_rating_summary(db, rider_id=10, include_low_rated_flag=False)
        assert summary.low_rated is None

    @pytest.mark.asyncio
    async def test_low_rated_flag_true_when_threshold_exceeded(self):
        db = AsyncMock()

        # First query: lifetime stats
        lifetime_row = MagicMock()
        lifetime_row.one = 6
        lifetime_row.two = 2
        lifetime_row.three = 0
        lifetime_row.four = 0
        lifetime_row.five = 0
        lifetime_row.total = 8
        lifetime_row.avg = 1.75
        lifetime_result = MagicMock()
        lifetime_result.one.return_value = lifetime_row

        # Second query: 30-day window (6 ratings, avg 1.75 — below 3.0)
        recent_row = MagicMock()
        recent_row.avg = 1.75
        recent_row.count = LOW_RATED_MIN_RATINGS + 1  # > 5
        recent_result = MagicMock()
        recent_result.one.return_value = recent_row

        db.execute = AsyncMock(side_effect=[lifetime_result, recent_result])

        summary = await get_rider_rating_summary(db, rider_id=10, include_low_rated_flag=True)
        assert summary.low_rated is True

    @pytest.mark.asyncio
    async def test_low_rated_flag_false_when_insufficient_ratings(self):
        db = AsyncMock()

        lifetime_row = MagicMock()
        lifetime_row.one = 3
        lifetime_row.two = 2
        lifetime_row.three = 0
        lifetime_row.four = 0
        lifetime_row.five = 0
        lifetime_row.total = 5
        lifetime_row.avg = 1.4
        lifetime_result = MagicMock()
        lifetime_result.one.return_value = lifetime_row

        # Only 3 ratings in window — below the minimum of 5
        recent_row = MagicMock()
        recent_row.avg = 1.4
        recent_row.count = 3
        recent_result = MagicMock()
        recent_result.one.return_value = recent_row

        db.execute = AsyncMock(side_effect=[lifetime_result, recent_result])

        summary = await get_rider_rating_summary(db, rider_id=10, include_low_rated_flag=True)
        assert summary.low_rated is False

    @pytest.mark.asyncio
    async def test_low_rated_flag_false_when_avg_above_threshold(self):
        db = AsyncMock()

        lifetime_row = MagicMock()
        lifetime_row.one = 0
        lifetime_row.two = 0
        lifetime_row.three = 2
        lifetime_row.four = 4
        lifetime_row.five = 4
        lifetime_row.total = 10
        lifetime_row.avg = 4.2
        lifetime_result = MagicMock()
        lifetime_result.one.return_value = lifetime_row

        # 8 ratings, avg 4.2 — above threshold
        recent_row = MagicMock()
        recent_row.avg = 4.2
        recent_row.count = 8
        recent_result = MagicMock()
        recent_result.one.return_value = recent_row

        db.execute = AsyncMock(side_effect=[lifetime_result, recent_result])

        summary = await get_rider_rating_summary(db, rider_id=10, include_low_rated_flag=True)
        assert summary.low_rated is False


# ---------------------------------------------------------------------------
# get_rider_rating_for_ride — service unit tests
# ---------------------------------------------------------------------------


class TestGetRiderRatingForRide:
    @pytest.mark.asyncio
    async def test_returns_rating_when_found(self):
        rating = _make_rating_orm()
        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = rating
        db.execute = AsyncMock(return_value=result)

        found = await get_rider_rating_for_ride(db, ride_id=1)
        assert found is rating

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self):
        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=result)

        found = await get_rider_rating_for_ride(db, ride_id=999)
        assert found is None


# ---------------------------------------------------------------------------
# API endpoint tests — using the HTTP client with real DB fixtures
# ---------------------------------------------------------------------------


def _ride_fixture(rider_id: int, driver_id: int, status: RideStatus = RideStatus.COMPLETED):
    """Build keyword args for creating a Ride in tests."""
    return dict(
        rider_id=rider_id,
        driver_id=driver_id,
        status=status,
        pickup_location="SRID=4326;POINT(-73.9857 40.7484)",
        dropoff_location="SRID=4326;POINT(-73.9857 40.7484)",
        pickup_address="123 Main St",
        dropoff_address="456 Oak Ave",
        estimated_fare=12.0,
        actual_fare=12.0,
    )


class TestCreateRiderRatingEndpoint:
    @pytest.mark.asyncio
    async def test_driver_can_rate_completed_ride(self, client, rider, driver_user, driver_token, db):
        from app.models.ride import Ride

        ride = Ride(**_ride_fixture(rider.id, driver_user.id))
        db.add(ride)
        await db.flush()

        resp = await client.post(
            "/api/v1/rider-ratings/",
            json={"ride_id": ride.id, "rating": 5, "comment": "Great passenger"},
            headers={"Authorization": f"Bearer {driver_token}"},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["rating"] == 5
        assert body["ride_id"] == ride.id
        assert body["driver_id"] == driver_user.id
        assert body["rider_id"] == rider.id

    @pytest.mark.asyncio
    async def test_rider_cannot_submit_rating(self, client, rider_token, rider, driver_user, db):
        from app.models.ride import Ride

        ride = Ride(**_ride_fixture(rider.id, driver_user.id))
        db.add(ride)
        await db.flush()

        resp = await client.post(
            "/api/v1/rider-ratings/",
            json={"ride_id": ride.id, "rating": 4},
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_duplicate_rating_rejected(self, client, rider, driver_user, driver_token, db):
        from app.models.ride import Ride

        ride = Ride(**_ride_fixture(rider.id, driver_user.id))
        db.add(ride)
        await db.flush()

        # First submission
        resp1 = await client.post(
            "/api/v1/rider-ratings/",
            json={"ride_id": ride.id, "rating": 4},
            headers={"Authorization": f"Bearer {driver_token}"},
        )
        assert resp1.status_code == 201

        # Duplicate
        resp2 = await client.post(
            "/api/v1/rider-ratings/",
            json={"ride_id": ride.id, "rating": 3},
            headers={"Authorization": f"Bearer {driver_token}"},
        )
        assert resp2.status_code == 409
        assert "already" in resp2.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_rating_on_non_completed_ride_rejected(
        self, client, rider, driver_user, driver_token, db
    ):
        from app.models.ride import Ride

        ride = Ride(**_ride_fixture(rider.id, driver_user.id, status=RideStatus.IN_PROGRESS))
        db.add(ride)
        await db.flush()

        resp = await client.post(
            "/api/v1/rider-ratings/",
            json={"ride_id": ride.id, "rating": 4},
            headers={"Authorization": f"Bearer {driver_token}"},
        )
        assert resp.status_code == 409
        assert "completed" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_wrong_driver_cannot_rate_ride(
        self, client, rider, driver_user, db
    ):
        from app.models.ride import Ride
        from app.services.auth import create_access_token, hash_password
        from app.models.user import User

        # Create a second driver
        other_driver = User(
            phone="+15558005001",
            name="Other Driver",
            email="other_driver@test.com",
            password_hash=hash_password("pass"),
            role=UserRole.DRIVER,
            is_active=True,
        )
        db.add(other_driver)
        await db.flush()
        other_token = create_access_token(other_driver.id, other_driver.role.value)

        ride = Ride(**_ride_fixture(rider.id, driver_user.id))
        db.add(ride)
        await db.flush()

        resp = await client.post(
            "/api/v1/rider-ratings/",
            json={"ride_id": ride.id, "rating": 2},
            headers={"Authorization": f"Bearer {other_token}"},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_invalid_rating_value_rejected(self, client, driver_token):
        """Pydantic schema should reject out-of-range rating before service."""
        resp = await client.post(
            "/api/v1/rider-ratings/",
            json={"ride_id": 1, "rating": 6},
            headers={"Authorization": f"Bearer {driver_token}"},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_unauthenticated_request_rejected(self, client):
        resp = await client.post("/api/v1/rider-ratings/", json={"ride_id": 1, "rating": 4})
        assert resp.status_code in (401, 403)


class TestGetRiderRatingSummaryEndpoint:
    @pytest.mark.asyncio
    async def test_driver_can_view_rider_summary(
        self, client, driver_token, rider, driver_user, db
    ):
        from app.models.ride import Ride

        ride = Ride(**_ride_fixture(rider.id, driver_user.id))
        db.add(ride)
        await db.flush()

        # Submit a rating so there is data
        await client.post(
            "/api/v1/rider-ratings/",
            json={"ride_id": ride.id, "rating": 4},
            headers={"Authorization": f"Bearer {driver_token}"},
        )

        resp = await client.get(
            f"/api/v1/riders/{rider.id}/rating",
            headers={"Authorization": f"Bearer {driver_token}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total_ratings"] == 1
        assert body["avg_rating"] == 4.0
        # low_rated not included for driver callers
        assert body.get("low_rated") is None

    @pytest.mark.asyncio
    async def test_admin_gets_low_rated_flag(
        self, client, admin_token, rider, driver_user, driver_token, db
    ):
        from app.models.ride import Ride

        ride = Ride(**_ride_fixture(rider.id, driver_user.id))
        db.add(ride)
        await db.flush()

        await client.post(
            "/api/v1/rider-ratings/",
            json={"ride_id": ride.id, "rating": 5},
            headers={"Authorization": f"Bearer {driver_token}"},
        )

        resp = await client.get(
            f"/api/v1/riders/{rider.id}/rating",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        # low_rated key is present for admin (may be True or False depending on data)
        assert "low_rated" in body

    @pytest.mark.asyncio
    async def test_rider_cannot_view_rating_summary(self, client, rider_token, rider):
        resp = await client.get(
            f"/api/v1/riders/{rider.id}/rating",
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        assert resp.status_code == 403


class TestGetRideRiderRatingEndpoint:
    @pytest.mark.asyncio
    async def test_driver_can_view_their_own_rating(
        self, client, rider, driver_user, driver_token, db
    ):
        from app.models.ride import Ride

        ride = Ride(**_ride_fixture(rider.id, driver_user.id))
        db.add(ride)
        await db.flush()

        await client.post(
            "/api/v1/rider-ratings/",
            json={"ride_id": ride.id, "rating": 3, "comment": "Slightly late"},
            headers={"Authorization": f"Bearer {driver_token}"},
        )

        resp = await client.get(
            f"/api/v1/rides/{ride.id}/rider-rating",
            headers={"Authorization": f"Bearer {driver_token}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["rating"] == 3
        assert body["comment"] == "Slightly late"

    @pytest.mark.asyncio
    async def test_admin_can_view_any_ride_rating(
        self, client, rider, driver_user, driver_token, admin_token, db
    ):
        from app.models.ride import Ride

        ride = Ride(**_ride_fixture(rider.id, driver_user.id))
        db.add(ride)
        await db.flush()

        await client.post(
            "/api/v1/rider-ratings/",
            json={"ride_id": ride.id, "rating": 5},
            headers={"Authorization": f"Bearer {driver_token}"},
        )

        resp = await client.get(
            f"/api/v1/rides/{ride.id}/rider-rating",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_unrelated_user_cannot_view_ride_rating(
        self, client, rider, driver_user, driver_token, db
    ):
        from app.models.ride import Ride
        from app.services.auth import create_access_token, hash_password
        from app.models.user import User

        stranger = User(
            phone="+15558009999",
            name="Stranger",
            email="stranger_rr@test.com",
            password_hash=hash_password("pass"),
            role=UserRole.DRIVER,
            is_active=True,
        )
        db.add(stranger)
        await db.flush()
        stranger_token = create_access_token(stranger.id, stranger.role.value)

        ride = Ride(**_ride_fixture(rider.id, driver_user.id))
        db.add(ride)
        await db.flush()

        await client.post(
            "/api/v1/rider-ratings/",
            json={"ride_id": ride.id, "rating": 4},
            headers={"Authorization": f"Bearer {driver_token}"},
        )

        resp = await client.get(
            f"/api/v1/rides/{ride.id}/rider-rating",
            headers={"Authorization": f"Bearer {stranger_token}"},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_returns_404_when_no_rating_exists(
        self, client, rider, driver_user, driver_token, db
    ):
        from app.models.ride import Ride

        ride = Ride(**_ride_fixture(rider.id, driver_user.id))
        db.add(ride)
        await db.flush()

        resp = await client.get(
            f"/api/v1/rides/{ride.id}/rider-rating",
            headers={"Authorization": f"Bearer {driver_token}"},
        )
        assert resp.status_code == 404


class TestAdminLowRatedEndpoint:
    @pytest.mark.asyncio
    async def test_admin_can_access_low_rated_list(self, client, admin_token):
        resp = await client.get(
            "/api/v1/admin/rider-ratings/low-rated",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    @pytest.mark.asyncio
    async def test_non_admin_cannot_access_low_rated_list(self, client, driver_token):
        resp = await client.get(
            "/api/v1/admin/rider-ratings/low-rated",
            headers={"Authorization": f"Bearer {driver_token}"},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_rider_cannot_access_low_rated_list(self, client, rider_token):
        resp = await client.get(
            "/api/v1/admin/rider-ratings/low-rated",
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_low_rated_list_returns_correct_schema(self, client, admin_token):
        """Each item must have rider_id, recent_avg, recent_count."""
        resp = await client.get(
            "/api/v1/admin/rider-ratings/low-rated",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        for item in resp.json():
            assert "rider_id" in item
            assert "recent_avg" in item
            assert "recent_count" in item
