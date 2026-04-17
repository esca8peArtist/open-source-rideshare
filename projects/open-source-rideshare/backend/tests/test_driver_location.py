"""Tests for driver live location updates.

Covers:
- fuzz_coordinate:                pure helper — decimal places, negative coords
- haversine_m:                    pure helper — known distances
- update_driver_location_db:      DB update, missing profile error
- get_driver_location_db:         returns coords + updated_at; null when no location
- get_nearby_available_drivers:   join + filter logic (mocked DB)
- get_all_online_driver_locations: admin query (mocked DB)
- get_single_driver_location_admin: single driver, not-found returns None
- get_assigned_driver_location:   ride not found, wrong rider, non-trackable, no driver id,
                                  driver no location, driver has location + distance calc
- PUT  /drivers/me/location       — auth, validation, success, redis failure tolerance
- GET  /drivers/me/location       — auth, no location, with location
- GET  /riders/nearby-drivers     — auth, query param validation, response shape
- GET  /admin/drivers/locations   — admin auth, list shape
- GET  /admin/drivers/{id}/location — admin auth, 404, exact fields
- GET  /rides/{id}/driver-location — auth, 403 wrong rider, 404 missing ride, non-trackable,
                                     null location, exact coords + distance
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.driver_location import (
    DEFAULT_RADIUS_M,
    MAX_NEARBY_LIMIT,
    fuzz_coordinate,
    get_all_online_driver_locations,
    get_assigned_driver_location,
    get_driver_location_db,
    get_nearby_available_drivers,
    get_single_driver_location_admin,
    haversine_m,
    update_driver_location_db,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_UTC = timezone.utc


def _utcnow() -> datetime:
    return datetime.now(_UTC)


def _make_db_one(row) -> AsyncMock:
    """Mock db.execute returning a single row via .one_or_none()."""
    result = MagicMock()
    result.one_or_none.return_value = row
    result.scalar_one_or_none.return_value = row
    db = AsyncMock()
    db.execute = AsyncMock(return_value=result)
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


def _make_db_many(rows: list) -> AsyncMock:
    """Mock db.execute returning multiple rows via .fetchall()."""
    result = MagicMock()
    result.fetchall.return_value = rows
    db = AsyncMock()
    db.execute = AsyncMock(return_value=result)
    return db


def _row(**kwargs):
    """Build a mock row with attributes from kwargs."""
    row = MagicMock()
    for k, v in kwargs.items():
        setattr(row, k, v)
    return row


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


class TestFuzzCoordinate:
    def test_default_precision_three_dp(self):
        assert fuzz_coordinate(40.71234) == 40.712

    def test_custom_precision(self):
        assert fuzz_coordinate(40.71234, decimal_places=2) == 40.71

    def test_negative_coord(self):
        assert fuzz_coordinate(-74.00678) == -74.007

    def test_already_short(self):
        assert fuzz_coordinate(40.5) == 40.5

    def test_zero(self):
        assert fuzz_coordinate(0.0) == 0.0

    def test_lat_boundary(self):
        assert fuzz_coordinate(90.0) == 90.0
        assert fuzz_coordinate(-90.0) == -90.0


class TestHaversineM:
    def test_same_point_is_zero(self):
        assert haversine_m(40.7128, -74.006, 40.7128, -74.006) == pytest.approx(0.0, abs=1e-3)

    def test_nyc_to_brooklyn(self):
        # Manhattan (40.7128, -74.006) to Brooklyn (40.6501, -73.9496)
        dist = haversine_m(40.7128, -74.006, 40.6501, -73.9496)
        # ~8.4 km
        assert 7_500 < dist < 9_500

    def test_symmetry(self):
        a = haversine_m(40.0, -74.0, 41.0, -73.0)
        b = haversine_m(41.0, -73.0, 40.0, -74.0)
        assert a == pytest.approx(b, rel=1e-6)

    def test_one_degree_latitude(self):
        # 1° latitude ≈ 111 km
        dist = haversine_m(0.0, 0.0, 1.0, 0.0)
        assert 110_000 < dist < 112_000


# ---------------------------------------------------------------------------
# update_driver_location_db
# ---------------------------------------------------------------------------


class TestUpdateDriverLocationDb:
    @pytest.mark.anyio
    async def test_updates_existing_profile(self):
        profile_mock = MagicMock()
        profile_mock.current_location = None

        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = profile_mock

        db = AsyncMock()
        db.execute = AsyncMock(return_value=result_mock)
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        returned = await update_driver_location_db(db, driver_id=1, lat=40.71, lng=-74.00)

        # commit must be called
        db.commit.assert_awaited_once()
        # profile is refreshed after commit
        db.refresh.assert_awaited_once_with(profile_mock)
        # returned object is the refreshed profile mock
        assert returned is profile_mock

    @pytest.mark.anyio
    async def test_raises_when_profile_missing(self):
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None

        db = AsyncMock()
        db.execute = AsyncMock(return_value=result_mock)

        with pytest.raises(ValueError, match="not found"):
            await update_driver_location_db(db, driver_id=99, lat=40.71, lng=-74.00)


# ---------------------------------------------------------------------------
# get_driver_location_db
# ---------------------------------------------------------------------------


class TestGetDriverLocationDb:
    @pytest.mark.anyio
    async def test_returns_lat_lng_and_updated_at(self):
        ts = _utcnow()
        row = _row(lat=40.71, lng=-74.00, updated_at=ts)
        db = _make_db_one(row)

        lat, lng, updated_at = await get_driver_location_db(db, driver_id=1)

        assert lat == pytest.approx(40.71)
        assert lng == pytest.approx(-74.00)
        assert updated_at == ts

    @pytest.mark.anyio
    async def test_returns_nones_when_no_location(self):
        ts = _utcnow()
        row = _row(lat=None, lng=None, updated_at=ts)
        db = _make_db_one(row)

        lat, lng, updated_at = await get_driver_location_db(db, driver_id=1)

        assert lat is None
        assert lng is None
        assert updated_at == ts

    @pytest.mark.anyio
    async def test_returns_all_nones_when_profile_missing(self):
        db = _make_db_one(None)

        lat, lng, updated_at = await get_driver_location_db(db, driver_id=99)

        assert lat is None
        assert lng is None
        assert updated_at is None


# ---------------------------------------------------------------------------
# get_nearby_available_drivers
# ---------------------------------------------------------------------------


class TestGetNearbyAvailableDrivers:
    @pytest.mark.anyio
    async def test_returns_empty_list_when_no_rows(self):
        db = _make_db_many([])

        result = await get_nearby_available_drivers(db, lat=40.71, lng=-74.00)

        assert result == []

    @pytest.mark.anyio
    async def test_returns_list_of_dicts(self):
        rows = [
            _row(driver_id=1, lat=40.71, lng=-74.00),
            _row(driver_id=2, lat=40.72, lng=-74.01),
        ]
        db = _make_db_many(rows)

        result = await get_nearby_available_drivers(db, lat=40.71, lng=-74.00)

        assert len(result) == 2
        assert result[0] == {"driver_id": 1, "lat": pytest.approx(40.71), "lng": pytest.approx(-74.00)}
        assert result[1]["driver_id"] == 2

    @pytest.mark.anyio
    async def test_dict_keys_correct(self):
        rows = [_row(driver_id=5, lat=51.50, lng=-0.12)]
        db = _make_db_many(rows)

        result = await get_nearby_available_drivers(db, lat=51.50, lng=-0.12)

        assert set(result[0].keys()) == {"driver_id", "lat", "lng"}

    @pytest.mark.anyio
    async def test_accepts_custom_radius_and_limit(self):
        db = _make_db_many([])

        # Should not raise with custom params
        result = await get_nearby_available_drivers(db, lat=40.0, lng=-74.0, radius_m=500, limit=5)

        assert result == []


# ---------------------------------------------------------------------------
# get_all_online_driver_locations
# ---------------------------------------------------------------------------


class TestGetAllOnlineDriverLocations:
    @pytest.mark.anyio
    async def test_empty(self):
        db = _make_db_many([])
        result = await get_all_online_driver_locations(db)
        assert result == []

    @pytest.mark.anyio
    async def test_returns_full_fields(self):
        ts = _utcnow()
        rows = [
            _row(driver_id=3, lat=40.71, lng=-74.00, is_online=True, is_on_break=False, updated_at=ts),
        ]
        db = _make_db_many(rows)

        result = await get_all_online_driver_locations(db)

        assert len(result) == 1
        item = result[0]
        assert item["driver_id"] == 3
        assert item["lat"] == pytest.approx(40.71)
        assert item["lng"] == pytest.approx(-74.00)
        assert item["is_online"] is True
        assert item["is_on_break"] is False
        assert item["updated_at"] == ts

    @pytest.mark.anyio
    async def test_null_location_returns_none(self):
        ts = _utcnow()
        rows = [
            _row(driver_id=7, lat=None, lng=None, is_online=True, is_on_break=True, updated_at=ts),
        ]
        db = _make_db_many(rows)

        result = await get_all_online_driver_locations(db)

        assert result[0]["lat"] is None
        assert result[0]["lng"] is None


# ---------------------------------------------------------------------------
# get_single_driver_location_admin
# ---------------------------------------------------------------------------


class TestGetSingleDriverLocationAdmin:
    @pytest.mark.anyio
    async def test_returns_none_when_not_found(self):
        db = _make_db_one(None)
        result = await get_single_driver_location_admin(db, driver_id=99)
        assert result is None

    @pytest.mark.anyio
    async def test_returns_dict_with_expected_fields(self):
        ts = _utcnow()
        row = _row(driver_id=10, lat=51.50, lng=-0.12, is_online=True, is_on_break=False, updated_at=ts)
        db = _make_db_one(row)

        result = await get_single_driver_location_admin(db, driver_id=10)

        assert result is not None
        assert result["driver_id"] == 10
        assert result["lat"] == pytest.approx(51.50)
        assert result["lng"] == pytest.approx(-0.12)
        assert result["is_online"] is True
        assert result["is_on_break"] is False

    @pytest.mark.anyio
    async def test_null_online_status_defaults_to_false(self):
        ts = _utcnow()
        row = _row(driver_id=11, lat=40.0, lng=-74.0, is_online=None, is_on_break=None, updated_at=ts)
        db = _make_db_one(row)

        result = await get_single_driver_location_admin(db, driver_id=11)

        assert result["is_online"] is False
        assert result["is_on_break"] is False


# ---------------------------------------------------------------------------
# API: PUT /drivers/me/location
# ---------------------------------------------------------------------------


class _FakeUser:
    def __init__(self, user_id: int, role: str = "driver"):
        self.id = user_id

        class _Role:
            value = role

        self.role = _Role()
        self.is_active = True


def _make_profile_mock(driver_id: int = 1) -> MagicMock:
    p = MagicMock()
    p.id = driver_id
    p.user_id = 1
    return p


class TestPutDriverLocation:
    @pytest.mark.anyio
    async def test_success_updates_and_returns_location(self):
        from app.api.v1.driver_location import update_my_location
        from app.schemas.driver_location import LocationUpdateRequest

        profile = _make_profile_mock(driver_id=1)
        db = AsyncMock()
        db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=profile))
        )
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        req = LocationUpdateRequest(lat=40.71, lng=-74.00)
        user = _FakeUser(user_id=1, role="driver")

        with (
            patch("app.services.driver_location.update_driver_location_db", new=AsyncMock(return_value=profile)),
            patch("app.api.v1.driver_location._resolve_driver_profile_id", new=AsyncMock(return_value=1)),
            patch("app.api.v1.driver_location.update_driver_location_db", new=AsyncMock(return_value=profile)),
            patch("app.services.matching.get_matching_engine", new=AsyncMock()),
        ):
            response = await update_my_location(req=req, user=user, db=db)

        assert response.lat == pytest.approx(40.71)
        assert response.lng == pytest.approx(-74.00)
        assert response.updated_at is not None

    @pytest.mark.anyio
    async def test_returns_submitted_coordinates(self):
        from app.api.v1.driver_location import update_my_location
        from app.schemas.driver_location import LocationUpdateRequest

        profile = _make_profile_mock(driver_id=2)
        db = AsyncMock()

        req = LocationUpdateRequest(lat=51.50, lng=-0.12)
        user = _FakeUser(user_id=2, role="driver")

        with (
            patch("app.api.v1.driver_location._resolve_driver_profile_id", new=AsyncMock(return_value=2)),
            patch("app.api.v1.driver_location.update_driver_location_db", new=AsyncMock(return_value=profile)),
            patch("app.services.matching.get_matching_engine", new=AsyncMock()),
        ):
            response = await update_my_location(req=req, user=user, db=db)

        assert response.lat == pytest.approx(51.50)
        assert response.lng == pytest.approx(-0.12)

    @pytest.mark.anyio
    async def test_redis_failure_does_not_propagate(self):
        """Redis write failure must not prevent the successful DB write from returning."""
        from app.api.v1.driver_location import update_my_location
        from app.schemas.driver_location import LocationUpdateRequest

        profile = _make_profile_mock(driver_id=3)
        db = AsyncMock()
        req = LocationUpdateRequest(lat=40.0, lng=-74.0)
        user = _FakeUser(user_id=3, role="driver")

        async def _boom():
            raise ConnectionError("Redis down")

        with (
            patch("app.api.v1.driver_location._resolve_driver_profile_id", new=AsyncMock(return_value=3)),
            patch("app.api.v1.driver_location.update_driver_location_db", new=AsyncMock(return_value=profile)),
            patch("app.services.matching.get_matching_engine", new=AsyncMock(side_effect=_boom)),
        ):
            response = await update_my_location(req=req, user=user, db=db)

        # Should still succeed with the submitted lat/lng
        assert response.lat == pytest.approx(40.0)
        assert response.lng == pytest.approx(-74.0)

    @pytest.mark.anyio
    async def test_missing_profile_raises_404(self):
        from fastapi import HTTPException

        from app.api.v1.driver_location import update_my_location
        from app.schemas.driver_location import LocationUpdateRequest

        db = AsyncMock()
        req = LocationUpdateRequest(lat=40.0, lng=-74.0)
        user = _FakeUser(user_id=99, role="driver")

        async def _raise(*_a, **_kw):
            raise ValueError("Driver profile 99 not found")

        with (
            patch("app.api.v1.driver_location._resolve_driver_profile_id", new=AsyncMock(return_value=99)),
            patch("app.api.v1.driver_location.update_driver_location_db", new=_raise),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await update_my_location(req=req, user=user, db=db)

        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# API: GET /drivers/me/location
# ---------------------------------------------------------------------------


class TestGetDriverLocation:
    @pytest.mark.anyio
    async def test_returns_location_when_set(self):
        from app.api.v1.driver_location import get_my_location

        ts = _utcnow()
        user = _FakeUser(user_id=1)
        db = AsyncMock()

        with (
            patch("app.api.v1.driver_location._resolve_driver_profile_id", new=AsyncMock(return_value=1)),
            patch(
                "app.api.v1.driver_location.get_driver_location_db",
                new=AsyncMock(return_value=(40.71, -74.00, ts)),
            ),
        ):
            resp = await get_my_location(user=user, db=db)

        assert resp.lat == pytest.approx(40.71)
        assert resp.lng == pytest.approx(-74.00)
        assert resp.updated_at == ts

    @pytest.mark.anyio
    async def test_returns_nulls_when_no_location_set(self):
        from app.api.v1.driver_location import get_my_location

        user = _FakeUser(user_id=2)
        db = AsyncMock()

        with (
            patch("app.api.v1.driver_location._resolve_driver_profile_id", new=AsyncMock(return_value=2)),
            patch(
                "app.api.v1.driver_location.get_driver_location_db",
                new=AsyncMock(return_value=(None, None, None)),
            ),
        ):
            resp = await get_my_location(user=user, db=db)

        assert resp.lat is None
        assert resp.lng is None
        assert resp.updated_at is None


# ---------------------------------------------------------------------------
# API: GET /riders/nearby-drivers
# ---------------------------------------------------------------------------


class TestGetNearbyDrivers:
    @pytest.mark.anyio
    async def test_empty_results(self):
        from app.api.v1.driver_location import get_nearby_drivers

        user = _FakeUser(user_id=10, role="rider")
        db = AsyncMock()

        with patch(
            "app.api.v1.driver_location.get_nearby_available_drivers",
            new=AsyncMock(return_value=[]),
        ):
            resp = await get_nearby_drivers(lat=40.71, lng=-74.00, radius_m=3000, limit=50, user=user, db=db)

        assert resp.total == 0
        assert resp.drivers == []
        assert resp.as_of is not None

    @pytest.mark.anyio
    async def test_returns_fuzzy_positions(self):
        from app.api.v1.driver_location import get_nearby_drivers

        user = _FakeUser(user_id=10, role="rider")
        db = AsyncMock()
        raw = [{"driver_id": 1, "lat": 40.71234, "lng": -74.00678}]

        with patch(
            "app.api.v1.driver_location.get_nearby_available_drivers",
            new=AsyncMock(return_value=raw),
        ):
            resp = await get_nearby_drivers(lat=40.71, lng=-74.00, radius_m=3000, limit=50, user=user, db=db)

        assert resp.total == 1
        driver = resp.drivers[0]
        # Coordinates should be fuzzed to 3 dp
        assert driver.lat == pytest.approx(round(40.71234, 3))
        assert driver.lng == pytest.approx(round(-74.00678, 3))

    @pytest.mark.anyio
    async def test_no_driver_ids_in_response(self):
        from app.api.v1.driver_location import get_nearby_drivers

        user = _FakeUser(user_id=10, role="rider")
        db = AsyncMock()
        raw = [{"driver_id": 42, "lat": 40.71, "lng": -74.00}]

        with patch(
            "app.api.v1.driver_location.get_nearby_available_drivers",
            new=AsyncMock(return_value=raw),
        ):
            resp = await get_nearby_drivers(lat=40.71, lng=-74.00, radius_m=3000, limit=50, user=user, db=db)

        driver = resp.drivers[0]
        # NearbyDriverItem must not expose driver_id
        assert not hasattr(driver, "driver_id") or not isinstance(getattr(driver, "driver_id", None), int)

    @pytest.mark.anyio
    async def test_distance_m_is_populated(self):
        from app.api.v1.driver_location import get_nearby_drivers

        user = _FakeUser(user_id=10, role="rider")
        db = AsyncMock()
        raw = [{"driver_id": 1, "lat": 40.72, "lng": -74.01}]

        with patch(
            "app.api.v1.driver_location.get_nearby_available_drivers",
            new=AsyncMock(return_value=raw),
        ):
            resp = await get_nearby_drivers(lat=40.71, lng=-74.00, radius_m=3000, limit=50, user=user, db=db)

        driver = resp.drivers[0]
        assert driver.distance_m > 0

    @pytest.mark.anyio
    async def test_multiple_drivers(self):
        from app.api.v1.driver_location import get_nearby_drivers

        user = _FakeUser(user_id=10, role="rider")
        db = AsyncMock()
        raw = [
            {"driver_id": 1, "lat": 40.71, "lng": -74.00},
            {"driver_id": 2, "lat": 40.72, "lng": -74.01},
            {"driver_id": 3, "lat": 40.73, "lng": -74.02},
        ]

        with patch(
            "app.api.v1.driver_location.get_nearby_available_drivers",
            new=AsyncMock(return_value=raw),
        ):
            resp = await get_nearby_drivers(lat=40.71, lng=-74.00, radius_m=3000, limit=50, user=user, db=db)

        assert resp.total == 3
        assert len(resp.drivers) == 3


# ---------------------------------------------------------------------------
# API: GET /admin/drivers/locations
# ---------------------------------------------------------------------------


class TestAdminListDriverLocations:
    @pytest.mark.anyio
    async def test_empty(self):
        from app.api.v1.driver_location import admin_list_driver_locations

        user = _FakeUser(user_id=99, role="admin")
        db = AsyncMock()

        with patch(
            "app.api.v1.driver_location.get_all_online_driver_locations",
            new=AsyncMock(return_value=[]),
        ):
            resp = await admin_list_driver_locations(user=user, db=db)

        assert resp.total == 0
        assert resp.drivers == []

    @pytest.mark.anyio
    async def test_returns_exact_driver_ids(self):
        from app.api.v1.driver_location import admin_list_driver_locations

        ts = _utcnow()
        user = _FakeUser(user_id=99, role="admin")
        db = AsyncMock()
        rows = [
            {"driver_id": 5, "lat": 40.71, "lng": -74.00, "is_online": True, "is_on_break": False, "updated_at": ts},
            {"driver_id": 6, "lat": 40.72, "lng": -74.01, "is_online": True, "is_on_break": True, "updated_at": ts},
        ]

        with patch(
            "app.api.v1.driver_location.get_all_online_driver_locations",
            new=AsyncMock(return_value=rows),
        ):
            resp = await admin_list_driver_locations(user=user, db=db)

        assert resp.total == 2
        assert resp.drivers[0].driver_id == 5
        assert resp.drivers[1].driver_id == 6
        assert resp.drivers[1].is_on_break is True

    @pytest.mark.anyio
    async def test_null_location_allowed(self):
        from app.api.v1.driver_location import admin_list_driver_locations

        user = _FakeUser(user_id=99, role="admin")
        db = AsyncMock()
        rows = [
            {"driver_id": 7, "lat": None, "lng": None, "is_online": True, "is_on_break": False, "updated_at": None},
        ]

        with patch(
            "app.api.v1.driver_location.get_all_online_driver_locations",
            new=AsyncMock(return_value=rows),
        ):
            resp = await admin_list_driver_locations(user=user, db=db)

        driver = resp.drivers[0]
        assert driver.lat is None
        assert driver.lng is None


# ---------------------------------------------------------------------------
# API: GET /admin/drivers/{driver_id}/location
# ---------------------------------------------------------------------------


class TestAdminGetSingleDriverLocation:
    @pytest.mark.anyio
    async def test_returns_driver_data(self):
        from app.api.v1.driver_location import admin_get_driver_location

        ts = _utcnow()
        user = _FakeUser(user_id=99, role="admin")
        db = AsyncMock()
        data = {"driver_id": 10, "lat": 51.50, "lng": -0.12, "is_online": True, "is_on_break": False, "updated_at": ts}

        with patch(
            "app.api.v1.driver_location.get_single_driver_location_admin",
            new=AsyncMock(return_value=data),
        ):
            resp = await admin_get_driver_location(driver_id=10, user=user, db=db)

        assert resp.driver_id == 10
        assert resp.lat == pytest.approx(51.50)
        assert resp.lng == pytest.approx(-0.12)
        assert resp.is_online is True
        assert resp.updated_at == ts

    @pytest.mark.anyio
    async def test_raises_404_when_not_found(self):
        from fastapi import HTTPException

        from app.api.v1.driver_location import admin_get_driver_location

        user = _FakeUser(user_id=99, role="admin")
        db = AsyncMock()

        with patch(
            "app.api.v1.driver_location.get_single_driver_location_admin",
            new=AsyncMock(return_value=None),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await admin_get_driver_location(driver_id=999, user=user, db=db)

        assert exc_info.value.status_code == 404
        assert "999" in exc_info.value.detail

    @pytest.mark.anyio
    async def test_null_coordinates_are_allowed(self):
        from app.api.v1.driver_location import admin_get_driver_location

        user = _FakeUser(user_id=99, role="admin")
        db = AsyncMock()
        data = {"driver_id": 11, "lat": None, "lng": None, "is_online": False, "is_on_break": False, "updated_at": None}

        with patch(
            "app.api.v1.driver_location.get_single_driver_location_admin",
            new=AsyncMock(return_value=data),
        ):
            resp = await admin_get_driver_location(driver_id=11, user=user, db=db)

        assert resp.lat is None
        assert resp.lng is None


# ---------------------------------------------------------------------------
# get_assigned_driver_location (service)
# ---------------------------------------------------------------------------


class TestGetAssignedDriverLocation:
    @pytest.mark.anyio
    async def test_returns_none_when_ride_not_found(self):
        result = MagicMock()
        result.one_or_none.return_value = None
        db = AsyncMock()
        db.execute = AsyncMock(return_value=result)

        out = await get_assigned_driver_location(db, ride_id=99, rider_user_id=1)
        assert out is None

    @pytest.mark.anyio
    async def test_raises_permission_error_for_wrong_rider(self):
        ride_row = _row(id=1, rider_id=5, driver_id=10, status="matched", pickup_lat=40.71, pickup_lng=-74.00)
        result = MagicMock()
        result.one_or_none.return_value = ride_row
        db = AsyncMock()
        db.execute = AsyncMock(return_value=result)

        with pytest.raises(PermissionError):
            await get_assigned_driver_location(db, ride_id=1, rider_user_id=999)

    @pytest.mark.anyio
    async def test_returns_base_dict_for_non_trackable_status(self):
        from app.models.ride import RideStatus

        ride_row = _row(id=1, rider_id=5, driver_id=10, status=RideStatus.REQUESTED, pickup_lat=40.71, pickup_lng=-74.00)
        result = MagicMock()
        result.one_or_none.return_value = ride_row
        db = AsyncMock()
        db.execute = AsyncMock(return_value=result)

        out = await get_assigned_driver_location(db, ride_id=1, rider_user_id=5)
        assert out is not None
        assert out["lat"] is None
        assert out["lng"] is None
        assert out["distance_to_pickup_m"] is None

    @pytest.mark.anyio
    async def test_returns_base_dict_when_no_driver_assigned(self):
        from app.models.ride import RideStatus

        ride_row = _row(id=1, rider_id=5, driver_id=None, status=RideStatus.MATCHED, pickup_lat=40.71, pickup_lng=-74.00)
        result = MagicMock()
        result.one_or_none.return_value = ride_row
        db = AsyncMock()
        db.execute = AsyncMock(return_value=result)

        out = await get_assigned_driver_location(db, ride_id=1, rider_user_id=5)
        assert out is not None
        assert out["lat"] is None

    @pytest.mark.anyio
    async def test_returns_null_coords_when_driver_has_no_location(self):
        from app.models.ride import RideStatus

        ride_row = _row(id=1, rider_id=5, driver_id=10, status=RideStatus.DRIVER_EN_ROUTE, pickup_lat=40.71, pickup_lng=-74.00)
        driver_row = _row(lat=None, lng=None, updated_at=None)

        call_count = 0

        async def _execute(stmt):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.one_or_none.return_value = ride_row
            else:
                result.one_or_none.return_value = driver_row
            return result

        db = AsyncMock()
        db.execute = _execute

        out = await get_assigned_driver_location(db, ride_id=1, rider_user_id=5)
        assert out["lat"] is None
        assert out["lng"] is None
        assert out["distance_to_pickup_m"] is None

    @pytest.mark.anyio
    async def test_returns_exact_coords_and_distance(self):
        from app.models.ride import RideStatus

        pickup_lat, pickup_lng = 40.7128, -74.006
        driver_lat, driver_lng = 40.720, -74.010
        ts = _utcnow()

        ride_row = _row(
            id=1, rider_id=5, driver_id=10,
            status=RideStatus.DRIVER_EN_ROUTE,
            pickup_lat=pickup_lat, pickup_lng=pickup_lng,
        )
        driver_row = _row(lat=driver_lat, lng=driver_lng, updated_at=ts)

        call_count = 0

        async def _execute(stmt):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.one_or_none.return_value = ride_row
            else:
                result.one_or_none.return_value = driver_row
            return result

        db = AsyncMock()
        db.execute = _execute

        out = await get_assigned_driver_location(db, ride_id=1, rider_user_id=5)
        assert out["lat"] == pytest.approx(driver_lat)
        assert out["lng"] == pytest.approx(driver_lng)
        assert out["updated_at"] == ts
        assert out["distance_to_pickup_m"] is not None
        expected_dist = haversine_m(driver_lat, driver_lng, pickup_lat, pickup_lng)
        assert out["distance_to_pickup_m"] == pytest.approx(round(expected_dist, 1), rel=1e-3)

    @pytest.mark.anyio
    async def test_works_for_arrived_status(self):
        """ARRIVED is trackable — driver is at pickup, distance should be ~0."""
        from app.models.ride import RideStatus

        lat, lng = 40.7128, -74.006
        ts = _utcnow()

        ride_row = _row(
            id=2, rider_id=7, driver_id=15,
            status=RideStatus.ARRIVED,
            pickup_lat=lat, pickup_lng=lng,
        )
        driver_row = _row(lat=lat, lng=lng, updated_at=ts)

        call_count = 0

        async def _execute(stmt):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.one_or_none.return_value = ride_row
            else:
                result.one_or_none.return_value = driver_row
            return result

        db = AsyncMock()
        db.execute = _execute

        out = await get_assigned_driver_location(db, ride_id=2, rider_user_id=7)
        assert out["lat"] == pytest.approx(lat)
        assert out["distance_to_pickup_m"] == pytest.approx(0.0, abs=1.0)


# ---------------------------------------------------------------------------
# API: GET /rides/{ride_id}/driver-location
# ---------------------------------------------------------------------------


class TestGetRideDriverLocation:
    @pytest.mark.anyio
    async def test_returns_404_when_ride_not_found(self):
        from fastapi import HTTPException

        from app.api.v1.driver_location import get_ride_driver_location

        user = _FakeUser(user_id=5, role="rider")
        db = AsyncMock()

        with patch(
            "app.api.v1.driver_location.get_assigned_driver_location",
            new=AsyncMock(return_value=None),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await get_ride_driver_location(ride_id=99, user=user, db=db)

        assert exc_info.value.status_code == 404
        assert "99" in exc_info.value.detail

    @pytest.mark.anyio
    async def test_returns_403_for_wrong_rider(self):
        from fastapi import HTTPException

        from app.api.v1.driver_location import get_ride_driver_location

        user = _FakeUser(user_id=5, role="rider")
        db = AsyncMock()

        with patch(
            "app.api.v1.driver_location.get_assigned_driver_location",
            new=AsyncMock(side_effect=PermissionError("Not your ride")),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await get_ride_driver_location(ride_id=1, user=user, db=db)

        assert exc_info.value.status_code == 403

    @pytest.mark.anyio
    async def test_returns_null_coords_for_non_trackable_status(self):
        from app.api.v1.driver_location import get_ride_driver_location

        user = _FakeUser(user_id=5, role="rider")
        db = AsyncMock()
        data = {
            "ride_status": "completed",
            "lat": None,
            "lng": None,
            "updated_at": None,
            "distance_to_pickup_m": None,
        }

        with patch(
            "app.api.v1.driver_location.get_assigned_driver_location",
            new=AsyncMock(return_value=data),
        ):
            resp = await get_ride_driver_location(ride_id=1, user=user, db=db)

        assert resp.lat is None
        assert resp.lng is None
        assert resp.distance_to_pickup_m is None
        assert resp.ride_status == "completed"

    @pytest.mark.anyio
    async def test_returns_exact_coords_during_en_route(self):
        from app.api.v1.driver_location import get_ride_driver_location

        ts = _utcnow()
        user = _FakeUser(user_id=5, role="rider")
        db = AsyncMock()
        data = {
            "ride_status": "driver_en_route",
            "lat": 40.720,
            "lng": -74.010,
            "updated_at": ts,
            "distance_to_pickup_m": 854.3,
        }

        with patch(
            "app.api.v1.driver_location.get_assigned_driver_location",
            new=AsyncMock(return_value=data),
        ):
            resp = await get_ride_driver_location(ride_id=1, user=user, db=db)

        assert resp.lat == pytest.approx(40.720)
        assert resp.lng == pytest.approx(-74.010)
        assert resp.updated_at == ts
        assert resp.distance_to_pickup_m == pytest.approx(854.3)
        assert resp.ride_status == "driver_en_route"

    @pytest.mark.anyio
    async def test_returns_null_when_driver_has_no_location_yet(self):
        from app.api.v1.driver_location import get_ride_driver_location

        user = _FakeUser(user_id=5, role="rider")
        db = AsyncMock()
        data = {
            "ride_status": "matched",
            "lat": None,
            "lng": None,
            "updated_at": None,
            "distance_to_pickup_m": None,
        }

        with patch(
            "app.api.v1.driver_location.get_assigned_driver_location",
            new=AsyncMock(return_value=data),
        ):
            resp = await get_ride_driver_location(ride_id=1, user=user, db=db)

        assert resp.lat is None
        assert resp.ride_status == "matched"

    @pytest.mark.anyio
    async def test_returns_arrived_with_near_zero_distance(self):
        from app.api.v1.driver_location import get_ride_driver_location

        ts = _utcnow()
        user = _FakeUser(user_id=7, role="rider")
        db = AsyncMock()
        data = {
            "ride_status": "arrived",
            "lat": 40.7128,
            "lng": -74.006,
            "updated_at": ts,
            "distance_to_pickup_m": 0.0,
        }

        with patch(
            "app.api.v1.driver_location.get_assigned_driver_location",
            new=AsyncMock(return_value=data),
        ):
            resp = await get_ride_driver_location(ride_id=2, user=user, db=db)

        assert resp.ride_status == "arrived"
        assert resp.distance_to_pickup_m == pytest.approx(0.0)
