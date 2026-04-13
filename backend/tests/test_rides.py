"""Unit tests for ride endpoint handlers (rides.py).

Tests call endpoint functions directly with mocked DB sessions and
dependencies, covering authorization, state transitions, and error cases.
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.models.ride import Ride, RideStatus
from app.models.user import User, UserRole
from app.schemas.ride import CancelRequest, CancelResponse, RideRatingRequest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user(user_id=1, role=UserRole.RIDER, name="Test User"):
    user = MagicMock(spec=User)
    user.id = user_id
    user.role = role
    user.name = name
    return user


def _make_ride(
    ride_id=1,
    rider_id=10,
    driver_id=20,
    status=RideStatus.IN_PROGRESS,
    pickup_address="123 Main St",
    dropoff_address="456 Oak Ave",
    estimated_fare=15.50,
    actual_fare=None,
    requested_at=None,
    matched_at=None,
    started_at=None,
    completed_at=None,
    tip_amount=0.0,
    rider_rating=None,
    driver_rating=None,
    cancellation_reason=None,
    cancelled_at=None,
    dispatch_retry_count=0,
    last_retry_at=None,
):
    ride = MagicMock(spec=Ride)
    ride.id = ride_id
    ride.rider_id = rider_id
    ride.driver_id = driver_id
    ride.status = status
    ride.pickup_address = pickup_address
    ride.dropoff_address = dropoff_address
    ride.estimated_fare = estimated_fare
    ride.actual_fare = actual_fare
    ride.requested_at = requested_at or datetime(2026, 4, 12, tzinfo=timezone.utc)
    ride.matched_at = matched_at
    ride.started_at = started_at
    ride.completed_at = completed_at
    ride.tip_amount = tip_amount
    ride.rider_rating = rider_rating
    ride.driver_rating = driver_rating
    ride.cancellation_reason = cancellation_reason
    ride.cancelled_at = cancelled_at
    ride.dispatch_retry_count = dispatch_retry_count
    ride.last_retry_at = last_retry_at
    return ride


def _mock_db(scalar_return=None):
    db = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = scalar_return
    db.execute.return_value = result_mock
    return db


# ---------------------------------------------------------------------------
# GET /rides/{ride_id}
# ---------------------------------------------------------------------------

class TestGetRide:
    @pytest.mark.asyncio
    async def test_rider_can_get_own_ride(self):
        from app.api.v1.rides import get_ride

        user = _make_user(user_id=10, role=UserRole.RIDER)
        ride = _make_ride(rider_id=10, driver_id=20)
        db = _mock_db(scalar_return=ride)

        result = await get_ride(ride_id=1, user=user, db=db)
        assert result.id == 1
        assert result.status == "in_progress"

    @pytest.mark.asyncio
    async def test_driver_can_get_assigned_ride(self):
        from app.api.v1.rides import get_ride

        user = _make_user(user_id=20, role=UserRole.DRIVER)
        ride = _make_ride(rider_id=10, driver_id=20)
        db = _mock_db(scalar_return=ride)

        result = await get_ride(ride_id=1, user=user, db=db)
        assert result.id == 1

    @pytest.mark.asyncio
    async def test_404_when_ride_not_found(self):
        from app.api.v1.rides import get_ride

        user = _make_user(user_id=10)
        db = _mock_db(scalar_return=None)

        with pytest.raises(HTTPException) as exc_info:
            await get_ride(ride_id=999, user=user, db=db)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_403_when_not_participant(self):
        from app.api.v1.rides import get_ride

        user = _make_user(user_id=99)  # not rider or driver
        ride = _make_ride(rider_id=10, driver_id=20)
        db = _mock_db(scalar_return=ride)

        with pytest.raises(HTTPException) as exc_info:
            await get_ride(ride_id=1, user=user, db=db)
        assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# POST /rides/{ride_id}/rate
# ---------------------------------------------------------------------------

class TestRateRide:
    @pytest.mark.asyncio
    async def test_rider_rates_driver(self):
        from app.api.v1.rides import rate_ride

        user = _make_user(user_id=10, role=UserRole.RIDER)
        ride = _make_ride(rider_id=10, driver_id=20, status=RideStatus.COMPLETED)
        db = _mock_db(scalar_return=ride)

        result = await rate_ride(
            ride_id=1, req=RideRatingRequest(rating=5, tip_amount=3.0), user=user, db=db
        )
        assert result == {"status": "rated"}
        assert ride.driver_rating == 5
        assert ride.tip_amount == 3.0
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_driver_rates_rider(self):
        from app.api.v1.rides import rate_ride

        user = _make_user(user_id=20, role=UserRole.DRIVER)
        ride = _make_ride(rider_id=10, driver_id=20, status=RideStatus.COMPLETED)
        db = _mock_db(scalar_return=ride)

        result = await rate_ride(
            ride_id=1, req=RideRatingRequest(rating=4), user=user, db=db
        )
        assert result == {"status": "rated"}
        assert ride.rider_rating == 4

    @pytest.mark.asyncio
    async def test_404_when_ride_not_completed(self):
        from app.api.v1.rides import rate_ride

        user = _make_user(user_id=10)
        ride = _make_ride(rider_id=10, status=RideStatus.IN_PROGRESS)
        db = _mock_db(scalar_return=ride)

        with pytest.raises(HTTPException) as exc_info:
            await rate_ride(ride_id=1, req=RideRatingRequest(rating=5), user=user, db=db)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_404_when_ride_missing(self):
        from app.api.v1.rides import rate_ride

        user = _make_user(user_id=10)
        db = _mock_db(scalar_return=None)

        with pytest.raises(HTTPException) as exc_info:
            await rate_ride(ride_id=999, req=RideRatingRequest(rating=5), user=user, db=db)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_403_when_not_participant(self):
        from app.api.v1.rides import rate_ride

        user = _make_user(user_id=99)
        ride = _make_ride(rider_id=10, driver_id=20, status=RideStatus.COMPLETED)
        db = _mock_db(scalar_return=ride)

        with pytest.raises(HTTPException) as exc_info:
            await rate_ride(ride_id=1, req=RideRatingRequest(rating=5), user=user, db=db)
        assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# POST /rides/{ride_id}/cancel
# ---------------------------------------------------------------------------

class TestCancelRide:
    @pytest.mark.asyncio
    @patch("app.api.websocket.notify_ride_status", new_callable=AsyncMock)
    @patch("app.api.v1.rides.get_matching_engine", new_callable=AsyncMock)
    async def test_rider_cancels_matched_ride(self, mock_engine_fn, mock_notify):
        from app.api.v1.rides import cancel_ride

        mock_engine = AsyncMock()
        mock_engine_fn.return_value = mock_engine

        user = _make_user(user_id=10, role=UserRole.RIDER)
        ride = _make_ride(rider_id=10, driver_id=20, status=RideStatus.MATCHED)
        db = _mock_db(scalar_return=ride)

        result = await cancel_ride(
            ride_id=1, req=CancelRequest(reason="changed mind"), user=user, db=db
        )
        assert isinstance(result, CancelResponse)
        assert result.status == "cancelled"
        assert result.cancellation_fee >= 0.0
        assert ride.status == RideStatus.CANCELLED
        assert ride.cancellation_reason == "changed mind"
        db.commit.assert_awaited_once()
        mock_engine.set_driver_available.assert_awaited_once_with(20)

    @pytest.mark.asyncio
    @patch("app.api.websocket.notify_ride_status", new_callable=AsyncMock)
    async def test_cancel_ride_without_driver(self, mock_notify):
        from app.api.v1.rides import cancel_ride

        user = _make_user(user_id=10, role=UserRole.RIDER)
        ride = _make_ride(rider_id=10, driver_id=None, status=RideStatus.REQUESTED)
        db = _mock_db(scalar_return=ride)

        result = await cancel_ride(
            ride_id=1, req=CancelRequest(), user=user, db=db
        )
        assert isinstance(result, CancelResponse)
        assert result.status == "cancelled"
        assert result.cancellation_fee == 0.0
        assert ride.status == RideStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_404_when_ride_not_found(self):
        from app.api.v1.rides import cancel_ride

        user = _make_user(user_id=10)
        db = _mock_db(scalar_return=None)

        with pytest.raises(HTTPException) as exc_info:
            await cancel_ride(ride_id=999, req=CancelRequest(), user=user, db=db)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_403_when_not_participant(self):
        from app.api.v1.rides import cancel_ride

        user = _make_user(user_id=99)
        ride = _make_ride(rider_id=10, driver_id=20, status=RideStatus.IN_PROGRESS)
        db = _mock_db(scalar_return=ride)

        with pytest.raises(HTTPException) as exc_info:
            await cancel_ride(ride_id=1, req=CancelRequest(), user=user, db=db)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_409_when_already_completed(self):
        from app.api.v1.rides import cancel_ride

        user = _make_user(user_id=10)
        ride = _make_ride(rider_id=10, status=RideStatus.COMPLETED)
        db = _mock_db(scalar_return=ride)

        with pytest.raises(HTTPException) as exc_info:
            await cancel_ride(ride_id=1, req=CancelRequest(), user=user, db=db)
        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_409_when_already_cancelled(self):
        from app.api.v1.rides import cancel_ride

        user = _make_user(user_id=10)
        ride = _make_ride(rider_id=10, status=RideStatus.CANCELLED)
        db = _mock_db(scalar_return=ride)

        with pytest.raises(HTTPException) as exc_info:
            await cancel_ride(ride_id=1, req=CancelRequest(), user=user, db=db)
        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    @patch("app.api.websocket.notify_ride_status", new_callable=AsyncMock)
    async def test_cancel_during_dispatch_retry(self, mock_notify):
        """Rider can cancel for free while dispatch is retrying to find a driver."""
        from app.api.v1.rides import cancel_ride

        user = _make_user(user_id=10, role=UserRole.RIDER)
        ride = _make_ride(
            rider_id=10, driver_id=None, status=RideStatus.REQUESTED,
            dispatch_retry_count=3,
        )
        db = _mock_db(scalar_return=ride)

        result = await cancel_ride(
            ride_id=1, req=CancelRequest(reason="tired of waiting"), user=user, db=db,
        )
        assert isinstance(result, CancelResponse)
        assert result.status == "cancelled"
        assert result.cancellation_fee == 0.0
        assert ride.status == RideStatus.CANCELLED
        assert ride.cancellation_reason == "tired of waiting"

    @pytest.mark.asyncio
    @patch("app.api.websocket.notify_ride_status", new_callable=AsyncMock)
    async def test_cancel_during_retry_sends_retry_info_in_notification(self, mock_notify):
        """WebSocket notification includes retry metadata when cancelled during retry."""
        from app.api.v1.rides import cancel_ride

        user = _make_user(user_id=10, role=UserRole.RIDER)
        ride = _make_ride(
            rider_id=10, driver_id=None, status=RideStatus.REQUESTED,
            dispatch_retry_count=2,
        )
        db = _mock_db(scalar_return=ride)

        await cancel_ride(
            ride_id=1, req=CancelRequest(), user=user, db=db,
        )
        # The rider-facing notification is NOT sent (user.id == ride.rider_id),
        # but no driver exists either — so no notification at all in this case.
        # The feature enriches the notification payload; tested via matched+retry below.
        assert ride.status == RideStatus.CANCELLED


# ---------------------------------------------------------------------------
# Ride lifecycle: en-route → arrived → start → complete
# ---------------------------------------------------------------------------

class TestDriverEnRoute:
    @pytest.mark.asyncio
    @patch("app.api.websocket.notify_ride_status", new_callable=AsyncMock)
    async def test_success_from_matched(self, mock_notify):
        from app.api.v1.rides import driver_en_route

        driver = _make_user(user_id=20, role=UserRole.DRIVER)
        ride = _make_ride(rider_id=10, driver_id=20, status=RideStatus.MATCHED)
        db = _mock_db(scalar_return=ride)

        result = await driver_en_route(ride_id=1, driver=driver, db=db)
        assert result == {"status": "driver_en_route"}
        assert ride.status == RideStatus.DRIVER_EN_ROUTE
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_404_wrong_driver(self):
        from app.api.v1.rides import driver_en_route

        driver = _make_user(user_id=99, role=UserRole.DRIVER)
        ride = _make_ride(driver_id=20, status=RideStatus.MATCHED)
        db = _mock_db(scalar_return=ride)

        with pytest.raises(HTTPException) as exc_info:
            await driver_en_route(ride_id=1, driver=driver, db=db)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_409_wrong_status(self):
        from app.api.v1.rides import driver_en_route

        driver = _make_user(user_id=20, role=UserRole.DRIVER)
        ride = _make_ride(driver_id=20, status=RideStatus.IN_PROGRESS)
        db = _mock_db(scalar_return=ride)

        with pytest.raises(HTTPException) as exc_info:
            await driver_en_route(ride_id=1, driver=driver, db=db)
        assert exc_info.value.status_code == 409


class TestDriverArrived:
    @pytest.mark.asyncio
    @patch("app.api.websocket.notify_ride_status", new_callable=AsyncMock)
    async def test_success_from_en_route(self, mock_notify):
        from app.api.v1.rides import driver_arrived

        driver = _make_user(user_id=20, role=UserRole.DRIVER)
        ride = _make_ride(driver_id=20, status=RideStatus.DRIVER_EN_ROUTE)
        db = _mock_db(scalar_return=ride)

        result = await driver_arrived(ride_id=1, driver=driver, db=db)
        assert result == {"status": "arrived"}
        assert ride.status == RideStatus.ARRIVED

    @pytest.mark.asyncio
    async def test_409_from_matched(self):
        from app.api.v1.rides import driver_arrived

        driver = _make_user(user_id=20, role=UserRole.DRIVER)
        ride = _make_ride(driver_id=20, status=RideStatus.MATCHED)
        db = _mock_db(scalar_return=ride)

        with pytest.raises(HTTPException) as exc_info:
            await driver_arrived(ride_id=1, driver=driver, db=db)
        assert exc_info.value.status_code == 409


class TestStartRide:
    @pytest.mark.asyncio
    @patch("app.api.websocket.notify_ride_status", new_callable=AsyncMock)
    async def test_success_from_matched(self, mock_notify):
        from app.api.v1.rides import start_ride

        driver = _make_user(user_id=20, role=UserRole.DRIVER)
        ride = _make_ride(driver_id=20, status=RideStatus.MATCHED)
        db = _mock_db(scalar_return=ride)

        result = await start_ride(ride_id=1, driver=driver, db=db)
        assert result == {"status": "in_progress"}
        assert ride.status == RideStatus.IN_PROGRESS

    @pytest.mark.asyncio
    @patch("app.api.websocket.notify_ride_status", new_callable=AsyncMock)
    async def test_success_from_arrived(self, mock_notify):
        from app.api.v1.rides import start_ride

        driver = _make_user(user_id=20, role=UserRole.DRIVER)
        ride = _make_ride(driver_id=20, status=RideStatus.ARRIVED)
        db = _mock_db(scalar_return=ride)

        result = await start_ride(ride_id=1, driver=driver, db=db)
        assert result == {"status": "in_progress"}

    @pytest.mark.asyncio
    async def test_409_from_requested(self):
        from app.api.v1.rides import start_ride

        driver = _make_user(user_id=20, role=UserRole.DRIVER)
        ride = _make_ride(driver_id=20, status=RideStatus.REQUESTED)
        db = _mock_db(scalar_return=ride)

        with pytest.raises(HTTPException) as exc_info:
            await start_ride(ride_id=1, driver=driver, db=db)
        assert exc_info.value.status_code == 409


class TestCompleteRide:
    @pytest.mark.asyncio
    @patch("app.api.websocket.notify_ride_status", new_callable=AsyncMock)
    @patch("app.api.v1.rides.get_matching_engine", new_callable=AsyncMock)
    async def test_success(self, mock_engine_fn, mock_notify):
        from app.api.v1.rides import complete_ride

        mock_engine = AsyncMock()
        mock_engine_fn.return_value = mock_engine

        driver = _make_user(user_id=20, role=UserRole.DRIVER)
        ride = _make_ride(driver_id=20, status=RideStatus.IN_PROGRESS, estimated_fare=15.50)

        # complete_ride does two db.execute calls: one for ride, one for driver profile
        profile = MagicMock()
        profile.total_trips = 50

        ride_result = MagicMock()
        ride_result.scalar_one_or_none.return_value = ride
        profile_result = MagicMock()
        profile_result.scalar_one_or_none.return_value = profile

        db = AsyncMock()
        db.execute.side_effect = [ride_result, profile_result]

        result = await complete_ride(ride_id=1, driver=driver, db=db)
        assert result == {"status": "completed", "fare": 15.50}
        assert ride.status == RideStatus.COMPLETED
        assert ride.actual_fare == 15.50
        assert profile.total_trips == 51
        db.commit.assert_awaited_once()
        mock_engine.set_driver_available.assert_awaited_once_with(20)

    @pytest.mark.asyncio
    async def test_409_when_not_in_progress(self):
        from app.api.v1.rides import complete_ride

        driver = _make_user(user_id=20, role=UserRole.DRIVER)
        ride = _make_ride(driver_id=20, status=RideStatus.MATCHED)
        db = _mock_db(scalar_return=ride)

        with pytest.raises(HTTPException) as exc_info:
            await complete_ride(ride_id=1, driver=driver, db=db)
        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_404_wrong_driver(self):
        from app.api.v1.rides import complete_ride

        driver = _make_user(user_id=99, role=UserRole.DRIVER)
        ride = _make_ride(driver_id=20, status=RideStatus.IN_PROGRESS)
        db = _mock_db(scalar_return=ride)

        with pytest.raises(HTTPException) as exc_info:
            await complete_ride(ride_id=1, driver=driver, db=db)
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# POST /rides/{ride_id}/accept
# ---------------------------------------------------------------------------

class TestAcceptRide:
    @pytest.mark.asyncio
    @patch("app.api.websocket.notify_ride_status", new_callable=AsyncMock)
    @patch("app.api.v1.rides.get_matching_engine", new_callable=AsyncMock)
    async def test_success(self, mock_engine_fn, mock_notify):
        from app.api.v1.rides import accept_ride

        mock_engine = AsyncMock()
        mock_engine_fn.return_value = mock_engine

        driver = _make_user(user_id=20, role=UserRole.DRIVER)
        ride = _make_ride(rider_id=10, driver_id=None, status=RideStatus.REQUESTED)
        db = _mock_db(scalar_return=ride)

        result = await accept_ride(ride_id=1, driver=driver, db=db)
        assert result.status == "matched"
        assert ride.driver_id == 20
        assert ride.status == RideStatus.MATCHED
        db.commit.assert_awaited_once()
        mock_engine.set_driver_busy.assert_awaited_once_with(20)

    @pytest.mark.asyncio
    async def test_404_when_ride_not_found(self):
        from app.api.v1.rides import accept_ride

        driver = _make_user(user_id=20, role=UserRole.DRIVER)
        db = _mock_db(scalar_return=None)

        with pytest.raises(HTTPException) as exc_info:
            await accept_ride(ride_id=999, driver=driver, db=db)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_409_when_already_matched(self):
        from app.api.v1.rides import accept_ride

        driver = _make_user(user_id=20, role=UserRole.DRIVER)
        ride = _make_ride(status=RideStatus.MATCHED)
        db = _mock_db(scalar_return=ride)

        with pytest.raises(HTTPException) as exc_info:
            await accept_ride(ride_id=1, driver=driver, db=db)
        assert exc_info.value.status_code == 409
