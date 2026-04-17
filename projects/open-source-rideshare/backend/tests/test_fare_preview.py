"""Tests for the fare preview / surge pricing transparency feature.

Covers:
- _haversine_km:          pure: known distances, zero distance, edge cases
- _estimate_duration_min: pure: basic estimate, speed override, zero guard
- build_pricing_summary:  pure: no surge, zone only, demand only, both active
- get_fare_preview:       mocked routing/db/redis — OSRM success, OSRM fallback,
                          surge zone active, demand pricing active, both active,
                          redis failure fallback, db failure fallback
- GET /pricing/fare-preview: endpoint — valid params, missing params, response shape
"""

from __future__ import annotations

import math
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.fare_preview import (
    FarePreviewResult,
    _estimate_duration_min,
    _haversine_km,
    build_pricing_summary,
    get_fare_preview,
)
from app.services.pricing import FareBreakdown


# ===========================================================================
# _haversine_km — pure distance helper
# ===========================================================================


class TestHaversineKm:
    def test_same_point_returns_zero(self):
        assert _haversine_km(0.0, 0.0, 0.0, 0.0) == pytest.approx(0.0, abs=1e-6)

    def test_nyc_to_la_approx(self):
        # JFK → LAX is ~3,940 km great-circle
        d = _haversine_km(40.6413, -73.7781, 33.9425, -118.4081)
        assert 3900 < d < 4000

    def test_short_urban_trip(self):
        # ~1 km apart in Manhattan
        d = _haversine_km(40.7128, -74.0060, 40.7200, -74.0060)
        assert 0.8 < d < 1.0

    def test_equator_crossing(self):
        # Two points straddling equator
        d = _haversine_km(-1.0, 0.0, 1.0, 0.0)
        assert d == pytest.approx(222.4, abs=1.0)

    def test_negative_coordinates(self):
        # Sydney, Australia — should return positive distance
        d = _haversine_km(-33.8688, 151.2093, -33.9000, 151.2500)
        assert d > 0

    def test_symmetry(self):
        a = _haversine_km(40.7128, -74.0060, 51.5074, -0.1278)
        b = _haversine_km(51.5074, -0.1278, 40.7128, -74.0060)
        assert a == pytest.approx(b, rel=1e-6)

    def test_positive_result_for_any_pair(self):
        d = _haversine_km(10.0, 20.0, 30.0, 40.0)
        assert d > 0


# ===========================================================================
# _estimate_duration_min — pure duration helper
# ===========================================================================


class TestEstimateDurationMin:
    def test_10km_at_30kmh(self):
        # 10 km / 30 km/h = 20 min
        assert _estimate_duration_min(10.0) == pytest.approx(20.0, abs=0.01)

    def test_60km_at_60kmh(self):
        assert _estimate_duration_min(60.0, avg_speed_kmh=60.0) == pytest.approx(60.0)

    def test_zero_distance(self):
        assert _estimate_duration_min(0.0) == pytest.approx(0.0)

    def test_speed_override(self):
        # Highway: 5 km at 90 km/h ≈ 3.33 min
        result = _estimate_duration_min(5.0, avg_speed_kmh=90.0)
        assert result == pytest.approx(5.0 / 90.0 * 60.0, abs=0.01)

    def test_invalid_speed_raises(self):
        with pytest.raises(ValueError):
            _estimate_duration_min(10.0, avg_speed_kmh=0.0)

    def test_proportional_to_distance(self):
        d1 = _estimate_duration_min(5.0)
        d2 = _estimate_duration_min(10.0)
        assert d2 == pytest.approx(d1 * 2, abs=0.01)


# ===========================================================================
# build_pricing_summary — pure summary builder
# ===========================================================================


class TestBuildPricingSummary:
    def test_no_surge_returns_standard_message(self):
        msg = build_pricing_summary(
            surge_zone_multiplier=1.0,
            surge_zone_name=None,
            demand_multiplier=1.0,
            demand_count=2,
            supply_count=5,
            combined_multiplier=1.0,
        )
        assert "Standard pricing" in msg
        assert "no surge" in msg.lower()

    def test_surge_zone_only(self):
        msg = build_pricing_summary(
            surge_zone_multiplier=1.3,
            surge_zone_name="Airport Zone",
            demand_multiplier=1.0,
            demand_count=0,
            supply_count=3,
            combined_multiplier=1.3,
        )
        assert "Airport Zone" in msg
        assert "30%" in msg
        assert "30%" in msg

    def test_demand_only(self):
        msg = build_pricing_summary(
            surge_zone_multiplier=1.0,
            surge_zone_name=None,
            demand_multiplier=1.25,
            demand_count=10,
            supply_count=2,
            combined_multiplier=1.25,
        )
        assert "high demand" in msg
        assert "25%" in msg
        assert "10 requests" in msg
        assert "2 available drivers" in msg

    def test_both_active(self):
        msg = build_pricing_summary(
            surge_zone_multiplier=1.2,
            surge_zone_name="Downtown Core",
            demand_multiplier=1.15,
            demand_count=8,
            supply_count=1,
            combined_multiplier=1.38,
        )
        assert "Downtown Core" in msg
        assert "20%" in msg
        assert "high demand" in msg
        assert "1 available driver" in msg  # singular
        assert "38%" in msg

    def test_demand_disabled(self):
        msg = build_pricing_summary(
            surge_zone_multiplier=1.0,
            surge_zone_name=None,
            demand_multiplier=1.3,  # elevated but disabled
            demand_count=10,
            supply_count=2,
            combined_multiplier=1.0,
            demand_pricing_enabled=False,
        )
        assert "Standard pricing" in msg

    def test_singular_driver(self):
        msg = build_pricing_summary(
            surge_zone_multiplier=1.0,
            surge_zone_name=None,
            demand_multiplier=1.2,
            demand_count=5,
            supply_count=1,
            combined_multiplier=1.2,
        )
        assert "1 available driver" in msg
        assert "drivers" not in msg

    def test_plural_drivers(self):
        msg = build_pricing_summary(
            surge_zone_multiplier=1.0,
            surge_zone_name=None,
            demand_multiplier=1.2,
            demand_count=5,
            supply_count=3,
            combined_multiplier=1.2,
        )
        assert "3 available drivers" in msg

    def test_cooperative_note_in_elevated_message(self):
        msg = build_pricing_summary(
            surge_zone_multiplier=1.5,
            surge_zone_name="Stadium Zone",
            demand_multiplier=1.0,
            demand_count=0,
            supply_count=2,
            combined_multiplier=1.5,
        )
        assert "cooperative" in msg.lower()


# ===========================================================================
# get_fare_preview — async service (mocked I/O)
# ===========================================================================


def _make_demand_info(
    multiplier: float = 1.0,
    is_elevated: bool = False,
    demand_count: int = 3,
    supply_count: int = 5,
):
    from app.services.demand_pricing import DemandInfo

    pct = round((multiplier - 1.0) * 100)
    explanation = (
        f"Fares are {pct}% higher due to high demand."
        if is_elevated
        else "Standard pricing — driver availability is good in your area."
    )
    return DemandInfo(
        geohash="dr5re",
        demand_count=demand_count,
        supply_count=supply_count,
        multiplier=multiplier,
        multiplier_cap=1.5,
        is_elevated=is_elevated,
        explanation=explanation,
    )


def _mock_db_no_zones() -> AsyncMock:
    """DB that returns zero surge zones."""
    db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    db.execute.return_value = result
    return db


def _mock_db_with_zone(multiplier: float = 1.3, name: str = "Test Zone") -> AsyncMock:
    """DB that returns a single active circular surge zone."""
    from app.models.surge import SurgePricingZone

    zone = MagicMock(spec=SurgePricingZone)
    zone.is_active = True
    zone.multiplier = multiplier
    zone.name = name
    zone.description = f"{name} description"
    zone.polygon = None
    zone.center_lat = 40.7128
    zone.center_lon = -74.0060
    zone.radius_km = 50.0  # large enough to match any NYC-ish coordinate
    zone.days_of_week = None
    zone.start_time = None
    zone.end_time = None

    db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = [zone]
    db.execute.return_value = result
    return db


@pytest.mark.anyio
class TestGetFarePreview:
    async def test_osrm_success_standard_pricing(self):
        """OSRM available, no surge, no elevated demand."""
        db = _mock_db_no_zones()
        redis = AsyncMock()
        demand_info = _make_demand_info(multiplier=1.0, is_elevated=False)

        with (
            patch("app.services.fare_preview.list_zones", new=AsyncMock(return_value=[])),
            patch("app.services.fare_preview.get_demand_info", new=AsyncMock(return_value=demand_info)),
            patch("app.services.routing.get_route", new=AsyncMock(return_value={"distance_km": 5.0, "duration_min": 12.0})),
        ):
            result = await get_fare_preview(40.7128, -74.0060, 40.7580, -73.9855, db, redis)

        assert result.route_source in ("osrm", "estimate")
        assert result.surge_zone_multiplier == 1.0
        assert result.surge_zone_name is None
        assert not result.is_surge_active

    async def test_haversine_fallback_when_osrm_fails(self):
        """When OSRM raises, distance falls back to Haversine."""
        db = _mock_db_no_zones()
        redis = AsyncMock()
        demand_info = _make_demand_info()

        with (
            patch(
                "app.services.fare_preview.list_zones",
                new=AsyncMock(return_value=[]),
            ),
            patch(
                "app.services.fare_preview.get_demand_info",
                new=AsyncMock(return_value=demand_info),
            ),
            patch(
                "app.services.routing.get_route",
                side_effect=Exception("OSRM down"),
            ),
        ):
            result = await get_fare_preview(40.7128, -74.0060, 40.7580, -73.9855, db, redis)

        assert result.route_source == "estimate"
        assert result.distance_km > 0
        assert result.duration_min > 0

    async def test_demand_elevated(self):
        """Elevated demand is reflected in multiplier and summary."""
        db = _mock_db_no_zones()
        redis = AsyncMock()
        demand_info = _make_demand_info(multiplier=1.3, is_elevated=True, demand_count=15, supply_count=2)

        with (
            patch(
                "app.services.fare_preview.list_zones",
                new=AsyncMock(return_value=[]),
            ),
            patch(
                "app.services.fare_preview.get_demand_info",
                new=AsyncMock(return_value=demand_info),
            ),
            patch(
                "app.services.routing.get_route",
                new=AsyncMock(return_value={"distance_km": 4.0, "duration_min": 10.0}),
            ),
        ):
            result = await get_fare_preview(40.7128, -74.0060, 40.7580, -73.9855, db, redis)

        assert result.demand_multiplier == 1.3
        assert result.is_demand_elevated
        assert result.is_surge_active
        assert result.demand_count == 15
        assert result.supply_count == 2

    async def test_redis_failure_falls_back_to_standard_pricing(self):
        """If Redis is unavailable, demand multiplier defaults to 1.0."""
        db = _mock_db_no_zones()
        redis = AsyncMock()

        with (
            patch(
                "app.services.fare_preview.list_zones",
                new=AsyncMock(return_value=[]),
            ),
            patch(
                "app.services.fare_preview.get_demand_info",
                side_effect=Exception("Redis unavailable"),
            ),
            patch(
                "app.services.routing.get_route",
                new=AsyncMock(return_value={"distance_km": 5.0, "duration_min": 12.0}),
            ),
        ):
            result = await get_fare_preview(40.7128, -74.0060, 40.7580, -73.9855, db, redis)

        assert result.demand_multiplier == 1.0
        assert not result.is_demand_elevated
        assert not result.is_surge_active

    async def test_db_failure_falls_back_to_no_zone(self):
        """If DB is unavailable for surge zones, zone multiplier defaults to 1.0."""
        redis = AsyncMock()
        demand_info = _make_demand_info()

        with (
            patch(
                "app.services.fare_preview.list_zones",
                side_effect=Exception("DB unavailable"),
            ),
            patch(
                "app.services.fare_preview.get_demand_info",
                new=AsyncMock(return_value=demand_info),
            ),
            patch(
                "app.services.routing.get_route",
                new=AsyncMock(return_value={"distance_km": 5.0, "duration_min": 12.0}),
            ),
        ):
            result = await get_fare_preview(40.7128, -74.0060, 40.7580, -73.9855, AsyncMock(), redis)

        assert result.surge_zone_multiplier == 1.0
        assert result.surge_zone_name is None

    async def test_combined_multiplier_calculation(self):
        """Combined multiplier = time-of-day × demand × surge zone."""
        db = _mock_db_no_zones()
        redis = AsyncMock()
        demand_info = _make_demand_info(multiplier=1.25, is_elevated=True)

        with (
            patch(
                "app.services.fare_preview.list_zones",
                new=AsyncMock(return_value=[]),
            ),
            patch(
                "app.services.fare_preview.get_demand_info",
                new=AsyncMock(return_value=demand_info),
            ),
            patch(
                "app.services.routing.get_route",
                new=AsyncMock(return_value={"distance_km": 5.0, "duration_min": 12.0}),
            ),
        ):
            result = await get_fare_preview(40.7128, -74.0060, 40.7580, -73.9855, db, redis)

        # combined = time_of_day (1.0 default) × demand (1.25) × zone (1.0)
        assert result.combined_multiplier == pytest.approx(1.25, abs=0.01)

    async def test_fare_components_are_positive(self):
        """All fare components must be non-negative."""
        db = _mock_db_no_zones()
        redis = AsyncMock()
        demand_info = _make_demand_info()

        with (
            patch(
                "app.services.fare_preview.list_zones",
                new=AsyncMock(return_value=[]),
            ),
            patch(
                "app.services.fare_preview.get_demand_info",
                new=AsyncMock(return_value=demand_info),
            ),
            patch(
                "app.services.routing.get_route",
                new=AsyncMock(return_value={"distance_km": 3.0, "duration_min": 8.0}),
            ),
        ):
            result = await get_fare_preview(40.7128, -74.0060, 40.7580, -73.9855, db, redis)

        assert result.breakdown.base >= 0
        assert result.breakdown.distance >= 0
        assert result.breakdown.time >= 0
        assert result.breakdown.total > 0

    async def test_is_surge_active_false_when_both_at_one(self):
        db = _mock_db_no_zones()
        redis = AsyncMock()
        demand_info = _make_demand_info(multiplier=1.0, is_elevated=False)

        with (
            patch("app.services.fare_preview.list_zones", new=AsyncMock(return_value=[])),
            patch("app.services.fare_preview.get_demand_info", new=AsyncMock(return_value=demand_info)),
            patch("app.services.routing.get_route", new=AsyncMock(return_value={"distance_km": 5.0, "duration_min": 12.0})),
        ):
            result = await get_fare_preview(40.7128, -74.0060, 40.7580, -73.9855, db, redis)

        assert not result.is_surge_active

    async def test_is_surge_active_true_when_zone_active(self):
        redis = AsyncMock()
        demand_info = _make_demand_info(multiplier=1.0, is_elevated=False)

        from app.models.surge import SurgePricingZone

        zone = MagicMock(spec=SurgePricingZone)
        zone.is_active = True
        zone.multiplier = 1.4
        zone.name = "Downtown"
        zone.description = None
        zone.polygon = None
        zone.center_lat = 40.7128
        zone.center_lon = -74.0060
        zone.radius_km = 50.0
        zone.days_of_week = None
        zone.start_time = None
        zone.end_time = None

        with (
            patch("app.services.fare_preview.list_zones", new=AsyncMock(return_value=[zone])),
            patch("app.services.fare_preview.is_zone_active_now", return_value=True),
            patch("app.services.fare_preview._point_in_zone", return_value=True),
            patch("app.services.fare_preview.get_demand_info", new=AsyncMock(return_value=demand_info)),
            patch("app.services.routing.get_route", new=AsyncMock(return_value={"distance_km": 5.0, "duration_min": 12.0})),
        ):
            result = await get_fare_preview(40.7128, -74.0060, 40.7580, -73.9855, AsyncMock(), redis)

        assert result.is_surge_active
        assert result.surge_zone_multiplier == 1.4
        assert result.surge_zone_name == "Downtown"

    async def test_result_fields_are_rounded(self):
        db = _mock_db_no_zones()
        redis = AsyncMock()
        demand_info = _make_demand_info()

        with (
            patch("app.services.fare_preview.list_zones", new=AsyncMock(return_value=[])),
            patch("app.services.fare_preview.get_demand_info", new=AsyncMock(return_value=demand_info)),
            patch("app.services.routing.get_route", new=AsyncMock(return_value={"distance_km": 5.1234, "duration_min": 12.567})),
        ):
            result = await get_fare_preview(40.7128, -74.0060, 40.7580, -73.9855, db, redis)

        # distance rounded to 2dp, duration to 1dp
        assert result.distance_km == pytest.approx(5.12, abs=0.01)
        assert result.duration_min == pytest.approx(12.6, abs=0.1)


# ===========================================================================
# GET /pricing/fare-preview — endpoint
# ===========================================================================


@pytest.mark.anyio
class TestFarePreviewEndpoint:
    async def _client(self, db_override=None):
        """Build an async test client with DB override."""
        from httpx import ASGITransport, AsyncClient
        from app.main import app
        from app.db.database import get_db

        if db_override is None:
            db_override = _mock_db_no_zones()

        app.dependency_overrides[get_db] = lambda: db_override
        client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
        return client, app

    async def test_missing_required_params_returns_422(self):
        client, app = await self._client()
        async with client:
            resp = await client.get("/api/v1/pricing/fare-preview")
        assert resp.status_code == 422
        app.dependency_overrides.clear()

    async def test_valid_params_returns_200(self):
        demand_info = _make_demand_info()

        with (
            patch("app.services.fare_preview.list_zones", new=AsyncMock(return_value=[])),
            patch("app.services.fare_preview.get_demand_info", new=AsyncMock(return_value=demand_info)),
            patch("app.services.routing.get_route", new=AsyncMock(return_value={"distance_km": 5.0, "duration_min": 12.0})),
            patch("app.services.matching.get_redis", new=AsyncMock(return_value=AsyncMock())),
        ):
            client, app = await self._client()
            async with client:
                resp = await client.get(
                    "/api/v1/pricing/fare-preview",
                    params={
                        "origin_lat": 40.7128,
                        "origin_lon": -74.0060,
                        "dest_lat": 40.7580,
                        "dest_lon": -73.9855,
                    },
                )
        app.dependency_overrides.clear()
        assert resp.status_code == 200

    async def test_response_shape(self):
        demand_info = _make_demand_info()

        with (
            patch("app.services.fare_preview.list_zones", new=AsyncMock(return_value=[])),
            patch("app.services.fare_preview.get_demand_info", new=AsyncMock(return_value=demand_info)),
            patch("app.services.routing.get_route", new=AsyncMock(return_value={"distance_km": 5.0, "duration_min": 12.0})),
            patch("app.services.matching.get_redis", new=AsyncMock(return_value=AsyncMock())),
        ):
            client, app = await self._client()
            async with client:
                resp = await client.get(
                    "/api/v1/pricing/fare-preview",
                    params={
                        "origin_lat": 40.7128,
                        "origin_lon": -74.0060,
                        "dest_lat": 40.7580,
                        "dest_lon": -73.9855,
                    },
                )
        app.dependency_overrides.clear()

        data = resp.json()
        # Top-level fields
        for field in ("distance_km", "duration_min", "route_source", "surge_zone",
                      "demand_pricing", "components", "combined_multiplier",
                      "subtotal", "platform_fee", "estimated_fare",
                      "pricing_summary", "is_surge_active", "currency"):
            assert field in data, f"Missing field: {field}"

        # Nested: surge_zone
        sz = data["surge_zone"]
        assert "multiplier" in sz
        assert "zone_name" in sz
        assert "zone_description" in sz

        # Nested: demand_pricing
        dp = data["demand_pricing"]
        for f in ("multiplier", "multiplier_cap", "demand_count", "supply_count",
                  "is_elevated", "explanation"):
            assert f in dp, f"Missing demand_pricing.{f}"

        # Nested: components
        comp = data["components"]
        for f in ("base", "distance", "time"):
            assert f in comp, f"Missing components.{f}"

    async def test_lat_out_of_range_returns_422(self):
        client, app = await self._client()
        async with client:
            resp = await client.get(
                "/api/v1/pricing/fare-preview",
                params={
                    "origin_lat": 999,  # invalid
                    "origin_lon": -74.0060,
                    "dest_lat": 40.7580,
                    "dest_lon": -73.9855,
                },
            )
        app.dependency_overrides.clear()
        assert resp.status_code == 422

    async def test_no_auth_required(self):
        """Endpoint must be accessible without Authorization header."""
        demand_info = _make_demand_info()

        with (
            patch("app.services.fare_preview.list_zones", new=AsyncMock(return_value=[])),
            patch("app.services.fare_preview.get_demand_info", new=AsyncMock(return_value=demand_info)),
            patch("app.services.routing.get_route", new=AsyncMock(return_value={"distance_km": 5.0, "duration_min": 12.0})),
            patch("app.services.matching.get_redis", new=AsyncMock(return_value=AsyncMock())),
        ):
            client, app = await self._client()
            async with client:
                # Deliberately no Authorization header
                resp = await client.get(
                    "/api/v1/pricing/fare-preview",
                    params={
                        "origin_lat": 40.7128,
                        "origin_lon": -74.0060,
                        "dest_lat": 40.7580,
                        "dest_lon": -73.9855,
                    },
                )
        app.dependency_overrides.clear()
        assert resp.status_code == 200

    async def test_standard_pricing_summary_when_no_surge(self):
        demand_info = _make_demand_info(multiplier=1.0, is_elevated=False)

        with (
            patch("app.services.fare_preview.list_zones", new=AsyncMock(return_value=[])),
            patch("app.services.fare_preview.get_demand_info", new=AsyncMock(return_value=demand_info)),
            patch("app.services.routing.get_route", new=AsyncMock(return_value={"distance_km": 5.0, "duration_min": 12.0})),
            patch("app.services.matching.get_redis", new=AsyncMock(return_value=AsyncMock())),
        ):
            client, app = await self._client()
            async with client:
                resp = await client.get(
                    "/api/v1/pricing/fare-preview",
                    params={
                        "origin_lat": 40.7128,
                        "origin_lon": -74.0060,
                        "dest_lat": 40.7580,
                        "dest_lon": -73.9855,
                    },
                )
        app.dependency_overrides.clear()

        data = resp.json()
        assert "Standard pricing" in data["pricing_summary"]
        assert data["is_surge_active"] is False
        assert data["surge_zone"]["multiplier"] == 1.0

    async def test_currency_field_defaults_to_usd(self):
        demand_info = _make_demand_info()

        with (
            patch("app.services.fare_preview.list_zones", new=AsyncMock(return_value=[])),
            patch("app.services.fare_preview.get_demand_info", new=AsyncMock(return_value=demand_info)),
            patch("app.services.routing.get_route", new=AsyncMock(return_value={"distance_km": 5.0, "duration_min": 12.0})),
            patch("app.services.matching.get_redis", new=AsyncMock(return_value=AsyncMock())),
        ):
            client, app = await self._client()
            async with client:
                resp = await client.get(
                    "/api/v1/pricing/fare-preview",
                    params={
                        "origin_lat": 40.7128,
                        "origin_lon": -74.0060,
                        "dest_lat": 40.7580,
                        "dest_lon": -73.9855,
                    },
                )
        app.dependency_overrides.clear()
        assert resp.json()["currency"] == "USD"
