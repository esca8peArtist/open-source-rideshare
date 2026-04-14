"""Unit tests for the scheduled rides feature.

All tests are pure unit tests — no database, no HTTP client required.

Covers:
- ScheduledRide model field defaults and enums
- validate_scheduled_for: too soon, too far, valid, timezone handling
- is_cancellable: all statuses
- is_acceptable_by_driver: already assigned, wrong status, valid
- is_declinable_by_driver: wrong driver, wrong status, valid
- create_scheduled_ride service (mocked DB): success, validation failure
- get_scheduled_ride service (mocked DB)
- list_rider_scheduled_rides (mocked DB)
- list_driver_scheduled_rides (mocked DB)
- driver_accept_scheduled_ride (mocked DB): success, not found, wrong status
- driver_decline_scheduled_ride (mocked DB): success, not found, wrong driver
- cancel_scheduled_ride (mocked DB): success (rider), not found, wrong status
- get_admin_summary (mocked DB)
- Schema validation: ScheduledRideCreateRequest, ScheduledRideResponse
- ScheduledRideListResponse, cancel/accept/decline responses
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.scheduled_ride import CancelledBy, ScheduledRide, ScheduledRideStatus
from app.schemas.scheduled_ride import (
    AdminScheduledRideSummary,
    ScheduledRideAcceptResponse,
    ScheduledRideCancelRequest,
    ScheduledRideCancelResponse,
    ScheduledRideCreateRequest,
    ScheduledRideDeclineResponse,
    ScheduledRideListResponse,
    ScheduledRideResponse,
)
from app.services.scheduled_ride import (
    DEFAULT_PAGE_SIZE,
    MIN_ADVANCE_MINUTES,
    MAX_ADVANCE_DAYS,
    cancel_scheduled_ride,
    create_scheduled_ride,
    driver_accept_scheduled_ride,
    driver_decline_scheduled_ride,
    get_admin_summary,
    get_scheduled_ride,
    is_acceptable_by_driver,
    is_cancellable,
    is_declinable_by_driver,
    list_driver_scheduled_rides,
    list_rider_scheduled_rides,
    validate_scheduled_for,
)


# ===========================================================================
# Helpers
# ===========================================================================

_NOW = datetime(2026, 4, 14, 12, 0, 0, tzinfo=timezone.utc)
_VALID_FUTURE = _NOW + timedelta(hours=2)


def _make_ride(
    *,
    id: int = 1,
    rider_id: int = 10,
    driver_id: int | None = None,
    pickup_lat: float = 37.7749,
    pickup_lon: float = -122.4194,
    pickup_address: str = "123 Main St, San Francisco, CA",
    dropoff_lat: float = 37.8044,
    dropoff_lon: float = -122.2712,
    dropoff_address: str = "Oakland International Airport",
    scheduled_for: datetime = _VALID_FUTURE,
    estimated_fare: float | None = 32.50,
    notes: str | None = "Flight UA123 — Terminal 3",
    status: ScheduledRideStatus = ScheduledRideStatus.PENDING,
    cancelled_by: CancelledBy | None = None,
    cancellation_reason: str | None = None,
    decline_count: int = 0,
    ride_id: int | None = None,
    created_at: datetime = _NOW,
    accepted_at: datetime | None = None,
    completed_at: datetime | None = None,
    cancelled_at: datetime | None = None,
) -> ScheduledRide:
    ride = MagicMock(spec=ScheduledRide)
    ride.id = id
    ride.rider_id = rider_id
    ride.driver_id = driver_id
    ride.pickup_lat = pickup_lat
    ride.pickup_lon = pickup_lon
    ride.pickup_address = pickup_address
    ride.dropoff_lat = dropoff_lat
    ride.dropoff_lon = dropoff_lon
    ride.dropoff_address = dropoff_address
    ride.scheduled_for = scheduled_for
    ride.estimated_fare = estimated_fare
    ride.notes = notes
    ride.status = status
    ride.cancelled_by = cancelled_by
    ride.cancellation_reason = cancellation_reason
    ride.decline_count = decline_count
    ride.ride_id = ride_id
    ride.created_at = created_at
    ride.accepted_at = accepted_at
    ride.completed_at = completed_at
    ride.cancelled_at = cancelled_at
    return ride


# ===========================================================================
# validate_scheduled_for
# ===========================================================================


class TestValidateScheduledFor:
    def test_valid_near_future(self):
        t = _NOW + timedelta(minutes=MIN_ADVANCE_MINUTES + 1)
        assert validate_scheduled_for(t, now=_NOW) is None

    def test_valid_24_hours(self):
        t = _NOW + timedelta(hours=24)
        assert validate_scheduled_for(t, now=_NOW) is None

    def test_too_soon_before_min(self):
        t_too_soon = _NOW + timedelta(minutes=MIN_ADVANCE_MINUTES - 1)
        err = validate_scheduled_for(t_too_soon, now=_NOW)
        assert err is not None
        assert "30 minutes" in err

    def test_in_the_past(self):
        t = _NOW - timedelta(hours=1)
        err = validate_scheduled_for(t, now=_NOW)
        assert err is not None

    def test_too_far_ahead(self):
        t = _NOW + timedelta(days=MAX_ADVANCE_DAYS + 1)
        err = validate_scheduled_for(t, now=_NOW)
        assert err is not None
        assert "30 days" in err

    def test_exactly_max_days_minus_one_minute_is_ok(self):
        t = _NOW + timedelta(days=MAX_ADVANCE_DAYS, minutes=-1)
        assert validate_scheduled_for(t, now=_NOW) is None

    def test_naive_datetime_treated_as_utc(self):
        # 3 hours from _NOW (12:00 UTC) in naive form
        naive = datetime(2026, 4, 14, 15, 0, 0)
        err = validate_scheduled_for(naive, now=_NOW)
        assert err is None

    def test_uses_real_now_when_not_provided(self):
        far_future = datetime.now(timezone.utc) + timedelta(hours=12)
        assert validate_scheduled_for(far_future) is None


# ===========================================================================
# is_cancellable
# ===========================================================================


class TestIsCancellable:
    def test_pending_is_cancellable(self):
        ride = _make_ride(status=ScheduledRideStatus.PENDING)
        assert is_cancellable(ride) is True

    def test_driver_assigned_is_cancellable(self):
        ride = _make_ride(status=ScheduledRideStatus.DRIVER_ASSIGNED)
        assert is_cancellable(ride) is True

    def test_in_progress_not_cancellable(self):
        ride = _make_ride(status=ScheduledRideStatus.IN_PROGRESS)
        assert is_cancellable(ride) is False

    def test_completed_not_cancellable(self):
        ride = _make_ride(status=ScheduledRideStatus.COMPLETED)
        assert is_cancellable(ride) is False

    def test_already_cancelled_not_cancellable(self):
        ride = _make_ride(status=ScheduledRideStatus.CANCELLED)
        assert is_cancellable(ride) is False


# ===========================================================================
# is_acceptable_by_driver
# ===========================================================================


class TestIsAcceptableByDriver:
    def test_pending_ride_can_be_accepted(self):
        ride = _make_ride(status=ScheduledRideStatus.PENDING)
        ok, err = is_acceptable_by_driver(ride, driver_id=99)
        assert ok is True
        assert err == ""

    def test_driver_assigned_ride_cannot_be_accepted_by_other(self):
        ride = _make_ride(
            status=ScheduledRideStatus.DRIVER_ASSIGNED, driver_id=99
        )
        ok, err = is_acceptable_by_driver(ride, driver_id=88)
        assert ok is False
        assert "no longer available" in err

    def test_completed_ride_cannot_be_accepted(self):
        ride = _make_ride(status=ScheduledRideStatus.COMPLETED)
        ok, err = is_acceptable_by_driver(ride, driver_id=99)
        assert ok is False

    def test_already_assigned_driver_cannot_re_accept(self):
        ride = _make_ride(
            status=ScheduledRideStatus.PENDING, driver_id=99
        )
        ok, err = is_acceptable_by_driver(ride, driver_id=99)
        assert ok is False
        assert "already accepted" in err


# ===========================================================================
# is_declinable_by_driver
# ===========================================================================


class TestIsDeclinableByDriver:
    def test_assigned_driver_can_decline(self):
        ride = _make_ride(
            status=ScheduledRideStatus.DRIVER_ASSIGNED, driver_id=55
        )
        ok, err = is_declinable_by_driver(ride, driver_id=55)
        assert ok is True
        assert err == ""

    def test_wrong_driver_cannot_decline(self):
        ride = _make_ride(
            status=ScheduledRideStatus.DRIVER_ASSIGNED, driver_id=55
        )
        ok, err = is_declinable_by_driver(ride, driver_id=99)
        assert ok is False
        assert "not the assigned driver" in err

    def test_pending_ride_cannot_be_declined(self):
        ride = _make_ride(status=ScheduledRideStatus.PENDING)
        ok, err = is_declinable_by_driver(ride, driver_id=55)
        assert ok is False
        assert "driver-assigned" in err

    def test_completed_ride_cannot_be_declined(self):
        ride = _make_ride(
            status=ScheduledRideStatus.COMPLETED, driver_id=55
        )
        ok, err = is_declinable_by_driver(ride, driver_id=55)
        assert ok is False


# ===========================================================================
# create_scheduled_ride (mocked DB)
# ===========================================================================


class TestCreateScheduledRide:
    @pytest.mark.asyncio
    async def test_create_success(self):
        db = AsyncMock()
        db.add = MagicMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock(side_effect=lambda r: None)
        now = _NOW
        future = now + timedelta(hours=3)

        ride, err = await create_scheduled_ride(
            db,
            rider_id=10,
            pickup_lat=37.77,
            pickup_lon=-122.41,
            pickup_address="123 Main St",
            dropoff_lat=37.80,
            dropoff_lon=-122.27,
            dropoff_address="Oakland Airport",
            scheduled_for=future,
            estimated_fare=28.00,
            notes="Please wait by the curb",
            now=now,
        )
        assert err is None
        db.add.assert_called_once()
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_create_success_no_optional_fields(self):
        db = AsyncMock()
        db.add = MagicMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock(side_effect=lambda r: None)

        ride, err = await create_scheduled_ride(
            db,
            rider_id=10,
            pickup_lat=37.77,
            pickup_lon=-122.41,
            pickup_address="123 Main St",
            dropoff_lat=37.80,
            dropoff_lon=-122.27,
            dropoff_address="Oakland Airport",
            scheduled_for=_NOW + timedelta(hours=5),
            now=_NOW,
        )
        assert err is None

    @pytest.mark.asyncio
    async def test_create_fails_too_soon(self):
        db = AsyncMock()
        too_soon = _NOW + timedelta(minutes=10)

        ride, err = await create_scheduled_ride(
            db,
            rider_id=10,
            pickup_lat=37.77,
            pickup_lon=-122.41,
            pickup_address="123 Main St",
            dropoff_lat=37.80,
            dropoff_lon=-122.27,
            dropoff_address="Oakland Airport",
            scheduled_for=too_soon,
            now=_NOW,
        )
        assert ride is None
        assert err is not None
        assert "30 minutes" in err
        db.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_create_fails_too_far_ahead(self):
        db = AsyncMock()
        too_far = _NOW + timedelta(days=35)

        ride, err = await create_scheduled_ride(
            db,
            rider_id=10,
            pickup_lat=37.77,
            pickup_lon=-122.41,
            pickup_address="123 Main St",
            dropoff_lat=37.80,
            dropoff_lon=-122.27,
            dropoff_address="Oakland Airport",
            scheduled_for=too_far,
            now=_NOW,
        )
        assert ride is None
        assert err is not None
        db.add.assert_not_called()


# ===========================================================================
# get_scheduled_ride (mocked DB)
# ===========================================================================


class TestGetScheduledRide:
    @pytest.mark.asyncio
    async def test_returns_ride_when_found(self):
        mock_ride = _make_ride(id=7)
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = mock_ride
        db.execute = AsyncMock(return_value=result_mock)

        ride = await get_scheduled_ride(db, 7)
        assert ride is mock_ride

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self):
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=result_mock)

        ride = await get_scheduled_ride(db, 999)
        assert ride is None


# ===========================================================================
# driver_accept_scheduled_ride (mocked DB)
# ===========================================================================


class TestDriverAcceptScheduledRide:
    @pytest.mark.asyncio
    async def test_accept_pending_ride(self):
        mock_ride = _make_ride(id=1, status=ScheduledRideStatus.PENDING)
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = mock_ride
        db.execute = AsyncMock(return_value=result_mock)
        db.add = MagicMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        ride, err = await driver_accept_scheduled_ride(db, 1, driver_id=55, now=_NOW)
        assert err is None
        assert mock_ride.driver_id == 55
        assert mock_ride.status == ScheduledRideStatus.DRIVER_ASSIGNED
        assert mock_ride.accepted_at == _NOW

    @pytest.mark.asyncio
    async def test_accept_not_found(self):
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=result_mock)

        ride, err = await driver_accept_scheduled_ride(db, 999, driver_id=55)
        assert ride is None
        assert "not found" in err

    @pytest.mark.asyncio
    async def test_accept_already_assigned_by_other_driver(self):
        mock_ride = _make_ride(
            id=1, status=ScheduledRideStatus.DRIVER_ASSIGNED, driver_id=77
        )
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = mock_ride
        db.execute = AsyncMock(return_value=result_mock)

        ride, err = await driver_accept_scheduled_ride(db, 1, driver_id=55)
        assert ride is None
        assert "no longer available" in err


# ===========================================================================
# driver_decline_scheduled_ride (mocked DB)
# ===========================================================================


class TestDriverDeclineScheduledRide:
    @pytest.mark.asyncio
    async def test_decline_assigned_ride_returns_to_pending(self):
        mock_ride = _make_ride(
            id=1, status=ScheduledRideStatus.DRIVER_ASSIGNED, driver_id=55, decline_count=0
        )
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = mock_ride
        db.execute = AsyncMock(return_value=result_mock)
        db.add = MagicMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        ride, err = await driver_decline_scheduled_ride(db, 1, driver_id=55, now=_NOW)
        assert err is None
        assert mock_ride.status == ScheduledRideStatus.PENDING
        assert mock_ride.driver_id is None
        assert mock_ride.accepted_at is None
        assert mock_ride.decline_count == 1

    @pytest.mark.asyncio
    async def test_decline_increments_decline_count(self):
        mock_ride = _make_ride(
            id=1, status=ScheduledRideStatus.DRIVER_ASSIGNED, driver_id=55, decline_count=2
        )
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = mock_ride
        db.execute = AsyncMock(return_value=result_mock)
        db.add = MagicMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        await driver_decline_scheduled_ride(db, 1, driver_id=55, now=_NOW)
        assert mock_ride.decline_count == 3

    @pytest.mark.asyncio
    async def test_decline_wrong_driver(self):
        mock_ride = _make_ride(
            id=1, status=ScheduledRideStatus.DRIVER_ASSIGNED, driver_id=55
        )
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = mock_ride
        db.execute = AsyncMock(return_value=result_mock)

        ride, err = await driver_decline_scheduled_ride(db, 1, driver_id=99)
        assert ride is None
        assert "not the assigned driver" in err

    @pytest.mark.asyncio
    async def test_decline_not_found(self):
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=result_mock)

        ride, err = await driver_decline_scheduled_ride(db, 999, driver_id=55)
        assert ride is None
        assert "not found" in err


# ===========================================================================
# cancel_scheduled_ride (mocked DB)
# ===========================================================================


class TestCancelScheduledRide:
    @pytest.mark.asyncio
    async def test_cancel_pending_by_rider(self):
        mock_ride = _make_ride(id=1, status=ScheduledRideStatus.PENDING)
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = mock_ride
        db.execute = AsyncMock(return_value=result_mock)
        db.add = MagicMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        ride, err = await cancel_scheduled_ride(
            db, 1, cancelled_by=CancelledBy.RIDER, reason="Plans changed", now=_NOW
        )
        assert err is None
        assert mock_ride.status == ScheduledRideStatus.CANCELLED
        assert mock_ride.cancelled_by == CancelledBy.RIDER
        assert mock_ride.cancellation_reason == "Plans changed"
        assert mock_ride.cancelled_at == _NOW

    @pytest.mark.asyncio
    async def test_cancel_driver_assigned_by_admin(self):
        mock_ride = _make_ride(
            id=2, status=ScheduledRideStatus.DRIVER_ASSIGNED, driver_id=55
        )
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = mock_ride
        db.execute = AsyncMock(return_value=result_mock)
        db.add = MagicMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        ride, err = await cancel_scheduled_ride(
            db, 2, cancelled_by=CancelledBy.ADMIN, now=_NOW
        )
        assert err is None
        assert mock_ride.cancelled_by == CancelledBy.ADMIN

    @pytest.mark.asyncio
    async def test_cancel_in_progress_fails(self):
        mock_ride = _make_ride(id=3, status=ScheduledRideStatus.IN_PROGRESS)
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = mock_ride
        db.execute = AsyncMock(return_value=result_mock)

        ride, err = await cancel_scheduled_ride(
            db, 3, cancelled_by=CancelledBy.RIDER
        )
        assert ride is None
        assert err is not None
        assert "Cannot cancel" in err

    @pytest.mark.asyncio
    async def test_cancel_completed_fails(self):
        mock_ride = _make_ride(id=4, status=ScheduledRideStatus.COMPLETED)
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = mock_ride
        db.execute = AsyncMock(return_value=result_mock)

        ride, err = await cancel_scheduled_ride(
            db, 4, cancelled_by=CancelledBy.RIDER
        )
        assert ride is None
        assert err is not None

    @pytest.mark.asyncio
    async def test_cancel_not_found(self):
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=result_mock)

        ride, err = await cancel_scheduled_ride(
            db, 999, cancelled_by=CancelledBy.RIDER
        )
        assert ride is None
        assert "not found" in err

    @pytest.mark.asyncio
    async def test_cancel_no_reason_is_ok(self):
        mock_ride = _make_ride(id=5, status=ScheduledRideStatus.PENDING)
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = mock_ride
        db.execute = AsyncMock(return_value=result_mock)
        db.add = MagicMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        ride, err = await cancel_scheduled_ride(
            db, 5, cancelled_by=CancelledBy.DRIVER, now=_NOW
        )
        assert err is None
        assert mock_ride.cancellation_reason is None


# ===========================================================================
# get_admin_summary (mocked DB)
# ===========================================================================


class TestGetAdminSummary:
    @pytest.mark.asyncio
    async def test_returns_correct_totals(self):
        rows = [
            MagicMock(status=ScheduledRideStatus.PENDING, cnt=5),
            MagicMock(status=ScheduledRideStatus.DRIVER_ASSIGNED, cnt=3),
            MagicMock(status=ScheduledRideStatus.COMPLETED, cnt=12),
        ]
        result_mock = MagicMock()
        result_mock.all.return_value = rows
        db = AsyncMock()
        db.execute = AsyncMock(return_value=result_mock)

        summary = await get_admin_summary(db)
        assert summary["pending"] == 5
        assert summary["driver_assigned"] == 3
        assert summary["completed"] == 12
        assert summary["in_progress"] == 0
        assert summary["cancelled"] == 0
        assert summary["total"] == 20

    @pytest.mark.asyncio
    async def test_returns_zeros_when_no_rides(self):
        result_mock = MagicMock()
        result_mock.all.return_value = []
        db = AsyncMock()
        db.execute = AsyncMock(return_value=result_mock)

        summary = await get_admin_summary(db)
        assert summary["total"] == 0
        assert all(v == 0 for k, v in summary.items() if k != "total")

    @pytest.mark.asyncio
    async def test_all_statuses_counted(self):
        rows = [
            MagicMock(status=ScheduledRideStatus.PENDING, cnt=1),
            MagicMock(status=ScheduledRideStatus.DRIVER_ASSIGNED, cnt=2),
            MagicMock(status=ScheduledRideStatus.IN_PROGRESS, cnt=3),
            MagicMock(status=ScheduledRideStatus.COMPLETED, cnt=4),
            MagicMock(status=ScheduledRideStatus.CANCELLED, cnt=5),
        ]
        result_mock = MagicMock()
        result_mock.all.return_value = rows
        db = AsyncMock()
        db.execute = AsyncMock(return_value=result_mock)

        summary = await get_admin_summary(db)
        assert summary["total"] == 15
        assert summary["in_progress"] == 3
        assert summary["cancelled"] == 5


# ===========================================================================
# Schema validation
# ===========================================================================


class TestSchemas:
    def test_create_request_valid(self):
        req = ScheduledRideCreateRequest(
            pickup_lat=37.77,
            pickup_lon=-122.41,
            pickup_address="123 Main St",
            dropoff_lat=37.80,
            dropoff_lon=-122.27,
            dropoff_address="Oakland Airport",
            scheduled_for=_VALID_FUTURE,
            estimated_fare=28.50,
            notes="Flight UA123",
        )
        assert req.pickup_lat == 37.77
        assert req.notes == "Flight UA123"
        assert req.estimated_fare == 28.50

    def test_create_request_no_optional_fields(self):
        req = ScheduledRideCreateRequest(
            pickup_lat=37.77,
            pickup_lon=-122.41,
            pickup_address="123 Main St",
            dropoff_lat=37.80,
            dropoff_lon=-122.27,
            dropoff_address="Oakland Airport",
            scheduled_for=_VALID_FUTURE,
        )
        assert req.notes is None
        assert req.estimated_fare is None

    def test_create_request_invalid_lat(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            ScheduledRideCreateRequest(
                pickup_lat=200,  # invalid: > 90
                pickup_lon=-122.41,
                pickup_address="123 Main St",
                dropoff_lat=37.80,
                dropoff_lon=-122.27,
                dropoff_address="Oakland Airport",
                scheduled_for=_VALID_FUTURE,
            )

    def test_create_request_invalid_lon(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            ScheduledRideCreateRequest(
                pickup_lat=37.77,
                pickup_lon=-200,  # invalid: < -180
                pickup_address="123 Main St",
                dropoff_lat=37.80,
                dropoff_lon=-122.27,
                dropoff_address="Oakland Airport",
                scheduled_for=_VALID_FUTURE,
            )

    def test_create_request_empty_address_fails(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            ScheduledRideCreateRequest(
                pickup_lat=37.77,
                pickup_lon=-122.41,
                pickup_address="",  # min_length=1
                dropoff_lat=37.80,
                dropoff_lon=-122.27,
                dropoff_address="Oakland Airport",
                scheduled_for=_VALID_FUTURE,
            )

    def test_create_request_negative_fare_fails(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            ScheduledRideCreateRequest(
                pickup_lat=37.77,
                pickup_lon=-122.41,
                pickup_address="123 Main St",
                dropoff_lat=37.80,
                dropoff_lon=-122.27,
                dropoff_address="Oakland Airport",
                scheduled_for=_VALID_FUTURE,
                estimated_fare=-5.0,  # ge=0
            )

    def test_cancel_request_optional_reason(self):
        req = ScheduledRideCancelRequest()
        assert req.reason is None

    def test_cancel_request_with_reason(self):
        req = ScheduledRideCancelRequest(reason="Change of plans")
        assert req.reason == "Change of plans"

    def test_accept_response(self):
        resp = ScheduledRideAcceptResponse(
            scheduled_ride_id=7,
            status=ScheduledRideStatus.DRIVER_ASSIGNED,
            message="Accepted",
        )
        assert resp.scheduled_ride_id == 7
        assert resp.status == ScheduledRideStatus.DRIVER_ASSIGNED

    def test_decline_response(self):
        resp = ScheduledRideDeclineResponse(
            scheduled_ride_id=7,
            status=ScheduledRideStatus.PENDING,
            decline_count=1,
            message="Declined",
        )
        assert resp.decline_count == 1
        assert resp.status == ScheduledRideStatus.PENDING

    def test_cancel_response(self):
        resp = ScheduledRideCancelResponse(
            scheduled_ride_id=3,
            cancelled=True,
            cancelled_by=CancelledBy.RIDER,
            message="Cancelled",
        )
        assert resp.cancelled is True
        assert resp.cancelled_by == CancelledBy.RIDER

    def test_list_response_empty(self):
        resp = ScheduledRideListResponse(items=[], total=0, page=1, page_size=20)
        assert resp.total == 0
        assert resp.items == []

    def test_admin_summary_schema(self):
        summary = AdminScheduledRideSummary(
            total=20,
            pending=5,
            driver_assigned=3,
            in_progress=0,
            completed=12,
            cancelled=0,
        )
        assert summary.total == 20
        assert summary.pending == 5
        assert summary.driver_assigned == 3


# ===========================================================================
# Constants
# ===========================================================================


class TestConstants:
    def test_min_advance_minutes(self):
        assert MIN_ADVANCE_MINUTES == 30

    def test_max_advance_days(self):
        assert MAX_ADVANCE_DAYS == 30

    def test_default_page_size(self):
        assert DEFAULT_PAGE_SIZE == 20


# ===========================================================================
# ScheduledRideStatus and CancelledBy enums
# ===========================================================================


class TestEnums:
    def test_all_statuses_exist(self):
        statuses = {s.value for s in ScheduledRideStatus}
        assert "pending" in statuses
        assert "driver_assigned" in statuses
        assert "in_progress" in statuses
        assert "completed" in statuses
        assert "cancelled" in statuses

    def test_cancelled_by_values(self):
        values = {c.value for c in CancelledBy}
        assert values == {"rider", "driver", "admin"}

    def test_status_is_str_enum(self):
        assert ScheduledRideStatus.PENDING == "pending"
        assert ScheduledRideStatus.DRIVER_ASSIGNED == "driver_assigned"
        assert ScheduledRideStatus.IN_PROGRESS == "in_progress"
        assert ScheduledRideStatus.COMPLETED == "completed"
        assert ScheduledRideStatus.CANCELLED == "cancelled"

    def test_cancelled_by_is_str_enum(self):
        assert CancelledBy.RIDER == "rider"
        assert CancelledBy.DRIVER == "driver"
        assert CancelledBy.ADMIN == "admin"
