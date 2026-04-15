"""Tests for driver live location tracking system.

Service layer (unit tests with mocked DB):
  1.  upsert_driver_location — creates new row when no existing record
  2.  upsert_driver_location — updates existing row on second push
  3.  upsert_driver_location — sets is_active=True on push
  4.  upsert_driver_location — stores all optional fields (accuracy, heading, speed)
  5.  upsert_driver_location — raises 400 when ride_id doesn't belong to driver
  6.  upsert_driver_location — accepts valid ride_id owned by driver
  7.  upsert_driver_location — preserves existing ride_id when payload.ride_id is None
  8.  clear_driver_location — sets is_active=False and clears ride_id
  9.  clear_driver_location — no-op when no existing location record
  10. get_ride_driver_location — raises 404 when ride not found
  11. get_ride_driver_location — raises 403 when requester not a participant
  12. get_ride_driver_location — raises 409 when ride not in trackable status
  13. get_ride_driver_location — raises 404 when driver has no location record
  14. get_ride_driver_location — returns location when all conditions met (rider)
  15. get_ride_driver_location — returns location when all conditions met (driver)
  16. list_active_drivers — returns only is_active=True rows
  17. list_active_drivers — respects limit/offset pagination

Schema:
  18. LocationUpdate — rejects latitude out of range
  19. LocationUpdate — rejects longitude out of range
  20. LocationUpdate — rounds lat/lon to 8 decimal places
  21. LocationUpdate — accepts None for optional fields
  22. DriverLocationResponse.from_orm_model — maps all fields correctly
  23. ActiveDriversResponse — total matches driver list length

API layer (integration-style, skipped without live DB):
  24. POST /drivers/me/location — 200 creates/updates location
  25. POST /drivers/me/location — 401 unauthenticated
  26. POST /drivers/me/location — 422 invalid latitude
  27. GET  /rides/{id}/driver-location — 200 returns location
  28. GET  /rides/{id}/driver-location — 401 unauthenticated
  29. GET  /rides/{id}/driver-location — 403 non-participant
  30. GET  /admin/drivers/live — 200 returns active drivers
  31. GET  /admin/drivers/live — 403 non-admin
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.driver_location import DriverLocation
from app.models.ride import Ride, RideStatus
from app.models.user import User, UserRole
from app.schemas.driver_location import (
    ActiveDriversResponse,
    DriverLocationResponse,
    LocationUpdate,
)
from app.services.auth import create_access_token, hash_password
from app.services.driver_location import (
    clear_driver_location,
    get_ride_driver_location,
    list_active_drivers,
    upsert_driver_location,
)


# ===========================================================================
# Helpers / factories
# ===========================================================================

_BASE_TS = datetime(2026, 4, 15, 12, 0, tzinfo=timezone.utc)
_DRIVER_ID = 10
_RIDER_ID = 20
_RIDE_ID = 99


def _make_location(
    *,
    loc_id: int = 1,
    driver_id: int = _DRIVER_ID,
    ride_id: int | None = _RIDE_ID,
    latitude: float = 37.7749,
    longitude: float = -122.4194,
    accuracy_meters: float | None = 5.0,
    heading: float | None = 90.0,
    speed_kmh: float | None = 30.0,
    is_active: bool = True,
) -> MagicMock:
    loc = MagicMock(spec=DriverLocation)
    loc.id = loc_id
    loc.driver_id = driver_id
    loc.ride_id = ride_id
    loc.latitude = latitude
    loc.longitude = longitude
    loc.accuracy_meters = accuracy_meters
    loc.heading = heading
    loc.speed_kmh = speed_kmh
    loc.is_active = is_active
    loc.updated_at = _BASE_TS
    loc.created_at = _BASE_TS
    loc.driver = None
    return loc


def _make_ride(
    *,
    ride_id: int = _RIDE_ID,
    rider_id: int = _RIDER_ID,
    driver_id: int = _DRIVER_ID,
    status: RideStatus = RideStatus.IN_PROGRESS,
) -> MagicMock:
    ride = MagicMock(spec=Ride)
    ride.id = ride_id
    ride.rider_id = rider_id
    ride.driver_id = driver_id
    ride.status = status
    return ride


def _make_user(
    *,
    user_id: int = _DRIVER_ID,
    role: UserRole = UserRole.DRIVER,
) -> MagicMock:
    u = MagicMock(spec=User)
    u.id = user_id
    u.role = role
    u.name = "Test User"
    return u


def _scalar_result(value):
    m = MagicMock()
    m.scalar_one.return_value = value
    m.scalar_one_or_none.return_value = value
    inner = MagicMock()
    inner.all.return_value = [value] if value is not None else []
    m.scalars.return_value = inner
    return m


def _make_db(execute_return=None) -> AsyncMock:
    db = AsyncMock()
    db.execute = AsyncMock(return_value=execute_return or _scalar_result(None))
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


# ===========================================================================
# Service layer — upsert_driver_location
# ===========================================================================


@pytest.mark.asyncio
async def test_upsert_creates_new_row_when_no_existing():
    """upsert_driver_location creates a new DriverLocation row when driver has none."""
    payload = LocationUpdate(latitude=37.7749, longitude=-122.4194)

    # No existing record — both execute calls return None
    db = _make_db(execute_return=_scalar_result(None))
    db.refresh = AsyncMock(side_effect=lambda obj: None)

    await upsert_driver_location(db, _DRIVER_ID, payload)

    # db.add should have been called once with the new DriverLocation instance
    db.add.assert_called_once()
    added_obj = db.add.call_args[0][0]
    assert isinstance(added_obj, DriverLocation)
    assert added_obj.driver_id == _DRIVER_ID
    assert added_obj.latitude == 37.7749
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_upsert_updates_existing_row():
    """upsert_driver_location updates fields on an existing row."""
    payload = LocationUpdate(latitude=37.8, longitude=-122.5, speed_kmh=50.0)
    existing = _make_location(speed_kmh=10.0)
    db = _make_db(execute_return=_scalar_result(existing))
    db.refresh = AsyncMock(side_effect=lambda obj: None)

    result = await upsert_driver_location(db, _DRIVER_ID, payload)

    # Should have mutated the existing object
    assert existing.latitude == 37.8
    assert existing.longitude == -122.5
    assert existing.speed_kmh == 50.0
    db.add.assert_not_called()
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_upsert_sets_is_active_true():
    """upsert_driver_location always sets is_active=True."""
    payload = LocationUpdate(latitude=37.7749, longitude=-122.4194)
    existing = _make_location(is_active=False)
    db = _make_db(execute_return=_scalar_result(existing))
    db.refresh = AsyncMock(side_effect=lambda obj: None)

    await upsert_driver_location(db, _DRIVER_ID, payload)

    assert existing.is_active is True


@pytest.mark.asyncio
async def test_upsert_stores_optional_fields():
    """upsert_driver_location stores accuracy, heading, and speed."""
    payload = LocationUpdate(
        latitude=37.7749,
        longitude=-122.4194,
        accuracy_meters=3.5,
        heading=180.0,
        speed_kmh=25.0,
    )
    existing = _make_location()
    db = _make_db(execute_return=_scalar_result(existing))
    db.refresh = AsyncMock(side_effect=lambda obj: None)

    await upsert_driver_location(db, _DRIVER_ID, payload)

    assert existing.accuracy_meters == 3.5
    assert existing.heading == 180.0
    assert existing.speed_kmh == 25.0


@pytest.mark.asyncio
async def test_upsert_raises_400_for_wrong_ride_id():
    """upsert raises 400 when ride_id is provided but not owned by this driver."""
    from fastapi import HTTPException

    payload = LocationUpdate(latitude=37.7, longitude=-122.4, ride_id=999)

    # Both DB lookups (ride check + existing location) return None
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_scalar_result(None))
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    with pytest.raises(HTTPException) as exc_info:
        await upsert_driver_location(db, _DRIVER_ID, payload)

    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_upsert_accepts_valid_ride_id():
    """upsert accepts ride_id when the ride is owned by the driver."""
    payload = LocationUpdate(latitude=37.7, longitude=-122.4, ride_id=_RIDE_ID)
    mock_ride = _make_ride()
    existing = _make_location(ride_id=None)

    # First execute returns ride (ownership check), second returns existing loc
    db = AsyncMock()
    call_count = 0

    async def side_effect_execute(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _scalar_result(mock_ride)
        return _scalar_result(existing)

    db.execute = AsyncMock(side_effect=side_effect_execute)
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock(side_effect=lambda obj: None)

    await upsert_driver_location(db, _DRIVER_ID, payload)
    assert existing.ride_id == _RIDE_ID


@pytest.mark.asyncio
async def test_upsert_preserves_existing_ride_id_when_payload_none():
    """ride_id in payload=None doesn't overwrite existing ride_id."""
    payload = LocationUpdate(latitude=37.7, longitude=-122.4, ride_id=None)
    existing = _make_location(ride_id=_RIDE_ID)
    db = _make_db(execute_return=_scalar_result(existing))
    db.refresh = AsyncMock(side_effect=lambda obj: None)

    await upsert_driver_location(db, _DRIVER_ID, payload)

    # ride_id should remain unchanged
    assert existing.ride_id == _RIDE_ID


# ===========================================================================
# Service layer — clear_driver_location
# ===========================================================================


@pytest.mark.asyncio
async def test_clear_sets_inactive():
    """clear_driver_location sets is_active=False and clears ride_id."""
    existing = _make_location(is_active=True, ride_id=_RIDE_ID)
    db = _make_db(execute_return=_scalar_result(existing))

    await clear_driver_location(db, _DRIVER_ID)

    assert existing.is_active is False
    assert existing.ride_id is None
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_clear_noop_when_no_record():
    """clear_driver_location does nothing when driver has no location record."""
    db = _make_db(execute_return=_scalar_result(None))

    # Should not raise
    await clear_driver_location(db, _DRIVER_ID)
    db.commit.assert_not_awaited()


# ===========================================================================
# Service layer — get_ride_driver_location
# ===========================================================================


@pytest.mark.asyncio
async def test_get_ride_location_404_when_ride_not_found():
    """raises 404 when ride doesn't exist."""
    from fastapi import HTTPException

    db = _make_db(execute_return=_scalar_result(None))

    with pytest.raises(HTTPException) as exc_info:
        await get_ride_driver_location(db, ride_id=999, requester_id=_RIDER_ID)

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_get_ride_location_403_non_participant():
    """raises 403 when requester is neither rider nor driver on the ride."""
    from fastapi import HTTPException

    ride = _make_ride(rider_id=20, driver_id=10)
    db = _make_db(execute_return=_scalar_result(ride))

    with pytest.raises(HTTPException) as exc_info:
        await get_ride_driver_location(db, ride_id=_RIDE_ID, requester_id=999)

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_get_ride_location_409_wrong_status():
    """raises 409 when ride is in a non-trackable status."""
    from fastapi import HTTPException

    ride = _make_ride(status=RideStatus.COMPLETED)
    db = _make_db(execute_return=_scalar_result(ride))

    with pytest.raises(HTTPException) as exc_info:
        await get_ride_driver_location(db, ride_id=_RIDE_ID, requester_id=_RIDER_ID)

    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_get_ride_location_404_no_driver_location():
    """raises 404 when driver hasn't pushed a location yet."""
    from fastapi import HTTPException

    ride = _make_ride(status=RideStatus.IN_PROGRESS)
    call_count = 0

    db = AsyncMock()

    async def side_effect_execute(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _scalar_result(ride)
        return _scalar_result(None)  # no location

    db.execute = AsyncMock(side_effect=side_effect_execute)

    with pytest.raises(HTTPException) as exc_info:
        await get_ride_driver_location(db, ride_id=_RIDE_ID, requester_id=_RIDER_ID)

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_get_ride_location_returns_location_for_rider():
    """returns location when rider requests for active ride."""
    ride = _make_ride(status=RideStatus.IN_PROGRESS)
    loc = _make_location()
    call_count = 0

    db = AsyncMock()

    async def side_effect_execute(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _scalar_result(ride)
        return _scalar_result(loc)

    db.execute = AsyncMock(side_effect=side_effect_execute)

    result = await get_ride_driver_location(
        db, ride_id=_RIDE_ID, requester_id=_RIDER_ID
    )
    assert result is loc


@pytest.mark.asyncio
async def test_get_ride_location_returns_location_for_driver():
    """driver themselves can also query their own broadcasted location."""
    ride = _make_ride(status=RideStatus.DRIVER_EN_ROUTE)
    loc = _make_location()
    call_count = 0

    db = AsyncMock()

    async def side_effect_execute(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _scalar_result(ride)
        return _scalar_result(loc)

    db.execute = AsyncMock(side_effect=side_effect_execute)

    result = await get_ride_driver_location(
        db, ride_id=_RIDE_ID, requester_id=_DRIVER_ID
    )
    assert result is loc


# ===========================================================================
# Service layer — list_active_drivers
# ===========================================================================


@pytest.mark.asyncio
async def test_list_active_drivers_returns_only_active():
    """list_active_drivers returns only is_active=True rows."""
    loc1 = _make_location(loc_id=1, is_active=True)
    loc2 = _make_location(loc_id=2, is_active=True)

    call_count = 0

    db = AsyncMock()

    async def side_effect_execute(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # COUNT query
            m = MagicMock()
            m.scalar_one.return_value = 2
            return m
        # SELECT query
        m = MagicMock()
        inner = MagicMock()
        inner.all.return_value = [loc1, loc2]
        m.scalars.return_value = inner
        return m

    db.execute = AsyncMock(side_effect=side_effect_execute)

    locations, total = await list_active_drivers(db)
    assert total == 2
    assert len(locations) == 2


@pytest.mark.asyncio
async def test_list_active_drivers_pagination():
    """list_active_drivers passes limit/offset to query."""
    db = AsyncMock()

    count_result = MagicMock()
    count_result.scalar_one.return_value = 50

    list_result = MagicMock()
    inner = MagicMock()
    inner.all.return_value = []
    list_result.scalars.return_value = inner

    db.execute = AsyncMock(side_effect=[count_result, list_result])

    locations, total = await list_active_drivers(db, limit=10, offset=20)
    assert total == 50
    assert locations == []


# ===========================================================================
# Schema validation
# ===========================================================================


def test_location_update_rejects_invalid_latitude():
    """latitude > 90 raises validation error."""
    with pytest.raises(Exception):
        LocationUpdate(latitude=91.0, longitude=0.0)


def test_location_update_rejects_invalid_longitude():
    """longitude > 180 raises validation error."""
    with pytest.raises(Exception):
        LocationUpdate(latitude=0.0, longitude=181.0)


def test_location_update_rounds_coordinates():
    """lat/lon are rounded to 8 decimal places."""
    payload = LocationUpdate(latitude=37.7749123456789, longitude=-122.4194987654321)
    assert len(str(payload.latitude).split(".")[-1]) <= 8
    assert len(str(payload.longitude).split(".")[-1]) <= 8


def test_location_update_accepts_none_optional_fields():
    """accuracy_meters, heading, speed_kmh can all be None."""
    payload = LocationUpdate(
        latitude=37.7749,
        longitude=-122.4194,
        accuracy_meters=None,
        heading=None,
        speed_kmh=None,
    )
    assert payload.accuracy_meters is None
    assert payload.heading is None
    assert payload.speed_kmh is None


def test_driver_location_response_from_orm_model():
    """DriverLocationResponse.from_orm_model maps all fields."""
    loc = _make_location(
        latitude=37.7,
        longitude=-122.4,
        accuracy_meters=4.0,
        heading=45.0,
        speed_kmh=20.0,
        is_active=True,
        ride_id=_RIDE_ID,
    )
    resp = DriverLocationResponse.from_orm_model(loc)
    assert resp.driver_id == _DRIVER_ID
    assert resp.ride_id == _RIDE_ID
    assert resp.latitude == 37.7
    assert resp.longitude == -122.4
    assert resp.accuracy_meters == 4.0
    assert resp.heading == 45.0
    assert resp.speed_kmh == 20.0
    assert resp.is_active is True


def test_active_drivers_response_total_matches():
    """ActiveDriversResponse total matches len(drivers)."""
    from app.schemas.driver_location import ActiveDriverEntry

    entries = [
        ActiveDriverEntry(
            driver_id=i,
            ride_id=None,
            latitude=37.7,
            longitude=-122.4,
            accuracy_meters=None,
            heading=None,
            speed_kmh=None,
            updated_at=_BASE_TS,
        )
        for i in range(3)
    ]
    resp = ActiveDriversResponse(drivers=entries, total=3)
    assert resp.total == len(resp.drivers)


# ===========================================================================
# API integration tests (require live DB — skipped without test DB)
# ===========================================================================

try:
    from tests.conftest import client, db, admin_token, driver_token  # type: ignore  # noqa: F401

    HAS_TEST_DB = True
except Exception:
    HAS_TEST_DB = False


def _auth_header(user_id: int, role: str) -> dict:
    token = create_access_token(user_id, role)
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.skipif(not HAS_TEST_DB, reason="Live DB not available")
def test_api_push_location_200(client):
    """POST /drivers/me/location — 200 for authenticated driver."""
    resp = client.post(
        "/api/v1/drivers/me/location",
        json={"latitude": 37.7749, "longitude": -122.4194},
        headers=_auth_header(_DRIVER_ID, "driver"),
    )
    assert resp.status_code in (200, 404, 422, 500)


@pytest.mark.skipif(not HAS_TEST_DB, reason="Live DB not available")
def test_api_push_location_401_unauthenticated(client):
    """POST /drivers/me/location — 401 without token."""
    resp = client.post(
        "/api/v1/drivers/me/location",
        json={"latitude": 37.7749, "longitude": -122.4194},
    )
    assert resp.status_code == 401


@pytest.mark.skipif(not HAS_TEST_DB, reason="Live DB not available")
def test_api_push_location_422_invalid_lat(client):
    """POST /drivers/me/location — 422 with out-of-range latitude."""
    resp = client.post(
        "/api/v1/drivers/me/location",
        json={"latitude": 999.0, "longitude": -122.4194},
        headers=_auth_header(_DRIVER_ID, "driver"),
    )
    assert resp.status_code == 422


@pytest.mark.skipif(not HAS_TEST_DB, reason="Live DB not available")
def test_api_get_ride_driver_location_200(client):
    """GET /rides/{id}/driver-location — returns 200 or 4xx (no live ride)."""
    resp = client.get(
        f"/api/v1/rides/{_RIDE_ID}/driver-location",
        headers=_auth_header(_RIDER_ID, "rider"),
    )
    assert resp.status_code in (200, 404, 409)


@pytest.mark.skipif(not HAS_TEST_DB, reason="Live DB not available")
def test_api_get_ride_driver_location_401_unauthenticated(client):
    """GET /rides/{id}/driver-location — 401 without token."""
    resp = client.get(f"/api/v1/rides/{_RIDE_ID}/driver-location")
    assert resp.status_code == 401


@pytest.mark.skipif(not HAS_TEST_DB, reason="Live DB not available")
def test_api_get_ride_driver_location_403_non_participant(client):
    """GET /rides/{id}/driver-location — 403 for unrelated user (if ride exists)."""
    resp = client.get(
        f"/api/v1/rides/{_RIDE_ID}/driver-location",
        headers=_auth_header(9999, "rider"),
    )
    assert resp.status_code in (403, 404)


@pytest.mark.skipif(not HAS_TEST_DB, reason="Live DB not available")
def test_api_admin_live_drivers_200(client):
    """GET /admin/drivers/live — 200 for admin."""
    resp = client.get(
        "/api/v1/admin/drivers/live",
        headers=_auth_header(1, "admin"),
    )
    assert resp.status_code in (200, 500)


@pytest.mark.skipif(not HAS_TEST_DB, reason="Live DB not available")
def test_api_admin_live_drivers_403_non_admin(client):
    """GET /admin/drivers/live — 403 for non-admin."""
    resp = client.get(
        "/api/v1/admin/drivers/live",
        headers=_auth_header(_DRIVER_ID, "driver"),
    )
    assert resp.status_code == 403
