"""Unit tests for scheduled ride API endpoints."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.models.ride import Ride, RideStatus
from app.models.user import User, UserRole
from app.schemas.ride import ScheduleRideRequest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user(user_id=1, role=UserRole.RIDER, name="Test Rider"):
    user = MagicMock(spec=User)
    user.id = user_id
    user.role = role
    user.name = name
    return user


def _make_scheduled_ride(
    ride_id=1,
    rider_id=10,
    status=RideStatus.SCHEDULED,
    pickup_address="123 Main St",
    dropoff_address="456 Oak Ave",
    estimated_fare=18.50,
    scheduled_for=None,
    requested_at=None,
):
    ride = MagicMock(spec=Ride)
    ride.id = ride_id
    ride.rider_id = rider_id
    ride.driver_id = None
    ride.status = status
    ride.pickup_address = pickup_address
    ride.dropoff_address = dropoff_address
    ride.estimated_fare = estimated_fare
    ride.actual_fare = None
    ride.scheduled_for = scheduled_for or (datetime.now(timezone.utc) + timedelta(hours=2))
    ride.requested_at = requested_at or datetime(2026, 4, 12, tzinfo=timezone.utc)
    ride.matched_at = None
    ride.started_at = None
    ride.completed_at = None
    ride.cancelled_at = None
    ride.cancellation_reason = None
    ride.distance_km = 8.5
    ride.duration_min = 15.0
    return ride


def _mock_db(scalar_return=None, scalars_return=None):
    db = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = scalar_return
    if scalars_return is not None:
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = scalars_return
        result_mock.scalars.return_value = scalars_mock
    # For select queries that return rows (e.g., existing scheduled times)
    result_mock.all.return_value = []
    db.execute.return_value = result_mock
    return db


# ---------------------------------------------------------------------------
# POST /rides/schedule
# ---------------------------------------------------------------------------

class TestScheduleRide:
    @pytest.mark.asyncio
    async def test_schedule_ride_success(self):
        from app.api.v1.rides import schedule_ride

        user = _make_user(user_id=10)
        db = _mock_db()
        scheduled_time = datetime.now(timezone.utc) + timedelta(hours=2)

        req = ScheduleRideRequest(
            pickup={"lat": 40.7128, "lng": -74.0060},
            dropoff={"lat": 40.7580, "lng": -73.9855},
            pickup_address="123 Main St",
            dropoff_address="456 Oak Ave",
            scheduled_for=scheduled_time,
        )

        with patch("app.api.v1.rides.get_route", new_callable=AsyncMock) as mock_route, \
             patch("app.api.v1.rides.calculate_fare", return_value=18.50), \
             patch("app.api.v1.rides.validate_schedule_time") as mock_validate, \
             patch("app.api.v1.rides.check_overlap") as mock_overlap:

            mock_route.return_value = {"distance_km": 8.5, "duration_min": 15.0}
            mock_validate.return_value = MagicMock(valid=True, reason="OK")
            mock_overlap.return_value = MagicMock(valid=True, reason="OK")

            # Mock db.refresh to populate ride fields
            async def fake_refresh(ride):
                ride.id = 1
                ride.status = RideStatus.SCHEDULED
                ride.pickup_address = "123 Main St"
                ride.dropoff_address = "456 Oak Ave"
                ride.estimated_fare = 18.50
                ride.scheduled_for = scheduled_time
                ride.requested_at = datetime(2026, 4, 12, tzinfo=timezone.utc)

            db.refresh = fake_refresh

            result = await schedule_ride(req=req, user=user, db=db)
            assert result.status == "scheduled"
            assert result.estimated_fare == 18.50
            assert result.scheduled_for == scheduled_time

    @pytest.mark.asyncio
    async def test_schedule_ride_too_soon_rejected(self):
        from app.api.v1.rides import schedule_ride

        user = _make_user(user_id=10)
        db = _mock_db()
        scheduled_time = datetime.now(timezone.utc) + timedelta(minutes=10)

        req = ScheduleRideRequest(
            pickup={"lat": 40.7128, "lng": -74.0060},
            dropoff={"lat": 40.7580, "lng": -73.9855},
            pickup_address="123 Main St",
            dropoff_address="456 Oak Ave",
            scheduled_for=scheduled_time,
        )

        with patch("app.api.v1.rides.validate_schedule_time") as mock_validate:
            mock_validate.return_value = MagicMock(
                valid=False, reason="Must schedule at least 30 minutes in advance",
            )

            with pytest.raises(HTTPException) as exc_info:
                await schedule_ride(req=req, user=user, db=db)
            assert exc_info.value.status_code == 422
            assert "30 minutes" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_schedule_ride_overlap_rejected(self):
        from app.api.v1.rides import schedule_ride

        user = _make_user(user_id=10)
        db = _mock_db()
        scheduled_time = datetime.now(timezone.utc) + timedelta(hours=2)

        req = ScheduleRideRequest(
            pickup={"lat": 40.7128, "lng": -74.0060},
            dropoff={"lat": 40.7580, "lng": -73.9855},
            pickup_address="123 Main St",
            dropoff_address="456 Oak Ave",
            scheduled_for=scheduled_time,
        )

        with patch("app.api.v1.rides.validate_schedule_time") as mock_validate, \
             patch("app.api.v1.rides.check_overlap") as mock_overlap:
            mock_validate.return_value = MagicMock(valid=True, reason="OK")
            mock_overlap.return_value = MagicMock(
                valid=False, reason="You already have a ride scheduled within 30 minutes of this time",
            )

            with pytest.raises(HTTPException) as exc_info:
                await schedule_ride(req=req, user=user, db=db)
            assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_schedule_ride_routing_error(self):
        from app.api.v1.rides import schedule_ride
        from app.services.routing import RoutingError

        user = _make_user(user_id=10)
        db = _mock_db()
        scheduled_time = datetime.now(timezone.utc) + timedelta(hours=2)

        req = ScheduleRideRequest(
            pickup={"lat": 40.7128, "lng": -74.0060},
            dropoff={"lat": 40.7580, "lng": -73.9855},
            pickup_address="123 Main St",
            dropoff_address="456 Oak Ave",
            scheduled_for=scheduled_time,
        )

        with patch("app.api.v1.rides.get_route", new_callable=AsyncMock) as mock_route, \
             patch("app.api.v1.rides.validate_schedule_time") as mock_validate, \
             patch("app.api.v1.rides.check_overlap") as mock_overlap:

            mock_validate.return_value = MagicMock(valid=True, reason="OK")
            mock_overlap.return_value = MagicMock(valid=True, reason="OK")
            mock_route.side_effect = RoutingError("No route found")

            with pytest.raises(HTTPException) as exc_info:
                await schedule_ride(req=req, user=user, db=db)
            assert exc_info.value.status_code == 422


# ---------------------------------------------------------------------------
# GET /rides/scheduled
# ---------------------------------------------------------------------------

class TestListScheduledRides:
    @pytest.mark.asyncio
    async def test_list_scheduled_rides_returns_upcoming(self):
        from app.api.v1.rides import list_scheduled_rides

        user = _make_user(user_id=10)
        ride1 = _make_scheduled_ride(ride_id=1, rider_id=10)
        ride2 = _make_scheduled_ride(ride_id=2, rider_id=10)

        db = AsyncMock()
        result_mock = MagicMock()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = [ride1, ride2]
        result_mock.scalars.return_value = scalars_mock
        db.execute.return_value = result_mock

        results = await list_scheduled_rides(user=user, db=db)
        assert len(results) == 2
        assert results[0].status == "scheduled"
        assert results[1].status == "scheduled"

    @pytest.mark.asyncio
    async def test_list_scheduled_rides_empty(self):
        from app.api.v1.rides import list_scheduled_rides

        user = _make_user(user_id=10)
        db = AsyncMock()
        result_mock = MagicMock()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = []
        result_mock.scalars.return_value = scalars_mock
        db.execute.return_value = result_mock

        results = await list_scheduled_rides(user=user, db=db)
        assert len(results) == 0


# ---------------------------------------------------------------------------
# DELETE /rides/scheduled/{ride_id}
# ---------------------------------------------------------------------------

class TestCancelScheduledRide:
    @pytest.mark.asyncio
    async def test_cancel_scheduled_ride_success(self):
        from app.api.v1.rides import cancel_scheduled_ride

        user = _make_user(user_id=10)
        ride = _make_scheduled_ride(ride_id=1, rider_id=10)
        db = _mock_db(scalar_return=ride)

        result = await cancel_scheduled_ride(ride_id=1, user=user, db=db)
        assert result["status"] == "cancelled"
        assert result["cancellation_fee"] == 0.0
        assert ride.status == RideStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_cancel_scheduled_ride_not_found(self):
        from app.api.v1.rides import cancel_scheduled_ride

        user = _make_user(user_id=10)
        db = _mock_db(scalar_return=None)

        with pytest.raises(HTTPException) as exc_info:
            await cancel_scheduled_ride(ride_id=999, user=user, db=db)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_cancel_scheduled_ride_not_authorized(self):
        from app.api.v1.rides import cancel_scheduled_ride

        user = _make_user(user_id=99)  # different user
        ride = _make_scheduled_ride(ride_id=1, rider_id=10)
        db = _mock_db(scalar_return=ride)

        with pytest.raises(HTTPException) as exc_info:
            await cancel_scheduled_ride(ride_id=1, user=user, db=db)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_cancel_non_scheduled_ride_rejected(self):
        from app.api.v1.rides import cancel_scheduled_ride

        user = _make_user(user_id=10)
        ride = _make_scheduled_ride(ride_id=1, rider_id=10)
        ride.status = RideStatus.REQUESTED  # not scheduled
        db = _mock_db(scalar_return=ride)

        with pytest.raises(HTTPException) as exc_info:
            await cancel_scheduled_ride(ride_id=1, user=user, db=db)
        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_cancel_sets_timestamp_and_reason(self):
        from app.api.v1.rides import cancel_scheduled_ride

        user = _make_user(user_id=10)
        ride = _make_scheduled_ride(ride_id=1, rider_id=10)
        db = _mock_db(scalar_return=ride)

        await cancel_scheduled_ride(ride_id=1, user=user, db=db)
        assert ride.cancelled_at is not None
        assert ride.cancellation_reason == "Cancelled by rider before dispatch"
