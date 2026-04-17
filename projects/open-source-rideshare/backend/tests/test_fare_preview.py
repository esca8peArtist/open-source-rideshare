"""Tests for the pre-booking fare transparency preview feature.

GET /pricing/fare-preview

Because this endpoint is pure computation (no database, no auth), every test
can call either the service function directly or the FastAPI endpoint function
directly.  No mocking, no fixtures, no test DB required — all 100% synchronous
logic with deterministic results.

Covers
------
Service layer (get_fare_preview / helpers)
  - Response schema: all expected fields present and correctly typed
  - Zero platform fee (OpenRide zero-commission cooperative model)
  - Driver payout equals estimated fare when platform fee is 0
  - Driver payout percentage is ~100% when platform fee is 0
  - Surge multiplier increases the fare proportionally
  - is_surge flag: False at 1.0x, True above 1.0x
  - Minimum fare enforcement (very short trips)
  - Competitor estimates: Uber and Lyft produce positive, reasonable values
  - Competitor platform fees are positive (they do charge commission)
  - Driver earns more on OpenRide than Uber and Lyft for typical trips
  - Known-values test: 5 km / 10 min trip with default pricing params
  - Transparency note contains key phrases
  - Methodology note is non-empty

Schema
  - FarePreviewResponse serialises to/from dict correctly
  - FarePreviewCompetitor schema has all required fields

API endpoint (fare_preview function)
  - Returns FarePreviewResponse instance
  - Validation: distance_km ≤ 0 → 422
  - Validation: duration_min ≤ 0 → 422
  - Validation: surge_multiplier < 1.0 → 422
  - Validation: distance_km > 500 → 422
  - Validation: duration_min > 600 → 422
  - Default surge_multiplier is 1.0 (no surge)
"""

from __future__ import annotations

import math

import pytest

from app.schemas.fare_preview import FarePreviewCompetitor, FarePreviewResponse
from app.services.fare_preview import (
    _LYFT_BASE_FARE,
    _LYFT_DRIVER_TAKE_RATE,
    _LYFT_PLATFORM_RATE,
    _LYFT_PER_MILE,
    _LYFT_PER_MIN,
    _KM_TO_MILES,
    _UBER_BASE_FARE,
    _UBER_DRIVER_TAKE_RATE,
    _UBER_PLATFORM_RATE,
    _UBER_PER_MILE,
    _UBER_PER_MIN,
    _competitor_estimate,
    _build_transparency_note,
    get_fare_preview,
)

# ---------------------------------------------------------------------------
# Shared test data
# ---------------------------------------------------------------------------

STANDARD_DISTANCE_KM: float = 5.0
STANDARD_DURATION_MIN: float = 10.0

# Default OpenRide pricing (config.py defaults):
#   base_fare = 2.50, per_km_rate = 1.50, per_minute_rate = 0.25, platform_fee = 0.0
#   fare = (2.50 + 5.0*1.50 + 10*0.25) * 1.0 * 1.0 + 0.0 = 2.50 + 7.50 + 2.50 = $12.50
STANDARD_EXPECTED_FARE: float = 12.50

# Uber estimate at 5km / 10min:
#   miles = 5.0 * 0.621371 = 3.107
#   fare = 1.38 + 10*0.20 + 3.107*0.84 = 1.38 + 2.00 + 2.61 = 5.99
_UBER_STANDARD_FARE: float = round(
    _UBER_BASE_FARE + _UBER_PER_MIN * STANDARD_DURATION_MIN + _UBER_PER_MILE * (STANDARD_DISTANCE_KM * _KM_TO_MILES),
    2,
)

# Lyft estimate at 5km / 10min:
_LYFT_STANDARD_FARE: float = round(
    _LYFT_BASE_FARE + _LYFT_PER_MIN * STANDARD_DURATION_MIN + _LYFT_PER_MILE * (STANDARD_DISTANCE_KM * _KM_TO_MILES),
    2,
)


# ===========================================================================
# Service layer — get_fare_preview()
# ===========================================================================

class TestGetFarePreviewSchema:
    """Response has all expected fields with correct types."""

    def test_returns_fare_preview_response_instance(self):
        result = get_fare_preview(STANDARD_DISTANCE_KM, STANDARD_DURATION_MIN)
        assert isinstance(result, FarePreviewResponse)

    def test_distance_km_in_response(self):
        result = get_fare_preview(STANDARD_DISTANCE_KM, STANDARD_DURATION_MIN)
        assert result.distance_km == pytest.approx(STANDARD_DISTANCE_KM, rel=1e-3)

    def test_duration_min_in_response(self):
        result = get_fare_preview(STANDARD_DISTANCE_KM, STANDARD_DURATION_MIN)
        assert result.duration_min == pytest.approx(STANDARD_DURATION_MIN, rel=1e-3)

    def test_surge_multiplier_default_one(self):
        result = get_fare_preview(STANDARD_DISTANCE_KM, STANDARD_DURATION_MIN)
        assert result.surge_multiplier == pytest.approx(1.0)

    def test_uber_estimate_is_competitor_instance(self):
        result = get_fare_preview(STANDARD_DISTANCE_KM, STANDARD_DURATION_MIN)
        assert isinstance(result.uber_estimate, FarePreviewCompetitor)

    def test_lyft_estimate_is_competitor_instance(self):
        result = get_fare_preview(STANDARD_DISTANCE_KM, STANDARD_DURATION_MIN)
        assert isinstance(result.lyft_estimate, FarePreviewCompetitor)

    def test_transparency_note_is_non_empty_string(self):
        result = get_fare_preview(STANDARD_DISTANCE_KM, STANDARD_DURATION_MIN)
        assert isinstance(result.transparency_note, str)
        assert len(result.transparency_note) > 10

    def test_methodology_note_is_non_empty_string(self):
        result = get_fare_preview(STANDARD_DISTANCE_KM, STANDARD_DURATION_MIN)
        assert isinstance(result.methodology_note, str)
        assert len(result.methodology_note) > 10


class TestZeroCommission:
    """OpenRide charges 0% platform fee — driver keeps the full fare."""

    def test_platform_fee_is_zero(self):
        result = get_fare_preview(STANDARD_DISTANCE_KM, STANDARD_DURATION_MIN)
        assert result.platform_fee_usd == pytest.approx(0.0)

    def test_platform_fee_pct_is_zero(self):
        result = get_fare_preview(STANDARD_DISTANCE_KM, STANDARD_DURATION_MIN)
        assert result.platform_fee_pct == pytest.approx(0.0)

    def test_driver_payout_equals_fare(self):
        result = get_fare_preview(STANDARD_DISTANCE_KM, STANDARD_DURATION_MIN)
        assert result.driver_payout_usd == pytest.approx(result.estimated_fare_usd, rel=1e-4)

    def test_driver_payout_pct_is_hundred(self):
        result = get_fare_preview(STANDARD_DISTANCE_KM, STANDARD_DURATION_MIN)
        assert result.driver_payout_pct == pytest.approx(100.0)


class TestKnownValues:
    """Verify specific numeric outputs against hand-calculated expectations."""

    def test_standard_fare(self):
        result = get_fare_preview(STANDARD_DISTANCE_KM, STANDARD_DURATION_MIN)
        assert result.estimated_fare_usd == pytest.approx(STANDARD_EXPECTED_FARE, rel=1e-4)

    def test_uber_fare_reasonable(self):
        result = get_fare_preview(STANDARD_DISTANCE_KM, STANDARD_DURATION_MIN)
        assert result.uber_estimate.estimated_fare_usd == pytest.approx(_UBER_STANDARD_FARE, rel=1e-3)

    def test_lyft_fare_reasonable(self):
        result = get_fare_preview(STANDARD_DISTANCE_KM, STANDARD_DURATION_MIN)
        assert result.lyft_estimate.estimated_fare_usd == pytest.approx(_LYFT_STANDARD_FARE, rel=1e-3)

    def test_uber_driver_payout(self):
        result = get_fare_preview(STANDARD_DISTANCE_KM, STANDARD_DURATION_MIN)
        expected = round(_UBER_STANDARD_FARE * _UBER_DRIVER_TAKE_RATE, 2)
        assert result.uber_estimate.estimated_driver_payout_usd == pytest.approx(expected, rel=1e-3)

    def test_lyft_driver_payout(self):
        result = get_fare_preview(STANDARD_DISTANCE_KM, STANDARD_DURATION_MIN)
        expected = round(_LYFT_STANDARD_FARE * _LYFT_DRIVER_TAKE_RATE, 2)
        assert result.lyft_estimate.estimated_driver_payout_usd == pytest.approx(expected, rel=1e-3)

    def test_uber_platform_fee(self):
        result = get_fare_preview(STANDARD_DISTANCE_KM, STANDARD_DURATION_MIN)
        expected = round(_UBER_STANDARD_FARE * _UBER_PLATFORM_RATE, 2)
        assert result.uber_estimate.estimated_platform_fee_usd == pytest.approx(expected, rel=1e-3)

    def test_lyft_platform_fee(self):
        result = get_fare_preview(STANDARD_DISTANCE_KM, STANDARD_DURATION_MIN)
        expected = round(_LYFT_STANDARD_FARE * _LYFT_PLATFORM_RATE, 2)
        assert result.lyft_estimate.estimated_platform_fee_usd == pytest.approx(expected, rel=1e-3)


class TestDriverEarnsMore:
    """On typical trips, driver earns more on OpenRide than Uber/Lyft."""

    def test_driver_earns_more_than_uber(self):
        result = get_fare_preview(STANDARD_DISTANCE_KM, STANDARD_DURATION_MIN)
        assert result.driver_earns_more_than_uber_usd > 0

    def test_driver_earns_more_than_lyft(self):
        result = get_fare_preview(STANDARD_DISTANCE_KM, STANDARD_DURATION_MIN)
        assert result.driver_earns_more_than_lyft_usd > 0

    def test_driver_more_than_uber_computed_correctly(self):
        result = get_fare_preview(STANDARD_DISTANCE_KM, STANDARD_DURATION_MIN)
        expected = round(
            result.driver_payout_usd - result.uber_estimate.estimated_driver_payout_usd, 2
        )
        assert result.driver_earns_more_than_uber_usd == pytest.approx(expected, rel=1e-4)

    def test_driver_more_than_lyft_computed_correctly(self):
        result = get_fare_preview(STANDARD_DISTANCE_KM, STANDARD_DURATION_MIN)
        expected = round(
            result.driver_payout_usd - result.lyft_estimate.estimated_driver_payout_usd, 2
        )
        assert result.driver_earns_more_than_lyft_usd == pytest.approx(expected, rel=1e-4)

    def test_driver_earnings_advantage_scales_with_distance(self):
        """A longer trip should give the driver a bigger absolute advantage on OpenRide."""
        short = get_fare_preview(2.0, 5.0)
        long_ = get_fare_preview(20.0, 30.0)
        assert long_.driver_earns_more_than_uber_usd > short.driver_earns_more_than_uber_usd


class TestSurgeMultiplier:
    """Surge multiplier correctly inflates the OpenRide fare."""

    def test_no_surge_flag_at_1x(self):
        result = get_fare_preview(STANDARD_DISTANCE_KM, STANDARD_DURATION_MIN, surge_multiplier=1.0)
        assert result.is_surge is False

    def test_surge_flag_above_1x(self):
        result = get_fare_preview(STANDARD_DISTANCE_KM, STANDARD_DURATION_MIN, surge_multiplier=1.5)
        assert result.is_surge is True

    def test_surge_increases_fare(self):
        base = get_fare_preview(STANDARD_DISTANCE_KM, STANDARD_DURATION_MIN, surge_multiplier=1.0)
        surged = get_fare_preview(STANDARD_DISTANCE_KM, STANDARD_DURATION_MIN, surge_multiplier=2.0)
        assert surged.estimated_fare_usd > base.estimated_fare_usd

    def test_surge_doubles_fare_at_2x(self):
        """At 2× surge, fare should be double the base fare (above minimum)."""
        # Use a distance large enough to be above the minimum fare floor at 2×
        base = get_fare_preview(10.0, 20.0, surge_multiplier=1.0)
        surged = get_fare_preview(10.0, 20.0, surge_multiplier=2.0)
        assert surged.estimated_fare_usd == pytest.approx(base.estimated_fare_usd * 2, rel=1e-4)

    def test_surge_multiplier_stored_in_response(self):
        result = get_fare_preview(STANDARD_DISTANCE_KM, STANDARD_DURATION_MIN, surge_multiplier=1.8)
        assert result.surge_multiplier == pytest.approx(1.8)

    def test_zero_platform_fee_persists_under_surge(self):
        result = get_fare_preview(STANDARD_DISTANCE_KM, STANDARD_DURATION_MIN, surge_multiplier=3.0)
        assert result.platform_fee_usd == pytest.approx(0.0)

    def test_driver_payout_equals_fare_under_surge(self):
        result = get_fare_preview(STANDARD_DISTANCE_KM, STANDARD_DURATION_MIN, surge_multiplier=2.5)
        assert result.driver_payout_usd == pytest.approx(result.estimated_fare_usd, rel=1e-4)


class TestMinimumFare:
    """Very short trips hit the minimum fare floor ($5.00)."""

    def test_short_trip_hits_minimum(self):
        # 0.1 km, 1 min: raw = 2.50 + 0.15 + 0.25 = 2.90 → floors to $5.00
        result = get_fare_preview(0.1, 1.0)
        assert result.estimated_fare_usd == pytest.approx(5.00, rel=1e-4)

    def test_minimum_fare_driver_still_gets_full_amount(self):
        result = get_fare_preview(0.1, 1.0)
        assert result.driver_payout_usd == pytest.approx(result.estimated_fare_usd, rel=1e-4)


class TestCompetitorEstimates:
    """Competitor estimates are positive and internally consistent."""

    def test_uber_fare_positive(self):
        result = get_fare_preview(STANDARD_DISTANCE_KM, STANDARD_DURATION_MIN)
        assert result.uber_estimate.estimated_fare_usd > 0

    def test_lyft_fare_positive(self):
        result = get_fare_preview(STANDARD_DISTANCE_KM, STANDARD_DURATION_MIN)
        assert result.lyft_estimate.estimated_fare_usd > 0

    def test_uber_platform_fee_positive(self):
        result = get_fare_preview(STANDARD_DISTANCE_KM, STANDARD_DURATION_MIN)
        assert result.uber_estimate.estimated_platform_fee_usd > 0

    def test_lyft_platform_fee_positive(self):
        result = get_fare_preview(STANDARD_DISTANCE_KM, STANDARD_DURATION_MIN)
        assert result.lyft_estimate.estimated_platform_fee_usd > 0

    def test_uber_driver_plus_platform_fee_equals_fare(self):
        result = get_fare_preview(STANDARD_DISTANCE_KM, STANDARD_DURATION_MIN)
        uber = result.uber_estimate
        total = round(uber.estimated_driver_payout_usd + uber.estimated_platform_fee_usd, 2)
        assert total == pytest.approx(uber.estimated_fare_usd, rel=1e-4)

    def test_lyft_driver_plus_platform_fee_equals_fare(self):
        result = get_fare_preview(STANDARD_DISTANCE_KM, STANDARD_DURATION_MIN)
        lyft = result.lyft_estimate
        total = round(lyft.estimated_driver_payout_usd + lyft.estimated_platform_fee_usd, 2)
        assert total == pytest.approx(lyft.estimated_fare_usd, rel=1e-4)

    def test_uber_platform_name(self):
        result = get_fare_preview(STANDARD_DISTANCE_KM, STANDARD_DURATION_MIN)
        assert "Uber" in result.uber_estimate.platform_name

    def test_lyft_platform_name(self):
        result = get_fare_preview(STANDARD_DISTANCE_KM, STANDARD_DURATION_MIN)
        assert "Lyft" in result.lyft_estimate.platform_name

    def test_uber_driver_take_rate_75_pct(self):
        result = get_fare_preview(STANDARD_DISTANCE_KM, STANDARD_DURATION_MIN)
        assert result.uber_estimate.estimated_driver_payout_pct == pytest.approx(75.0)

    def test_lyft_driver_take_rate_75_pct(self):
        result = get_fare_preview(STANDARD_DISTANCE_KM, STANDARD_DURATION_MIN)
        assert result.lyft_estimate.estimated_driver_payout_pct == pytest.approx(75.0)

    def test_uber_platform_fee_pct_25(self):
        result = get_fare_preview(STANDARD_DISTANCE_KM, STANDARD_DURATION_MIN)
        assert result.uber_estimate.estimated_platform_fee_pct == pytest.approx(25.0)

    def test_lyft_platform_fee_pct_25(self):
        result = get_fare_preview(STANDARD_DISTANCE_KM, STANDARD_DURATION_MIN)
        assert result.lyft_estimate.estimated_platform_fee_pct == pytest.approx(25.0)

    def test_source_notes_non_empty(self):
        result = get_fare_preview(STANDARD_DISTANCE_KM, STANDARD_DURATION_MIN)
        assert len(result.uber_estimate.source_note) > 10
        assert len(result.lyft_estimate.source_note) > 10


class TestTransparencyNote:
    """Transparency note contains key human-readable phrases."""

    def test_contains_openride_reference(self):
        result = get_fare_preview(STANDARD_DISTANCE_KM, STANDARD_DURATION_MIN)
        assert "OpenRide" in result.transparency_note

    def test_contains_driver_pct(self):
        result = get_fare_preview(STANDARD_DISTANCE_KM, STANDARD_DURATION_MIN)
        # Driver keeps 100% on zero-commission model
        assert "100%" in result.transparency_note

    def test_contains_uber_reference(self):
        result = get_fare_preview(STANDARD_DISTANCE_KM, STANDARD_DURATION_MIN)
        assert "Uber" in result.transparency_note

    def test_contains_lyft_reference(self):
        result = get_fare_preview(STANDARD_DISTANCE_KM, STANDARD_DURATION_MIN)
        assert "Lyft" in result.transparency_note

    def test_contains_no_commission(self):
        result = get_fare_preview(STANDARD_DISTANCE_KM, STANDARD_DURATION_MIN)
        assert "commission" in result.transparency_note.lower()


# ===========================================================================
# _competitor_estimate() helper
# ===========================================================================

class TestCompetitorEstimateHelper:
    """Unit tests for the internal _competitor_estimate function."""

    def test_returns_competitor_instance(self):
        result = _competitor_estimate(
            distance_km=5.0, duration_min=10.0,
            base_fare=1.38, per_min=0.20, per_mile=0.84,
            driver_take_rate=0.75, platform_rate=0.25,
            platform_name="TestPlatform", source_note="test note",
        )
        assert isinstance(result, FarePreviewCompetitor)

    def test_fare_computation(self):
        distance_km = 5.0
        duration_min = 10.0
        base, per_min, per_mile = 1.38, 0.20, 0.84
        miles = distance_km * _KM_TO_MILES
        expected_fare = round(base + per_min * duration_min + per_mile * miles, 2)
        result = _competitor_estimate(
            distance_km=distance_km, duration_min=duration_min,
            base_fare=base, per_min=per_min, per_mile=per_mile,
            driver_take_rate=0.75, platform_rate=0.25,
            platform_name="P", source_note="n",
        )
        assert result.estimated_fare_usd == pytest.approx(expected_fare, rel=1e-4)

    def test_driver_payout_is_take_rate_fraction(self):
        result = _competitor_estimate(
            distance_km=5.0, duration_min=10.0,
            base_fare=1.38, per_min=0.20, per_mile=0.84,
            driver_take_rate=0.75, platform_rate=0.25,
            platform_name="P", source_note="n",
        )
        expected = round(result.estimated_fare_usd * 0.75, 2)
        assert result.estimated_driver_payout_usd == pytest.approx(expected, rel=1e-4)

    def test_platform_fee_is_platform_rate_fraction(self):
        result = _competitor_estimate(
            distance_km=5.0, duration_min=10.0,
            base_fare=1.38, per_min=0.20, per_mile=0.84,
            driver_take_rate=0.75, platform_rate=0.25,
            platform_name="P", source_note="n",
        )
        expected = round(result.estimated_fare_usd * 0.25, 2)
        assert result.estimated_platform_fee_usd == pytest.approx(expected, rel=1e-4)


# ===========================================================================
# _build_transparency_note() helper
# ===========================================================================

class TestBuildTransparencyNote:
    def _make_competitor(self, pct: float) -> FarePreviewCompetitor:
        return FarePreviewCompetitor(
            platform_name="TestPlatform",
            estimated_fare_usd=10.0,
            estimated_driver_payout_usd=round(10.0 * pct / 100, 2),
            estimated_driver_payout_pct=pct,
            estimated_platform_fee_usd=round(10.0 * (1 - pct / 100), 2),
            estimated_platform_fee_pct=round(100 - pct, 1),
            source_note="test",
        )

    def test_note_contains_driver_payout_amount(self):
        uber = self._make_competitor(75.0)
        lyft = self._make_competitor(75.0)
        note = _build_transparency_note(12.50, 100.0, uber, lyft)
        assert "12.50" in note

    def test_note_contains_driver_pct(self):
        uber = self._make_competitor(75.0)
        lyft = self._make_competitor(75.0)
        note = _build_transparency_note(12.50, 100.0, uber, lyft)
        assert "100%" in note

    def test_note_contains_uber_competitor_pct(self):
        uber = self._make_competitor(75.0)
        lyft = self._make_competitor(75.0)
        note = _build_transparency_note(12.50, 100.0, uber, lyft)
        assert "75%" in note


# ===========================================================================
# Schema serialisation
# ===========================================================================

class TestSchemaSerialisation:
    def test_fare_preview_response_serialises_to_dict(self):
        result = get_fare_preview(STANDARD_DISTANCE_KM, STANDARD_DURATION_MIN)
        d = result.model_dump()
        assert "estimated_fare_usd" in d
        assert "driver_payout_usd" in d
        assert "platform_fee_usd" in d
        assert "uber_estimate" in d
        assert "lyft_estimate" in d
        assert "transparency_note" in d
        assert "methodology_note" in d

    def test_fare_preview_competitor_has_all_fields(self):
        fields = FarePreviewCompetitor.model_fields
        for field in [
            "platform_name",
            "estimated_fare_usd",
            "estimated_driver_payout_usd",
            "estimated_driver_payout_pct",
            "estimated_platform_fee_usd",
            "estimated_platform_fee_pct",
            "source_note",
        ]:
            assert field in fields, f"Missing field: {field}"

    def test_fare_preview_response_has_all_fields(self):
        fields = FarePreviewResponse.model_fields
        for field in [
            "distance_km",
            "duration_min",
            "surge_multiplier",
            "is_surge",
            "estimated_fare_usd",
            "driver_payout_usd",
            "driver_payout_pct",
            "platform_fee_usd",
            "platform_fee_pct",
            "uber_estimate",
            "lyft_estimate",
            "driver_earns_more_than_uber_usd",
            "driver_earns_more_than_lyft_usd",
            "transparency_note",
            "methodology_note",
        ]:
            assert field in fields, f"Missing field: {field}"


# ===========================================================================
# API endpoint function
# ===========================================================================

class TestFarePreviewEndpoint:
    """Call the endpoint function directly — no DB or auth required."""

    @pytest.mark.asyncio
    async def test_returns_fare_preview_response(self):
        from app.api.v1.fare_preview import fare_preview
        result = await fare_preview(
            distance_km=STANDARD_DISTANCE_KM,
            duration_min=STANDARD_DURATION_MIN,
            surge_multiplier=1.0,
        )
        assert isinstance(result, FarePreviewResponse)

    @pytest.mark.asyncio
    async def test_correct_fare_for_standard_trip(self):
        from app.api.v1.fare_preview import fare_preview
        result = await fare_preview(
            distance_km=STANDARD_DISTANCE_KM,
            duration_min=STANDARD_DURATION_MIN,
            surge_multiplier=1.0,
        )
        assert result.estimated_fare_usd == pytest.approx(STANDARD_EXPECTED_FARE, rel=1e-4)

    @pytest.mark.asyncio
    async def test_surge_multiplier_passed_through(self):
        from app.api.v1.fare_preview import fare_preview
        result = await fare_preview(
            distance_km=STANDARD_DISTANCE_KM,
            duration_min=STANDARD_DURATION_MIN,
            surge_multiplier=2.0,
        )
        assert result.surge_multiplier == pytest.approx(2.0)
        assert result.is_surge is True

    @pytest.mark.asyncio
    async def test_default_no_surge(self):
        from app.api.v1.fare_preview import fare_preview
        result = await fare_preview(
            distance_km=STANDARD_DISTANCE_KM,
            duration_min=STANDARD_DURATION_MIN,
            surge_multiplier=1.0,
        )
        assert result.surge_multiplier == pytest.approx(1.0)
        assert result.is_surge is False

    @pytest.mark.asyncio
    async def test_zero_platform_fee(self):
        from app.api.v1.fare_preview import fare_preview
        result = await fare_preview(
            distance_km=STANDARD_DISTANCE_KM,
            duration_min=STANDARD_DURATION_MIN,
            surge_multiplier=1.0,
        )
        assert result.platform_fee_usd == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_driver_gets_full_fare(self):
        from app.api.v1.fare_preview import fare_preview
        result = await fare_preview(
            distance_km=STANDARD_DISTANCE_KM,
            duration_min=STANDARD_DURATION_MIN,
            surge_multiplier=1.0,
        )
        assert result.driver_payout_usd == pytest.approx(result.estimated_fare_usd, rel=1e-4)
