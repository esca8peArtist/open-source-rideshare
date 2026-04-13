"""Tests for transparent supply/demand-aware pricing.

Covers: geohash encoding/decoding, demand tracking, supply counting,
multiplier calculation, demand info generation, pricing integration,
admin configuration, and edge cases.
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.demand_pricing import (
    DemandInfo,
    _decode_geohash_center,
    _geohash_dimensions,
    calculate_demand_multiplier,
    encode_geohash,
    geohash_neighbors,
    get_area_demand,
    get_area_supply,
    get_demand_count,
    get_demand_info,
    record_demand,
)
from app.services.pricing import FareBreakdown, calculate_fare_breakdown
from app.schemas.demand_pricing import (
    DemandInfoResponse,
    DemandPricingConfigResponse,
    DemandPricingConfigUpdate,
)
from app.schemas.ride import DemandInfoSummary, FareBreakdownResponse


# ===========================================================================
# Geohash Encoding Tests
# ===========================================================================


class TestGeohashEncoding:
    def test_encode_known_location_nyc(self):
        """New York City should produce a known geohash prefix."""
        gh = encode_geohash(40.7128, -74.0060, precision=5)
        assert len(gh) == 5
        assert gh.startswith("dr5r")

    def test_encode_known_location_sf(self):
        """San Francisco should produce a known geohash prefix."""
        gh = encode_geohash(37.7749, -122.4194, precision=5)
        assert len(gh) == 5
        assert gh.startswith("9q8y")

    def test_encode_equator_prime_meridian(self):
        gh = encode_geohash(0.0, 0.0, precision=5)
        assert len(gh) == 5
        assert gh == "s0000"

    def test_encode_precision_varies_length(self):
        for p in range(1, 9):
            gh = encode_geohash(40.7128, -74.0060, precision=p)
            assert len(gh) == p

    def test_encode_nearby_points_same_cell(self):
        """Two nearby points should land in the same geohash cell at precision 5."""
        gh1 = encode_geohash(40.7128, -74.0060, precision=5)
        gh2 = encode_geohash(40.7130, -74.0058, precision=5)
        assert gh1 == gh2

    def test_encode_distant_points_different_cells(self):
        """NYC and SF should have different geohashes."""
        gh_nyc = encode_geohash(40.7128, -74.0060, precision=5)
        gh_sf = encode_geohash(37.7749, -122.4194, precision=5)
        assert gh_nyc != gh_sf

    def test_encode_negative_coordinates(self):
        """Southern hemisphere / western hemisphere coordinates."""
        gh = encode_geohash(-33.8688, 151.2093, precision=5)  # Sydney
        assert len(gh) == 5

    def test_encode_extreme_coordinates(self):
        """Boundary coordinates should not crash."""
        gh_north = encode_geohash(89.99, 0.0, precision=5)
        gh_south = encode_geohash(-89.99, 0.0, precision=5)
        gh_east = encode_geohash(0.0, 179.99, precision=5)
        gh_west = encode_geohash(0.0, -179.99, precision=5)
        assert all(len(g) == 5 for g in [gh_north, gh_south, gh_east, gh_west])


class TestGeohashDecoding:
    def test_decode_roundtrip(self):
        """Encoding then decoding should return approximately the original point."""
        lat, lng = 40.7128, -74.0060
        gh = encode_geohash(lat, lng, precision=6)
        dec_lat, dec_lng = _decode_geohash_center(gh)
        assert abs(dec_lat - lat) < 0.02
        assert abs(dec_lng - lng) < 0.02

    def test_decode_equator(self):
        gh = encode_geohash(0.0, 0.0, precision=8)
        lat, lng = _decode_geohash_center(gh)
        assert abs(lat) < 0.001
        assert abs(lng) < 0.001

    def test_decode_southern_hemisphere(self):
        gh = encode_geohash(-33.87, 151.21, precision=6)
        lat, lng = _decode_geohash_center(gh)
        assert lat < 0
        assert lng > 0


class TestGeohashNeighbors:
    def test_returns_nine_cells(self):
        """Should return 9 cells (center + 8 neighbors)."""
        gh = encode_geohash(40.7128, -74.0060, precision=5)
        neighbors = geohash_neighbors(gh)
        assert len(neighbors) >= 8  # at least 8, may be 9
        assert gh in neighbors

    def test_neighbors_are_unique(self):
        gh = encode_geohash(40.7128, -74.0060, precision=5)
        neighbors = geohash_neighbors(gh)
        assert len(neighbors) == len(set(neighbors))

    def test_neighbors_all_same_precision(self):
        gh = encode_geohash(40.7128, -74.0060, precision=5)
        neighbors = geohash_neighbors(gh)
        assert all(len(n) == 5 for n in neighbors)


class TestGeohashDimensions:
    def test_higher_precision_smaller_cells(self):
        lat3, lng3 = _geohash_dimensions(3)
        lat5, lng5 = _geohash_dimensions(5)
        assert lat5 < lat3
        assert lng5 < lng3

    def test_dimensions_positive(self):
        for p in range(1, 9):
            lat, lng = _geohash_dimensions(p)
            assert lat > 0
            assert lng > 0


# ===========================================================================
# Demand Tracking Tests
# ===========================================================================


def _make_mock_pipeline():
    """Create a mock pipeline that works as an async context manager."""
    pipe = MagicMock()
    pipe.incr = MagicMock()
    pipe.expire = MagicMock()
    pipe.execute = AsyncMock(return_value=[1, True])
    pipe.__aenter__ = AsyncMock(return_value=pipe)
    pipe.__aexit__ = AsyncMock(return_value=False)
    return pipe


class TestRecordDemand:
    @pytest.mark.asyncio
    async def test_records_demand_increments_counter(self):
        pipe = _make_mock_pipeline()
        redis_client = MagicMock()
        redis_client.pipeline.return_value = pipe

        gh = await record_demand(redis_client, 40.7128, -74.0060)

        assert len(gh) == 5
        pipe.incr.assert_called_once()
        pipe.expire.assert_called_once()
        pipe.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_geohash(self):
        pipe = _make_mock_pipeline()
        redis_client = MagicMock()
        redis_client.pipeline.return_value = pipe

        gh = await record_demand(redis_client, 37.7749, -122.4194)
        expected = encode_geohash(37.7749, -122.4194)
        assert gh == expected


class TestGetDemandCount:
    @pytest.mark.asyncio
    async def test_returns_count_from_redis(self):
        redis_client = AsyncMock()
        redis_client.get = AsyncMock(return_value="7")

        count = await get_demand_count(redis_client, "dr5ru")
        assert count == 7

    @pytest.mark.asyncio
    async def test_returns_zero_for_missing_key(self):
        redis_client = AsyncMock()
        redis_client.get = AsyncMock(return_value=None)

        count = await get_demand_count(redis_client, "dr5ru")
        assert count == 0

    @pytest.mark.asyncio
    async def test_returns_zero_for_empty_string(self):
        redis_client = AsyncMock()
        redis_client.get = AsyncMock(return_value="")

        # Empty string should return 0 (falsy)
        count = await get_demand_count(redis_client, "dr5ru")
        assert count == 0


class TestGetAreaDemand:
    @pytest.mark.asyncio
    async def test_sums_demand_across_neighbors(self):
        """Area demand should sum counts from the cell and all neighbors."""
        redis_client = AsyncMock()
        # Return "2" for every get call (center + neighbors)
        redis_client.get = AsyncMock(return_value="2")

        total = await get_area_demand(redis_client, 40.7128, -74.0060)

        # Should be sum of counts across all neighbor cells
        gh = encode_geohash(40.7128, -74.0060)
        n_cells = len(geohash_neighbors(gh))
        assert total == 2 * n_cells

    @pytest.mark.asyncio
    async def test_handles_zero_demand(self):
        redis_client = AsyncMock()
        redis_client.get = AsyncMock(return_value=None)

        total = await get_area_demand(redis_client, 40.7128, -74.0060)
        assert total == 0


# ===========================================================================
# Supply Counting Tests
# ===========================================================================


class TestGetAreaSupply:
    @pytest.mark.asyncio
    async def test_counts_available_drivers(self):
        redis_client = AsyncMock()
        # geosearch returns list of member names
        redis_client.geosearch = AsyncMock(return_value=["1", "2", "3"])
        # All three are available
        redis_client.get = AsyncMock(return_value="available")

        count = await get_area_supply(redis_client, 40.7128, -74.0060)
        assert count == 3

    @pytest.mark.asyncio
    async def test_excludes_busy_drivers(self):
        redis_client = AsyncMock()
        redis_client.geosearch = AsyncMock(return_value=["1", "2", "3"])

        async def mock_get(key):
            if key.endswith(":1"):
                return "available"
            if key.endswith(":2"):
                return "busy"
            return "available"

        redis_client.get = AsyncMock(side_effect=mock_get)

        count = await get_area_supply(redis_client, 40.7128, -74.0060)
        assert count == 2

    @pytest.mark.asyncio
    async def test_returns_zero_when_no_drivers(self):
        redis_client = AsyncMock()
        redis_client.geosearch = AsyncMock(return_value=[])

        count = await get_area_supply(redis_client, 40.7128, -74.0060)
        assert count == 0

    @pytest.mark.asyncio
    async def test_excludes_drivers_with_no_status(self):
        redis_client = AsyncMock()
        redis_client.geosearch = AsyncMock(return_value=["1", "2"])

        async def mock_get(key):
            if key.endswith(":1"):
                return "available"
            return None  # status expired

        redis_client.get = AsyncMock(side_effect=mock_get)

        count = await get_area_supply(redis_client, 40.7128, -74.0060)
        assert count == 1

    @pytest.mark.asyncio
    async def test_uses_custom_radius(self):
        redis_client = AsyncMock()
        redis_client.geosearch = AsyncMock(return_value=[])

        await get_area_supply(redis_client, 40.7128, -74.0060, radius_km=15.0)

        call_kwargs = redis_client.geosearch.call_args
        assert call_kwargs.kwargs["radius"] == 15.0


# ===========================================================================
# Multiplier Calculation Tests
# ===========================================================================


class TestCalculateDemandMultiplier:
    def test_returns_one_when_below_threshold(self):
        """No adjustment when demand/supply ratio is low."""
        mult = calculate_demand_multiplier(
            demand=3, supply=5, demand_threshold=2.0, max_multiplier=1.5, scale_factor=0.25,
        )
        assert mult == 1.0

    def test_returns_one_at_threshold(self):
        mult = calculate_demand_multiplier(
            demand=10, supply=5, demand_threshold=2.0, max_multiplier=1.5, scale_factor=0.25,
        )
        assert mult == 1.0

    def test_increases_above_threshold(self):
        """Demand/supply = 3.0 with threshold 2.0 → excess = 1.0 → 1.0 + 1.0*0.25 = 1.25."""
        mult = calculate_demand_multiplier(
            demand=15, supply=5, demand_threshold=2.0, max_multiplier=1.5, scale_factor=0.25,
        )
        assert mult == 1.25

    def test_caps_at_max_multiplier(self):
        """Even extreme demand should be capped."""
        mult = calculate_demand_multiplier(
            demand=100, supply=1, demand_threshold=2.0, max_multiplier=1.5, scale_factor=0.25,
        )
        assert mult == 1.5

    def test_zero_supply_uses_one(self):
        """Zero drivers → effective supply = 1 to avoid division by zero."""
        mult = calculate_demand_multiplier(
            demand=5, supply=0, demand_threshold=2.0, max_multiplier=1.5, scale_factor=0.25,
        )
        # ratio = 5/1 = 5.0, excess = 3.0, mult = 1 + 3*0.25 = 1.75 → capped at 1.5
        assert mult == 1.5

    def test_zero_demand_returns_one(self):
        mult = calculate_demand_multiplier(
            demand=0, supply=10, demand_threshold=2.0, max_multiplier=1.5, scale_factor=0.25,
        )
        assert mult == 1.0

    def test_returns_one_when_max_is_one(self):
        """If cooperative sets max to 1.0, demand pricing is effectively disabled."""
        mult = calculate_demand_multiplier(
            demand=100, supply=1, demand_threshold=2.0, max_multiplier=1.0, scale_factor=0.25,
        )
        assert mult == 1.0

    @patch("app.services.demand_pricing.settings")
    def test_returns_one_when_disabled(self, mock_settings):
        mock_settings.demand_pricing_enabled = False
        mult = calculate_demand_multiplier(
            demand=100, supply=1, demand_threshold=2.0, max_multiplier=1.5, scale_factor=0.25,
        )
        assert mult == 1.0

    def test_multiplier_is_rounded_to_two_decimals(self):
        """Multiplier should be cleanly rounded."""
        mult = calculate_demand_multiplier(
            demand=11, supply=5, demand_threshold=2.0, max_multiplier=2.0, scale_factor=0.33,
        )
        assert mult == round(mult, 2)

    def test_exact_threshold_ratio(self):
        """Ratio exactly at threshold → 1.0."""
        mult = calculate_demand_multiplier(
            demand=6, supply=3, demand_threshold=2.0, max_multiplier=1.5, scale_factor=0.25,
        )
        assert mult == 1.0

    def test_slightly_above_threshold(self):
        """Just above threshold should produce a small increase."""
        mult = calculate_demand_multiplier(
            demand=7, supply=3, demand_threshold=2.0, max_multiplier=1.5, scale_factor=0.25,
        )
        # ratio = 7/3 ≈ 2.33, excess ≈ 0.33, mult ≈ 1.08
        assert 1.0 < mult < 1.15

    def test_high_scale_factor(self):
        """Higher scale factor means faster multiplier growth."""
        mult_low = calculate_demand_multiplier(
            demand=15, supply=5, demand_threshold=2.0, max_multiplier=2.0, scale_factor=0.1,
        )
        mult_high = calculate_demand_multiplier(
            demand=15, supply=5, demand_threshold=2.0, max_multiplier=2.0, scale_factor=0.5,
        )
        assert mult_high > mult_low


# ===========================================================================
# Demand Info (Full Transparency) Tests
# ===========================================================================


class TestGetDemandInfo:
    @pytest.mark.asyncio
    @patch("app.services.demand_pricing.settings")
    async def test_standard_pricing_when_no_demand(self, mock_settings):
        mock_settings.demand_pricing_enabled = True
        mock_settings.demand_pricing_max_multiplier = 1.5
        mock_settings.demand_pricing_threshold = 2.0
        mock_settings.demand_pricing_scale_factor = 0.25
        mock_settings.driver_search_radius_km = 8.0

        redis_client = AsyncMock()
        redis_client.get = AsyncMock(return_value=None)
        redis_client.geosearch = AsyncMock(return_value=["1", "2"])

        # Mock available status for drivers
        async def mock_get(key):
            if "status" in key:
                return "available"
            return None

        redis_client.get = AsyncMock(side_effect=mock_get)

        info = await get_demand_info(redis_client, 40.7128, -74.0060)

        assert isinstance(info, DemandInfo)
        assert info.multiplier == 1.0
        assert not info.is_elevated
        assert "good" in info.explanation.lower() or "standard" in info.explanation.lower()

    @pytest.mark.asyncio
    @patch("app.services.demand_pricing.settings")
    async def test_elevated_pricing_explanation(self, mock_settings):
        mock_settings.demand_pricing_enabled = True
        mock_settings.demand_pricing_max_multiplier = 1.5
        mock_settings.demand_pricing_threshold = 2.0
        mock_settings.demand_pricing_scale_factor = 0.25
        mock_settings.driver_search_radius_km = 8.0

        redis_client = AsyncMock()
        redis_client.geosearch = AsyncMock(return_value=["1"])

        call_count = [0]

        async def mock_get(key):
            if "status" in key:
                return "available"
            # Demand keys — return high counts
            call_count[0] += 1
            return "10"

        redis_client.get = AsyncMock(side_effect=mock_get)

        info = await get_demand_info(redis_client, 40.7128, -74.0060)

        assert info.multiplier > 1.0
        assert info.is_elevated
        assert "higher" in info.explanation.lower() or "%" in info.explanation
        assert "capped" in info.explanation.lower()

    @pytest.mark.asyncio
    @patch("app.services.demand_pricing.settings")
    async def test_disabled_demand_pricing(self, mock_settings):
        mock_settings.demand_pricing_enabled = False
        mock_settings.demand_pricing_max_multiplier = 1.5
        mock_settings.demand_pricing_threshold = 2.0
        mock_settings.demand_pricing_scale_factor = 0.25
        mock_settings.driver_search_radius_km = 8.0

        redis_client = AsyncMock()
        redis_client.get = AsyncMock(return_value="100")
        redis_client.geosearch = AsyncMock(return_value=[])

        info = await get_demand_info(redis_client, 40.7128, -74.0060)

        assert info.multiplier == 1.0
        assert not info.is_elevated
        assert "disabled" in info.explanation.lower()

    @pytest.mark.asyncio
    @patch("app.services.demand_pricing.settings")
    async def test_demand_info_includes_counts(self, mock_settings):
        mock_settings.demand_pricing_enabled = True
        mock_settings.demand_pricing_max_multiplier = 1.5
        mock_settings.demand_pricing_threshold = 2.0
        mock_settings.demand_pricing_scale_factor = 0.25
        mock_settings.driver_search_radius_km = 8.0

        redis_client = AsyncMock()
        redis_client.geosearch = AsyncMock(return_value=["1"])

        async def mock_get(key):
            if "status" in key:
                return "available"
            return "5"

        redis_client.get = AsyncMock(side_effect=mock_get)

        info = await get_demand_info(redis_client, 40.7128, -74.0060)

        assert info.demand_count >= 0
        assert info.supply_count >= 0
        assert info.multiplier_cap == 1.5
        assert len(info.geohash) == 5


# ===========================================================================
# Pricing Integration Tests
# ===========================================================================


class TestPricingIntegration:
    def test_fare_breakdown_has_demand_fields(self):
        """FareBreakdown should include demand multiplier fields."""
        bd = calculate_fare_breakdown(10.0, 15.0)
        assert hasattr(bd, "demand_multiplier")
        assert hasattr(bd, "demand_label")
        assert bd.demand_multiplier == 1.0
        assert bd.demand_label is None

    def test_demand_multiplier_increases_fare(self):
        bd_normal = calculate_fare_breakdown(10.0, 15.0)
        bd_demand = calculate_fare_breakdown(10.0, 15.0, demand_multiplier=1.3)

        assert bd_demand.total > bd_normal.total
        assert bd_demand.demand_multiplier == 1.3

    def test_demand_label_passed_through(self):
        label = "High demand: 15 requests vs 3 drivers"
        bd = calculate_fare_breakdown(10.0, 15.0, demand_multiplier=1.2, demand_label=label)
        assert bd.demand_label == label

    def test_demand_and_time_multipliers_stack(self):
        """Both multipliers should be applied together."""
        from app.services.pricing import set_time_multipliers

        set_time_multipliers([
            {"start_hour": 0, "end_hour": 24, "multiplier": 1.25, "label": "Peak"},
        ])

        try:
            bd = calculate_fare_breakdown(
                10.0, 15.0,
                demand_multiplier=1.3,
                at_time=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
            )
            # Combined: 1.25 * 1.3 = 1.625
            assert bd.multiplier == 1.25
            assert bd.demand_multiplier == 1.3
            # Subtotal should reflect both multipliers
            base_fare = bd.base + bd.distance + bd.time
            expected_subtotal = base_fare * 1.25 * 1.3
            assert abs(bd.subtotal - round(expected_subtotal, 2)) < 0.02
        finally:
            set_time_multipliers([])

    def test_demand_multiplier_one_has_no_effect(self):
        bd_without = calculate_fare_breakdown(10.0, 15.0)
        bd_with = calculate_fare_breakdown(10.0, 15.0, demand_multiplier=1.0)
        assert bd_without.total == bd_with.total

    def test_minimum_fare_still_applies(self):
        """Even with demand multiplier, minimum fare should be enforced."""
        bd = calculate_fare_breakdown(0.1, 0.1, demand_multiplier=1.0)
        assert bd.subtotal >= 5.00  # default minimum fare


# ===========================================================================
# Schema Tests
# ===========================================================================


class TestDemandPricingSchemas:
    def test_demand_info_response(self):
        resp = DemandInfoResponse(
            geohash="dr5ru",
            demand_count=15,
            supply_count=3,
            multiplier=1.3,
            multiplier_cap=1.5,
            is_elevated=True,
            explanation="Fares are 30% higher due to high demand.",
        )
        assert resp.multiplier == 1.3
        assert resp.is_elevated is True

    def test_config_response(self):
        resp = DemandPricingConfigResponse(
            enabled=True,
            max_multiplier=1.5,
            threshold=2.0,
            scale_factor=0.25,
        )
        assert resp.enabled is True

    def test_config_update_partial(self):
        update = DemandPricingConfigUpdate(max_multiplier=1.3)
        assert update.max_multiplier == 1.3
        assert update.enabled is None
        assert update.threshold is None
        assert update.scale_factor is None

    def test_config_update_full(self):
        update = DemandPricingConfigUpdate(
            enabled=False,
            max_multiplier=2.0,
            threshold=3.0,
            scale_factor=0.5,
        )
        assert update.enabled is False
        assert update.max_multiplier == 2.0

    def test_demand_info_summary_schema(self):
        summary = DemandInfoSummary(
            multiplier=1.25,
            is_elevated=True,
            explanation="Fares are 25% higher.",
        )
        assert summary.multiplier == 1.25

    def test_fare_breakdown_response_has_demand_fields(self):
        resp = FareBreakdownResponse(
            base=2.5,
            distance=15.0,
            time=3.75,
            multiplier=1.0,
            demand_multiplier=1.2,
            demand_label="High demand",
            subtotal=25.50,
            total=25.50,
        )
        assert resp.demand_multiplier == 1.2
        assert resp.demand_label == "High demand"

    def test_fare_breakdown_response_defaults(self):
        resp = FareBreakdownResponse(
            base=2.5, distance=15.0, time=3.75, subtotal=21.25, total=21.25,
        )
        assert resp.demand_multiplier == 1.0
        assert resp.demand_label is None


# ===========================================================================
# Edge Cases
# ===========================================================================


class TestEdgeCases:
    def test_geohash_at_international_date_line(self):
        """Points near 180/-180 longitude should encode correctly."""
        gh_east = encode_geohash(0.0, 179.9, precision=5)
        gh_west = encode_geohash(0.0, -179.9, precision=5)
        assert len(gh_east) == 5
        assert len(gh_west) == 5
        # These are very far apart, different hashes
        assert gh_east != gh_west

    def test_geohash_at_poles(self):
        gh_north = encode_geohash(89.9, 0.0, precision=5)
        gh_south = encode_geohash(-89.9, 0.0, precision=5)
        assert gh_north != gh_south

    def test_multiplier_with_very_high_demand(self):
        """Extreme demand should still be capped."""
        mult = calculate_demand_multiplier(
            demand=10000, supply=1,
            demand_threshold=2.0, max_multiplier=1.5, scale_factor=0.25,
        )
        assert mult == 1.5

    def test_multiplier_with_very_high_supply(self):
        """Abundant supply should keep multiplier at 1.0."""
        mult = calculate_demand_multiplier(
            demand=5, supply=1000,
            demand_threshold=2.0, max_multiplier=1.5, scale_factor=0.25,
        )
        assert mult == 1.0

    def test_multiplier_demand_equals_supply(self):
        """1:1 ratio (below threshold of 2) should return 1.0."""
        mult = calculate_demand_multiplier(
            demand=10, supply=10,
            demand_threshold=2.0, max_multiplier=1.5, scale_factor=0.25,
        )
        assert mult == 1.0

    @pytest.mark.asyncio
    async def test_record_demand_multiple_times(self):
        """Multiple requests should increment the counter."""
        pipe = _make_mock_pipeline()
        redis_client = MagicMock()
        redis_client.pipeline.return_value = pipe

        await record_demand(redis_client, 40.7128, -74.0060)
        await record_demand(redis_client, 40.7128, -74.0060)
        await record_demand(redis_client, 40.7128, -74.0060)

        assert pipe.incr.call_count == 3

    def test_different_precision_different_granularity(self):
        """Lower precision = larger cells = more points in same cell."""
        # Two points ~1km apart
        gh_p3_a = encode_geohash(40.7128, -74.0060, precision=3)
        gh_p3_b = encode_geohash(40.7200, -74.0060, precision=3)
        gh_p6_a = encode_geohash(40.7128, -74.0060, precision=6)
        gh_p6_b = encode_geohash(40.7200, -74.0060, precision=6)

        # At low precision they're in the same cell
        assert gh_p3_a == gh_p3_b
        # At high precision they may differ
        # (this is a property test — at precision 6 ~0.6km cells, 0.8km apart points may differ)

    @patch("app.services.demand_pricing.settings")
    def test_uses_settings_defaults(self, mock_settings):
        """Should read from settings when params not explicitly passed."""
        mock_settings.demand_pricing_enabled = True
        mock_settings.demand_pricing_threshold = 3.0
        mock_settings.demand_pricing_max_multiplier = 2.0
        mock_settings.demand_pricing_scale_factor = 0.5

        # demand=10, supply=2 → ratio=5, excess=2, mult=1+2*0.5=2.0
        mult = calculate_demand_multiplier(demand=10, supply=2)
        assert mult == 2.0


# ===========================================================================
# Admin Configuration Tests
# ===========================================================================


class TestAdminConfiguration:
    @patch("app.services.demand_pricing.settings")
    def test_disabling_returns_one(self, mock_settings):
        mock_settings.demand_pricing_enabled = False
        mult = calculate_demand_multiplier(
            demand=100, supply=1,
            demand_threshold=2.0, max_multiplier=1.5, scale_factor=0.25,
        )
        assert mult == 1.0

    def test_max_multiplier_respected(self):
        for cap in [1.0, 1.1, 1.25, 1.5, 2.0, 3.0]:
            mult = calculate_demand_multiplier(
                demand=1000, supply=1,
                demand_threshold=1.0, max_multiplier=cap, scale_factor=1.0,
            )
            assert mult <= cap

    def test_threshold_zero_means_always_active(self):
        """With threshold=0, any demand > 0 with supply > 0 triggers pricing."""
        mult = calculate_demand_multiplier(
            demand=3, supply=3,
            demand_threshold=0.0, max_multiplier=2.0, scale_factor=0.25,
        )
        # ratio = 1.0, excess = 1.0, mult = 1 + 1*0.25 = 1.25
        assert mult == 1.25

    def test_scale_factor_zero_means_no_increase(self):
        """Scale factor 0 means multiplier stays at 1.0 regardless of demand."""
        mult = calculate_demand_multiplier(
            demand=100, supply=1,
            demand_threshold=2.0, max_multiplier=2.0, scale_factor=0.0,
        )
        assert mult == 1.0
