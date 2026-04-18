"""Tests for GET /surge/current — lightweight surge status endpoint.

Covers:
- _get_zone_multiplier:     no zones, active zone, inactive zone, db failure
- surge_current_status:     no surge, zone only, demand only, both, fallbacks
- GET /surge/current:       endpoint shape, missing params, no auth required
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.v1.surge_status import _get_zone_multiplier


# ===========================================================================
# Helpers shared across test classes
# ===========================================================================


def _mock_db_no_zones() -> AsyncMock:
    db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    db.execute.return_value = result
    return db


def _mock_db_with_zone(multiplier: float = 1.3, name: str = "Test Zone") -> AsyncMock:
    from app.models.surge import SurgePricingZone

    zone = MagicMock(spec=SurgePricingZone)
    zone.is_active = True
    zone.multiplier = multiplier
    zone.name = name
    zone.description = f"{name} description"
    zone.polygon = None
    zone.center_lat = 40.7128
    zone.center_lon = -74.0060
    zone.radius_km = 50.0
    zone.days_of_week = None
    zone.start_time = None
    zone.end_time = None

    db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = [zone]
    db.execute.return_value = result
    return db


def _make_demand_info(multiplier: float = 1.0, is_elevated: bool = False):
    from app.services.demand_pricing import DemandInfo

    pct = round((multiplier - 1.0) * 100)
    explanation = (
        f"Fares are {pct}% higher due to high demand."
        if is_elevated
        else "Standard pricing — driver availability is good in your area."
    )
    return DemandInfo(
        geohash="dr5re",
        demand_count=10 if is_elevated else 2,
        supply_count=2 if is_elevated else 8,
        multiplier=multiplier,
        multiplier_cap=1.5,
        is_elevated=is_elevated,
        explanation=explanation,
    )


# ===========================================================================
# _get_zone_multiplier — pure async helper
# ===========================================================================


@pytest.mark.anyio
class TestGetZoneMultiplier:
    async def test_no_zones_returns_one(self):
        with patch("app.api.v1.surge_status.list_zones", new=AsyncMock(return_value=[])):
            mult, name = await _get_zone_multiplier(AsyncMock(), 40.7128, -74.0060)
        assert mult == 1.0
        assert name is None

    async def test_active_matching_zone_returns_multiplier(self):
        from app.models.surge import SurgePricingZone

        zone = MagicMock(spec=SurgePricingZone)
        zone.multiplier = 1.4
        zone.name = "Airport"

        with (
            patch("app.api.v1.surge_status.list_zones", new=AsyncMock(return_value=[zone])),
            patch("app.api.v1.surge_status.is_zone_active_now", return_value=True),
            patch("app.api.v1.surge_status._point_in_zone", return_value=True),
        ):
            mult, name = await _get_zone_multiplier(AsyncMock(), 40.7128, -74.0060)

        assert mult == 1.4
        assert name == "Airport"

    async def test_inactive_zone_skipped(self):
        from app.models.surge import SurgePricingZone

        zone = MagicMock(spec=SurgePricingZone)
        zone.multiplier = 1.5
        zone.name = "Night Zone"

        with (
            patch("app.api.v1.surge_status.list_zones", new=AsyncMock(return_value=[zone])),
            patch("app.api.v1.surge_status.is_zone_active_now", return_value=False),
        ):
            mult, name = await _get_zone_multiplier(AsyncMock(), 40.7128, -74.0060)

        assert mult == 1.0
        assert name is None

    async def test_point_outside_zone_skipped(self):
        from app.models.surge import SurgePricingZone

        zone = MagicMock(spec=SurgePricingZone)
        zone.multiplier = 1.3
        zone.name = "Downtown"

        with (
            patch("app.api.v1.surge_status.list_zones", new=AsyncMock(return_value=[zone])),
            patch("app.api.v1.surge_status.is_zone_active_now", return_value=True),
            patch("app.api.v1.surge_status._point_in_zone", return_value=False),
        ):
            mult, name = await _get_zone_multiplier(AsyncMock(), 40.7128, -74.0060)

        assert mult == 1.0

    async def test_picks_highest_multiplier_among_multiple_zones(self):
        from app.models.surge import SurgePricingZone

        zone_low = MagicMock(spec=SurgePricingZone)
        zone_low.multiplier = 1.2
        zone_low.name = "Low Zone"

        zone_high = MagicMock(spec=SurgePricingZone)
        zone_high.multiplier = 1.8
        zone_high.name = "High Zone"

        with (
            patch("app.api.v1.surge_status.list_zones", new=AsyncMock(return_value=[zone_low, zone_high])),
            patch("app.api.v1.surge_status.is_zone_active_now", return_value=True),
            patch("app.api.v1.surge_status._point_in_zone", return_value=True),
        ):
            mult, name = await _get_zone_multiplier(AsyncMock(), 40.7128, -74.0060)

        assert mult == 1.8
        assert name == "High Zone"

    async def test_db_failure_returns_one(self):
        with patch("app.api.v1.surge_status.list_zones", side_effect=Exception("DB down")):
            mult, name = await _get_zone_multiplier(AsyncMock(), 40.7128, -74.0060)
        assert mult == 1.0
        assert name is None


# ===========================================================================
# GET /surge/current — endpoint integration
# ===========================================================================


@pytest.mark.anyio
class TestSurgeCurrentEndpoint:
    async def _client(self, db_override=None):
        from httpx import ASGITransport, AsyncClient
        from app.main import app
        from app.db.database import get_db

        if db_override is None:
            db_override = _mock_db_no_zones()

        app.dependency_overrides[get_db] = lambda: db_override
        client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
        return client, app

    async def test_missing_params_returns_422(self):
        client, app = await self._client()
        async with client:
            resp = await client.get("/api/v1/surge/current")
        app.dependency_overrides.clear()
        assert resp.status_code == 422

    async def test_lat_out_of_range_returns_422(self):
        client, app = await self._client()
        async with client:
            resp = await client.get(
                "/api/v1/surge/current",
                params={"lat": 999, "lng": -74.0060},
            )
        app.dependency_overrides.clear()
        assert resp.status_code == 422

    async def test_lng_out_of_range_returns_422(self):
        client, app = await self._client()
        async with client:
            resp = await client.get(
                "/api/v1/surge/current",
                params={"lat": 40.7128, "lng": 999},
            )
        app.dependency_overrides.clear()
        assert resp.status_code == 422

    async def test_no_surge_returns_200_with_standard_message(self):
        demand_info = _make_demand_info(multiplier=1.0, is_elevated=False)

        with (
            patch("app.api.v1.surge_status.list_zones", new=AsyncMock(return_value=[])),
            patch("app.api.v1.surge_status.get_demand_info", new=AsyncMock(return_value=demand_info)),
            patch("app.services.matching.get_redis", new=AsyncMock(return_value=AsyncMock())),
        ):
            client, app = await self._client()
            async with client:
                resp = await client.get(
                    "/api/v1/surge/current",
                    params={"lat": 40.7128, "lng": -74.0060},
                )
        app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["is_surge_active"] is False
        assert data["zone_multiplier"] == 1.0
        assert data["demand_multiplier"] == 1.0
        assert data["combined_multiplier"] == 1.0
        assert data["zone_name"] is None
        assert "Standard pricing" in data["message"]

    async def test_zone_surge_active(self):
        from app.models.surge import SurgePricingZone

        zone = MagicMock(spec=SurgePricingZone)
        zone.multiplier = 1.3
        zone.name = "Stadium"
        demand_info = _make_demand_info(multiplier=1.0, is_elevated=False)

        with (
            patch("app.api.v1.surge_status.list_zones", new=AsyncMock(return_value=[zone])),
            patch("app.api.v1.surge_status.is_zone_active_now", return_value=True),
            patch("app.api.v1.surge_status._point_in_zone", return_value=True),
            patch("app.api.v1.surge_status.get_demand_info", new=AsyncMock(return_value=demand_info)),
            patch("app.services.matching.get_redis", new=AsyncMock(return_value=AsyncMock())),
        ):
            client, app = await self._client()
            async with client:
                resp = await client.get(
                    "/api/v1/surge/current",
                    params={"lat": 40.7128, "lng": -74.0060},
                )
        app.dependency_overrides.clear()

        data = resp.json()
        assert data["is_surge_active"] is True
        assert data["zone_multiplier"] == 1.3
        assert data["zone_name"] == "Stadium"
        assert "Stadium" in data["message"]
        assert "30%" in data["message"]

    async def test_demand_surge_active(self):
        demand_info = _make_demand_info(multiplier=1.25, is_elevated=True)

        with (
            patch("app.api.v1.surge_status.list_zones", new=AsyncMock(return_value=[])),
            patch("app.api.v1.surge_status.get_demand_info", new=AsyncMock(return_value=demand_info)),
            patch("app.services.matching.get_redis", new=AsyncMock(return_value=AsyncMock())),
        ):
            client, app = await self._client()
            async with client:
                resp = await client.get(
                    "/api/v1/surge/current",
                    params={"lat": 40.7128, "lng": -74.0060},
                )
        app.dependency_overrides.clear()

        data = resp.json()
        assert data["is_surge_active"] is True
        assert data["demand_multiplier"] == 1.25
        assert data["zone_name"] is None
        assert "high demand" in data["message"]
        assert "25%" in data["message"]

    async def test_both_zone_and_demand_active(self):
        from app.models.surge import SurgePricingZone

        zone = MagicMock(spec=SurgePricingZone)
        zone.multiplier = 1.2
        zone.name = "Airport"
        demand_info = _make_demand_info(multiplier=1.3, is_elevated=True)

        with (
            patch("app.api.v1.surge_status.list_zones", new=AsyncMock(return_value=[zone])),
            patch("app.api.v1.surge_status.is_zone_active_now", return_value=True),
            patch("app.api.v1.surge_status._point_in_zone", return_value=True),
            patch("app.api.v1.surge_status.get_demand_info", new=AsyncMock(return_value=demand_info)),
            patch("app.services.matching.get_redis", new=AsyncMock(return_value=AsyncMock())),
        ):
            client, app = await self._client()
            async with client:
                resp = await client.get(
                    "/api/v1/surge/current",
                    params={"lat": 40.7128, "lng": -74.0060},
                )
        app.dependency_overrides.clear()

        data = resp.json()
        assert data["is_surge_active"] is True
        assert data["zone_multiplier"] == pytest.approx(1.2)
        assert data["demand_multiplier"] == pytest.approx(1.3)
        # combined = 1.2 * 1.3 = 1.56
        assert data["combined_multiplier"] == pytest.approx(1.56, abs=0.01)
        assert "Airport" in data["message"]
        assert "high demand" in data["message"]

    async def test_redis_unavailable_falls_back_to_no_demand_surge(self):
        with (
            patch("app.api.v1.surge_status.list_zones", new=AsyncMock(return_value=[])),
            patch("app.services.matching.get_redis", side_effect=Exception("Redis unavailable")),
        ):
            client, app = await self._client()
            async with client:
                resp = await client.get(
                    "/api/v1/surge/current",
                    params={"lat": 40.7128, "lng": -74.0060},
                )
        app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["demand_multiplier"] == 1.0
        assert data["is_surge_active"] is False

    async def test_db_failure_falls_back_to_no_zone_surge(self):
        demand_info = _make_demand_info(multiplier=1.0, is_elevated=False)

        with (
            patch("app.api.v1.surge_status.list_zones", side_effect=Exception("DB down")),
            patch("app.api.v1.surge_status.get_demand_info", new=AsyncMock(return_value=demand_info)),
            patch("app.services.matching.get_redis", new=AsyncMock(return_value=AsyncMock())),
        ):
            client, app = await self._client()
            async with client:
                resp = await client.get(
                    "/api/v1/surge/current",
                    params={"lat": 40.7128, "lng": -74.0060},
                )
        app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["zone_multiplier"] == 1.0
        assert data["zone_name"] is None

    async def test_no_auth_required(self):
        demand_info = _make_demand_info()

        with (
            patch("app.api.v1.surge_status.list_zones", new=AsyncMock(return_value=[])),
            patch("app.api.v1.surge_status.get_demand_info", new=AsyncMock(return_value=demand_info)),
            patch("app.services.matching.get_redis", new=AsyncMock(return_value=AsyncMock())),
        ):
            client, app = await self._client()
            async with client:
                resp = await client.get(
                    "/api/v1/surge/current",
                    params={"lat": 40.7128, "lng": -74.0060},
                )
        app.dependency_overrides.clear()
        assert resp.status_code == 200

    async def test_response_shape(self):
        demand_info = _make_demand_info()

        with (
            patch("app.api.v1.surge_status.list_zones", new=AsyncMock(return_value=[])),
            patch("app.api.v1.surge_status.get_demand_info", new=AsyncMock(return_value=demand_info)),
            patch("app.services.matching.get_redis", new=AsyncMock(return_value=AsyncMock())),
        ):
            client, app = await self._client()
            async with client:
                resp = await client.get(
                    "/api/v1/surge/current",
                    params={"lat": 40.7128, "lng": -74.0060},
                )
        app.dependency_overrides.clear()

        data = resp.json()
        for field in ("is_surge_active", "zone_multiplier", "demand_multiplier",
                      "combined_multiplier", "zone_name", "message"):
            assert field in data, f"Missing field: {field}"
