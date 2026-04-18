"""Tests for the rider-submits-driver-rating feature.

Covers:
- submit_driver_rating service: success, duplicate, non-completed ride,
  wrong rider, invalid rating value, ride not found
- get_driver_rating_for_ride service: found / not found
- POST /rides/{ride_id}/driver-rating — rider submits rating
- GET  /rides/{ride_id}/driver-rating — rider retrieves submitted rating

Service tests use AsyncMock / MagicMock (no live DB required).
Endpoint tests use the real DB fixtures from conftest.py.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.feedback import RideFeedback
from app.models.ride import Ride, RideStatus
from app.services.driver_rating_submit import (
    DriverRatingError,
    get_driver_rating_for_ride,
    submit_driver_rating,
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
    ride.driver_rating = None
    return ride


def _make_feedback(
    feedback_id: int = 1,
    ride_id: int = 1,
    rider_id: int = 10,
    rating: int = 4,
    comment: str | None = None,
) -> MagicMock:
    fb = MagicMock(spec=RideFeedback)
    fb.id = feedback_id
    fb.ride_id = ride_id
    fb.user_id = rider_id
    fb.role = "rider"
    fb.rating = rating
    fb.comment = comment
    fb.created_at = _utcnow()
    return fb


def _make_db_for_submit(
    ride: MagicMock | None = None,
    existing_feedback: MagicMock | None = None,
) -> AsyncMock:
    """Build a two-query db mock: first returns ride, second returns existing feedback."""
    db = AsyncMock()

    ride_result = MagicMock()
    ride_result.scalar_one_or_none.return_value = ride

    feedback_result = MagicMock()
    feedback_result.scalar_one_or_none.return_value = existing_feedback

    db.execute = AsyncMock(side_effect=[ride_result, feedback_result])
    db.commit = AsyncMock()
    db.add = MagicMock()
    db.refresh = AsyncMock()
    return db


def _ride_kwargs(rider_id: int, driver_id: int, status: RideStatus = RideStatus.COMPLETED) -> dict:
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


# ---------------------------------------------------------------------------
# submit_driver_rating — validation tests
# ---------------------------------------------------------------------------


class TestSubmitDriverRatingValidation:
    @pytest.mark.asyncio
    async def test_rejects_rating_below_1(self):
        db = AsyncMock()
        with pytest.raises(DriverRatingError) as exc_info:
            await submit_driver_rating(db, ride_id=1, rider_user_id=10, rating=0)
        assert exc_info.value.status_code == 422

    @pytest.mark.asyncio
    async def test_rejects_rating_above_5(self):
        db = AsyncMock()
        with pytest.raises(DriverRatingError) as exc_info:
            await submit_driver_rating(db, ride_id=1, rider_user_id=10, rating=6)
        assert exc_info.value.status_code == 422

    @pytest.mark.asyncio
    async def test_rejects_when_ride_not_found(self):
        db = AsyncMock()
        no_ride = MagicMock()
        no_ride.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=no_ride)

        with pytest.raises(DriverRatingError) as exc_info:
            await submit_driver_rating(db, ride_id=99, rider_user_id=10, rating=4)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_rejects_wrong_rider(self):
        ride = _make_ride(rider_id=10)
        db = _make_db_for_submit(ride=ride)

        with pytest.raises(DriverRatingError) as exc_info:
            await submit_driver_rating(db, ride_id=1, rider_user_id=999, rating=4)
        assert exc_info.value.status_code == 403
        assert "rider" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_rejects_non_completed_ride(self):
        ride = _make_ride(rider_id=10, status=RideStatus.IN_PROGRESS)
        db = _make_db_for_submit(ride=ride)

        with pytest.raises(DriverRatingError) as exc_info:
            await submit_driver_rating(db, ride_id=1, rider_user_id=10, rating=5)
        assert exc_info.value.status_code == 409
        assert "completed" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_rejects_duplicate_rating(self):
        ride = _make_ride(rider_id=10)
        existing = _make_feedback(rider_id=10)
        db = _make_db_for_submit(ride=ride, existing_feedback=existing)

        with pytest.raises(DriverRatingError) as exc_info:
            await submit_driver_rating(db, ride_id=1, rider_user_id=10, rating=3)
        assert exc_info.value.status_code == 409
        assert "already rated" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_rejects_cancelled_ride(self):
        ride = _make_ride(rider_id=10, status=RideStatus.CANCELLED)
        db = _make_db_for_submit(ride=ride)

        with pytest.raises(DriverRatingError) as exc_info:
            await submit_driver_rating(db, ride_id=1, rider_user_id=10, rating=4)
        assert exc_info.value.status_code == 409


# ---------------------------------------------------------------------------
# submit_driver_rating — success path
# ---------------------------------------------------------------------------


class TestSubmitDriverRatingSuccess:
    @pytest.mark.asyncio
    async def test_creates_feedback_record(self):
        ride = _make_ride(rider_id=10)
        db = _make_db_for_submit(ride=ride, existing_feedback=None)

        await submit_driver_rating(db, ride_id=1, rider_user_id=10, rating=5)

        db.add.assert_called_once()
        db.commit.assert_awaited_once()
        db.refresh.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_updates_ride_driver_rating(self):
        ride = _make_ride(rider_id=10)
        db = _make_db_for_submit(ride=ride, existing_feedback=None)

        await submit_driver_rating(db, ride_id=1, rider_user_id=10, rating=4)

        assert ride.driver_rating == 4

    @pytest.mark.asyncio
    async def test_rating_1_star_accepted(self):
        ride = _make_ride(rider_id=10)
        db = _make_db_for_submit(ride=ride, existing_feedback=None)
        await submit_driver_rating(db, ride_id=1, rider_user_id=10, rating=1)
        assert ride.driver_rating == 1

    @pytest.mark.asyncio
    async def test_rating_with_comment(self):
        ride = _make_ride(rider_id=10)
        db = _make_db_for_submit(ride=ride, existing_feedback=None)
        await submit_driver_rating(db, ride_id=1, rider_user_id=10, rating=3, comment="Okay ride")
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_feedback_role_is_rider(self):
        ride = _make_ride(rider_id=10)
        db = _make_db_for_submit(ride=ride, existing_feedback=None)
        await submit_driver_rating(db, ride_id=1, rider_user_id=10, rating=5)
        added = db.add.call_args[0][0]
        assert isinstance(added, RideFeedback)
        assert added.role == "rider"
        assert added.user_id == 10
        assert added.ride_id == 1
        assert added.rating == 5


# ---------------------------------------------------------------------------
# get_driver_rating_for_ride service
# ---------------------------------------------------------------------------


class TestGetDriverRatingForRide:
    @pytest.mark.asyncio
    async def test_returns_feedback_when_found(self):
        db = AsyncMock()
        expected = _make_feedback(rating=4)
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = expected
        db.execute = AsyncMock(return_value=result_mock)

        result = await get_driver_rating_for_ride(db, ride_id=1, rider_user_id=10)
        assert result is expected

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self):
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=result_mock)

        result = await get_driver_rating_for_ride(db, ride_id=1, rider_user_id=10)
        assert result is None


# ---------------------------------------------------------------------------
# POST /rides/{ride_id}/driver-rating — endpoint tests (real DB)
# ---------------------------------------------------------------------------


class TestSubmitDriverRatingEndpoint:
    @pytest.mark.asyncio
    async def test_rider_can_rate_completed_ride(self, client, rider, driver_user, rider_token, db):
        ride = Ride(**_ride_kwargs(rider.id, driver_user.id))
        db.add(ride)
        await db.flush()

        resp = await client.post(
            f"/api/v1/rides/{ride.id}/driver-rating",
            json={"rating": 5, "comment": "Excellent driver"},
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["rating"] == 5
        assert body["ride_id"] == ride.id
        assert body["rider_id"] == rider.id

    @pytest.mark.asyncio
    async def test_driver_cannot_submit_rating(self, client, driver_token, rider, driver_user, db):
        ride = Ride(**_ride_kwargs(rider.id, driver_user.id))
        db.add(ride)
        await db.flush()

        resp = await client.post(
            f"/api/v1/rides/{ride.id}/driver-rating",
            json={"rating": 4},
            headers={"Authorization": f"Bearer {driver_token}"},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_duplicate_rating_rejected(self, client, rider, driver_user, rider_token, db):
        ride = Ride(**_ride_kwargs(rider.id, driver_user.id))
        db.add(ride)
        await db.flush()

        resp1 = await client.post(
            f"/api/v1/rides/{ride.id}/driver-rating",
            json={"rating": 5},
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        assert resp1.status_code == 201

        resp2 = await client.post(
            f"/api/v1/rides/{ride.id}/driver-rating",
            json={"rating": 3},
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        assert resp2.status_code == 409

    @pytest.mark.asyncio
    async def test_non_completed_ride_rejected(self, client, rider, driver_user, rider_token, db):
        ride = Ride(**_ride_kwargs(rider.id, driver_user.id, status=RideStatus.IN_PROGRESS))
        db.add(ride)
        await db.flush()

        resp = await client.post(
            f"/api/v1/rides/{ride.id}/driver-rating",
            json={"rating": 4},
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_wrong_rider_rejected(self, client, driver_user, db):
        from app.models.user import User, UserRole
        from app.services.auth import create_access_token, hash_password

        other_rider = User(
            phone="+15559999999",
            name="Other Rider",
            email="other@test.com",
            password_hash=hash_password("testpass123"),
            role=UserRole.RIDER,
            is_active=True,
        )
        db.add(other_rider)
        await db.flush()

        original_rider_id = driver_user.id + 100  # a user that doesn't exist on this ride

        ride = Ride(**_ride_kwargs(original_rider_id, driver_user.id))
        db.add(ride)
        await db.flush()

        other_token = create_access_token(other_rider.id, other_rider.role.value)
        resp = await client.post(
            f"/api/v1/rides/{ride.id}/driver-rating",
            json={"rating": 4},
            headers={"Authorization": f"Bearer {other_token}"},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_invalid_rating_value_rejected(self, client, rider, driver_user, rider_token, db):
        ride = Ride(**_ride_kwargs(rider.id, driver_user.id))
        db.add(ride)
        await db.flush()

        resp = await client.post(
            f"/api/v1/rides/{ride.id}/driver-rating",
            json={"rating": 6},
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /rides/{ride_id}/driver-rating — endpoint tests (real DB)
# ---------------------------------------------------------------------------


class TestGetDriverRatingEndpoint:
    @pytest.mark.asyncio
    async def test_returns_submitted_rating(self, client, rider, driver_user, rider_token, db):
        ride = Ride(**_ride_kwargs(rider.id, driver_user.id))
        db.add(ride)
        await db.flush()

        # Submit first
        post_resp = await client.post(
            f"/api/v1/rides/{ride.id}/driver-rating",
            json={"rating": 4, "comment": "Good driver"},
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        assert post_resp.status_code == 201

        # Now GET it
        get_resp = await client.get(
            f"/api/v1/rides/{ride.id}/driver-rating",
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        assert get_resp.status_code == 200
        body = get_resp.json()
        assert body["rating"] == 4
        assert body["comment"] == "Good driver"
        assert body["ride_id"] == ride.id

    @pytest.mark.asyncio
    async def test_returns_404_when_not_rated(self, client, rider, driver_user, rider_token, db):
        ride = Ride(**_ride_kwargs(rider.id, driver_user.id))
        db.add(ride)
        await db.flush()

        resp = await client.get(
            f"/api/v1/rides/{ride.id}/driver-rating",
            headers={"Authorization": f"Bearer {rider_token}"},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_driver_cannot_get_rating(self, client, rider, driver_user, driver_token, db):
        ride = Ride(**_ride_kwargs(rider.id, driver_user.id))
        db.add(ride)
        await db.flush()

        resp = await client.get(
            f"/api/v1/rides/{ride.id}/driver-rating",
            headers={"Authorization": f"Bearer {driver_token}"},
        )
        assert resp.status_code == 403
