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


# ---------------------------------------------------------------------------
# PATCH /rides/scheduled/{ride_id}
# ---------------------------------------------------------------------------

class TestUpdateScheduledRide:
    """Tests for PATCH /rides/scheduled/{ride_id}."""

    def _mock_db_for_patch(self, ride, coord_rows=None):
        """DB mock that returns `ride` on scalar_one_or_none and coord_rows on .one()."""
        db = AsyncMock()

        ride_result = MagicMock()
        ride_result.scalar_one_or_none.return_value = ride
        # overlap query: no existing scheduled times
        ride_result.all.return_value = []

        if coord_rows is not None:
            coord_result = MagicMock()
            coord_result.one.return_value = coord_rows
            db.execute.side_effect = [ride_result, ride_result, coord_result]
        else:
            db.execute.return_value = ride_result

        async def fake_refresh(obj):
            pass

        db.refresh = fake_refresh
        return db

    @pytest.mark.asyncio
    async def test_update_scheduled_time_success(self):
        from app.api.v1.rides import update_scheduled_ride
        from app.schemas.ride import ScheduleRideUpdate

        user = _make_user(user_id=10)
        new_time = datetime.now(timezone.utc) + timedelta(hours=3)
        ride = _make_scheduled_ride(ride_id=1, rider_id=10)
        db = self._mock_db_for_patch(ride)

        req = ScheduleRideUpdate(scheduled_for=new_time)

        with patch("app.api.v1.rides.validate_schedule_time") as mock_val, \
             patch("app.api.v1.rides.check_overlap") as mock_overlap:
            mock_val.return_value = MagicMock(valid=True, reason="OK")
            mock_overlap.return_value = MagicMock(valid=True, reason="OK")

            result = await update_scheduled_ride(ride_id=1, req=req, user=user, db=db)

        assert ride.scheduled_for == new_time
        assert result.status == "scheduled"

    @pytest.mark.asyncio
    async def test_update_not_found(self):
        from app.api.v1.rides import update_scheduled_ride
        from app.schemas.ride import ScheduleRideUpdate

        user = _make_user(user_id=10)
        db = _mock_db(scalar_return=None)
        req = ScheduleRideUpdate(scheduled_for=datetime.now(timezone.utc) + timedelta(hours=3))

        with pytest.raises(HTTPException) as exc_info:
            await update_scheduled_ride(ride_id=999, req=req, user=user, db=db)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_update_not_authorized(self):
        from app.api.v1.rides import update_scheduled_ride
        from app.schemas.ride import ScheduleRideUpdate

        user = _make_user(user_id=99)
        ride = _make_scheduled_ride(ride_id=1, rider_id=10)
        db = _mock_db(scalar_return=ride)
        req = ScheduleRideUpdate(scheduled_for=datetime.now(timezone.utc) + timedelta(hours=3))

        with pytest.raises(HTTPException) as exc_info:
            await update_scheduled_ride(ride_id=1, req=req, user=user, db=db)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_update_wrong_status(self):
        from app.api.v1.rides import update_scheduled_ride
        from app.schemas.ride import ScheduleRideUpdate

        user = _make_user(user_id=10)
        ride = _make_scheduled_ride(ride_id=1, rider_id=10)
        ride.status = RideStatus.REQUESTED
        db = _mock_db(scalar_return=ride)
        req = ScheduleRideUpdate(scheduled_for=datetime.now(timezone.utc) + timedelta(hours=3))

        with pytest.raises(HTTPException) as exc_info:
            await update_scheduled_ride(ride_id=1, req=req, user=user, db=db)
        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_update_time_too_soon(self):
        from app.api.v1.rides import update_scheduled_ride
        from app.schemas.ride import ScheduleRideUpdate

        user = _make_user(user_id=10)
        ride = _make_scheduled_ride(ride_id=1, rider_id=10)
        db = self._mock_db_for_patch(ride)
        req = ScheduleRideUpdate(scheduled_for=datetime.now(timezone.utc) + timedelta(minutes=5))

        with patch("app.api.v1.rides.validate_schedule_time") as mock_val:
            mock_val.return_value = MagicMock(
                valid=False, reason="Must schedule at least 30 minutes in advance"
            )
            with pytest.raises(HTTPException) as exc_info:
                await update_scheduled_ride(ride_id=1, req=req, user=user, db=db)
        assert exc_info.value.status_code == 422

    @pytest.mark.asyncio
    async def test_update_time_overlap(self):
        from app.api.v1.rides import update_scheduled_ride
        from app.schemas.ride import ScheduleRideUpdate

        user = _make_user(user_id=10)
        ride = _make_scheduled_ride(ride_id=1, rider_id=10)
        db = self._mock_db_for_patch(ride)
        req = ScheduleRideUpdate(scheduled_for=datetime.now(timezone.utc) + timedelta(hours=2))

        with patch("app.api.v1.rides.validate_schedule_time") as mock_val, \
             patch("app.api.v1.rides.check_overlap") as mock_overlap:
            mock_val.return_value = MagicMock(valid=True, reason="OK")
            mock_overlap.return_value = MagicMock(
                valid=False, reason="You already have a ride scheduled within 30 minutes"
            )
            with pytest.raises(HTTPException) as exc_info:
                await update_scheduled_ride(ride_id=1, req=req, user=user, db=db)
        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_update_pickup_address_recalculates_fare(self):
        from app.api.v1.rides import update_scheduled_ride
        from app.schemas.ride import LocationPoint, ScheduleRideUpdate

        user = _make_user(user_id=10)
        ride = _make_scheduled_ride(ride_id=1, rider_id=10, estimated_fare=18.50)

        coord_mock = MagicMock()
        coord_mock.plat = 40.7128
        coord_mock.plng = -74.0060
        coord_mock.dlat = 40.7580
        coord_mock.dlng = -73.9855

        db = self._mock_db_for_patch(ride, coord_rows=coord_mock)

        req = ScheduleRideUpdate(
            pickup=LocationPoint(lat=40.7200, lng=-74.0100),
            pickup_address="789 New St",
        )

        with patch("app.api.v1.rides.get_route", new_callable=AsyncMock) as mock_route, \
             patch("app.api.v1.rides.calculate_fare", return_value=22.00), \
             patch("app.api.v1.rides.ST_MakePoint") as mock_point:
            mock_route.return_value = {"distance_km": 10.0, "duration_min": 20.0}
            mock_point.return_value = MagicMock()

            result = await update_scheduled_ride(ride_id=1, req=req, user=user, db=db)

        assert ride.estimated_fare == 22.00
        assert ride.pickup_address == "789 New St"

    @pytest.mark.asyncio
    async def test_update_no_fields_is_noop(self):
        from app.api.v1.rides import update_scheduled_ride
        from app.schemas.ride import ScheduleRideUpdate

        user = _make_user(user_id=10)
        ride = _make_scheduled_ride(ride_id=1, rider_id=10, estimated_fare=18.50)
        original_fare = ride.estimated_fare
        original_time = ride.scheduled_for
        db = self._mock_db_for_patch(ride)

        req = ScheduleRideUpdate()

        result = await update_scheduled_ride(ride_id=1, req=req, user=user, db=db)
        assert ride.estimated_fare == original_fare
        assert ride.scheduled_for == original_time
        assert result.status == "scheduled"


# ---------------------------------------------------------------------------
# GET /admin/rides/scheduled
# ---------------------------------------------------------------------------

class TestAdminListScheduledRides:
    """Tests for GET /admin/rides/scheduled."""

    @pytest.mark.asyncio
    async def test_returns_upcoming_by_default(self):
        from app.api.v1.admin import list_scheduled_rides_admin

        ride1 = _make_scheduled_ride(ride_id=1, rider_id=10)
        ride1.driver_id = None
        ride1.tip_amount = 0.0
        ride1.distance_km = 8.5
        ride1.duration_min = 15.0
        ride1.actual_fare = None
        ride1.rider_rating = None
        ride1.driver_rating = None
        ride1.cancellation_reason = None
        ride1.matched_at = None
        ride1.started_at = None
        ride1.completed_at = None
        ride1.cancelled_at = None
        ride1.scheduled_for = datetime.now(timezone.utc) + timedelta(hours=2)
        ride1.rider = MagicMock()
        ride1.rider.name = "Test Rider"
        ride1.driver = None

        db = AsyncMock()
        count_result = MagicMock()
        count_result.scalar.return_value = 1
        rides_result = MagicMock()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = [ride1]
        rides_result.scalars.return_value = scalars_mock
        db.execute.side_effect = [count_result, rides_result]

        result = await list_scheduled_rides_admin(
            rider_id=None, from_date=None, to_date=None,
            include_past=False, page=1, per_page=50, db=db,
        )
        assert result.total == 1
        assert len(result.rides) == 1
        assert result.rides[0].status == "scheduled"

    @pytest.mark.asyncio
    async def test_empty_result(self):
        from app.api.v1.admin import list_scheduled_rides_admin

        db = AsyncMock()
        count_result = MagicMock()
        count_result.scalar.return_value = 0
        rides_result = MagicMock()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = []
        rides_result.scalars.return_value = scalars_mock
        db.execute.side_effect = [count_result, rides_result]

        result = await list_scheduled_rides_admin(
            rider_id=None, from_date=None, to_date=None,
            include_past=False, page=1, per_page=50, db=db,
        )
        assert result.total == 0
        assert result.rides == []

    @pytest.mark.asyncio
    async def test_pagination_fields_returned(self):
        from app.api.v1.admin import list_scheduled_rides_admin

        db = AsyncMock()
        count_result = MagicMock()
        count_result.scalar.return_value = 0
        rides_result = MagicMock()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = []
        rides_result.scalars.return_value = scalars_mock
        db.execute.side_effect = [count_result, rides_result]

        result = await list_scheduled_rides_admin(
            rider_id=None, from_date=None, to_date=None,
            include_past=False, page=2, per_page=25, db=db,
        )
        assert result.page == 2
        assert result.per_page == 25
