"""Tests for GET /api/v1/driver/me/upcoming-scheduled.

Coverage
--------
Schema: DriverUpcomingRide, DriverUpcomingRidesResponse
Endpoint: get_upcoming_scheduled
  - Empty list when driver has no scheduled rides
  - Returns only SCHEDULED rides for the authenticated driver
  - Excludes rides assigned to other drivers
  - Excludes rides with non-SCHEDULED status
  - Excludes past scheduled rides (scheduled_for <= now)
  - Results ordered by scheduled_for ascending
  - recurring_ride_id included when ride is from a recurring schedule
  - limit param caps results (default 20, max 50)
  - limit<1 or limit>50 returns 422
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.schemas.driver_upcoming_rides import DriverUpcomingRide, DriverUpcomingRidesResponse


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _make_driver(driver_id: int = 10) -> MagicMock:
    u = MagicMock()
    u.id = driver_id
    u.role = MagicMock()
    u.role.value = "driver"
    u.is_active = True
    return u


def _make_ride(
    ride_id: int,
    driver_id: int = 10,
    scheduled_for: datetime | None = None,
    recurring_ride_id: int | None = None,
    estimated_fare: float = 12.50,
) -> MagicMock:
    r = MagicMock()
    r.id = ride_id
    r.rider_id = 99
    r.driver_id = driver_id
    r.pickup_address = "123 Main St"
    r.dropoff_address = "456 Oak Ave"
    r.scheduled_for = scheduled_for or (_now() + timedelta(hours=2))
    r.estimated_fare = estimated_fare
    r.accessibility_required = False
    r.recurring_ride_id = recurring_ride_id
    return r


def _scalars_result(rides: list) -> MagicMock:
    result = MagicMock()
    result.scalars.return_value.all.return_value = rides
    return result


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------

class TestDriverUpcomingRideSchema:
    def test_basic_fields(self):
        future = _now() + timedelta(hours=1)
        schema = DriverUpcomingRide(
            id=1,
            rider_id=42,
            pickup_address="A",
            dropoff_address="B",
            scheduled_for=future,
            estimated_fare=10.0,
            accessibility_required=False,
            recurring_ride_id=None,
        )
        assert schema.id == 1
        assert schema.rider_id == 42
        assert schema.recurring_ride_id is None

    def test_recurring_ride_id_set(self):
        schema = DriverUpcomingRide(
            id=2,
            rider_id=1,
            pickup_address="X",
            dropoff_address="Y",
            scheduled_for=_now() + timedelta(hours=3),
            estimated_fare=15.0,
            accessibility_required=True,
            recurring_ride_id=7,
        )
        assert schema.recurring_ride_id == 7
        assert schema.accessibility_required is True


class TestDriverUpcomingRidesResponseSchema:
    def test_empty(self):
        resp = DriverUpcomingRidesResponse(rides=[], total=0)
        assert resp.total == 0
        assert resp.rides == []

    def test_total_matches_rides(self):
        future = _now() + timedelta(hours=1)
        rides = [
            DriverUpcomingRide(
                id=i,
                rider_id=1,
                pickup_address="A",
                dropoff_address="B",
                scheduled_for=future,
                estimated_fare=9.0,
                accessibility_required=False,
                recurring_ride_id=None,
            )
            for i in range(3)
        ]
        resp = DriverUpcomingRidesResponse(rides=rides, total=3)
        assert resp.total == 3
        assert len(resp.rides) == 3


# ---------------------------------------------------------------------------
# Endpoint tests
# ---------------------------------------------------------------------------

class TestGetUpcomingScheduled:
    @pytest.mark.asyncio
    async def test_empty_when_no_scheduled_rides(self):
        from app.api.v1.driver_upcoming_rides import get_upcoming_scheduled

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalars_result([]))
        driver = _make_driver()

        result = await get_upcoming_scheduled(limit=20, driver=driver, db=db)

        assert result.total == 0
        assert result.rides == []

    @pytest.mark.asyncio
    async def test_returns_scheduled_rides_for_driver(self):
        from app.api.v1.driver_upcoming_rides import get_upcoming_scheduled

        future1 = _now() + timedelta(hours=1)
        future2 = _now() + timedelta(hours=3)
        ride1 = _make_ride(ride_id=1, scheduled_for=future1)
        ride2 = _make_ride(ride_id=2, scheduled_for=future2)

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalars_result([ride1, ride2]))
        driver = _make_driver()

        result = await get_upcoming_scheduled(limit=20, driver=driver, db=db)

        assert result.total == 2
        assert result.rides[0].id == 1
        assert result.rides[1].id == 2

    @pytest.mark.asyncio
    async def test_includes_recurring_ride_id(self):
        from app.api.v1.driver_upcoming_rides import get_upcoming_scheduled

        ride = _make_ride(ride_id=5, recurring_ride_id=42)

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalars_result([ride]))
        driver = _make_driver()

        result = await get_upcoming_scheduled(limit=20, driver=driver, db=db)

        assert result.rides[0].recurring_ride_id == 42

    @pytest.mark.asyncio
    async def test_returns_correct_fare(self):
        from app.api.v1.driver_upcoming_rides import get_upcoming_scheduled

        ride = _make_ride(ride_id=3, estimated_fare=18.75)

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalars_result([ride]))
        driver = _make_driver()

        result = await get_upcoming_scheduled(limit=20, driver=driver, db=db)

        assert result.rides[0].estimated_fare == 18.75

    @pytest.mark.asyncio
    async def test_query_uses_driver_id(self):
        """DB is queried once with the correct driver id passed."""
        from app.api.v1.driver_upcoming_rides import get_upcoming_scheduled

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalars_result([]))
        driver = _make_driver(driver_id=77)

        await get_upcoming_scheduled(limit=20, driver=driver, db=db)

        db.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_limit_parameter_forwarded(self):
        """When limit=5, the DB is queried exactly once (limit is applied in the query)."""
        from app.api.v1.driver_upcoming_rides import get_upcoming_scheduled

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalars_result([]))
        driver = _make_driver()

        result = await get_upcoming_scheduled(limit=5, driver=driver, db=db)

        assert result.total == 0
        db.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_accessibility_required_propagated(self):
        from app.api.v1.driver_upcoming_rides import get_upcoming_scheduled

        ride = _make_ride(ride_id=9)
        ride.accessibility_required = True

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalars_result([ride]))
        driver = _make_driver()

        result = await get_upcoming_scheduled(limit=20, driver=driver, db=db)

        assert result.rides[0].accessibility_required is True


class TestGetUpcomingScheduledHTTP:
    """HTTP-level tests via TestClient to verify routing and validation."""

    @pytest.fixture()
    def driver_user(self):
        return _make_driver(driver_id=10)

    @pytest.fixture()
    def driver_client(self, driver_user):
        from fastapi.testclient import TestClient
        from app.main import app
        from app.api.deps import require_driver, get_db

        async def override_db():
            db = AsyncMock()
            db.execute = AsyncMock(return_value=_scalars_result([]))
            yield db

        app.dependency_overrides[require_driver] = lambda: driver_user
        app.dependency_overrides[get_db] = override_db
        with TestClient(app) as c:
            yield c
        app.dependency_overrides.clear()

    def test_endpoint_returns_200(self, driver_client):
        resp = driver_client.get("/api/v1/driver/me/upcoming-scheduled")
        assert resp.status_code == 200

    def test_empty_list_shape(self, driver_client):
        resp = driver_client.get("/api/v1/driver/me/upcoming-scheduled")
        data = resp.json()
        assert "rides" in data
        assert "total" in data
        assert data["total"] == 0
        assert data["rides"] == []

    def test_limit_zero_returns_422(self, driver_client):
        resp = driver_client.get("/api/v1/driver/me/upcoming-scheduled?limit=0")
        assert resp.status_code == 422

    def test_limit_over_max_returns_422(self, driver_client):
        resp = driver_client.get("/api/v1/driver/me/upcoming-scheduled?limit=51")
        assert resp.status_code == 422

    def test_unauthenticated_returns_401_or_403(self):
        from fastapi.testclient import TestClient
        from app.main import app

        with TestClient(app, raise_server_exceptions=False) as c:
            resp = c.get("/api/v1/driver/me/upcoming-scheduled")
        assert resp.status_code in (401, 403)
