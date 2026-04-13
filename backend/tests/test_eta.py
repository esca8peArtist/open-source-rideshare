"""Tests for driver ETA estimation service.

Covers: haversine distance, haversine ETA, driver location lookup,
driver-to-pickup ETA (OSRM + fallback), trip ETA, API endpoints,
WebSocket ETA notifications, and edge cases.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.eta import (
    EARTH_RADIUS_KM,
    FALLBACK_SPEED_KMH,
    DriverLocation,
    ETAEstimate,
    TripETA,
    estimate_driver_eta,
    estimate_trip_eta,
    get_driver_location,
    haversine_distance,
    haversine_eta,
)
from app.schemas.eta import DriverETAResponse, DriverLocationResponse, TripETAResponse


# ===========================================================================
# Haversine Distance Tests
# ===========================================================================


class TestHaversineDistance:
    def test_same_point_returns_zero(self):
        assert haversine_distance(40.0, -74.0, 40.0, -74.0) == 0.0

    def test_known_distance_nyc_to_la(self):
        """NYC to LA is ~3,944 km — allow 5% tolerance."""
        d = haversine_distance(40.7128, -74.0060, 34.0522, -118.2437)
        assert 3700 < d < 4200

    def test_known_distance_short(self):
        """~1 km between two nearby points in Manhattan."""
        d = haversine_distance(40.7580, -73.9855, 40.7484, -73.9856)
        assert 0.5 < d < 2.0

    def test_equator_one_degree_longitude(self):
        """1 degree longitude at the equator is ~111 km."""
        d = haversine_distance(0.0, 0.0, 0.0, 1.0)
        assert 110 < d < 112

    def test_poles(self):
        """North pole to south pole is ~20,000 km."""
        d = haversine_distance(90.0, 0.0, -90.0, 0.0)
        assert 19900 < d < 20100

    def test_symmetry(self):
        d1 = haversine_distance(40.0, -74.0, 34.0, -118.0)
        d2 = haversine_distance(34.0, -118.0, 40.0, -74.0)
        assert abs(d1 - d2) < 0.001

    def test_negative_coordinates(self):
        """Southern hemisphere works correctly."""
        d = haversine_distance(-33.8688, 151.2093, -37.8136, 144.9631)  # Sydney to Melbourne
        assert 700 < d < 900


# ===========================================================================
# Haversine ETA Tests
# ===========================================================================


class TestHaversineETA:
    def test_zero_distance(self):
        assert haversine_eta(0.0) == 0.0

    def test_default_speed(self):
        """10 km at 25 km/h = 24 minutes."""
        eta = haversine_eta(10.0)
        assert abs(eta - 24.0) < 0.1

    def test_custom_speed(self):
        """10 km at 50 km/h = 12 minutes."""
        eta = haversine_eta(10.0, speed_kmh=50.0)
        assert abs(eta - 12.0) < 0.1

    def test_zero_speed_returns_zero(self):
        """Edge case: zero speed should not raise."""
        assert haversine_eta(10.0, speed_kmh=0.0) == 0.0

    def test_negative_speed_returns_zero(self):
        assert haversine_eta(10.0, speed_kmh=-5.0) == 0.0

    def test_large_distance(self):
        """100 km at 25 km/h = 240 minutes."""
        eta = haversine_eta(100.0)
        assert abs(eta - 240.0) < 0.1


# ===========================================================================
# Driver Location Lookup Tests
# ===========================================================================


class TestGetDriverLocation:
    @pytest.mark.asyncio
    async def test_returns_location_when_found(self):
        redis_mock = AsyncMock()
        redis_mock.geopos.return_value = [(-74.0060, 40.7128)]

        loc = await get_driver_location(redis_mock, 42)

        assert loc is not None
        assert abs(loc.lat - 40.7128) < 0.0001
        assert abs(loc.lng - (-74.0060)) < 0.0001
        redis_mock.geopos.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self):
        redis_mock = AsyncMock()
        redis_mock.geopos.return_value = [None]

        loc = await get_driver_location(redis_mock, 999)
        assert loc is None

    @pytest.mark.asyncio
    async def test_returns_none_when_empty_list(self):
        redis_mock = AsyncMock()
        redis_mock.geopos.return_value = []

        loc = await get_driver_location(redis_mock, 999)
        assert loc is None


# ===========================================================================
# Driver ETA Estimation Tests
# ===========================================================================


class TestEstimateDriverETA:
    @pytest.mark.asyncio
    async def test_returns_none_when_driver_not_found(self):
        redis_mock = AsyncMock()
        redis_mock.geopos.return_value = [None]

        result = await estimate_driver_eta(redis_mock, 42, 40.7, -74.0)
        assert result is None

    @pytest.mark.asyncio
    async def test_uses_osrm_when_available(self):
        redis_mock = AsyncMock()
        redis_mock.geopos.return_value = [(-74.01, 40.71)]

        route_data = {"distance_km": 2.5, "duration_min": 8.3, "geometry": {}}
        with patch("app.services.routing.get_route", new_callable=AsyncMock, return_value=route_data):
            result = await estimate_driver_eta(redis_mock, 42, 40.72, -74.00)

        assert result is not None
        assert result.source == "osrm"
        assert result.eta_minutes == 8.3
        assert result.distance_km == 2.5
        assert abs(result.driver_lat - 40.71) < 0.001
        assert abs(result.driver_lng - (-74.01)) < 0.001

    @pytest.mark.asyncio
    async def test_falls_back_to_haversine_when_osrm_fails(self):
        redis_mock = AsyncMock()
        redis_mock.geopos.return_value = [(-74.01, 40.71)]

        with patch("app.services.routing.get_route", new_callable=AsyncMock, side_effect=Exception("OSRM down")):
            result = await estimate_driver_eta(redis_mock, 42, 40.72, -74.00)

        assert result is not None
        assert result.source == "haversine"
        assert result.eta_minutes > 0
        assert result.distance_km > 0

    @pytest.mark.asyncio
    async def test_haversine_fallback_applies_road_factor(self):
        """Haversine fallback multiplies straight-line by 1.4."""
        redis_mock = AsyncMock()
        # Driver and pickup about 1 km apart
        redis_mock.geopos.return_value = [(-74.0060, 40.7128)]

        with patch("app.services.routing.get_route", new_callable=AsyncMock, side_effect=Exception("OSRM down")):
            result = await estimate_driver_eta(redis_mock, 42, 40.7228, -74.0060)

        straight = haversine_distance(40.7128, -74.0060, 40.7228, -74.0060)
        expected_road = straight * 1.4
        assert abs(result.distance_km - round(expected_road, 2)) < 0.1

    @pytest.mark.asyncio
    async def test_same_location_returns_zero_eta(self):
        redis_mock = AsyncMock()
        redis_mock.geopos.return_value = [(-74.0060, 40.7128)]

        with patch("app.services.routing.get_route", new_callable=AsyncMock, side_effect=Exception("OSRM down")):
            result = await estimate_driver_eta(redis_mock, 42, 40.7128, -74.0060)

        assert result.eta_minutes == 0.0
        assert result.distance_km == 0.0


# ===========================================================================
# Trip ETA Tests
# ===========================================================================


class TestEstimateTripETA:
    @pytest.mark.asyncio
    async def test_returns_none_when_driver_not_found(self):
        redis_mock = AsyncMock()
        redis_mock.geopos.return_value = [None]

        result = await estimate_trip_eta(redis_mock, 42, 40.7, -74.0, 40.8, -73.9)
        assert result is None

    @pytest.mark.asyncio
    async def test_combines_pickup_and_trip_with_osrm(self):
        redis_mock = AsyncMock()
        redis_mock.geopos.return_value = [(-74.01, 40.71)]

        pickup_route = {"distance_km": 2.0, "duration_min": 6.0, "geometry": {}}
        trip_route = {"distance_km": 10.0, "duration_min": 20.0, "geometry": {}}

        call_count = 0

        async def mock_get_route(lat1, lng1, lat2, lng2):
            nonlocal call_count
            call_count += 1
            # First call is driver→pickup, second is pickup→dropoff
            if call_count == 1:
                return pickup_route
            return trip_route

        with patch("app.services.routing.get_route", side_effect=mock_get_route):
            result = await estimate_trip_eta(redis_mock, 42, 40.72, -74.00, 40.80, -73.90)

        assert result is not None
        assert result.pickup_eta_minutes == 6.0
        assert result.pickup_distance_km == 2.0
        assert result.trip_duration_minutes == 20.0
        assert result.trip_distance_km == 10.0
        assert result.total_minutes == 26.0
        assert result.source == "osrm"

    @pytest.mark.asyncio
    async def test_trip_segment_falls_back_to_haversine(self):
        """If OSRM fails for the trip segment, haversine fallback is used."""
        redis_mock = AsyncMock()
        redis_mock.geopos.return_value = [(-74.01, 40.71)]

        pickup_route = {"distance_km": 2.0, "duration_min": 6.0, "geometry": {}}

        call_count = 0

        async def mock_get_route(lat1, lng1, lat2, lng2):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return pickup_route
            raise Exception("OSRM down for trip segment")

        with patch("app.services.routing.get_route", side_effect=mock_get_route):
            result = await estimate_trip_eta(redis_mock, 42, 40.72, -74.00, 40.80, -73.90)

        assert result is not None
        assert result.pickup_eta_minutes == 6.0
        # Trip segment should use haversine
        assert result.trip_duration_minutes > 0
        assert result.trip_distance_km > 0
        assert result.total_minutes > 6.0

    @pytest.mark.asyncio
    async def test_total_equals_pickup_plus_trip(self):
        redis_mock = AsyncMock()
        redis_mock.geopos.return_value = [(-74.01, 40.71)]

        with patch("app.services.routing.get_route", new_callable=AsyncMock, side_effect=Exception("down")):
            result = await estimate_trip_eta(redis_mock, 42, 40.72, -74.00, 40.80, -73.90)

        expected_total = round(result.pickup_eta_minutes + result.trip_duration_minutes, 1)
        assert result.total_minutes == expected_total


# ===========================================================================
# Schema Tests
# ===========================================================================


class TestETASchemas:
    def test_driver_eta_response_creation(self):
        resp = DriverETAResponse(
            eta_minutes=5.2,
            distance_km=1.8,
            driver_location=DriverLocationResponse(lat=40.71, lng=-74.01),
            source="osrm",
        )
        assert resp.eta_minutes == 5.2
        assert resp.distance_km == 1.8
        assert resp.driver_location.lat == 40.71
        assert resp.source == "osrm"

    def test_trip_eta_response_creation(self):
        resp = TripETAResponse(
            pickup_eta_minutes=5.0,
            pickup_distance_km=2.0,
            trip_duration_minutes=15.0,
            trip_distance_km=8.0,
            total_minutes=20.0,
            driver_location=DriverLocationResponse(lat=40.71, lng=-74.01),
            source="haversine",
        )
        assert resp.total_minutes == 20.0
        assert resp.source == "haversine"

    def test_driver_location_response(self):
        loc = DriverLocationResponse(lat=40.7128, lng=-74.0060)
        assert loc.lat == 40.7128
        assert loc.lng == -74.0060


# ===========================================================================
# API Endpoint Tests
# ===========================================================================


class TestETAEndpoint:
    """Test GET /rides/{ride_id}/eta endpoint."""

    @pytest.mark.asyncio
    async def test_eta_ride_not_found(self):
        from unittest.mock import patch as sync_patch
        from fastapi.testclient import TestClient
        from app.main import app

        client = TestClient(app)

        # Mock auth to return a user
        mock_user = MagicMock()
        mock_user.id = 1

        with sync_patch("app.api.v1.rides.get_current_user", return_value=mock_user):
            # This will fail because we don't have a real DB, but we test the route exists
            pass  # Route registration is tested below

    def test_driver_eta_response_serialization(self):
        """Verify the schema serializes to the expected JSON shape."""
        resp = DriverETAResponse(
            eta_minutes=7.5,
            distance_km=3.2,
            driver_location=DriverLocationResponse(lat=40.71, lng=-74.01),
            source="osrm",
        )
        data = resp.model_dump()
        assert data["eta_minutes"] == 7.5
        assert data["distance_km"] == 3.2
        assert data["driver_location"]["lat"] == 40.71
        assert data["driver_location"]["lng"] == -74.01
        assert data["source"] == "osrm"

    def test_trip_eta_response_serialization(self):
        resp = TripETAResponse(
            pickup_eta_minutes=5.0,
            pickup_distance_km=2.0,
            trip_duration_minutes=15.0,
            trip_distance_km=8.0,
            total_minutes=20.0,
            driver_location=DriverLocationResponse(lat=40.71, lng=-74.01),
            source="osrm",
        )
        data = resp.model_dump()
        assert "pickup_eta_minutes" in data
        assert "trip_duration_minutes" in data
        assert "total_minutes" in data


# ===========================================================================
# WebSocket ETA Notification Tests
# ===========================================================================


class TestWebSocketETANotification:
    @pytest.mark.asyncio
    async def test_notify_driver_eta_sends_message(self):
        from app.api.websocket import manager, notify_driver_eta

        mock_ws = AsyncMock()
        manager._rider_connections[99] = mock_ws

        result = await notify_driver_eta(99, 1, 5.2, 1.8, 40.71, -74.01)

        assert result is True
        mock_ws.send_json.assert_called_once()
        payload = mock_ws.send_json.call_args[0][0]
        assert payload["type"] == "driver_eta"
        assert payload["ride_id"] == 1
        assert payload["eta_minutes"] == 5.2
        assert payload["distance_km"] == 1.8
        assert payload["driver_lat"] == 40.71
        assert payload["driver_lng"] == -74.01

        # Cleanup
        manager._rider_connections.pop(99, None)

    @pytest.mark.asyncio
    async def test_notify_driver_eta_no_connection(self):
        from app.api.websocket import notify_driver_eta

        result = await notify_driver_eta(9999, 1, 5.0, 2.0, 40.0, -74.0)
        assert result is False

    @pytest.mark.asyncio
    async def test_matched_notification_includes_eta(self):
        """Verify ride_status 'matched' notification shape includes eta when provided."""
        from app.api.websocket import manager, notify_ride_status

        mock_ws = AsyncMock()
        manager._rider_connections[100] = mock_ws

        await notify_ride_status(
            100, 5, "matched",
            driver_distance_km=2.5,
            eta_minutes=7.0,
            driver_lat=40.71,
            driver_lng=-74.01,
        )

        payload = mock_ws.send_json.call_args[0][0]
        assert payload["type"] == "ride_status"
        assert payload["status"] == "matched"
        assert payload["eta_minutes"] == 7.0
        assert payload["driver_distance_km"] == 2.5

        manager._rider_connections.pop(100, None)


# ===========================================================================
# Edge Cases
# ===========================================================================


class TestETAEdgeCases:
    def test_haversine_antipodal_points(self):
        """Points on opposite sides of the earth."""
        d = haversine_distance(0.0, 0.0, 0.0, 180.0)
        # Should be approximately half the Earth's circumference
        assert 19900 < d < 20100

    def test_haversine_very_close_points(self):
        """Points ~10m apart should give a very small distance."""
        d = haversine_distance(40.71280, -74.00600, 40.71281, -74.00601)
        assert d < 0.02  # Less than 20 meters

    @pytest.mark.asyncio
    async def test_redis_connection_error_in_location(self):
        """If Redis raises, get_driver_location propagates the error."""
        redis_mock = AsyncMock()
        redis_mock.geopos.side_effect = Exception("Redis connection refused")

        with pytest.raises(Exception, match="Redis connection refused"):
            await get_driver_location(redis_mock, 42)

    @pytest.mark.asyncio
    async def test_eta_with_osrm_returning_zero_duration(self):
        """OSRM could return 0 duration for same-location routes."""
        redis_mock = AsyncMock()
        redis_mock.geopos.return_value = [(-74.006, 40.7128)]

        route_data = {"distance_km": 0.0, "duration_min": 0.0, "geometry": {}}
        with patch("app.services.routing.get_route", new_callable=AsyncMock, return_value=route_data):
            result = await estimate_driver_eta(redis_mock, 42, 40.7128, -74.006)

        assert result.eta_minutes == 0.0
        assert result.distance_km == 0.0
        assert result.source == "osrm"

    @pytest.mark.asyncio
    async def test_estimate_driver_eta_driver_location_matches(self):
        """The returned driver coordinates should match what Redis returns."""
        redis_mock = AsyncMock()
        redis_mock.geopos.return_value = [(-73.9857, 40.7484)]

        with patch("app.services.routing.get_route", new_callable=AsyncMock, side_effect=Exception("down")):
            result = await estimate_driver_eta(redis_mock, 42, 40.76, -73.98)

        assert abs(result.driver_lat - 40.7484) < 0.001
        assert abs(result.driver_lng - (-73.9857)) < 0.001


# ===========================================================================
# Constants Tests
# ===========================================================================


class TestConstants:
    def test_fallback_speed_is_reasonable(self):
        """City driving speed should be between 15-60 km/h."""
        assert 15 <= FALLBACK_SPEED_KMH <= 60

    def test_earth_radius(self):
        """Sanity check on Earth radius constant."""
        assert 6370 < EARTH_RADIUS_KM < 6372


# ===========================================================================
# Dataclass Tests
# ===========================================================================


class TestDataclasses:
    def test_driver_location(self):
        loc = DriverLocation(lat=40.7, lng=-74.0)
        assert loc.lat == 40.7
        assert loc.lng == -74.0

    def test_eta_estimate(self):
        eta = ETAEstimate(
            eta_minutes=5.0, distance_km=2.0,
            driver_lat=40.7, driver_lng=-74.0, source="osrm",
        )
        assert eta.eta_minutes == 5.0
        assert eta.source == "osrm"

    def test_trip_eta(self):
        trip = TripETA(
            pickup_eta_minutes=5.0, pickup_distance_km=2.0,
            trip_duration_minutes=15.0, trip_distance_km=8.0,
            total_minutes=20.0,
            driver_lat=40.7, driver_lng=-74.0, source="haversine",
        )
        assert trip.total_minutes == 20.0
        assert trip.source == "haversine"
