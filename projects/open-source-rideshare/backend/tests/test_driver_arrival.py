"""Tests for GET /rides/{ride_id}/driver-arrival.

Coverage
--------
Pure-function unit tests:
  1.  _eta_minutes — standard distance
  2.  _eta_minutes — zero distance returns 1 minute
  3.  _eta_minutes — sub-minute distance returns 1 minute
  4.  _build_message — driver not assigned
  5.  _build_message — driver assigned, no GPS fix
  6.  _build_message — driver en route with GPS fix (distance + ETA)
  7.  _build_message — driver en route, ETA of exactly 1 minute (no plural)
  8.  _build_message — ride ARRIVED (post-pickup status)
  9.  _build_message — ride IN_PROGRESS (post-pickup status)
  10. _build_message — ride COMPLETED (post-pickup status)
  11. _build_message — ride CANCELLED (post-pickup status)

Service unit tests (mocked DB):
  12. get_driver_arrival — ValueError (ride not found)
  13. get_driver_arrival — PermissionError (wrong rider, non-admin)
  14. get_driver_arrival — admin bypasses ownership check
  15. get_driver_arrival — no driver assigned
  16. get_driver_arrival — driver assigned, no DriverProfile row (no GPS)
  17. get_driver_arrival — driver assigned, DriverProfile exists, lat/lng are None
  18. get_driver_arrival — driver en route with GPS fix: distance and ETA populated
  19. get_driver_arrival — verifies ETA formula at 25 km/h
  20. get_driver_arrival — ride COMPLETED still returns status and coordinates
  21. get_driver_arrival — message correct for en route with GPS
  22. get_driver_arrival — message correct for assigned but no GPS

API endpoint tests (mocked service):
  23. GET /rides/{id}/driver-arrival — 403 when caller is a driver role
  24. GET /rides/{id}/driver-arrival — 404 when ride not found (ValueError)
  25. GET /rides/{id}/driver-arrival — 404 when wrong rider (PermissionError)
"""

from __future__ import annotations

import math
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.ride import Ride, RideStatus
from app.schemas.driver_arrival import DriverArrivalResponse
from app.services.driver_arrival import (
    _SPEED_M_PER_MIN,
    _build_message,
    _eta_minutes,
    get_driver_arrival,
)

# ---------------------------------------------------------------------------
# Shared test coordinates
# ---------------------------------------------------------------------------

# Grand Central, NYC
_PICKUP_LAT, _PICKUP_LNG = 40.7527, -73.9772
# Times Square, NYC (~ 1 060 m via haversine)
_DRIVER_LAT, _DRIVER_LNG = 40.7580, -73.9855


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ride(
    id: int = 1,
    rider_id: int = 5,
    driver_id: int | None = 10,
    status: RideStatus = RideStatus.DRIVER_EN_ROUTE,
) -> MagicMock:
    ride = MagicMock(spec=Ride)
    ride.id = id
    ride.rider_id = rider_id
    ride.driver_id = driver_id
    ride.status = status
    return ride


def _one_or_none(value) -> MagicMock:
    m = MagicMock()
    m.one_or_none.return_value = value
    return m


def _profile_row(lat: float | None = _DRIVER_LAT, lng: float | None = _DRIVER_LNG) -> MagicMock:
    row = MagicMock()
    row.lat = lat
    row.lng = lng
    return row


# ---------------------------------------------------------------------------
# 1–3: _eta_minutes
# ---------------------------------------------------------------------------


class TestEtaMinutes:

    def test_standard_distance(self):
        """Test 1: 5000 m at 25 km/h = 12 minutes."""
        # 5000 m / (25000/60 m/min) = 12.0 → 12
        result = _eta_minutes(5000.0)
        expected = max(1, round(5000.0 / _SPEED_M_PER_MIN))
        assert result == expected

    def test_zero_distance_returns_one(self):
        """Test 2: zero distance → 1 minute minimum."""
        assert _eta_minutes(0.0) == 1

    def test_sub_minute_distance_returns_one(self):
        """Test 3: distance below one minute → 1 minute minimum."""
        # One minute covers 25000/60 ≈ 416 m.  Use 100 m.
        assert _eta_minutes(100.0) == 1


# ---------------------------------------------------------------------------
# 4–11: _build_message
# ---------------------------------------------------------------------------


class TestBuildMessage:

    def test_driver_not_assigned(self):
        """Test 4: no driver assigned → appropriate message."""
        msg = _build_message(RideStatus.REQUESTED, False, None, None)
        assert "not yet assigned" in msg.lower()

    def test_driver_assigned_no_gps(self):
        """Test 5: driver assigned but no GPS fix."""
        msg = _build_message(RideStatus.DRIVER_EN_ROUTE, True, None, None)
        assert "unavailable" in msg.lower()

    def test_driver_en_route_with_gps(self):
        """Test 6: driver en route with GPS → distance and ETA in message."""
        msg = _build_message(RideStatus.DRIVER_EN_ROUTE, True, 800.0, 2)
        assert "0.8 km" in msg
        assert "2 minutes" in msg

    def test_eta_one_minute_no_plural(self):
        """Test 7: ETA of exactly 1 minute uses singular 'minute'."""
        msg = _build_message(RideStatus.DRIVER_EN_ROUTE, True, 100.0, 1)
        assert "1 minute" in msg
        assert "minutes" not in msg

    def test_post_pickup_arrived(self):
        """Test 8: ARRIVED status shows ride status label."""
        msg = _build_message(RideStatus.ARRIVED, True, None, None)
        assert "arrived" in msg.lower()

    def test_post_pickup_in_progress(self):
        """Test 9: IN_PROGRESS status shows ride status label."""
        msg = _build_message(RideStatus.IN_PROGRESS, True, None, None)
        assert "in progress" in msg.lower()

    def test_post_pickup_completed(self):
        """Test 10: COMPLETED status shows ride status label."""
        msg = _build_message(RideStatus.COMPLETED, True, None, None)
        assert "completed" in msg.lower()

    def test_post_pickup_cancelled(self):
        """Test 11: CANCELLED status shows ride status label."""
        msg = _build_message(RideStatus.CANCELLED, True, None, None)
        assert "cancelled" in msg.lower()


# ---------------------------------------------------------------------------
# 12–22: Service unit tests (mocked DB)
# ---------------------------------------------------------------------------


class TestGetDriverArrivalService:

    @pytest.mark.asyncio
    async def test_ride_not_found_raises_value_error(self):
        """Test 12: ValueError when ride does not exist."""
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_one_or_none(None))
        with pytest.raises(ValueError, match="not found"):
            await get_driver_arrival(ride_id=99, caller_id=5, caller_is_admin=False, db=db)

    @pytest.mark.asyncio
    async def test_wrong_rider_raises_permission_error(self):
        """Test 13: PermissionError when caller is not the ride's rider."""
        ride = _make_ride(rider_id=5)
        row = (ride, _PICKUP_LAT, _PICKUP_LNG)
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_one_or_none(row))
        with pytest.raises(PermissionError):
            await get_driver_arrival(ride_id=1, caller_id=99, caller_is_admin=False, db=db)

    @pytest.mark.asyncio
    async def test_admin_bypasses_ownership_check(self):
        """Test 14: admin caller (different user id) can access any ride."""
        ride = _make_ride(rider_id=5, driver_id=None, status=RideStatus.REQUESTED)
        row = (ride, _PICKUP_LAT, _PICKUP_LNG)
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_one_or_none(row))
        result = await get_driver_arrival(
            ride_id=1, caller_id=999, caller_is_admin=True, db=db
        )
        assert result.ride_id == 1
        assert result.driver_assigned is False

    @pytest.mark.asyncio
    async def test_no_driver_assigned(self):
        """Test 15: ride with no driver returns driver_assigned=False and None coords."""
        ride = _make_ride(driver_id=None, status=RideStatus.REQUESTED)
        row = (ride, _PICKUP_LAT, _PICKUP_LNG)
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_one_or_none(row))
        result = await get_driver_arrival(
            ride_id=1, caller_id=5, caller_is_admin=False, db=db
        )
        assert result.driver_assigned is False
        assert result.driver_lat is None
        assert result.driver_lng is None
        assert result.distance_to_pickup_m is None
        assert result.eta_minutes is None
        assert "not yet assigned" in result.message.lower()

    @pytest.mark.asyncio
    async def test_driver_assigned_no_profile_row(self):
        """Test 16: driver assigned but DriverProfile row missing → no GPS data."""
        ride = _make_ride(driver_id=10, status=RideStatus.DRIVER_EN_ROUTE)
        row = (ride, _PICKUP_LAT, _PICKUP_LNG)
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _one_or_none(row),          # ride fetch
                _one_or_none(None),         # profile fetch → no row
            ]
        )
        result = await get_driver_arrival(
            ride_id=1, caller_id=5, caller_is_admin=False, db=db
        )
        assert result.driver_assigned is True
        assert result.driver_lat is None
        assert result.distance_to_pickup_m is None
        assert "unavailable" in result.message.lower()

    @pytest.mark.asyncio
    async def test_driver_profile_exists_but_lat_lng_none(self):
        """Test 17: profile exists but lat/lng are None (no GPS fix yet)."""
        ride = _make_ride(driver_id=10, status=RideStatus.DRIVER_EN_ROUTE)
        row = (ride, _PICKUP_LAT, _PICKUP_LNG)
        profile = _profile_row(lat=None, lng=None)
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _one_or_none(row),
                _one_or_none(profile),
            ]
        )
        result = await get_driver_arrival(
            ride_id=1, caller_id=5, caller_is_admin=False, db=db
        )
        assert result.driver_lat is None
        assert result.driver_lng is None
        assert result.distance_to_pickup_m is None
        assert result.eta_minutes is None
        assert "unavailable" in result.message.lower()

    @pytest.mark.asyncio
    async def test_driver_en_route_with_gps(self):
        """Test 18: driver en route with GPS fix → distance and ETA populated."""
        ride = _make_ride(driver_id=10, status=RideStatus.DRIVER_EN_ROUTE)
        row = (ride, _PICKUP_LAT, _PICKUP_LNG)
        profile = _profile_row(lat=_DRIVER_LAT, lng=_DRIVER_LNG)
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _one_or_none(row),
                _one_or_none(profile),
            ]
        )

        # Patch haversine_m to return a known value
        with patch(
            "app.services.driver_arrival.haversine_m", return_value=1060.0
        ):
            result = await get_driver_arrival(
                ride_id=1, caller_id=5, caller_is_admin=False, db=db
            )

        assert result.driver_assigned is True
        assert result.driver_lat == _DRIVER_LAT
        assert result.driver_lng == _DRIVER_LNG
        assert result.distance_to_pickup_m is not None
        assert result.distance_to_pickup_m > 0
        assert result.eta_minutes is not None
        assert result.eta_minutes >= 1

    @pytest.mark.asyncio
    async def test_eta_formula_matches_spec(self):
        """Test 19: ETA uses max(1, round(distance_m / (25000/60))) at 25 km/h."""
        ride = _make_ride(driver_id=10, status=RideStatus.DRIVER_EN_ROUTE)
        row = (ride, _PICKUP_LAT, _PICKUP_LNG)
        profile = _profile_row(lat=_DRIVER_LAT, lng=_DRIVER_LNG)
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _one_or_none(row),
                _one_or_none(profile),
            ]
        )

        injected_distance_m = 5000.0
        expected_eta = max(1, round(injected_distance_m / (25_000 / 60)))

        with patch(
            "app.services.driver_arrival.haversine_m", return_value=injected_distance_m
        ):
            result = await get_driver_arrival(
                ride_id=1, caller_id=5, caller_is_admin=False, db=db
            )

        assert result.eta_minutes == expected_eta

    @pytest.mark.asyncio
    async def test_completed_ride_returns_status(self):
        """Test 20: COMPLETED ride still returns current status string."""
        ride = _make_ride(driver_id=10, status=RideStatus.COMPLETED)
        row = (ride, _PICKUP_LAT, _PICKUP_LNG)
        profile = _profile_row(lat=_DRIVER_LAT, lng=_DRIVER_LNG)
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _one_or_none(row),
                _one_or_none(profile),
            ]
        )

        with patch("app.services.driver_arrival.haversine_m", return_value=200.0):
            result = await get_driver_arrival(
                ride_id=1, caller_id=5, caller_is_admin=False, db=db
            )

        assert result.status == "completed"
        # GPS coords still populated even post-completion
        assert result.driver_lat == _DRIVER_LAT
        assert result.driver_lng == _DRIVER_LNG
        assert "completed" in result.message.lower()

    @pytest.mark.asyncio
    async def test_message_en_route_with_gps(self):
        """Test 21: message contains km distance and minutes for en-route ride."""
        ride = _make_ride(driver_id=10, status=RideStatus.DRIVER_EN_ROUTE)
        row = (ride, _PICKUP_LAT, _PICKUP_LNG)
        profile = _profile_row(lat=_DRIVER_LAT, lng=_DRIVER_LNG)
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _one_or_none(row),
                _one_or_none(profile),
            ]
        )

        with patch("app.services.driver_arrival.haversine_m", return_value=800.0):
            result = await get_driver_arrival(
                ride_id=1, caller_id=5, caller_is_admin=False, db=db
            )

        assert "0.8 km" in result.message
        assert "minute" in result.message

    @pytest.mark.asyncio
    async def test_message_assigned_no_gps(self):
        """Test 22: message says location unavailable when driver assigned but no fix."""
        ride = _make_ride(driver_id=10, status=RideStatus.DRIVER_EN_ROUTE)
        row = (ride, _PICKUP_LAT, _PICKUP_LNG)
        profile = _profile_row(lat=None, lng=None)
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _one_or_none(row),
                _one_or_none(profile),
            ]
        )
        result = await get_driver_arrival(
            ride_id=1, caller_id=5, caller_is_admin=False, db=db
        )
        assert "unavailable" in result.message.lower()


# ---------------------------------------------------------------------------
# 23–25: API endpoint tests
# ---------------------------------------------------------------------------


class TestDriverArrivalAPI:
    """Lightweight tests that mock the service layer and test the router logic."""

    @pytest.mark.asyncio
    async def test_driver_role_gets_403(self):
        """Test 23: driver-role caller receives 403 Forbidden."""
        from fastapi.testclient import TestClient
        from unittest.mock import patch, AsyncMock
        from app.main import app
        from app.models.user import User, UserRole
        from app.api.deps import get_current_user, get_db

        driver_user = MagicMock(spec=User)
        driver_user.id = 10
        driver_user.role = UserRole.DRIVER
        driver_user.is_active = True

        async def override_user():
            return driver_user

        async def override_db():
            yield AsyncMock()

        app.dependency_overrides[get_current_user] = override_user
        app.dependency_overrides[get_db] = override_db

        try:
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get("/api/v1/rides/1/driver-arrival")
            assert resp.status_code == 403
        finally:
            app.dependency_overrides.pop(get_current_user, None)
            app.dependency_overrides.pop(get_db, None)

    @pytest.mark.asyncio
    async def test_ride_not_found_returns_404(self):
        """Test 24: ValueError from service → 404 Not Found."""
        from fastapi.testclient import TestClient
        from app.main import app
        from app.models.user import User, UserRole
        from app.api.deps import get_current_user, get_db
        import app.api.v1.driver_arrival as router_module

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
            with patch.object(router_module, "get_driver_arrival", side_effect=mock_service):
                client = TestClient(app, raise_server_exceptions=False)
                resp = client.get("/api/v1/rides/9999/driver-arrival")
                assert resp.status_code == 404
        finally:
            app.dependency_overrides.pop(get_current_user, None)
            app.dependency_overrides.pop(get_db, None)

    @pytest.mark.asyncio
    async def test_wrong_rider_returns_404(self):
        """Test 25: PermissionError from service → 404 (hides existence from other riders)."""
        from fastapi.testclient import TestClient
        from app.main import app
        from app.models.user import User, UserRole
        from app.api.deps import get_current_user, get_db
        import app.api.v1.driver_arrival as router_module

        rider_user = MagicMock(spec=User)
        rider_user.id = 99
        rider_user.role = UserRole.RIDER
        rider_user.is_active = True

        async def override_user():
            return rider_user

        async def override_db():
            yield AsyncMock()

        async def mock_service(*args, **kwargs):
            raise PermissionError("Not authorised")

        app.dependency_overrides[get_current_user] = override_user
        app.dependency_overrides[get_db] = override_db

        try:
            with patch.object(router_module, "get_driver_arrival", side_effect=mock_service):
                client = TestClient(app, raise_server_exceptions=False)
                resp = client.get("/api/v1/rides/1/driver-arrival")
                assert resp.status_code == 404
        finally:
            app.dependency_overrides.pop(get_current_user, None)
            app.dependency_overrides.pop(get_db, None)
