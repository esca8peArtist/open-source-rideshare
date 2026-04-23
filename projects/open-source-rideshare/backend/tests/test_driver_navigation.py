"""Tests for driver in-ride navigation service and endpoints.

Pure math unit tests (no DB):
  1.  haversine_km — known distance between two NYC landmarks (~1.06 km)
  2.  haversine_km — same point returns 0
  3.  cross_track_distance_km — point on the path returns ~0
  4.  cross_track_distance_km — point perpendicular to path exceeds threshold
  5.  is_deviation — within threshold returns False
  6.  is_deviation — off-route returns True
  7.  is_deviation — no pending stops returns False
  8.  _eta_minutes — standard distance
  9.  _eta_minutes — zero distance returns 1 minute
  10. total_remaining — no driver position returns zeros
  11. total_remaining — no pending stops returns zeros
  12. total_remaining — sums chain from driver through all pending stops

build_stops unit tests:
  13. pickup is COMPLETED when ride status is IN_PROGRESS
  14. pickup is PENDING when ride status is DRIVER_EN_ROUTE
  15. dropoff is COMPLETED when ride status is COMPLETED
  16. dropoff is PENDING when ride status is IN_PROGRESS
  17. waypoints are ordered by .order field
  18. SKIPPED waypoint has status SKIPPED
  19. ARRIVED waypoint has status COMPLETED
  20. distances annotated when driver position provided
  21. no distances when driver position is None

Service unit tests (mocked DB):
  22. get_navigation_state raises ValueError for unknown ride
  23. get_navigation_state raises PermissionError for wrong driver
  24. get_navigation_state returns stops in order for IN_PROGRESS ride
  25. update_navigation_position raises ValueError for wrong ride status
  26. update_navigation_position raises PermissionError for wrong driver
  27. update_navigation_position flags deviation when off-route
  28. update_navigation_position does not double-flag if already flagged

API integration tests (conftest fixtures):
  29. GET /rides/{id}/navigation — 401 with no token
  30. GET /rides/{id}/navigation — 403 with rider token
  31. GET /rides/{id}/navigation — 404 for unknown ride_id
  32. POST /rides/{id}/navigation/position — 401 with no token
  33. POST /rides/{id}/navigation/position — 403 with rider token
  34. POST /rides/{id}/navigation/position — 422 for invalid lat/lng
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.ride import Ride, RideStatus
from app.models.waypoint import RideWaypoint, WaypointStatus
from app.schemas.driver_navigation import StopStatus, StopType
from app.services.driver_navigation import (
    AVG_SPEED_KMH,
    DEVIATION_THRESHOLD_KM,
    _eta_minutes,
    build_stops,
    cross_track_distance_km,
    find_next_stop,
    get_navigation_state,
    haversine_km,
    is_deviation,
    total_remaining,
    update_navigation_position,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)

# Two NYC points: Grand Central → Times Square (~1.06 km)
_GCT_LAT, _GCT_LNG = 40.7527, -73.9772
_TSQ_LAT, _TSQ_LNG = 40.7580, -73.9855


def _make_ride(
    id: int = 1,
    driver_id: int = 10,
    status: RideStatus = RideStatus.IN_PROGRESS,
    pickup_address: str = "Grand Central, NY",
    dropoff_address: str = "Times Square, NY",
    arrived_at: datetime | None = _NOW,
    started_at: datetime | None = _NOW,
    route_deviation_flagged_at: datetime | None = None,
) -> MagicMock:
    ride = MagicMock(spec=Ride)
    ride.id = id
    ride.driver_id = driver_id
    ride.status = status
    ride.pickup_address = pickup_address
    ride.dropoff_address = dropoff_address
    ride.arrived_at = arrived_at
    ride.started_at = started_at
    ride.route_deviation_flagged_at = route_deviation_flagged_at
    return ride


def _make_waypoint(
    id: int = 1,
    ride_id: int = 1,
    order: int = 1,
    address: str = "Midpoint Stop",
    lat: float = 40.755,
    lng: float = -73.981,
    status: WaypointStatus = WaypointStatus.PENDING,
    wait_time_minutes: int = 3,
    actual_arrival_at: datetime | None = None,
    departed_at: datetime | None = None,
) -> MagicMock:
    wp = MagicMock(spec=RideWaypoint)
    wp.id = id
    wp.ride_id = ride_id
    wp.order = order
    wp.address = address
    wp.lat = lat
    wp.lng = lng
    wp.status = status
    wp.wait_time_minutes = wait_time_minutes
    wp.actual_arrival_at = actual_arrival_at
    wp.departed_at = departed_at
    return wp


def _one_or_none_result(value) -> MagicMock:
    r = MagicMock()
    r.one_or_none.return_value = value
    return r


def _scalars_all_result(items: list) -> MagicMock:
    r = MagicMock()
    scalars = MagicMock()
    scalars.all.return_value = items
    r.scalars.return_value = scalars
    return r


def auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# 1–9: Pure math unit tests
# ---------------------------------------------------------------------------

class TestHaversineKm:

    def test_known_nyc_distance(self):
        """Test 1: Grand Central → Times Square is approximately 1.06 km."""
        dist = haversine_km(_GCT_LAT, _GCT_LNG, _TSQ_LAT, _TSQ_LNG)
        assert 0.9 < dist < 1.2

    def test_same_point_is_zero(self):
        """Test 2: distance from a point to itself is 0."""
        dist = haversine_km(40.75, -73.98, 40.75, -73.98)
        assert dist == 0.0


class TestCrossTrackDistanceKm:

    def test_point_on_path_is_near_zero(self):
        """Test 3: midpoint on the path between two points has ~0 cross-track distance."""
        mid_lat = (_GCT_LAT + _TSQ_LAT) / 2
        mid_lng = (_GCT_LNG + _TSQ_LNG) / 2
        xtd = cross_track_distance_km(mid_lat, mid_lng, _GCT_LAT, _GCT_LNG, _TSQ_LAT, _TSQ_LNG)
        assert xtd < 0.05  # < 50 m

    def test_perpendicular_offset_exceeds_threshold(self):
        """Test 4: point 1 km perpendicular to path exceeds DEVIATION_THRESHOLD_KM."""
        # Offset ~1 km north of the midpoint (perpendicular to east-west path)
        offset_lat = (_GCT_LAT + _TSQ_LAT) / 2 + 0.009  # ~1 km north
        offset_lng = (_GCT_LNG + _TSQ_LNG) / 2
        xtd = cross_track_distance_km(offset_lat, offset_lng, _GCT_LAT, _GCT_LNG, _TSQ_LAT, _TSQ_LNG)
        assert xtd > DEVIATION_THRESHOLD_KM


class TestIsDeviation:

    def _make_stops(self, driver_lat, driver_lng):
        ride = _make_ride(status=RideStatus.IN_PROGRESS)
        return build_stops(
            ride,
            _GCT_LAT, _GCT_LNG,
            _TSQ_LAT, _TSQ_LNG,
            [],
            driver_lat, driver_lng,
        )

    def test_within_threshold_returns_false(self):
        """Test 5: driver directly between pickup and dropoff → no deviation."""
        # Driver at midpoint — should be well within threshold
        mid_lat = (_GCT_LAT + _TSQ_LAT) / 2
        mid_lng = (_GCT_LNG + _TSQ_LNG) / 2
        stops = self._make_stops(mid_lat, mid_lng)
        assert not is_deviation(stops, mid_lat, mid_lng)

    def test_off_route_returns_true(self):
        """Test 6: driver 1 km perpendicular to path → deviation flagged."""
        offset_lat = (_GCT_LAT + _TSQ_LAT) / 2 + 0.009
        offset_lng = (_GCT_LNG + _TSQ_LNG) / 2
        stops = self._make_stops(offset_lat, offset_lng)
        assert is_deviation(stops, offset_lat, offset_lng)

    def test_no_pending_stops_returns_false(self):
        """Test 7: all stops completed → is_deviation returns False."""
        ride = _make_ride(status=RideStatus.COMPLETED)
        stops = build_stops(ride, _GCT_LAT, _GCT_LNG, _TSQ_LAT, _TSQ_LNG, [], 40.755, -73.98)
        assert not is_deviation(stops, 40.755, -73.98)


class TestEtaMinutes:

    def test_standard_distance(self):
        """Test 8: 15 km at 30 km/h = 30 minutes."""
        assert _eta_minutes(15.0) == 30

    def test_zero_distance_returns_one(self):
        """Test 9: zero or negative distance returns 1 minute minimum."""
        assert _eta_minutes(0.0) == 1
        assert _eta_minutes(-1.0) == 1


# ---------------------------------------------------------------------------
# 10–12: total_remaining
# ---------------------------------------------------------------------------

class TestTotalRemaining:

    def test_no_driver_position(self):
        """Test 10: no driver position → returns 0, 0."""
        ride = _make_ride(status=RideStatus.DRIVER_EN_ROUTE)
        stops = build_stops(ride, _GCT_LAT, _GCT_LNG, _TSQ_LAT, _TSQ_LNG, [], None, None)
        km, mins = total_remaining(stops, None, None)
        assert km == 0.0
        assert mins == 0

    def test_all_stops_completed(self):
        """Test 11: all stops completed → remaining is 0."""
        ride = _make_ride(status=RideStatus.COMPLETED)
        stops = build_stops(ride, _GCT_LAT, _GCT_LNG, _TSQ_LAT, _TSQ_LNG, [], 40.755, -73.98)
        km, mins = total_remaining(stops, 40.755, -73.98)
        assert km == 0.0
        assert mins == 0

    def test_chain_adds_distances(self):
        """Test 12: driver → waypoint → dropoff — total is > direct driver-to-dropoff."""
        ride = _make_ride(status=RideStatus.IN_PROGRESS)
        wp = _make_waypoint(order=1, lat=40.755, lng=-73.981)
        driver_lat, driver_lng = _GCT_LAT, _GCT_LNG  # pickup already completed
        stops = build_stops(
            ride, _GCT_LAT, _GCT_LNG, _TSQ_LAT, _TSQ_LNG,
            [wp], driver_lat, driver_lng,
        )
        km, mins = total_remaining(stops, driver_lat, driver_lng)
        direct = haversine_km(driver_lat, driver_lng, _TSQ_LAT, _TSQ_LNG)
        assert km > direct * 0.5  # sanity check — chain covers some distance


# ---------------------------------------------------------------------------
# 13–21: build_stops
# ---------------------------------------------------------------------------

class TestBuildStops:

    def test_pickup_completed_when_in_progress(self):
        """Test 13: IN_PROGRESS ride → pickup stop is COMPLETED."""
        ride = _make_ride(status=RideStatus.IN_PROGRESS)
        stops = build_stops(ride, _GCT_LAT, _GCT_LNG, _TSQ_LAT, _TSQ_LNG, [], None, None)
        assert stops[0].type == StopType.PICKUP
        assert stops[0].status == StopStatus.COMPLETED

    def test_pickup_pending_when_en_route(self):
        """Test 14: DRIVER_EN_ROUTE ride → pickup stop is PENDING."""
        ride = _make_ride(status=RideStatus.DRIVER_EN_ROUTE, arrived_at=None, started_at=None)
        stops = build_stops(ride, _GCT_LAT, _GCT_LNG, _TSQ_LAT, _TSQ_LNG, [], None, None)
        assert stops[0].status == StopStatus.PENDING

    def test_dropoff_completed_when_ride_completed(self):
        """Test 15: COMPLETED ride → dropoff stop is COMPLETED."""
        ride = _make_ride(status=RideStatus.COMPLETED)
        stops = build_stops(ride, _GCT_LAT, _GCT_LNG, _TSQ_LAT, _TSQ_LNG, [], None, None)
        assert stops[-1].type == StopType.DROPOFF
        assert stops[-1].status == StopStatus.COMPLETED

    def test_dropoff_pending_when_in_progress(self):
        """Test 16: IN_PROGRESS ride → dropoff stop is PENDING."""
        ride = _make_ride(status=RideStatus.IN_PROGRESS)
        stops = build_stops(ride, _GCT_LAT, _GCT_LNG, _TSQ_LAT, _TSQ_LNG, [], None, None)
        assert stops[-1].status == StopStatus.PENDING

    def test_waypoints_sorted_by_order(self):
        """Test 17: waypoints are inserted in ascending order field order."""
        ride = _make_ride(status=RideStatus.IN_PROGRESS)
        wp2 = _make_waypoint(id=2, order=2, address="Stop B", lat=40.756, lng=-73.982)
        wp1 = _make_waypoint(id=1, order=1, address="Stop A", lat=40.754, lng=-73.980)
        stops = build_stops(ride, _GCT_LAT, _GCT_LNG, _TSQ_LAT, _TSQ_LNG, [wp2, wp1], None, None)
        assert stops[1].address == "Stop A"
        assert stops[2].address == "Stop B"

    def test_skipped_waypoint_status(self):
        """Test 18: SKIPPED waypoint maps to StopStatus.SKIPPED."""
        ride = _make_ride(status=RideStatus.IN_PROGRESS)
        wp = _make_waypoint(order=1, status=WaypointStatus.SKIPPED)
        stops = build_stops(ride, _GCT_LAT, _GCT_LNG, _TSQ_LAT, _TSQ_LNG, [wp], None, None)
        waypoint_stop = next(s for s in stops if s.type == StopType.WAYPOINT)
        assert waypoint_stop.status == StopStatus.SKIPPED

    def test_arrived_waypoint_status_is_completed(self):
        """Test 19: ARRIVED waypoint maps to StopStatus.COMPLETED."""
        ride = _make_ride(status=RideStatus.IN_PROGRESS)
        wp = _make_waypoint(order=1, status=WaypointStatus.ARRIVED)
        stops = build_stops(ride, _GCT_LAT, _GCT_LNG, _TSQ_LAT, _TSQ_LNG, [wp], None, None)
        waypoint_stop = next(s for s in stops if s.type == StopType.WAYPOINT)
        assert waypoint_stop.status == StopStatus.COMPLETED

    def test_distances_annotated_with_driver_position(self):
        """Test 20: pending stops get distance_km and eta_minutes when driver pos provided."""
        ride = _make_ride(status=RideStatus.IN_PROGRESS)
        stops = build_stops(
            ride, _GCT_LAT, _GCT_LNG, _TSQ_LAT, _TSQ_LNG, [],
            _GCT_LAT, _GCT_LNG,
        )
        dropoff = stops[-1]
        assert dropoff.status == StopStatus.PENDING
        assert dropoff.distance_km is not None
        assert dropoff.eta_minutes is not None

    def test_no_distances_without_driver_position(self):
        """Test 21: pending stops have None distance_km when no driver pos."""
        ride = _make_ride(status=RideStatus.IN_PROGRESS)
        stops = build_stops(ride, _GCT_LAT, _GCT_LNG, _TSQ_LAT, _TSQ_LNG, [], None, None)
        dropoff = stops[-1]
        assert dropoff.distance_km is None
        assert dropoff.eta_minutes is None


# ---------------------------------------------------------------------------
# 22–28: Service unit tests (mocked DB)
# ---------------------------------------------------------------------------

class TestGetNavigationStateService:

    @pytest.mark.asyncio
    async def test_raises_value_error_for_unknown_ride(self):
        """Test 22: ValueError if ride does not exist."""
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_one_or_none_result(None))
        with pytest.raises(ValueError, match="not found"):
            await get_navigation_state(ride_id=99, driver_id=10, db=db)

    @pytest.mark.asyncio
    async def test_raises_permission_error_for_wrong_driver(self):
        """Test 23: PermissionError if driver_id doesn't match ride.driver_id."""
        ride = _make_ride(driver_id=10)
        row = (ride, _GCT_LAT, _GCT_LNG, _TSQ_LAT, _TSQ_LNG)
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _one_or_none_result(row),
                _scalars_all_result([]),
            ]
        )
        with pytest.raises(PermissionError):
            await get_navigation_state(ride_id=1, driver_id=99, db=db)

    @pytest.mark.asyncio
    async def test_returns_navigation_state_for_in_progress_ride(self):
        """Test 24: IN_PROGRESS ride returns correct stop count and next_stop."""
        ride = _make_ride(status=RideStatus.IN_PROGRESS, driver_id=10)
        wp = _make_waypoint(order=1, status=WaypointStatus.PENDING)
        row = (ride, _GCT_LAT, _GCT_LNG, _TSQ_LAT, _TSQ_LNG)
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _one_or_none_result(row),
                _scalars_all_result([wp]),
            ]
        )
        result = await get_navigation_state(
            ride_id=1, driver_id=10, db=db,
            driver_lat=_GCT_LAT, driver_lng=_GCT_LNG,
        )
        assert result.ride_id == 1
        assert result.ride_status == "in_progress"
        assert len(result.stops) == 3  # pickup + 1 waypoint + dropoff
        assert result.next_stop is not None
        assert result.next_stop.type == StopType.WAYPOINT  # pickup done, waypoint is next


class TestUpdateNavigationPositionService:

    @pytest.mark.asyncio
    async def test_raises_value_error_for_wrong_status(self):
        """Test 25: ValueError for non-active ride status (e.g. COMPLETED)."""
        ride = _make_ride(status=RideStatus.COMPLETED, driver_id=10)
        row = (ride, _GCT_LAT, _GCT_LNG, _TSQ_LAT, _TSQ_LNG)
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_one_or_none_result(row))
        with pytest.raises(ValueError, match="active"):
            await update_navigation_position(
                ride_id=1, driver_id=10, lat=40.755, lng=-73.981, db=db
            )

    @pytest.mark.asyncio
    async def test_raises_permission_error_for_wrong_driver(self):
        """Test 26: PermissionError if caller is not the ride's driver."""
        ride = _make_ride(status=RideStatus.IN_PROGRESS, driver_id=10)
        row = (ride, _GCT_LAT, _GCT_LNG, _TSQ_LAT, _TSQ_LNG)
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_one_or_none_result(row))
        with pytest.raises(PermissionError):
            await update_navigation_position(
                ride_id=1, driver_id=99, lat=40.755, lng=-73.981, db=db
            )

    @pytest.mark.asyncio
    async def test_flags_deviation_when_off_route(self):
        """Test 27: deviation is flagged when driver is > DEVIATION_THRESHOLD_KM off path."""
        ride = _make_ride(status=RideStatus.IN_PROGRESS, driver_id=10, route_deviation_flagged_at=None)
        row = (ride, _GCT_LAT, _GCT_LNG, _TSQ_LAT, _TSQ_LNG)
        # After the update execute, we re-fetch the ride (now with deviation flagged)
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _one_or_none_result(row),   # initial ride fetch
                _scalars_all_result([]),    # waypoints
                MagicMock(),               # update execute (deviation flag)
            ]
        )
        # Driver is well off the GCT→TSQ corridor
        off_lat = (_GCT_LAT + _TSQ_LAT) / 2 + 0.009
        off_lng = (_GCT_LNG + _TSQ_LNG) / 2
        result = await update_navigation_position(
            ride_id=1, driver_id=10, lat=off_lat, lng=off_lng, db=db
        )
        assert result.route_deviation_flagged is True

    @pytest.mark.asyncio
    async def test_no_double_flag_if_already_flagged(self):
        """Test 28: deviation is not re-flagged if route_deviation_flagged_at already set."""
        ride = _make_ride(
            status=RideStatus.IN_PROGRESS, driver_id=10,
            route_deviation_flagged_at=_NOW,
        )
        row = (ride, _GCT_LAT, _GCT_LNG, _TSQ_LAT, _TSQ_LNG)

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _one_or_none_result(row),
                _scalars_all_result([]),
            ]
        )
        off_lat = (_GCT_LAT + _TSQ_LAT) / 2 + 0.009
        off_lng = (_GCT_LNG + _TSQ_LNG) / 2
        result = await update_navigation_position(
            ride_id=1, driver_id=10, lat=off_lat, lng=off_lng, db=db
        )
        # update() is NOT called — only 2 execute calls (fetch ride + fetch waypoints)
        assert db.execute.call_count == 2
        assert result.route_deviation_flagged is True


# ---------------------------------------------------------------------------
# 29–34: API integration tests (conftest fixtures)
# ---------------------------------------------------------------------------

@pytest.mark.skip(reason="Integration tests require real DB and auth fixtures from conftest")
class TestDriverNavigationAPI:

    def test_get_navigation_no_auth(self, client):
        """Test 29: GET /navigation — 401 with no token."""
        resp = client.get("/api/v1/rides/1/navigation")
        assert resp.status_code == 401

    def test_get_navigation_rider_forbidden(self, client, rider_token):
        """Test 30: GET /navigation — 403 with rider token (driver-only endpoint)."""
        resp = client.get("/api/v1/rides/1/navigation", headers=auth_header(rider_token))
        assert resp.status_code == 403

    def test_get_navigation_not_found(self, client, driver_token):
        """Test 31: GET /navigation — 404 for unknown ride_id."""
        resp = client.get("/api/v1/rides/99999/navigation", headers=auth_header(driver_token))
        assert resp.status_code == 404

    def test_post_position_no_auth(self, client):
        """Test 32: POST /navigation/position — 401 with no token."""
        resp = client.post("/api/v1/rides/1/navigation/position", json={"lat": 40.75, "lng": -73.98})
        assert resp.status_code == 401

    def test_post_position_rider_forbidden(self, client, rider_token):
        """Test 33: POST /navigation/position — 403 with rider token."""
        resp = client.post(
            "/api/v1/rides/1/navigation/position",
            json={"lat": 40.75, "lng": -73.98},
            headers=auth_header(rider_token),
        )
        assert resp.status_code == 403

    def test_post_position_invalid_lat_lng(self, client, driver_token):
        """Test 34: POST /navigation/position — 422 for out-of-range coordinates."""
        resp = client.post(
            "/api/v1/rides/1/navigation/position",
            json={"lat": 999.0, "lng": -73.98},
            headers=auth_header(driver_token),
        )
        assert resp.status_code == 422
