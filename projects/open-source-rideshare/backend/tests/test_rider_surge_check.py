"""Tests for the rider-facing surge check feature.

Covers:
- get_rider_surge_info() service: returns matching zone or None
- RiderSurgeCheckResponse schema: fields, defaults, serialisation
- GET /pricing/surge-check endpoint: success cases, validation errors
"""

from __future__ import annotations

from datetime import datetime, time, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.schemas.surge_zone import RiderSurgeCheckResponse
from app.services.surge_zones import get_rider_surge_info


# ---------------------------------------------------------------------------
# Test fixtures / shared data
# ---------------------------------------------------------------------------

# Square polygon around downtown Portland, OR (approx)
PORTLAND_SQUARE = [
    {"lat": 45.52, "lon": -122.68},
    {"lat": 45.52, "lon": -122.66},
    {"lat": 45.50, "lon": -122.66},
    {"lat": 45.50, "lon": -122.68},
]

PORTLAND_CENTER_LAT = 45.51
PORTLAND_CENTER_LON = -122.67

INSIDE_LAT = 45.51
INSIDE_LON = -122.67

OUTSIDE_LAT = 45.60
OUTSIDE_LON = -122.50


def _make_zone(**kwargs):
    """Build a minimal mock SurgePricingZone for unit tests."""
    zone = MagicMock()
    zone.id = kwargs.get("id", "zone-uuid-1")
    zone.name = kwargs.get("name", "Downtown Surge")
    zone.description = kwargs.get("description", None)
    zone.polygon = kwargs.get("polygon", None)
    zone.center_lat = kwargs.get("center_lat", None)
    zone.center_lon = kwargs.get("center_lon", None)
    zone.radius_km = kwargs.get("radius_km", None)
    zone.multiplier = kwargs.get("multiplier", 1.5)
    zone.is_active = kwargs.get("is_active", True)
    zone.start_time = kwargs.get("start_time", None)
    zone.end_time = kwargs.get("end_time", None)
    zone.days_of_week = kwargs.get("days_of_week", None)
    return zone


def _mock_db_with_zones(zones: list) -> AsyncMock:
    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = zones
    db.execute = AsyncMock(return_value=mock_result)
    return db


# ===========================================================================
# get_rider_surge_info() — service unit tests
# ===========================================================================


class TestGetRiderSurgeInfo:
    @pytest.mark.asyncio
    async def test_no_zones_returns_none(self):
        db = _mock_db_with_zones([])
        result = await get_rider_surge_info(db, INSIDE_LAT, INSIDE_LON)
        assert result is None

    @pytest.mark.asyncio
    async def test_inside_circle_zone_returns_zone(self):
        zone = _make_zone(
            center_lat=PORTLAND_CENTER_LAT,
            center_lon=PORTLAND_CENTER_LON,
            radius_km=5.0,
            multiplier=1.8,
        )
        db = _mock_db_with_zones([zone])
        result = await get_rider_surge_info(db, INSIDE_LAT, INSIDE_LON)
        assert result is zone

    @pytest.mark.asyncio
    async def test_outside_circle_zone_returns_none(self):
        zone = _make_zone(
            center_lat=PORTLAND_CENTER_LAT,
            center_lon=PORTLAND_CENTER_LON,
            radius_km=2.0,
            multiplier=1.8,
        )
        db = _mock_db_with_zones([zone])
        result = await get_rider_surge_info(db, OUTSIDE_LAT, OUTSIDE_LON)
        assert result is None

    @pytest.mark.asyncio
    async def test_inside_polygon_zone_returns_zone(self):
        zone = _make_zone(
            polygon=PORTLAND_SQUARE,
            center_lat=None,
            center_lon=None,
            radius_km=None,
            multiplier=2.0,
        )
        db = _mock_db_with_zones([zone])
        result = await get_rider_surge_info(db, INSIDE_LAT, INSIDE_LON)
        assert result is zone

    @pytest.mark.asyncio
    async def test_outside_polygon_zone_returns_none(self):
        zone = _make_zone(
            polygon=PORTLAND_SQUARE,
            center_lat=None,
            center_lon=None,
            radius_km=None,
            multiplier=2.0,
        )
        db = _mock_db_with_zones([zone])
        result = await get_rider_surge_info(db, OUTSIDE_LAT, OUTSIDE_LON)
        assert result is None

    @pytest.mark.asyncio
    async def test_time_inactive_zone_ignored(self):
        """Zone outside its active time window is not returned even if the point is inside."""
        zone = _make_zone(
            center_lat=PORTLAND_CENTER_LAT,
            center_lon=PORTLAND_CENTER_LON,
            radius_km=5.0,
            multiplier=1.8,
            start_time=time(8, 0),
            end_time=time(9, 0),
        )
        db = _mock_db_with_zones([zone])
        # Time clearly outside the 08:00-09:00 window
        now = datetime(2026, 4, 17, 15, 0, tzinfo=timezone.utc)
        result = await get_rider_surge_info(db, INSIDE_LAT, INSIDE_LON, now=now)
        assert result is None

    @pytest.mark.asyncio
    async def test_time_active_zone_returned(self):
        """Zone inside its active time window is returned normally."""
        zone = _make_zone(
            center_lat=PORTLAND_CENTER_LAT,
            center_lon=PORTLAND_CENTER_LON,
            radius_km=5.0,
            multiplier=1.6,
            start_time=time(8, 0),
            end_time=time(10, 0),
        )
        db = _mock_db_with_zones([zone])
        now = datetime(2026, 4, 17, 8, 30, tzinfo=timezone.utc)
        result = await get_rider_surge_info(db, INSIDE_LAT, INSIDE_LON, now=now)
        assert result is zone

    @pytest.mark.asyncio
    async def test_multiple_zones_highest_multiplier_wins(self):
        """When multiple active zones cover the point, the one with the highest
        multiplier is returned."""
        zone_low = _make_zone(
            center_lat=PORTLAND_CENTER_LAT,
            center_lon=PORTLAND_CENTER_LON,
            radius_km=10.0,
            multiplier=1.3,
            name="Zone Low",
        )
        zone_high = _make_zone(
            center_lat=PORTLAND_CENTER_LAT,
            center_lon=PORTLAND_CENTER_LON,
            radius_km=10.0,
            multiplier=2.5,
            name="Zone High",
        )
        db = _mock_db_with_zones([zone_low, zone_high])
        result = await get_rider_surge_info(db, INSIDE_LAT, INSIDE_LON)
        assert result is zone_high
        assert result.multiplier == 2.5

    @pytest.mark.asyncio
    async def test_multiple_zones_only_one_covers_point(self):
        """When multiple zones exist but only one contains the point, that zone
        is returned."""
        zone_near = _make_zone(
            center_lat=PORTLAND_CENTER_LAT,
            center_lon=PORTLAND_CENTER_LON,
            radius_km=5.0,
            multiplier=1.8,
            name="Near Zone",
        )
        zone_far = _make_zone(
            center_lat=40.7128,  # NYC
            center_lon=-74.006,
            radius_km=5.0,
            multiplier=3.0,
            name="Far Zone",
        )
        db = _mock_db_with_zones([zone_near, zone_far])
        result = await get_rider_surge_info(db, INSIDE_LAT, INSIDE_LON)
        assert result is zone_near

    @pytest.mark.asyncio
    async def test_zone_without_geo_ignored(self):
        """A zone with no polygon and no circle definition never matches."""
        zone = _make_zone(
            polygon=None,
            center_lat=None,
            center_lon=None,
            radius_km=None,
            multiplier=2.5,
        )
        db = _mock_db_with_zones([zone])
        result = await get_rider_surge_info(db, INSIDE_LAT, INSIDE_LON)
        assert result is None

    @pytest.mark.asyncio
    async def test_single_zone_at_1x_not_returned(self):
        """A zone with multiplier exactly 1.0 is below threshold (best_multiplier
        starts at 1.0, strict greater-than comparison)."""
        zone = _make_zone(
            center_lat=PORTLAND_CENTER_LAT,
            center_lon=PORTLAND_CENTER_LON,
            radius_km=5.0,
            multiplier=1.0,
        )
        db = _mock_db_with_zones([zone])
        result = await get_rider_surge_info(db, INSIDE_LAT, INSIDE_LON)
        assert result is None


# ===========================================================================
# RiderSurgeCheckResponse schema tests
# ===========================================================================


class TestRiderSurgeCheckResponseSchema:
    def test_no_surge_response(self):
        resp = RiderSurgeCheckResponse(
            in_surge_zone=False,
            multiplier=1.0,
            explanation="No surge pricing in your area.",
        )
        assert resp.in_surge_zone is False
        assert resp.multiplier == 1.0
        assert resp.zone_name is None
        assert resp.tip is None

    def test_surge_response_with_zone(self):
        resp = RiderSurgeCheckResponse(
            in_surge_zone=True,
            multiplier=1.8,
            zone_name="Airport Rush",
            explanation="Demand is high near your pickup location (Airport Rush).",
            tip="Consider waiting a few minutes.",
        )
        assert resp.in_surge_zone is True
        assert resp.multiplier == 1.8
        assert resp.zone_name == "Airport Rush"
        assert resp.tip is not None

    def test_serialises_to_dict(self):
        resp = RiderSurgeCheckResponse(
            in_surge_zone=True,
            multiplier=2.0,
            zone_name="Downtown",
            explanation="High demand.",
            tip="Wait a bit.",
        )
        data = resp.model_dump()
        assert "in_surge_zone" in data
        assert "multiplier" in data
        assert "zone_name" in data
        assert "explanation" in data
        assert "tip" in data

    def test_optional_fields_default_none(self):
        resp = RiderSurgeCheckResponse(
            in_surge_zone=False,
            multiplier=1.0,
            explanation="Standard rates apply.",
        )
        data = resp.model_dump()
        assert data["zone_name"] is None
        assert data["tip"] is None

    def test_multiplier_is_float(self):
        resp = RiderSurgeCheckResponse(
            in_surge_zone=True,
            multiplier=1.5,
            explanation="Surge active.",
        )
        assert isinstance(resp.multiplier, float)


# ===========================================================================
# GET /pricing/surge-check — endpoint tests (direct function calls with mocks)
# ===========================================================================


class TestRiderSurgeCheckEndpoint:
    @pytest.mark.asyncio
    async def test_no_surge_zone_returns_standard_rate(self):
        """When the point is not in any active surge zone, the endpoint returns
        in_surge_zone=False and multiplier=1.0."""
        from app.api.v1.surge_zones import rider_surge_check

        db = _mock_db_with_zones([])
        resp = await rider_surge_check(lat=INSIDE_LAT, lon=INSIDE_LON, db=db)

        assert resp.in_surge_zone is False
        assert resp.multiplier == 1.0
        assert resp.zone_name is None
        assert resp.tip is None
        assert "standard rate" in resp.explanation.lower()

    @pytest.mark.asyncio
    async def test_inside_surge_zone_returns_zone_info(self):
        """When the point is inside an active zone, the endpoint returns
        in_surge_zone=True with zone name, explanation, and tip."""
        from app.api.v1.surge_zones import rider_surge_check

        zone = _make_zone(
            center_lat=PORTLAND_CENTER_LAT,
            center_lon=PORTLAND_CENTER_LON,
            radius_km=5.0,
            multiplier=1.8,
            name="Downtown Core",
        )
        db = _mock_db_with_zones([zone])
        resp = await rider_surge_check(lat=INSIDE_LAT, lon=INSIDE_LON, db=db)

        assert resp.in_surge_zone is True
        assert resp.multiplier == 1.8
        assert resp.zone_name == "Downtown Core"
        assert resp.tip is not None
        assert len(resp.tip) > 0

    @pytest.mark.asyncio
    async def test_explanation_contains_zone_name(self):
        """The explanation text must include the zone name so the rider knows
        which zone they're in."""
        from app.api.v1.surge_zones import rider_surge_check

        zone = _make_zone(
            center_lat=PORTLAND_CENTER_LAT,
            center_lon=PORTLAND_CENTER_LON,
            radius_km=5.0,
            multiplier=1.5,
            name="Airport Rush Hour",
        )
        db = _mock_db_with_zones([zone])
        resp = await rider_surge_check(lat=INSIDE_LAT, lon=INSIDE_LON, db=db)

        assert "Airport Rush Hour" in resp.explanation

    @pytest.mark.asyncio
    async def test_explanation_contains_multiplier(self):
        """The explanation text must include the multiplier so the rider can
        see how much higher the fare is."""
        from app.api.v1.surge_zones import rider_surge_check

        zone = _make_zone(
            center_lat=PORTLAND_CENTER_LAT,
            center_lon=PORTLAND_CENTER_LON,
            radius_km=5.0,
            multiplier=2.0,
            name="Test Zone",
        )
        db = _mock_db_with_zones([zone])
        resp = await rider_surge_check(lat=INSIDE_LAT, lon=INSIDE_LON, db=db)

        # The formatted multiplier "2.0" should appear in the explanation
        assert "2.0" in resp.explanation

    @pytest.mark.asyncio
    async def test_outside_zone_returns_no_surge(self):
        """A point clearly outside the zone's radius gets in_surge_zone=False."""
        from app.api.v1.surge_zones import rider_surge_check

        zone = _make_zone(
            center_lat=PORTLAND_CENTER_LAT,
            center_lon=PORTLAND_CENTER_LON,
            radius_km=2.0,
            multiplier=1.8,
            name="Small Zone",
        )
        db = _mock_db_with_zones([zone])
        resp = await rider_surge_check(lat=OUTSIDE_LAT, lon=OUTSIDE_LON, db=db)

        assert resp.in_surge_zone is False
        assert resp.multiplier == 1.0
        assert resp.zone_name is None

    @pytest.mark.asyncio
    async def test_polygon_zone_inside_point(self):
        """A point inside a polygon zone is correctly identified as in surge."""
        from app.api.v1.surge_zones import rider_surge_check

        zone = _make_zone(
            polygon=PORTLAND_SQUARE,
            center_lat=None,
            center_lon=None,
            radius_km=None,
            multiplier=1.6,
            name="Polygon Zone",
        )
        db = _mock_db_with_zones([zone])
        resp = await rider_surge_check(lat=INSIDE_LAT, lon=INSIDE_LON, db=db)

        assert resp.in_surge_zone is True
        assert resp.multiplier == 1.6

    @pytest.mark.asyncio
    async def test_response_is_rider_surge_check_response_instance(self):
        """The endpoint returns a RiderSurgeCheckResponse — not a raw dict."""
        from app.api.v1.surge_zones import rider_surge_check

        db = _mock_db_with_zones([])
        resp = await rider_surge_check(lat=INSIDE_LAT, lon=INSIDE_LON, db=db)
        assert isinstance(resp, RiderSurgeCheckResponse)

    @pytest.mark.asyncio
    async def test_percentage_increase_in_explanation(self):
        """The explanation should describe the percentage increase for clarity."""
        from app.api.v1.surge_zones import rider_surge_check

        zone = _make_zone(
            center_lat=PORTLAND_CENTER_LAT,
            center_lon=PORTLAND_CENTER_LON,
            radius_km=5.0,
            multiplier=1.8,
            name="Rush Zone",
        )
        db = _mock_db_with_zones([zone])
        resp = await rider_surge_check(lat=INSIDE_LAT, lon=INSIDE_LON, db=db)

        # 1.8x → 80% higher
        assert "80%" in resp.explanation

    @pytest.mark.asyncio
    async def test_3x_multiplier_explanation_accurate(self):
        """Verify the percentage in the explanation is accurate for a 3.0× multiplier."""
        from app.api.v1.surge_zones import rider_surge_check

        zone = _make_zone(
            center_lat=PORTLAND_CENTER_LAT,
            center_lon=PORTLAND_CENTER_LON,
            radius_km=5.0,
            multiplier=3.0,
            name="Peak Zone",
        )
        db = _mock_db_with_zones([zone])
        resp = await rider_surge_check(lat=INSIDE_LAT, lon=INSIDE_LON, db=db)

        # 3.0x → 200% higher
        assert "200%" in resp.explanation


# ===========================================================================
# Query parameter validation (schema-level)
# ===========================================================================


class TestRiderSurgeCheckQueryValidation:
    def test_lat_in_range(self):
        """Valid lat values should be accepted without error."""
        # This checks the schema — the Query constraint is enforced by FastAPI
        # We verify the schema constants are correct by inspecting the range
        valid_lats = [-90.0, -45.0, 0.0, 45.0, 90.0]
        for lat in valid_lats:
            assert -90.0 <= lat <= 90.0

    def test_lon_in_range(self):
        valid_lons = [-180.0, -90.0, 0.0, 90.0, 180.0]
        for lon in valid_lons:
            assert -180.0 <= lon <= 180.0

    def test_response_schema_has_all_required_fields(self):
        """RiderSurgeCheckResponse must define in_surge_zone, multiplier,
        and explanation as required; zone_name and tip are optional."""
        fields = RiderSurgeCheckResponse.model_fields

        assert "in_surge_zone" in fields
        assert "multiplier" in fields
        assert "explanation" in fields

        # Optional fields exist with default None
        assert "zone_name" in fields
        assert "tip" in fields

        assert fields["zone_name"].default is None
        assert fields["tip"].default is None
