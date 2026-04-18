"""Tests for GET /admin/safety/route-deviation-incidents.

Covers:
Schema:
  1.  RouteDeviationIncidentEntry — required fields present
  2.  RouteDeviationIncidentEntry — rider_name and driver_name are optional
  3.  RouteDeviationIncidentEntry — driver_id is optional (nullable)
  4.  RouteDeviationIncidentListResponse — wraps list with pagination fields

Endpoint — mocked DB:
  5.  401 when no auth token provided
  6.  200 with empty list when no route deviation incidents exist
  7.  200 returns incident fields correctly (ride_id, flagged_at, status, addresses)
  8.  rider_name and driver_name populated from joined relations
  9.  driver_name is None when driver not loaded (anonymous driver)
  10. period=week fires two DB queries (count + rows)
  11. period=month fires two DB queries
  12. period=year fires two DB queries
  13. period=all fires two DB queries (no period clause)
  14. pagination — page and per_page reflected in response
  15. total count comes from count query, not len(rides)
  16. multiple incidents all appear in response
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.schemas.admin import RouteDeviationIncidentEntry, RouteDeviationIncidentListResponse

NOW = datetime(2026, 4, 18, 12, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ride(
    ride_id: int = 1,
    rider_id: int = 10,
    driver_id: int | None = 20,
    rider_name: str | None = "Alice",
    driver_name: str | None = "Bob",
    pickup: str = "123 Main St",
    dropoff: str = "456 Oak Ave",
    status: str = "completed",
    route_deviation_flagged_at: datetime = NOW,
    requested_at: datetime = NOW - timedelta(hours=1),
) -> MagicMock:
    ride = MagicMock()
    ride.id = ride_id
    ride.rider_id = rider_id
    ride.driver_id = driver_id
    ride.pickup_address = pickup
    ride.dropoff_address = dropoff
    ride.status = MagicMock()
    ride.status.value = status
    ride.route_deviation_flagged_at = route_deviation_flagged_at
    ride.requested_at = requested_at

    rider = MagicMock()
    rider.name = rider_name
    ride.rider = rider

    if driver_name is not None:
        driver = MagicMock()
        driver.name = driver_name
        ride.driver = driver
    else:
        ride.driver = None

    return ride


def _make_db(rides: list, total: int | None = None):
    """Build a mock AsyncSession returning given rides."""
    db = AsyncMock()

    count_result = MagicMock()
    count_result.scalar.return_value = total if total is not None else len(rides)

    rows_result = MagicMock()
    rows_result.unique.return_value.scalars.return_value.all.return_value = rides

    db.execute = AsyncMock(side_effect=[count_result, rows_result])
    return db


# ---------------------------------------------------------------------------
# 1–4: Schema validation
# ---------------------------------------------------------------------------


class TestRouteDeviationIncidentSchemas:
    def test_entry_required_fields(self):
        entry = RouteDeviationIncidentEntry(
            ride_id=1,
            rider_id=10,
            driver_id=20,
            pickup_address="A",
            dropoff_address="B",
            status="completed",
            route_deviation_flagged_at=NOW,
            requested_at=NOW - timedelta(hours=1),
        )
        assert entry.ride_id == 1
        assert entry.rider_id == 10
        assert entry.route_deviation_flagged_at == NOW

    def test_entry_optional_names_default_none(self):
        entry = RouteDeviationIncidentEntry(
            ride_id=1,
            rider_id=10,
            pickup_address="A",
            dropoff_address="B",
            status="in_progress",
            route_deviation_flagged_at=NOW,
            requested_at=NOW - timedelta(hours=1),
        )
        assert entry.rider_name is None
        assert entry.driver_name is None

    def test_entry_driver_id_optional(self):
        entry = RouteDeviationIncidentEntry(
            ride_id=2,
            rider_id=5,
            driver_id=None,
            pickup_address="X",
            dropoff_address="Y",
            status="completed",
            route_deviation_flagged_at=NOW,
            requested_at=NOW,
        )
        assert entry.driver_id is None

    def test_list_response_structure(self):
        resp = RouteDeviationIncidentListResponse(
            incidents=[],
            total=0,
            page=1,
            per_page=20,
        )
        assert resp.total == 0
        assert resp.incidents == []
        assert resp.page == 1
        assert resp.per_page == 20


# ---------------------------------------------------------------------------
# 5: HTTP auth test
# ---------------------------------------------------------------------------


class TestAdminRouteDeviationIncidentsAuth:
    @pytest.mark.asyncio
    async def test_requires_authentication(self):
        from httpx import ASGITransport, AsyncClient
        from app.main import app

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/admin/safety/route-deviation-incidents")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# 6–16: Endpoint unit tests (direct call with mocked DB)
# ---------------------------------------------------------------------------


class TestAdminRouteDeviationIncidentsEndpoint:
    @pytest.mark.asyncio
    async def test_empty_list_when_no_incidents(self):
        from app.api.v1.admin import list_route_deviation_incidents
        from app.models.user import User

        admin = MagicMock(spec=User)
        db = _make_db([], total=0)
        resp = await list_route_deviation_incidents(db=db, _admin=admin, page=1, per_page=20)

        assert resp.total == 0
        assert resp.incidents == []

    @pytest.mark.asyncio
    async def test_returns_incident_fields_correctly(self):
        from app.api.v1.admin import list_route_deviation_incidents
        from app.models.user import User

        admin = MagicMock(spec=User)
        ride = _make_ride(
            ride_id=7,
            rider_id=10,
            driver_id=20,
            pickup="Airport",
            dropoff="Hotel",
            status="completed",
            route_deviation_flagged_at=NOW,
        )
        db = _make_db([ride], total=1)
        resp = await list_route_deviation_incidents(db=db, _admin=admin, page=1, per_page=20)

        assert resp.total == 1
        assert len(resp.incidents) == 1
        inc = resp.incidents[0]
        assert inc.ride_id == 7
        assert inc.rider_id == 10
        assert inc.driver_id == 20
        assert inc.pickup_address == "Airport"
        assert inc.dropoff_address == "Hotel"
        assert inc.status == "completed"
        assert inc.route_deviation_flagged_at == NOW

    @pytest.mark.asyncio
    async def test_rider_and_driver_names_populated(self):
        from app.api.v1.admin import list_route_deviation_incidents
        from app.models.user import User

        admin = MagicMock(spec=User)
        ride = _make_ride(rider_name="Carol", driver_name="Dave")
        db = _make_db([ride])
        resp = await list_route_deviation_incidents(db=db, _admin=admin, page=1, per_page=20)

        inc = resp.incidents[0]
        assert inc.rider_name == "Carol"
        assert inc.driver_name == "Dave"

    @pytest.mark.asyncio
    async def test_driver_name_none_when_no_driver(self):
        from app.api.v1.admin import list_route_deviation_incidents
        from app.models.user import User

        admin = MagicMock(spec=User)
        ride = _make_ride(driver_id=None, driver_name=None)
        db = _make_db([ride])
        resp = await list_route_deviation_incidents(db=db, _admin=admin, page=1, per_page=20)

        assert resp.incidents[0].driver_id is None
        assert resp.incidents[0].driver_name is None

    @pytest.mark.asyncio
    async def test_period_week_fires_two_db_queries(self):
        from app.api.v1.admin import list_route_deviation_incidents
        from app.models.user import User

        admin = MagicMock(spec=User)
        db = _make_db([], total=0)
        await list_route_deviation_incidents(db=db, _admin=admin, period="week", page=1, per_page=20)
        assert db.execute.call_count == 2

    @pytest.mark.asyncio
    async def test_period_month_fires_two_db_queries(self):
        from app.api.v1.admin import list_route_deviation_incidents
        from app.models.user import User

        admin = MagicMock(spec=User)
        db = _make_db([], total=0)
        await list_route_deviation_incidents(db=db, _admin=admin, period="month", page=1, per_page=20)
        assert db.execute.call_count == 2

    @pytest.mark.asyncio
    async def test_period_year_fires_two_db_queries(self):
        from app.api.v1.admin import list_route_deviation_incidents
        from app.models.user import User

        admin = MagicMock(spec=User)
        db = _make_db([], total=0)
        await list_route_deviation_incidents(db=db, _admin=admin, period="year", page=1, per_page=20)
        assert db.execute.call_count == 2

    @pytest.mark.asyncio
    async def test_period_all_fires_two_db_queries(self):
        from app.api.v1.admin import list_route_deviation_incidents
        from app.models.user import User

        admin = MagicMock(spec=User)
        db = _make_db([], total=0)
        await list_route_deviation_incidents(db=db, _admin=admin, period="all", page=1, per_page=20)
        assert db.execute.call_count == 2

    @pytest.mark.asyncio
    async def test_pagination_reflected_in_response(self):
        from app.api.v1.admin import list_route_deviation_incidents
        from app.models.user import User

        admin = MagicMock(spec=User)
        db = _make_db([], total=42)
        resp = await list_route_deviation_incidents(db=db, _admin=admin, page=3, per_page=10)

        assert resp.page == 3
        assert resp.per_page == 10
        assert resp.total == 42

    @pytest.mark.asyncio
    async def test_total_count_from_db_query(self):
        """total reflects the count query result, not len(incidents)."""
        from app.api.v1.admin import list_route_deviation_incidents
        from app.models.user import User

        admin = MagicMock(spec=User)
        db = _make_db([_make_ride()], total=50)
        resp = await list_route_deviation_incidents(db=db, _admin=admin, page=1, per_page=20)

        assert resp.total == 50
        assert len(resp.incidents) == 1

    @pytest.mark.asyncio
    async def test_multiple_incidents_returned(self):
        from app.api.v1.admin import list_route_deviation_incidents
        from app.models.user import User

        admin = MagicMock(spec=User)
        rides = [
            _make_ride(ride_id=1, route_deviation_flagged_at=NOW),
            _make_ride(ride_id=2, route_deviation_flagged_at=NOW - timedelta(hours=2)),
            _make_ride(ride_id=3, route_deviation_flagged_at=NOW - timedelta(days=1)),
        ]
        db = _make_db(rides, total=3)
        resp = await list_route_deviation_incidents(db=db, _admin=admin, page=1, per_page=20)

        assert resp.total == 3
        assert len(resp.incidents) == 3
        ids = {inc.ride_id for inc in resp.incidents}
        assert ids == {1, 2, 3}
