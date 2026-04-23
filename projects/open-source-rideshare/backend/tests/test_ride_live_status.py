"""Tests for GET /api/v1/rides/{ride_id}/live-status.

Coverage
--------
Pure-function unit tests:
  1.  _eta_minutes — standard distance
  2.  _eta_minutes — zero distance returns 1 minute
  3.  _eta_minutes — sub-minute distance returns 1 minute
  4.  _build_phase_message — SCHEDULED
  5.  _build_phase_message — REQUESTED
  6.  _build_phase_message — MATCHED
  7.  _build_phase_message — DRIVER_EN_ROUTE with GPS (ETA + distance)
  8.  _build_phase_message — DRIVER_EN_ROUTE without GPS (fallback)
  9.  _build_phase_message — ARRIVED
  10. _build_phase_message — IN_PROGRESS with ETA
  11. _build_phase_message — IN_PROGRESS without ETA (fallback)
  12. _build_phase_message — COMPLETED
  13. _build_phase_message — CANCELLED

Service unit tests (mocked DB):
  14. get_ride_live_status — ValueError when ride not found
  15. get_ride_live_status — PermissionError for unrelated rider
  16. get_ride_live_status — rider can access their own ride
  17. get_ride_live_status — assigned driver can access their ride
  18. get_ride_live_status — admin can access any ride
  19. get_ride_live_status — status REQUESTED: pickup/dropoff distances are None
  20. get_ride_live_status — status DRIVER_EN_ROUTE: pickup distance/ETA populated
  21. get_ride_live_status — status IN_PROGRESS: dropoff distance/ETA populated
  22. get_ride_live_status — no driver assigned: driver_lat/lng are None
  23. get_ride_live_status — driver assigned but no GPS fix: distances are None
  24. get_ride_live_status — timestamps mapped correctly (matched_at → driver_matched_at, arrived_at → pickup_at)
  25. get_ride_live_status — poll_interval_seconds matches status
  26. get_ride_live_status — COMPLETED status, poll=60

API endpoint tests (mocked service):
  27. GET /rides/{id}/live-status — 404 when ride not found (ValueError)
  28. GET /rides/{id}/live-status — 404 when unauthorised (PermissionError)
  29. GET /rides/{id}/live-status — 200 for rider with valid response shape
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.ride import Ride, RideStatus
from app.schemas.ride_live_status import RideLiveStatus
from app.services.ride_live_status import (
    _SPEED_M_PER_MIN,
    _build_phase_message,
    _eta_minutes,
    get_ride_live_status,
)

# ---------------------------------------------------------------------------
# Shared test coordinates
# ---------------------------------------------------------------------------

_PICKUP_LAT, _PICKUP_LNG = 40.7527, -73.9772   # Grand Central, NYC
_DROPOFF_LAT, _DROPOFF_LNG = 40.7614, -73.9776  # Rockefeller Center, NYC
_DRIVER_LAT, _DRIVER_LNG = 40.7580, -73.9855    # Times Square, NYC (~1 060 m from pickup)


# ---------------------------------------------------------------------------
# DB mock helpers
# ---------------------------------------------------------------------------


def _one_or_none(value) -> MagicMock:
    m = MagicMock()
    m.one_or_none.return_value = value
    return m


def _make_ride(
    id: int = 1,
    rider_id: int = 5,
    driver_id: int | None = 10,
    status: RideStatus = RideStatus.DRIVER_EN_ROUTE,
    matched_at: datetime | None = None,
    arrived_at: datetime | None = None,
    completed_at: datetime | None = None,
) -> MagicMock:
    ride = MagicMock(spec=Ride)
    ride.id = id
    ride.rider_id = rider_id
    ride.driver_id = driver_id
    ride.status = status
    ride.requested_at = datetime(2024, 6, 1, 10, 0, 0, tzinfo=timezone.utc)
    ride.matched_at = matched_at
    ride.arrived_at = arrived_at
    ride.completed_at = completed_at
    return ride


def _make_db_for_ride(
    ride: MagicMock,
    pickup_lat: float = _PICKUP_LAT,
    pickup_lng: float = _PICKUP_LNG,
    dropoff_lat: float = _DROPOFF_LAT,
    dropoff_lng: float = _DROPOFF_LNG,
    driver_lat: float | None = _DRIVER_LAT,
    driver_lng: float | None = _DRIVER_LNG,
    include_profile: bool = True,
) -> AsyncMock:
    """Build a mock DB that returns ride row then optionally a DriverProfile row."""
    ride_row = (ride, pickup_lat, pickup_lng, dropoff_lat, dropoff_lng)

    if include_profile and ride.driver_id is not None:
        profile_row = MagicMock()
        profile_row.lat = driver_lat
        profile_row.lng = driver_lng
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _one_or_none(ride_row),
                _one_or_none(profile_row),
            ]
        )
    else:
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_one_or_none(ride_row))

    return db


# ---------------------------------------------------------------------------
# 1–3: _eta_minutes
# ---------------------------------------------------------------------------


class TestEtaMinutes:

    def test_standard_distance(self):
        """Test 1: 5000 m at 25 km/h = expected round value."""
        result = _eta_minutes(5000.0)
        expected = max(1, round(5000.0 / _SPEED_M_PER_MIN))
        assert result == expected

    def test_zero_distance_returns_one(self):
        """Test 2: zero distance → 1 minute minimum."""
        assert _eta_minutes(0.0) == 1

    def test_sub_minute_distance_returns_one(self):
        """Test 3: distance below one minute → 1 minute minimum."""
        assert _eta_minutes(100.0) == 1


# ---------------------------------------------------------------------------
# 4–13: _build_phase_message
# ---------------------------------------------------------------------------


class TestBuildPhaseMessage:

    def test_scheduled(self):
        """Test 4: SCHEDULED status."""
        msg = _build_phase_message(RideStatus.SCHEDULED, None, None, None)
        assert msg == "Your ride is scheduled"

    def test_requested(self):
        """Test 5: REQUESTED status."""
        msg = _build_phase_message(RideStatus.REQUESTED, None, None, None)
        assert "looking for a driver" in msg.lower()

    def test_matched(self):
        """Test 6: MATCHED status."""
        msg = _build_phase_message(RideStatus.MATCHED, None, None, None)
        assert "driver matched" in msg.lower()

    def test_driver_en_route_with_gps(self):
        """Test 7: DRIVER_EN_ROUTE with ETA and distance populated."""
        msg = _build_phase_message(RideStatus.DRIVER_EN_ROUTE, 3, 800.0, None)
        assert "3 min" in msg
        assert "800 m" in msg

    def test_driver_en_route_without_gps(self):
        """Test 8: DRIVER_EN_ROUTE without GPS falls back to generic message."""
        msg = _build_phase_message(RideStatus.DRIVER_EN_ROUTE, None, None, None)
        assert "on the way" in msg.lower()

    def test_arrived(self):
        """Test 9: ARRIVED status."""
        msg = _build_phase_message(RideStatus.ARRIVED, None, None, None)
        assert "arrived" in msg.lower()

    def test_in_progress_with_eta(self):
        """Test 10: IN_PROGRESS with ETA to dropoff."""
        msg = _build_phase_message(RideStatus.IN_PROGRESS, None, None, 12)
        assert "12 min" in msg
        assert "destination" in msg.lower()

    def test_in_progress_without_eta(self):
        """Test 11: IN_PROGRESS without GPS falls back to generic message."""
        msg = _build_phase_message(RideStatus.IN_PROGRESS, None, None, None)
        assert "on your way" in msg.lower()

    def test_completed(self):
        """Test 12: COMPLETED status."""
        msg = _build_phase_message(RideStatus.COMPLETED, None, None, None)
        assert msg == "Ride complete"

    def test_cancelled(self):
        """Test 13: CANCELLED status."""
        msg = _build_phase_message(RideStatus.CANCELLED, None, None, None)
        assert msg == "Ride cancelled"


# ---------------------------------------------------------------------------
# 14–26: Service unit tests (mocked DB)
# ---------------------------------------------------------------------------


class TestGetRideLiveStatusService:

    @pytest.mark.asyncio
    async def test_ride_not_found_raises_value_error(self):
        """Test 14: ValueError when ride does not exist."""
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_one_or_none(None))
        with pytest.raises(ValueError, match="not found"):
            await get_ride_live_status(
                ride_id=99, caller_id=5, caller_is_driver=False, caller_is_admin=False, db=db
            )

    @pytest.mark.asyncio
    async def test_unrelated_rider_raises_permission_error(self):
        """Test 15: PermissionError for a caller who is not rider, driver, or admin."""
        ride = _make_ride(rider_id=5, driver_id=10)
        db = _make_db_for_ride(ride, include_profile=False)
        db.execute = AsyncMock(
            return_value=_one_or_none((ride, _PICKUP_LAT, _PICKUP_LNG, _DROPOFF_LAT, _DROPOFF_LNG))
        )
        with pytest.raises(PermissionError):
            await get_ride_live_status(
                ride_id=1, caller_id=99, caller_is_driver=False, caller_is_admin=False, db=db
            )

    @pytest.mark.asyncio
    async def test_rider_can_access_own_ride(self):
        """Test 16: ride owner (rider) receives a result."""
        ride = _make_ride(rider_id=5, driver_id=None, status=RideStatus.REQUESTED)
        db = _make_db_for_ride(ride, include_profile=False)
        db.execute = AsyncMock(
            return_value=_one_or_none((ride, _PICKUP_LAT, _PICKUP_LNG, _DROPOFF_LAT, _DROPOFF_LNG))
        )
        result = await get_ride_live_status(
            ride_id=1, caller_id=5, caller_is_driver=False, caller_is_admin=False, db=db
        )
        assert result.ride_id == 1
        assert result.status == "requested"

    @pytest.mark.asyncio
    async def test_assigned_driver_can_access_ride(self):
        """Test 17: assigned driver (caller_is_driver=True, driver_id matches) is allowed."""
        ride = _make_ride(rider_id=5, driver_id=10, status=RideStatus.DRIVER_EN_ROUTE)
        db = _make_db_for_ride(ride, driver_lat=_DRIVER_LAT, driver_lng=_DRIVER_LNG)
        with patch("app.services.ride_live_status.haversine_m", return_value=1060.0):
            result = await get_ride_live_status(
                ride_id=1, caller_id=10, caller_is_driver=True, caller_is_admin=False, db=db
            )
        assert result.ride_id == 1

    @pytest.mark.asyncio
    async def test_admin_can_access_any_ride(self):
        """Test 18: admin bypasses ownership check entirely."""
        ride = _make_ride(rider_id=5, driver_id=None, status=RideStatus.REQUESTED)
        db = AsyncMock()
        db.execute = AsyncMock(
            return_value=_one_or_none((ride, _PICKUP_LAT, _PICKUP_LNG, _DROPOFF_LAT, _DROPOFF_LNG))
        )
        result = await get_ride_live_status(
            ride_id=1, caller_id=999, caller_is_driver=False, caller_is_admin=True, db=db
        )
        assert result.ride_id == 1

    @pytest.mark.asyncio
    async def test_requested_status_no_distances(self):
        """Test 19: REQUESTED ride has no pickup or dropoff distances."""
        ride = _make_ride(rider_id=5, driver_id=None, status=RideStatus.REQUESTED)
        db = AsyncMock()
        db.execute = AsyncMock(
            return_value=_one_or_none((ride, _PICKUP_LAT, _PICKUP_LNG, _DROPOFF_LAT, _DROPOFF_LNG))
        )
        result = await get_ride_live_status(
            ride_id=1, caller_id=5, caller_is_driver=False, caller_is_admin=False, db=db
        )
        assert result.distance_to_pickup_m is None
        assert result.eta_to_pickup_minutes is None
        assert result.distance_to_dropoff_m is None
        assert result.eta_to_dropoff_minutes is None

    @pytest.mark.asyncio
    async def test_driver_en_route_pickup_distance_populated(self):
        """Test 20: DRIVER_EN_ROUTE populates pickup distance/ETA."""
        ride = _make_ride(rider_id=5, driver_id=10, status=RideStatus.DRIVER_EN_ROUTE)
        db = _make_db_for_ride(ride, driver_lat=_DRIVER_LAT, driver_lng=_DRIVER_LNG)
        with patch("app.services.ride_live_status.haversine_m", return_value=1060.0):
            result = await get_ride_live_status(
                ride_id=1, caller_id=5, caller_is_driver=False, caller_is_admin=False, db=db
            )
        assert result.distance_to_pickup_m is not None
        assert result.distance_to_pickup_m > 0
        assert result.eta_to_pickup_minutes is not None
        assert result.eta_to_pickup_minutes >= 1
        # Dropoff should be None for this status
        assert result.distance_to_dropoff_m is None
        assert result.eta_to_dropoff_minutes is None

    @pytest.mark.asyncio
    async def test_in_progress_dropoff_distance_populated(self):
        """Test 21: IN_PROGRESS populates dropoff distance/ETA, not pickup."""
        ride = _make_ride(rider_id=5, driver_id=10, status=RideStatus.IN_PROGRESS)
        db = _make_db_for_ride(ride, driver_lat=_DRIVER_LAT, driver_lng=_DRIVER_LNG)
        with patch("app.services.ride_live_status.haversine_m", return_value=900.0):
            result = await get_ride_live_status(
                ride_id=1, caller_id=5, caller_is_driver=False, caller_is_admin=False, db=db
            )
        assert result.distance_to_dropoff_m is not None
        assert result.distance_to_dropoff_m > 0
        assert result.eta_to_dropoff_minutes is not None
        # Pickup should be None for IN_PROGRESS
        assert result.distance_to_pickup_m is None
        assert result.eta_to_pickup_minutes is None

    @pytest.mark.asyncio
    async def test_no_driver_assigned_null_gps(self):
        """Test 22: no driver assigned → driver_lat, driver_lng are None."""
        ride = _make_ride(rider_id=5, driver_id=None, status=RideStatus.REQUESTED)
        db = AsyncMock()
        db.execute = AsyncMock(
            return_value=_one_or_none((ride, _PICKUP_LAT, _PICKUP_LNG, _DROPOFF_LAT, _DROPOFF_LNG))
        )
        result = await get_ride_live_status(
            ride_id=1, caller_id=5, caller_is_driver=False, caller_is_admin=False, db=db
        )
        assert result.driver_lat is None
        assert result.driver_lng is None

    @pytest.mark.asyncio
    async def test_driver_assigned_no_gps_fix(self):
        """Test 23: driver assigned but DriverProfile has no GPS → distances None."""
        ride = _make_ride(rider_id=5, driver_id=10, status=RideStatus.DRIVER_EN_ROUTE)
        db = _make_db_for_ride(ride, driver_lat=None, driver_lng=None)
        result = await get_ride_live_status(
            ride_id=1, caller_id=5, caller_is_driver=False, caller_is_admin=False, db=db
        )
        assert result.driver_lat is None
        assert result.driver_lng is None
        assert result.distance_to_pickup_m is None
        assert result.eta_to_pickup_minutes is None

    @pytest.mark.asyncio
    async def test_timestamps_mapped_correctly(self):
        """Test 24: matched_at → driver_matched_at, arrived_at → pickup_at."""
        matched_dt = datetime(2024, 6, 1, 10, 5, 0, tzinfo=timezone.utc)
        arrived_dt = datetime(2024, 6, 1, 10, 15, 0, tzinfo=timezone.utc)
        ride = _make_ride(
            rider_id=5,
            driver_id=None,
            status=RideStatus.ARRIVED,
            matched_at=matched_dt,
            arrived_at=arrived_dt,
        )
        db = AsyncMock()
        db.execute = AsyncMock(
            return_value=_one_or_none((ride, _PICKUP_LAT, _PICKUP_LNG, _DROPOFF_LAT, _DROPOFF_LNG))
        )
        result = await get_ride_live_status(
            ride_id=1, caller_id=5, caller_is_driver=False, caller_is_admin=False, db=db
        )
        assert result.driver_matched_at == matched_dt.isoformat()
        assert result.pickup_at == arrived_dt.isoformat()

    @pytest.mark.asyncio
    async def test_poll_interval_by_status(self):
        """Test 25: poll_interval_seconds reflects the current status."""
        cases = [
            (RideStatus.REQUESTED, 5),
            (RideStatus.DRIVER_EN_ROUTE, 5),
            (RideStatus.ARRIVED, 10),
            (RideStatus.IN_PROGRESS, 10),
        ]
        for ride_status, expected_poll in cases:
            ride = _make_ride(rider_id=5, driver_id=None, status=ride_status)
            db = AsyncMock()
            db.execute = AsyncMock(
                return_value=_one_or_none(
                    (ride, _PICKUP_LAT, _PICKUP_LNG, _DROPOFF_LAT, _DROPOFF_LNG)
                )
            )
            result = await get_ride_live_status(
                ride_id=1, caller_id=5, caller_is_driver=False, caller_is_admin=False, db=db
            )
            assert result.poll_interval_seconds == expected_poll, (
                f"Expected poll={expected_poll} for status={ride_status}, got {result.poll_interval_seconds}"
            )

    @pytest.mark.asyncio
    async def test_completed_poll_interval_60(self):
        """Test 26: COMPLETED ride has poll_interval_seconds=60."""
        ride = _make_ride(
            rider_id=5,
            driver_id=10,
            status=RideStatus.COMPLETED,
            completed_at=datetime(2024, 6, 1, 11, 0, 0, tzinfo=timezone.utc),
        )
        db = _make_db_for_ride(ride, driver_lat=None, driver_lng=None)
        result = await get_ride_live_status(
            ride_id=1, caller_id=5, caller_is_driver=False, caller_is_admin=False, db=db
        )
        assert result.poll_interval_seconds == 60
        assert result.status == "completed"
        assert result.completed_at is not None


# ---------------------------------------------------------------------------
# 27–29: API endpoint tests (mocked service)
# ---------------------------------------------------------------------------


class TestRideLiveStatusAPI:
    """Lightweight tests that mock the service layer and test the router logic."""

    @pytest.mark.asyncio
    async def test_ride_not_found_returns_404(self):
        """Test 27: ValueError from service → 404 Not Found."""
        from fastapi.testclient import TestClient
        from app.main import app
        from app.models.user import User, UserRole
        from app.api.deps import get_current_user, get_db
        import app.api.v1.ride_live_status as router_module

        rider_user = MagicMock(spec=User)
        rider_user.id = 5
        rider_user.role = UserRole.RIDER
        rider_user.is_active = True

        async def override_user():
            return rider_user

        async def override_db():
            yield AsyncMock()

        async def mock_service(*args, **kwargs):
            raise ValueError("Ride not found")

        app.dependency_overrides[get_current_user] = override_user
        app.dependency_overrides[get_db] = override_db

        try:
            with patch.object(router_module, "get_ride_live_status", side_effect=mock_service):
                client = TestClient(app, raise_server_exceptions=False)
                resp = client.get("/api/v1/rides/9999/live-status")
                assert resp.status_code == 404
        finally:
            app.dependency_overrides.pop(get_current_user, None)
            app.dependency_overrides.pop(get_db, None)

    @pytest.mark.asyncio
    async def test_unauthorised_caller_returns_404(self):
        """Test 28: PermissionError from service → 404 (prevents enumeration)."""
        from fastapi.testclient import TestClient
        from app.main import app
        from app.models.user import User, UserRole
        from app.api.deps import get_current_user, get_db
        import app.api.v1.ride_live_status as router_module

        other_rider = MagicMock(spec=User)
        other_rider.id = 99
        other_rider.role = UserRole.RIDER
        other_rider.is_active = True

        async def override_user():
            return other_rider

        async def override_db():
            yield AsyncMock()

        async def mock_service(*args, **kwargs):
            raise PermissionError("Not authorised to view this ride")

        app.dependency_overrides[get_current_user] = override_user
        app.dependency_overrides[get_db] = override_db

        try:
            with patch.object(router_module, "get_ride_live_status", side_effect=mock_service):
                client = TestClient(app, raise_server_exceptions=False)
                resp = client.get("/api/v1/rides/1/live-status")
                assert resp.status_code == 404
        finally:
            app.dependency_overrides.pop(get_current_user, None)
            app.dependency_overrides.pop(get_db, None)

    @pytest.mark.asyncio
    async def test_valid_rider_request_returns_200(self):
        """Test 29: valid caller with mocked service receives 200 and expected shape."""
        from fastapi.testclient import TestClient
        from app.main import app
        from app.models.user import User, UserRole
        from app.api.deps import get_current_user, get_db
        import app.api.v1.ride_live_status as router_module

        rider_user = MagicMock(spec=User)
        rider_user.id = 5
        rider_user.role = UserRole.RIDER
        rider_user.is_active = True

        mock_response = RideLiveStatus(
            ride_id=1,
            status="driver_en_route",
            driver_lat=_DRIVER_LAT,
            driver_lng=_DRIVER_LNG,
            distance_to_pickup_m=1060.0,
            eta_to_pickup_minutes=3,
            distance_to_dropoff_m=None,
            eta_to_dropoff_minutes=None,
            requested_at="2024-06-01T10:00:00+00:00",
            driver_matched_at=None,
            pickup_at=None,
            completed_at=None,
            phase_message="Driver is 3 min away (1060 m)",
            poll_interval_seconds=5,
        )

        async def override_user():
            return rider_user

        async def override_db():
            yield AsyncMock()

        async def mock_service(*args, **kwargs):
            return mock_response

        app.dependency_overrides[get_current_user] = override_user
        app.dependency_overrides[get_db] = override_db

        try:
            with patch.object(router_module, "get_ride_live_status", side_effect=mock_service):
                client = TestClient(app, raise_server_exceptions=False)
                resp = client.get("/api/v1/rides/1/live-status")
                assert resp.status_code == 200
                data = resp.json()
                assert data["ride_id"] == 1
                assert data["status"] == "driver_en_route"
                assert data["poll_interval_seconds"] == 5
                assert "phase_message" in data
                assert data["driver_lat"] == _DRIVER_LAT
                assert data["driver_lng"] == _DRIVER_LNG
        finally:
            app.dependency_overrides.pop(get_current_user, None)
            app.dependency_overrides.pop(get_db, None)
