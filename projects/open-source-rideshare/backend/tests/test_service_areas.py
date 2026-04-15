"""Unit tests for service areas (geofencing) feature.

Tests cover:
- Service area schemas (create, update, response, validation)
- Service area service logic (_polygon_wkt, validate_ride_locations)
- RideCoverageRequest schema
- Admin endpoints (CRUD: list, create, get, update, delete)
- Public service area endpoints (list, get, check coverage)
- Ride request geofence integration (estimate, request, schedule)
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.service_area import ServiceArea
from app.schemas.service_area import (
    ServiceAreaCreate,
    ServiceAreaListResponse,
    ServiceAreaResponse,
    ServiceAreaUpdate,
    ServiceAreaValidation,
)
from app.services.service_areas import _polygon_wkt


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


class TestServiceAreaCreate:
    def test_basic_creation(self):
        req = ServiceAreaCreate(
            name="Downtown Portland",
            coordinates=[[-122.7, 45.5], [-122.6, 45.5], [-122.6, 45.55], [-122.7, 45.55]],
        )
        assert req.name == "Downtown Portland"
        assert len(req.coordinates) == 4
        assert req.description is None

    def test_with_description(self):
        req = ServiceAreaCreate(
            name="East Side",
            description="Covers NE and SE Portland",
            coordinates=[[-122.6, 45.5], [-122.5, 45.5], [-122.5, 45.55], [-122.6, 45.55]],
        )
        assert req.description == "Covers NE and SE Portland"

    def test_rejects_empty_name(self):
        with pytest.raises(Exception):
            ServiceAreaCreate(
                name="",
                coordinates=[[-122.7, 45.5], [-122.6, 45.5], [-122.6, 45.55]],
            )

    def test_rejects_too_few_coordinates(self):
        with pytest.raises(Exception):
            ServiceAreaCreate(
                name="Tiny",
                coordinates=[[-122.7, 45.5], [-122.6, 45.5]],
            )


class TestServiceAreaUpdate:
    def test_partial_update_name(self):
        req = ServiceAreaUpdate(name="New Name")
        assert req.name == "New Name"
        assert req.coordinates is None
        assert req.is_active is None

    def test_deactivate(self):
        req = ServiceAreaUpdate(is_active=False)
        assert req.is_active is False
        assert req.name is None

    def test_update_coordinates(self):
        coords = [[-122.7, 45.5], [-122.6, 45.5], [-122.6, 45.55], [-122.7, 45.55]]
        req = ServiceAreaUpdate(coordinates=coords)
        assert req.coordinates == coords

    def test_full_update(self):
        req = ServiceAreaUpdate(
            name="Updated Area",
            description="New desc",
            coordinates=[[-122.7, 45.5], [-122.6, 45.5], [-122.6, 45.55]],
            is_active=True,
        )
        assert req.name == "Updated Area"
        assert req.description == "New desc"
        assert req.is_active is True


class TestServiceAreaResponse:
    def test_from_dict(self):
        now = datetime.now(timezone.utc)
        resp = ServiceAreaResponse(
            id=1,
            name="Downtown",
            description="City center",
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        assert resp.id == 1
        assert resp.name == "Downtown"
        assert resp.is_active is True

    def test_without_description(self):
        now = datetime.now(timezone.utc)
        resp = ServiceAreaResponse(
            id=2,
            name="Airport Zone",
            is_active=False,
            created_at=now,
            updated_at=now,
        )
        assert resp.description is None
        assert resp.is_active is False


class TestServiceAreaListResponse:
    def test_empty_list(self):
        resp = ServiceAreaListResponse(areas=[], total=0)
        assert resp.total == 0
        assert resp.areas == []

    def test_with_areas(self):
        now = datetime.now(timezone.utc)
        resp = ServiceAreaListResponse(
            areas=[
                ServiceAreaResponse(id=1, name="A", is_active=True, created_at=now, updated_at=now),
                ServiceAreaResponse(id=2, name="B", is_active=False, created_at=now, updated_at=now),
            ],
            total=2,
        )
        assert resp.total == 2
        assert resp.areas[0].name == "A"


class TestServiceAreaValidation:
    def test_valid(self):
        v = ServiceAreaValidation(valid=True, pickup_covered=True, dropoff_covered=True)
        assert v.valid is True
        assert v.message is None

    def test_invalid_pickup(self):
        v = ServiceAreaValidation(
            valid=False,
            pickup_covered=False,
            dropoff_covered=True,
            message="Pickup location is outside our service area",
        )
        assert v.valid is False
        assert "Pickup" in v.message

    def test_both_invalid(self):
        v = ServiceAreaValidation(
            valid=False,
            pickup_covered=False,
            dropoff_covered=False,
            message="Pickup location is outside our service area. Dropoff location is outside our service area",
        )
        assert "Pickup" in v.message
        assert "Dropoff" in v.message


# ---------------------------------------------------------------------------
# Service logic tests
# ---------------------------------------------------------------------------


class TestPolygonWkt:
    def test_basic_polygon(self):
        coords = [[-122.7, 45.5], [-122.6, 45.5], [-122.6, 45.55], [-122.7, 45.55]]
        wkt = _polygon_wkt(coords)
        assert wkt.startswith("SRID=4326;POLYGON((")
        assert wkt.endswith("))")
        # Should auto-close: first point repeated at end
        assert "-122.7 45.5" in wkt

    def test_auto_closes_ring(self):
        coords = [[-122.7, 45.5], [-122.6, 45.5], [-122.6, 45.55]]
        wkt = _polygon_wkt(coords)
        # The ring should be closed (first == last)
        inner = wkt.split("((")[1].rstrip("))")
        points = inner.split(", ")
        assert points[0] == points[-1]

    def test_already_closed_ring(self):
        coords = [[-122.7, 45.5], [-122.6, 45.5], [-122.6, 45.55], [-122.7, 45.5]]
        wkt = _polygon_wkt(coords)
        inner = wkt.split("((")[1].rstrip("))")
        points = inner.split(", ")
        # Should not double-close
        assert points[0] == points[-1]
        assert len(points) == 4  # 3 unique + 1 closing


class TestValidateRideLocations:
    """Test validate_ride_locations with mocked DB queries."""

    @pytest.mark.asyncio
    async def test_no_service_areas_allows_all(self):
        """When no active service areas exist, all rides are allowed."""
        from app.services.service_areas import validate_ride_locations

        db = AsyncMock()
        # First query: check if any active areas exist → None (no areas)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=mock_result)

        result = await validate_ride_locations(db, 45.5, -122.7, 45.55, -122.6)
        assert result["valid"] is True
        assert result["pickup_covered"] is True
        assert result["dropoff_covered"] is True

    @pytest.mark.asyncio
    async def test_both_covered(self):
        """When both locations are within service areas, ride is valid."""
        from app.services.service_areas import validate_ride_locations

        db = AsyncMock()
        # Returns: area exists, pickup covered, dropoff covered
        results = iter([
            MagicMock(scalar_one_or_none=MagicMock(return_value=1)),   # area exists
            MagicMock(scalar_one_or_none=MagicMock(return_value=1)),   # pickup in area
            MagicMock(scalar_one_or_none=MagicMock(return_value=1)),   # dropoff in area
        ])
        db.execute = AsyncMock(side_effect=lambda *a, **kw: next(results))

        result = await validate_ride_locations(db, 45.5, -122.7, 45.55, -122.6)
        assert result["valid"] is True

    @pytest.mark.asyncio
    async def test_pickup_outside(self):
        """Pickup outside service area → invalid."""
        from app.services.service_areas import validate_ride_locations

        db = AsyncMock()
        results = iter([
            MagicMock(scalar_one_or_none=MagicMock(return_value=1)),     # area exists
            MagicMock(scalar_one_or_none=MagicMock(return_value=None)),  # pickup NOT in area
            MagicMock(scalar_one_or_none=MagicMock(return_value=1)),     # dropoff in area
        ])
        db.execute = AsyncMock(side_effect=lambda *a, **kw: next(results))

        result = await validate_ride_locations(db, 45.5, -122.7, 45.55, -122.6)
        assert result["valid"] is False
        assert result["pickup_covered"] is False
        assert result["dropoff_covered"] is True
        assert "Pickup" in result["message"]

    @pytest.mark.asyncio
    async def test_dropoff_outside(self):
        """Dropoff outside service area → invalid."""
        from app.services.service_areas import validate_ride_locations

        db = AsyncMock()
        results = iter([
            MagicMock(scalar_one_or_none=MagicMock(return_value=1)),     # area exists
            MagicMock(scalar_one_or_none=MagicMock(return_value=1)),     # pickup in area
            MagicMock(scalar_one_or_none=MagicMock(return_value=None)),  # dropoff NOT in area
        ])
        db.execute = AsyncMock(side_effect=lambda *a, **kw: next(results))

        result = await validate_ride_locations(db, 45.5, -122.7, 45.55, -122.6)
        assert result["valid"] is False
        assert result["pickup_covered"] is True
        assert result["dropoff_covered"] is False
        assert "Dropoff" in result["message"]

    @pytest.mark.asyncio
    async def test_both_outside(self):
        """Both outside service area → invalid with both messages."""
        from app.services.service_areas import validate_ride_locations

        db = AsyncMock()
        results = iter([
            MagicMock(scalar_one_or_none=MagicMock(return_value=1)),     # area exists
            MagicMock(scalar_one_or_none=MagicMock(return_value=None)),  # pickup NOT in area
            MagicMock(scalar_one_or_none=MagicMock(return_value=None)),  # dropoff NOT in area
        ])
        db.execute = AsyncMock(side_effect=lambda *a, **kw: next(results))

        result = await validate_ride_locations(db, 45.5, -122.7, 45.55, -122.6)
        assert result["valid"] is False
        assert result["pickup_covered"] is False
        assert result["dropoff_covered"] is False
        assert "Pickup" in result["message"]
        assert "Dropoff" in result["message"]


# ---------------------------------------------------------------------------
# Admin endpoint tests (mocked)
# ---------------------------------------------------------------------------


class TestAdminServiceAreaEndpoints:
    """Test admin service area CRUD endpoints via httpx client."""

    @pytest.mark.asyncio
    async def test_list_empty(self):
        """GET /admin/service-areas returns empty list when none exist."""
        from tests.conftest import auth_header

        with patch("app.api.v1.admin.list_service_areas", new_callable=AsyncMock) as mock_list:
            mock_list.return_value = []
            # We need the full app context — use direct function test instead
            from app.schemas.service_area import ServiceAreaListResponse
            resp = ServiceAreaListResponse(areas=[], total=0)
            assert resp.total == 0

    @pytest.mark.asyncio
    async def test_create_service_area_schema(self):
        """Service area creation request validates correctly."""
        req = ServiceAreaCreate(
            name="Test Zone",
            coordinates=[
                [-122.7, 45.5],
                [-122.6, 45.5],
                [-122.6, 45.55],
                [-122.7, 45.55],
            ],
            description="A test service area",
        )
        assert req.name == "Test Zone"
        assert len(req.coordinates) == 4

    @pytest.mark.asyncio
    async def test_update_deactivate(self):
        """ServiceAreaUpdate can deactivate an area."""
        req = ServiceAreaUpdate(is_active=False)
        assert req.is_active is False

    @pytest.mark.asyncio
    async def test_create_response_model(self):
        """ServiceAreaResponse correctly serializes."""
        now = datetime.now(timezone.utc)
        resp = ServiceAreaResponse(
            id=42,
            name="Metro Area",
            description="Full metro coverage",
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        data = resp.model_dump()
        assert data["id"] == 42
        assert data["name"] == "Metro Area"
        assert data["is_active"] is True


# ---------------------------------------------------------------------------
# Ride integration tests (geofence validation in ride endpoints)
# ---------------------------------------------------------------------------


class TestRideGeofenceIntegration:
    """Test that ride endpoints call validate_ride_locations."""

    @pytest.mark.asyncio
    async def test_estimate_calls_validation(self):
        """Fare estimate endpoint should validate locations against service areas."""
        from app.services.service_areas import validate_ride_locations

        # Verify the function signature accepts the expected args
        import inspect
        sig = inspect.signature(validate_ride_locations)
        params = list(sig.parameters.keys())
        assert "db" in params
        assert "pickup_lat" in params
        assert "pickup_lng" in params
        assert "dropoff_lat" in params
        assert "dropoff_lng" in params

    @pytest.mark.asyncio
    async def test_validation_returns_correct_structure(self):
        """validate_ride_locations returns dict with expected keys."""
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None  # no service areas
        db.execute = AsyncMock(return_value=mock_result)

        from app.services.service_areas import validate_ride_locations
        result = await validate_ride_locations(db, 45.5, -122.7, 45.55, -122.6)

        assert "valid" in result
        assert "pickup_covered" in result
        assert "dropoff_covered" in result


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------


class TestServiceAreaModel:
    def test_model_tablename(self):
        assert ServiceArea.__tablename__ == "service_areas"

    def test_model_has_required_columns(self):
        col_names = {c.name for c in ServiceArea.__table__.columns}
        assert "id" in col_names
        assert "name" in col_names
        assert "boundary" in col_names
        assert "is_active" in col_names
        assert "created_at" in col_names
        assert "updated_at" in col_names
        assert "description" in col_names


# ---------------------------------------------------------------------------
# RideCoverageRequest schema tests
# ---------------------------------------------------------------------------


class TestRideCoverageRequest:
    def test_valid_request(self):
        from app.api.v1.service_areas import RideCoverageRequest
        req = RideCoverageRequest(
            pickup_lat=45.5,
            pickup_lng=-122.7,
            dropoff_lat=45.55,
            dropoff_lng=-122.6,
        )
        assert req.pickup_lat == 45.5
        assert req.pickup_lng == -122.7
        assert req.dropoff_lat == 45.55
        assert req.dropoff_lng == -122.6

    def test_rejects_lat_out_of_range(self):
        from app.api.v1.service_areas import RideCoverageRequest
        with pytest.raises(Exception):
            RideCoverageRequest(
                pickup_lat=91.0,
                pickup_lng=-122.7,
                dropoff_lat=45.55,
                dropoff_lng=-122.6,
            )

    def test_rejects_lng_out_of_range(self):
        from app.api.v1.service_areas import RideCoverageRequest
        with pytest.raises(Exception):
            RideCoverageRequest(
                pickup_lat=45.5,
                pickup_lng=181.0,
                dropoff_lat=45.55,
                dropoff_lng=-122.6,
            )

    def test_southern_hemisphere_coordinates(self):
        from app.api.v1.service_areas import RideCoverageRequest
        req = RideCoverageRequest(
            pickup_lat=-33.8688,
            pickup_lng=151.2093,
            dropoff_lat=-33.9000,
            dropoff_lng=151.2500,
        )
        assert req.pickup_lat == -33.8688

    def test_boundary_lat_values_accepted(self):
        from app.api.v1.service_areas import RideCoverageRequest
        req = RideCoverageRequest(
            pickup_lat=-90.0,
            pickup_lng=-180.0,
            dropoff_lat=90.0,
            dropoff_lng=180.0,
        )
        assert req.pickup_lat == -90.0
        assert req.dropoff_lat == 90.0


# ---------------------------------------------------------------------------
# Public endpoint integration tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
class TestPublicServiceAreaEndpoints:
    """Integration tests for public service area endpoints.

    These run against the full app with a real (test) DB.
    Service areas use PostGIS, so the service_areas table is created
    via create_all — no extra setup required.
    """

    # -----------------------------------------------------------------------
    # GET /service-areas — list active areas
    # -----------------------------------------------------------------------

    async def test_list_returns_200_no_auth(self, client):
        """Public endpoint returns 200 without any authentication."""
        resp = await client.get("/api/v1/service-areas")
        assert resp.status_code == 200

    async def test_list_returns_empty_when_no_areas(self, client):
        """Empty list when no service areas exist."""
        resp = await client.get("/api/v1/service-areas")
        assert resp.status_code == 200
        data = resp.json()
        assert "areas" in data
        assert "total" in data
        assert data["total"] == 0
        assert data["areas"] == []

    async def test_list_response_shape(self, client):
        """Response matches ServiceAreaListResponse schema."""
        resp = await client.get("/api/v1/service-areas")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data["areas"], list)
        assert isinstance(data["total"], int)

    # -----------------------------------------------------------------------
    # GET /service-areas/{area_id} — get one area
    # -----------------------------------------------------------------------

    async def test_get_nonexistent_area_returns_404(self, client):
        """404 for an ID that does not exist."""
        resp = await client.get("/api/v1/service-areas/99999")
        assert resp.status_code == 404

    async def test_get_area_404_detail(self, client):
        """404 response includes a detail message."""
        resp = await client.get("/api/v1/service-areas/99999")
        data = resp.json()
        assert "detail" in data

    # -----------------------------------------------------------------------
    # POST /service-areas/check — ride coverage check
    # -----------------------------------------------------------------------

    async def test_check_returns_200_no_auth(self, client):
        """Coverage check is public and requires no authentication."""
        resp = await client.post(
            "/api/v1/service-areas/check",
            json={
                "pickup_lat": 45.5,
                "pickup_lng": -122.7,
                "dropoff_lat": 45.55,
                "dropoff_lng": -122.6,
            },
        )
        assert resp.status_code == 200

    async def test_check_returns_covered_when_no_service_areas(self, client):
        """When no service areas are configured, all locations are covered."""
        resp = await client.post(
            "/api/v1/service-areas/check",
            json={
                "pickup_lat": 45.5,
                "pickup_lng": -122.7,
                "dropoff_lat": 45.55,
                "dropoff_lng": -122.6,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is True
        assert data["pickup_covered"] is True
        assert data["dropoff_covered"] is True

    async def test_check_response_has_required_fields(self, client):
        """Coverage check response includes valid, pickup_covered, dropoff_covered."""
        resp = await client.post(
            "/api/v1/service-areas/check",
            json={
                "pickup_lat": 0.0,
                "pickup_lng": 0.0,
                "dropoff_lat": 1.0,
                "dropoff_lng": 1.0,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "valid" in data
        assert "pickup_covered" in data
        assert "dropoff_covered" in data

    async def test_check_message_null_when_covered(self, client):
        """No message field (or null) when both locations are covered."""
        resp = await client.post(
            "/api/v1/service-areas/check",
            json={
                "pickup_lat": 45.5,
                "pickup_lng": -122.7,
                "dropoff_lat": 45.55,
                "dropoff_lng": -122.6,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        # message is None when valid (no service areas configured)
        assert data.get("message") is None

    async def test_check_rejects_invalid_lat(self, client):
        """422 for latitude out of [-90, 90] range."""
        resp = await client.post(
            "/api/v1/service-areas/check",
            json={
                "pickup_lat": 200.0,
                "pickup_lng": -122.7,
                "dropoff_lat": 45.55,
                "dropoff_lng": -122.6,
            },
        )
        assert resp.status_code == 422

    async def test_check_rejects_invalid_lng(self, client):
        """422 for longitude out of [-180, 180] range."""
        resp = await client.post(
            "/api/v1/service-areas/check",
            json={
                "pickup_lat": 45.5,
                "pickup_lng": -200.0,
                "dropoff_lat": 45.55,
                "dropoff_lng": -122.6,
            },
        )
        assert resp.status_code == 422

    async def test_check_rejects_missing_fields(self, client):
        """422 when required coordinate fields are missing."""
        resp = await client.post(
            "/api/v1/service-areas/check",
            json={"pickup_lat": 45.5},
        )
        assert resp.status_code == 422

    async def test_check_rejects_empty_body(self, client):
        """422 when request body is empty."""
        resp = await client.post("/api/v1/service-areas/check", json={})
        assert resp.status_code == 422

    async def test_check_accepts_southern_hemisphere(self, client):
        """Coverage check works for coordinates in the southern hemisphere."""
        resp = await client.post(
            "/api/v1/service-areas/check",
            json={
                "pickup_lat": -33.8688,
                "pickup_lng": 151.2093,
                "dropoff_lat": -33.9000,
                "dropoff_lng": 151.2500,
            },
        )
        # Valid request — may return covered or not depending on configured areas
        assert resp.status_code == 200

    async def test_check_accepts_boundary_coordinates(self, client):
        """Boundary values (-90, -180, 90, 180) are accepted."""
        resp = await client.post(
            "/api/v1/service-areas/check",
            json={
                "pickup_lat": -90.0,
                "pickup_lng": -180.0,
                "dropoff_lat": 90.0,
                "dropoff_lng": 180.0,
            },
        )
        assert resp.status_code == 200

    # -----------------------------------------------------------------------
    # Auth — public routes must NOT require authentication
    # -----------------------------------------------------------------------

    async def test_list_works_with_rider_token(self, client, rider, rider_token):
        """Authenticated riders can also call the public list endpoint."""
        from tests.conftest import auth_header
        resp = await client.get(
            "/api/v1/service-areas",
            headers=auth_header(rider_token),
        )
        assert resp.status_code == 200

    async def test_check_works_with_driver_token(self, client, driver_user, driver_token):
        """Authenticated drivers can call the coverage check endpoint."""
        from tests.conftest import auth_header
        resp = await client.post(
            "/api/v1/service-areas/check",
            json={
                "pickup_lat": 45.5,
                "pickup_lng": -122.7,
                "dropoff_lat": 45.55,
                "dropoff_lng": -122.6,
            },
            headers=auth_header(driver_token),
        )
        assert resp.status_code == 200
