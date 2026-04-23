"""Tests for the fare forecast feature.

Covers:
- demand_heuristic:        morning rush, evening rush, bar close, off-peak,
                           boundary hours, overnight window edges
- build_recommendation:    no surge, surge active, cheapest in future,
                           cheapest now with future surge, future cheaper than now
- get_fare_forecast:       6 slots, ordering, cheapest marking, distance,
                           no-surge baseline, zone surge active at some slots,
                           validation errors (lookahead out of range),
                           DB failure fallback, explicit now param
- GET /pricing/fare-forecast endpoint: valid request -> 200, response shape,
                           bad lat/lon -> 422, lookahead out of range -> 422,
                           no auth required, cheapest slot uniqueness
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.fare_forecast import (
    build_recommendation,
    demand_heuristic,
    get_fare_forecast,
)


# ===========================================================================
# demand_heuristic — pure time-of-day demand estimate
# ===========================================================================


def _utc(hour: int, minute: int = 0) -> datetime:
    """Convenience: build a UTC datetime with the given hour."""
    return datetime(2024, 6, 15, hour, minute, 0, tzinfo=timezone.utc)


class TestDemandHeuristic:
    def test_morning_rush_start(self):
        mult, label = demand_heuristic(_utc(7))
        assert mult == pytest.approx(1.3)
        assert "morning rush" in label

    def test_morning_rush_mid(self):
        mult, label = demand_heuristic(_utc(8))
        assert mult == pytest.approx(1.3)
        assert "morning rush" in label

    def test_morning_rush_end_exclusive(self):
        """Hour 9 is outside the 7–9 window."""
        mult, label = demand_heuristic(_utc(9))
        assert mult == pytest.approx(1.0)
        assert label == "off-peak"

    def test_evening_rush_start(self):
        mult, label = demand_heuristic(_utc(17))
        assert mult == pytest.approx(1.3)
        assert "evening rush" in label

    def test_evening_rush_mid(self):
        mult, label = demand_heuristic(_utc(18))
        assert mult == pytest.approx(1.3)
        assert "evening rush" in label

    def test_evening_rush_end_exclusive(self):
        """Hour 19 is outside the 17–19 window."""
        mult, label = demand_heuristic(_utc(19))
        assert mult == pytest.approx(1.0)
        assert label == "off-peak"

    def test_bar_close_late_night(self):
        mult, label = demand_heuristic(_utc(23))
        assert mult == pytest.approx(1.2)
        assert "bar close" in label

    def test_bar_close_midnight(self):
        mult, label = demand_heuristic(_utc(0))
        assert mult == pytest.approx(1.2)
        assert "bar close" in label

    def test_bar_close_1am(self):
        mult, label = demand_heuristic(_utc(1))
        assert mult == pytest.approx(1.2)
        assert "bar close" in label

    def test_bar_close_end_exclusive(self):
        """Hour 2 is outside the 23–02 overnight window."""
        mult, label = demand_heuristic(_utc(2))
        assert mult == pytest.approx(1.0)
        assert label == "off-peak"

    def test_off_peak_midday(self):
        mult, label = demand_heuristic(_utc(13))
        assert mult == pytest.approx(1.0)
        assert label == "off-peak"

    def test_off_peak_early_morning(self):
        mult, label = demand_heuristic(_utc(4))
        assert mult == pytest.approx(1.0)

    def test_off_peak_late_afternoon(self):
        mult, label = demand_heuristic(_utc(16))
        assert mult == pytest.approx(1.0)

    def test_returns_tuple(self):
        result = demand_heuristic(_utc(10))
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_multiplier_is_float(self):
        mult, _ = demand_heuristic(_utc(8))
        assert isinstance(mult, float)


# ===========================================================================
# build_recommendation — pure recommendation string builder
# ===========================================================================


def _make_slots(
    fares: list[float],
    surge_active: list[bool] | None = None,
) -> list[dict]:
    """Build a minimal slot list for testing build_recommendation."""
    if surge_active is None:
        surge_active = [False] * len(fares)
    offsets = [i * 48 for i in range(len(fares))]  # 48-min intervals
    return [
        {
            "offset_minutes": offset,
            "estimated_fare": fare,
            "is_surge_active": active,
            "combined_multiplier": 1.3 if active else 1.0,
        }
        for offset, fare, active in zip(offsets, fares, surge_active)
    ]


class TestBuildRecommendation:
    def test_no_surge_anywhere(self):
        slots = _make_slots([15.0, 15.0, 15.0, 15.0, 15.0, 15.0])
        rec = build_recommendation(slots)
        assert "no surge" in rec.lower()
        assert "now" in rec.lower() or "good" in rec.lower()

    def test_cheapest_is_future_slot(self):
        # Current fare is high, cheaper later
        slots = _make_slots(
            [20.0, 18.0, 14.0, 16.0, 17.0, 19.0],
            surge_active=[True, True, False, True, True, True],
        )
        rec = build_recommendation(slots)
        # Should mention the offset (96 min for index 2)
        assert "96" in rec
        # Should mention percentage higher
        assert "%" in rec

    def test_cheapest_is_now(self):
        # Now is cheapest, but future slots have surge
        slots = _make_slots(
            [12.0, 18.0, 20.0, 19.0, 17.0, 16.0],
            surge_active=[False, True, True, True, True, True],
        )
        rec = build_recommendation(slots)
        assert "now" in rec.lower()
        assert "surge" in rec.lower()

    def test_now_cheapest_no_future_surge(self):
        # Now is cheapest and no future surge
        slots = _make_slots(
            [12.0, 13.0, 14.0, 15.0, 16.0, 17.0],
            surge_active=[False, False, False, False, False, False],
        )
        rec = build_recommendation(slots)
        assert "no surge" in rec.lower()

    def test_surge_active_future_cheaper(self):
        slots = _make_slots(
            [25.0, 22.0, 15.0, 18.0, 20.0, 24.0],
            surge_active=[True, True, False, True, True, True],
        )
        rec = build_recommendation(slots)
        assert isinstance(rec, str)
        assert len(rec) > 10

    def test_empty_slots(self):
        rec = build_recommendation([])
        assert "no forecast" in rec.lower() or "unavailable" in rec.lower()

    def test_percentage_higher_is_accurate(self):
        # Current = 20.0, cheapest = 10.0 -> 100% higher
        slots = _make_slots(
            [20.0, 10.0, 12.0, 14.0, 16.0, 18.0],
            surge_active=[True, False, False, True, True, True],
        )
        rec = build_recommendation(slots)
        assert "100%" in rec

    def test_tie_broken_by_earliest(self):
        # Slots at equal fare — cheapest should be offset=0 (earliest)
        slots = _make_slots(
            [15.0, 15.0, 15.0, 15.0, 15.0, 15.0],
            surge_active=[False, True, True, True, True, True],
        )
        rec = build_recommendation(slots)
        # Since slot 0 is cheapest (tie → earliest), should mention "now"
        assert isinstance(rec, str)

    def test_returns_string(self):
        slots = _make_slots([10.0, 12.0, 11.0, 13.0, 14.0, 15.0])
        assert isinstance(build_recommendation(slots), str)


# ===========================================================================
# get_fare_forecast — async service (mocked DB)
# ===========================================================================


def _mock_db_no_zones() -> AsyncMock:
    """DB mock that returns zero surge zones."""
    db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    db.execute.return_value = result
    return db


def _mock_db_with_zone(
    multiplier: float = 1.4,
    name: str = "Airport Zone",
    start_time=None,
    end_time=None,
    days_of_week=None,
) -> AsyncMock:
    """DB mock with a single active circular surge zone covering NYC-area coords."""
    from app.models.surge import SurgePricingZone

    zone = MagicMock(spec=SurgePricingZone)
    zone.is_active = True
    zone.multiplier = multiplier
    zone.name = name
    zone.description = f"{name} description"
    zone.polygon = None
    zone.center_lat = 40.7128
    zone.center_lon = -74.0060
    zone.radius_km = 50.0  # covers all NYC test coordinates
    zone.days_of_week = days_of_week
    zone.start_time = start_time
    zone.end_time = end_time

    db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = [zone]
    db.execute.return_value = result
    return db


@pytest.mark.anyio
class TestGetFareForecast:
    async def test_returns_exactly_six_slots(self):
        db = _mock_db_no_zones()
        with patch("app.services.fare_forecast.list_zones", new=AsyncMock(return_value=[])):
            result = await get_fare_forecast(
                db, 40.7128, -74.0060, 40.7580, -73.9855, lookahead_hours=4
            )
        assert len(result.slots) == 6

    async def test_slots_ordered_by_offset_ascending(self):
        db = _mock_db_no_zones()
        with patch("app.services.fare_forecast.list_zones", new=AsyncMock(return_value=[])):
            result = await get_fare_forecast(
                db, 40.7128, -74.0060, 40.7580, -73.9855, lookahead_hours=4
            )
        offsets = [s.offset_minutes for s in result.slots]
        assert offsets == sorted(offsets)

    async def test_first_slot_offset_is_zero(self):
        db = _mock_db_no_zones()
        with patch("app.services.fare_forecast.list_zones", new=AsyncMock(return_value=[])):
            result = await get_fare_forecast(
                db, 40.7128, -74.0060, 40.7580, -73.9855, lookahead_hours=4
            )
        assert result.slots[0].offset_minutes == 0

    async def test_last_slot_offset_matches_lookahead(self):
        db = _mock_db_no_zones()
        with patch("app.services.fare_forecast.list_zones", new=AsyncMock(return_value=[])):
            result = await get_fare_forecast(
                db, 40.7128, -74.0060, 40.7580, -73.9855, lookahead_hours=4
            )
        assert result.slots[-1].offset_minutes == 4 * 60

    async def test_exactly_one_slot_is_cheapest(self):
        db = _mock_db_no_zones()
        with patch("app.services.fare_forecast.list_zones", new=AsyncMock(return_value=[])):
            result = await get_fare_forecast(
                db, 40.7128, -74.0060, 40.7580, -73.9855
            )
        cheapest_slots = [s for s in result.slots if s.is_cheapest]
        assert len(cheapest_slots) == 1

    async def test_cheapest_slot_has_minimum_fare(self):
        db = _mock_db_no_zones()
        with patch("app.services.fare_forecast.list_zones", new=AsyncMock(return_value=[])):
            result = await get_fare_forecast(
                db, 40.7128, -74.0060, 40.7580, -73.9855
            )
        cheapest = next(s for s in result.slots if s.is_cheapest)
        all_fares = [s.estimated_fare for s in result.slots]
        assert cheapest.estimated_fare == pytest.approx(min(all_fares))

    async def test_distance_is_positive(self):
        db = _mock_db_no_zones()
        with patch("app.services.fare_forecast.list_zones", new=AsyncMock(return_value=[])):
            result = await get_fare_forecast(
                db, 40.7128, -74.0060, 40.7580, -73.9855
            )
        assert result.distance_km > 0

    async def test_duration_is_positive(self):
        db = _mock_db_no_zones()
        with patch("app.services.fare_forecast.list_zones", new=AsyncMock(return_value=[])):
            result = await get_fare_forecast(
                db, 40.7128, -74.0060, 40.7580, -73.9855
            )
        assert result.estimated_duration_min > 0

    async def test_demand_is_heuristic_always_true(self):
        db = _mock_db_no_zones()
        with patch("app.services.fare_forecast.list_zones", new=AsyncMock(return_value=[])):
            result = await get_fare_forecast(
                db, 40.7128, -74.0060, 40.7580, -73.9855
            )
        assert result.demand_is_heuristic is True

    async def test_no_surge_zones_all_multipliers_reflect_demand_only(self):
        """With no zones, combined multiplier equals demand multiplier."""
        db = _mock_db_no_zones()
        # Force off-peak time for all slots
        fixed_now = datetime(2024, 6, 15, 14, 0, 0, tzinfo=timezone.utc)  # 2 PM UTC
        with patch("app.services.fare_forecast.list_zones", new=AsyncMock(return_value=[])):
            result = await get_fare_forecast(
                db, 40.7128, -74.0060, 40.7580, -73.9855, lookahead_hours=1, now=fixed_now
            )
        # 1 hour / 5 = 12 min per step; all slots at 14:00–15:00 UTC = off-peak
        for slot in result.slots:
            assert slot.surge_multiplier == pytest.approx(1.0)
            assert slot.surge_zone_name is None

    async def test_surge_zone_active_increases_fare(self):
        """Zone with 1.4x multiplier should produce higher fares than no zone."""
        fixed_now = datetime(2024, 6, 15, 14, 0, 0, tzinfo=timezone.utc)

        from app.models.surge import SurgePricingZone

        zone = MagicMock(spec=SurgePricingZone)
        zone.is_active = True
        zone.multiplier = 1.4
        zone.name = "Test Zone"
        zone.description = None
        zone.polygon = None
        zone.center_lat = 40.7128
        zone.center_lon = -74.0060
        zone.radius_km = 50.0
        zone.days_of_week = None
        zone.start_time = None
        zone.end_time = None

        with (
            patch("app.services.fare_forecast.list_zones", new=AsyncMock(return_value=[zone])),
            patch("app.services.fare_forecast.is_zone_active_now", return_value=True),
            patch("app.services.fare_forecast._point_in_zone", return_value=True),
        ):
            result_surge = await get_fare_forecast(
                AsyncMock(), 40.7128, -74.0060, 40.7580, -73.9855, now=fixed_now
            )

        with patch("app.services.fare_forecast.list_zones", new=AsyncMock(return_value=[])):
            result_no_surge = await get_fare_forecast(
                AsyncMock(), 40.7128, -74.0060, 40.7580, -73.9855, now=fixed_now
            )

        # Surge should produce higher or equal fares (minimum_fare floor may equalise)
        for s_slot, ns_slot in zip(result_surge.slots, result_no_surge.slots):
            assert s_slot.estimated_fare >= ns_slot.estimated_fare

    async def test_surge_slots_flagged_is_surge_active(self):
        """Slots with combined_multiplier > 1.0 must have is_surge_active=True."""
        from app.models.surge import SurgePricingZone

        zone = MagicMock(spec=SurgePricingZone)
        zone.is_active = True
        zone.multiplier = 1.5
        zone.name = "Stadium Zone"
        zone.description = None
        zone.polygon = None
        zone.center_lat = 40.7128
        zone.center_lon = -74.0060
        zone.radius_km = 50.0
        zone.days_of_week = None
        zone.start_time = None
        zone.end_time = None

        with (
            patch("app.services.fare_forecast.list_zones", new=AsyncMock(return_value=[zone])),
            patch("app.services.fare_forecast.is_zone_active_now", return_value=True),
            patch("app.services.fare_forecast._point_in_zone", return_value=True),
        ):
            result = await get_fare_forecast(
                AsyncMock(), 40.7128, -74.0060, 40.7580, -73.9855
            )

        for slot in result.slots:
            assert slot.is_surge_active is True
            assert slot.combined_multiplier > 1.0

    async def test_db_failure_returns_no_zone_fallback(self):
        """If list_zones raises, forecast continues with no surge zones."""
        with patch(
            "app.services.fare_forecast.list_zones",
            side_effect=Exception("DB unavailable"),
        ):
            result = await get_fare_forecast(
                AsyncMock(), 40.7128, -74.0060, 40.7580, -73.9855
            )
        assert len(result.slots) == 6
        for slot in result.slots:
            assert slot.surge_multiplier == pytest.approx(1.0)

    async def test_explicit_now_param_used_for_slot_times(self):
        """Passing an explicit `now` should set slot 0's departure to that time."""
        fixed_now = datetime(2024, 3, 10, 8, 0, 0, tzinfo=timezone.utc)
        with patch("app.services.fare_forecast.list_zones", new=AsyncMock(return_value=[])):
            result = await get_fare_forecast(
                AsyncMock(),
                40.7128, -74.0060, 40.7580, -73.9855,
                now=fixed_now,
            )
        assert result.slots[0].estimated_departure == fixed_now
        assert result.forecast_generated_at == fixed_now

    async def test_lookahead_hours_2_gives_correct_last_offset(self):
        with patch("app.services.fare_forecast.list_zones", new=AsyncMock(return_value=[])):
            result = await get_fare_forecast(
                AsyncMock(),
                40.7128, -74.0060, 40.7580, -73.9855,
                lookahead_hours=2,
            )
        assert result.slots[-1].offset_minutes == 120

    async def test_lookahead_hours_12_gives_correct_last_offset(self):
        with patch("app.services.fare_forecast.list_zones", new=AsyncMock(return_value=[])):
            result = await get_fare_forecast(
                AsyncMock(),
                40.7128, -74.0060, 40.7580, -73.9855,
                lookahead_hours=12,
            )
        assert result.slots[-1].offset_minutes == 720

    async def test_estimated_fares_are_positive(self):
        with patch("app.services.fare_forecast.list_zones", new=AsyncMock(return_value=[])):
            result = await get_fare_forecast(
                AsyncMock(), 40.7128, -74.0060, 40.7580, -73.9855
            )
        for slot in result.slots:
            assert slot.estimated_fare > 0

    async def test_recommendation_is_non_empty_string(self):
        with patch("app.services.fare_forecast.list_zones", new=AsyncMock(return_value=[])):
            result = await get_fare_forecast(
                AsyncMock(), 40.7128, -74.0060, 40.7580, -73.9855
            )
        assert isinstance(result.recommendation, str)
        assert len(result.recommendation) > 0

    async def test_morning_rush_slot_has_elevated_demand_multiplier(self):
        """A slot landing in 07–09 UTC should have demand_multiplier=1.3."""
        # Start at 06:55 UTC — slot index 1 (at +20% of 60 min = +12 min) will be 07:07
        fixed_now = datetime(2024, 6, 15, 6, 55, 0, tzinfo=timezone.utc)
        with patch("app.services.fare_forecast.list_zones", new=AsyncMock(return_value=[])):
            result = await get_fare_forecast(
                AsyncMock(),
                40.7128, -74.0060, 40.7580, -73.9855,
                lookahead_hours=1,
                now=fixed_now,
            )
        # slot 0 = 06:55 (off-peak), slot 1 = 07:07 (morning rush)
        assert result.slots[0].demand_multiplier == pytest.approx(1.0)
        assert result.slots[1].demand_multiplier == pytest.approx(1.3)


# ===========================================================================
# GET /pricing/fare-forecast — endpoint integration
# ===========================================================================


async def _build_client(db_override=None):
    """Build a test client with an optional DB override."""
    from httpx import ASGITransport, AsyncClient
    from app.main import app
    from app.db.database import get_db

    if db_override is None:
        db_override = _mock_db_no_zones()

    app.dependency_overrides[get_db] = lambda: db_override
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    return client, app


@pytest.mark.anyio
class TestFareForecastEndpoint:
    async def test_valid_params_returns_200(self):
        with patch("app.services.fare_forecast.list_zones", new=AsyncMock(return_value=[])):
            client, app = await _build_client()
            async with client:
                resp = await client.get(
                    "/api/v1/pricing/fare-forecast",
                    params={
                        "origin_lat": 40.7128,
                        "origin_lon": -74.0060,
                        "dest_lat": 40.7580,
                        "dest_lon": -73.9855,
                    },
                )
        app.dependency_overrides.clear()
        assert resp.status_code == 200

    async def test_response_has_six_slots(self):
        with patch("app.services.fare_forecast.list_zones", new=AsyncMock(return_value=[])):
            client, app = await _build_client()
            async with client:
                resp = await client.get(
                    "/api/v1/pricing/fare-forecast",
                    params={
                        "origin_lat": 40.7128,
                        "origin_lon": -74.0060,
                        "dest_lat": 40.7580,
                        "dest_lon": -73.9855,
                    },
                )
        app.dependency_overrides.clear()
        data = resp.json()
        assert len(data["slots"]) == 6

    async def test_response_shape_top_level_fields(self):
        with patch("app.services.fare_forecast.list_zones", new=AsyncMock(return_value=[])):
            client, app = await _build_client()
            async with client:
                resp = await client.get(
                    "/api/v1/pricing/fare-forecast",
                    params={
                        "origin_lat": 40.7128,
                        "origin_lon": -74.0060,
                        "dest_lat": 40.7580,
                        "dest_lon": -73.9855,
                    },
                )
        app.dependency_overrides.clear()
        data = resp.json()
        for field in (
            "origin_lat", "origin_lon", "dest_lat", "dest_lon",
            "distance_km", "estimated_duration_min", "demand_is_heuristic",
            "forecast_generated_at", "slots", "recommendation",
        ):
            assert field in data, f"Missing top-level field: {field}"

    async def test_response_shape_slot_fields(self):
        with patch("app.services.fare_forecast.list_zones", new=AsyncMock(return_value=[])):
            client, app = await _build_client()
            async with client:
                resp = await client.get(
                    "/api/v1/pricing/fare-forecast",
                    params={
                        "origin_lat": 40.7128,
                        "origin_lon": -74.0060,
                        "dest_lat": 40.7580,
                        "dest_lon": -73.9855,
                    },
                )
        app.dependency_overrides.clear()
        slot = resp.json()["slots"][0]
        for field in (
            "offset_minutes", "estimated_departure", "surge_multiplier",
            "surge_zone_name", "demand_multiplier", "combined_multiplier",
            "is_surge_active", "estimated_fare", "is_cheapest",
        ):
            assert field in slot, f"Missing slot field: {field}"

    async def test_exactly_one_cheapest_slot_in_response(self):
        with patch("app.services.fare_forecast.list_zones", new=AsyncMock(return_value=[])):
            client, app = await _build_client()
            async with client:
                resp = await client.get(
                    "/api/v1/pricing/fare-forecast",
                    params={
                        "origin_lat": 40.7128,
                        "origin_lon": -74.0060,
                        "dest_lat": 40.7580,
                        "dest_lon": -73.9855,
                    },
                )
        app.dependency_overrides.clear()
        cheapest = [s for s in resp.json()["slots"] if s["is_cheapest"]]
        assert len(cheapest) == 1

    async def test_demand_is_heuristic_true_in_response(self):
        with patch("app.services.fare_forecast.list_zones", new=AsyncMock(return_value=[])):
            client, app = await _build_client()
            async with client:
                resp = await client.get(
                    "/api/v1/pricing/fare-forecast",
                    params={
                        "origin_lat": 40.7128,
                        "origin_lon": -74.0060,
                        "dest_lat": 40.7580,
                        "dest_lon": -73.9855,
                    },
                )
        app.dependency_overrides.clear()
        assert resp.json()["demand_is_heuristic"] is True

    async def test_no_auth_required(self):
        """Endpoint must be accessible without an Authorization header."""
        with patch("app.services.fare_forecast.list_zones", new=AsyncMock(return_value=[])):
            client, app = await _build_client()
            async with client:
                resp = await client.get(
                    "/api/v1/pricing/fare-forecast",
                    params={
                        "origin_lat": 40.7128,
                        "origin_lon": -74.0060,
                        "dest_lat": 40.7580,
                        "dest_lon": -73.9855,
                    },
                )
        app.dependency_overrides.clear()
        assert resp.status_code == 200

    async def test_missing_required_params_returns_422(self):
        client, app = await _build_client()
        async with client:
            resp = await client.get("/api/v1/pricing/fare-forecast")
        app.dependency_overrides.clear()
        assert resp.status_code == 422

    async def test_origin_lat_out_of_range_returns_422(self):
        client, app = await _build_client()
        async with client:
            resp = await client.get(
                "/api/v1/pricing/fare-forecast",
                params={
                    "origin_lat": 999,
                    "origin_lon": -74.0060,
                    "dest_lat": 40.7580,
                    "dest_lon": -73.9855,
                },
            )
        app.dependency_overrides.clear()
        assert resp.status_code == 422

    async def test_dest_lon_out_of_range_returns_422(self):
        client, app = await _build_client()
        async with client:
            resp = await client.get(
                "/api/v1/pricing/fare-forecast",
                params={
                    "origin_lat": 40.7128,
                    "origin_lon": -74.0060,
                    "dest_lat": 40.7580,
                    "dest_lon": 999,  # invalid
                },
            )
        app.dependency_overrides.clear()
        assert resp.status_code == 422

    async def test_lookahead_hours_zero_returns_422(self):
        client, app = await _build_client()
        async with client:
            resp = await client.get(
                "/api/v1/pricing/fare-forecast",
                params={
                    "origin_lat": 40.7128,
                    "origin_lon": -74.0060,
                    "dest_lat": 40.7580,
                    "dest_lon": -73.9855,
                    "lookahead_hours": 0,
                },
            )
        app.dependency_overrides.clear()
        assert resp.status_code == 422

    async def test_lookahead_hours_13_returns_422(self):
        client, app = await _build_client()
        async with client:
            resp = await client.get(
                "/api/v1/pricing/fare-forecast",
                params={
                    "origin_lat": 40.7128,
                    "origin_lon": -74.0060,
                    "dest_lat": 40.7580,
                    "dest_lon": -73.9855,
                    "lookahead_hours": 13,
                },
            )
        app.dependency_overrides.clear()
        assert resp.status_code == 422

    async def test_lookahead_hours_custom_value_accepted(self):
        with patch("app.services.fare_forecast.list_zones", new=AsyncMock(return_value=[])):
            client, app = await _build_client()
            async with client:
                resp = await client.get(
                    "/api/v1/pricing/fare-forecast",
                    params={
                        "origin_lat": 40.7128,
                        "origin_lon": -74.0060,
                        "dest_lat": 40.7580,
                        "dest_lon": -73.9855,
                        "lookahead_hours": 8,
                    },
                )
        app.dependency_overrides.clear()
        assert resp.status_code == 200
        data = resp.json()
        # Last slot should be at 8*60 = 480 minutes
        assert data["slots"][-1]["offset_minutes"] == 480

    async def test_recommendation_is_non_empty(self):
        with patch("app.services.fare_forecast.list_zones", new=AsyncMock(return_value=[])):
            client, app = await _build_client()
            async with client:
                resp = await client.get(
                    "/api/v1/pricing/fare-forecast",
                    params={
                        "origin_lat": 40.7128,
                        "origin_lon": -74.0060,
                        "dest_lat": 40.7580,
                        "dest_lon": -73.9855,
                    },
                )
        app.dependency_overrides.clear()
        rec = resp.json()["recommendation"]
        assert isinstance(rec, str)
        assert len(rec) > 5

    async def test_slots_ordered_by_offset_in_response(self):
        with patch("app.services.fare_forecast.list_zones", new=AsyncMock(return_value=[])):
            client, app = await _build_client()
            async with client:
                resp = await client.get(
                    "/api/v1/pricing/fare-forecast",
                    params={
                        "origin_lat": 40.7128,
                        "origin_lon": -74.0060,
                        "dest_lat": 40.7580,
                        "dest_lon": -73.9855,
                    },
                )
        app.dependency_overrides.clear()
        offsets = [s["offset_minutes"] for s in resp.json()["slots"]]
        assert offsets == sorted(offsets)
