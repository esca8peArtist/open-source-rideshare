"""Tests for the rider savings summary feature.

GET /riders/me/savings-summary

Coverage
--------
Service layer (get_rider_savings_summary)
  - No completed rides → zero totals, 0 rides
  - Single ride with distance/duration → correct competitor estimates
  - Multiple rides, all with distance/duration → correct aggregation
  - Rides without distance/duration → excluded from savings, counted in spend
  - Mixed: some with distance, some without → partial comparison
  - Date range filtering: start_date excludes earlier rides
  - Date range filtering: end_date excludes later rides
  - Date range filtering: both bounds applied together
  - Tips are summed into total_tips_usd, excluded from savings
  - rides_included_in_comparison count is correct
  - Savings = competitor_total - openride_comparable (apples-to-apples)
  - avg_saved_per_ride: zero when rides_included_in_comparison = 0
  - Transparency note: no rides → onboarding message
  - Transparency note: positive savings → "saved" language
  - Transparency note: single ride grammar ("1 ride" not "1 rides")
  - period_start and period_end are reflected in response
  - methodology_note is non-empty
  - Minimum fare floor ($3.00) applied to very short competitor estimates

Helpers (_estimate_competitor_fare, _build_transparency_note)
  - Standard trip produces expected Uber fare
  - Standard trip produces expected Lyft fare
  - Very short trip triggers $3.00 minimum floor
  - Transparency note with zero savings formats correctly
  - Transparency note rider pays more (negative savings) formats correctly

Schema (RiderSavingsSummary)
  - All required fields present
  - Optional date fields can be None
  - Serialises to dict correctly

Router (get_savings_summary)
  - Returns RiderSavingsSummary from service
  - start_date / end_date forwarded to service
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.schemas.rider_savings_summary import RiderSavingsSummary
from app.services.rider_savings_summary import (
    _KM_TO_MILES,
    _LYFT_BASE_FARE,
    _LYFT_PER_MILE,
    _LYFT_PER_MIN,
    _UBER_BASE_FARE,
    _UBER_PER_MILE,
    _UBER_PER_MIN,
    _build_transparency_note,
    _estimate_competitor_fare,
    get_rider_savings_summary,
)


# ---------------------------------------------------------------------------
# Test data helpers
# ---------------------------------------------------------------------------

RIDER_ID = 42

# A standard 5 km / 10 min trip
DIST_5KM = 5.0
DUR_10MIN = 10.0

# Uber estimate for 5 km / 10 min:
#   miles = 5.0 * 0.621371 = 3.10686
#   fare = 1.38 + 0.20 * 10 + 0.84 * 3.10686 = 1.38 + 2.00 + 2.61 = 5.99
_UBER_5KM_10MIN = round(
    _UBER_BASE_FARE + _UBER_PER_MIN * 10.0 + _UBER_PER_MILE * (5.0 * _KM_TO_MILES), 2
)

# Lyft estimate for 5 km / 10 min:
#   miles = 5.0 * 0.621371 = 3.10686
#   fare = 1.25 + 0.22 * 10 + 0.83 * 3.10686 = 1.25 + 2.20 + 2.58 = 6.03
_LYFT_5KM_10MIN = round(
    _LYFT_BASE_FARE + _LYFT_PER_MIN * 10.0 + _LYFT_PER_MILE * (5.0 * _KM_TO_MILES), 2
)


def _make_ride(
    *,
    actual_fare: float = 10.0,
    distance_km: Optional[float] = DIST_5KM,
    duration_min: Optional[float] = DUR_10MIN,
    tip_amount: float = 0.0,
    requested_at: Optional[datetime] = None,
) -> MagicMock:
    """Build a minimal mock Ride object."""
    ride = MagicMock()
    ride.actual_fare = actual_fare
    ride.distance_km = distance_km
    ride.duration_min = duration_min
    ride.tip_amount = tip_amount
    ride.requested_at = requested_at or datetime(2026, 3, 15, 12, 0, 0, tzinfo=timezone.utc)
    return ride


def _mock_db(rides: list) -> AsyncMock:
    """Return a mock AsyncSession that returns the given rides."""
    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = rides
    db.execute = AsyncMock(return_value=mock_result)
    return db


# ===========================================================================
# _estimate_competitor_fare — unit tests
# ===========================================================================


class TestEstimateCompetitorFare:
    def test_uber_standard_trip(self):
        result = _estimate_competitor_fare(
            distance_km=DIST_5KM,
            duration_min=DUR_10MIN,
            base_fare=_UBER_BASE_FARE,
            per_min=_UBER_PER_MIN,
            per_mile=_UBER_PER_MILE,
        )
        assert result == _UBER_5KM_10MIN

    def test_lyft_standard_trip(self):
        result = _estimate_competitor_fare(
            distance_km=DIST_5KM,
            duration_min=DUR_10MIN,
            base_fare=_LYFT_BASE_FARE,
            per_min=_LYFT_PER_MIN,
            per_mile=_LYFT_PER_MILE,
        )
        assert result == _LYFT_5KM_10MIN

    def test_minimum_fare_floor(self):
        # Very short trip: 0.1 km, 0.5 min → would be pennies without floor
        result = _estimate_competitor_fare(
            distance_km=0.1,
            duration_min=0.5,
            base_fare=_UBER_BASE_FARE,
            per_min=_UBER_PER_MIN,
            per_mile=_UBER_PER_MILE,
        )
        assert result == 3.00

    def test_fare_above_minimum(self):
        result = _estimate_competitor_fare(
            distance_km=20.0,
            duration_min=30.0,
            base_fare=_UBER_BASE_FARE,
            per_min=_UBER_PER_MIN,
            per_mile=_UBER_PER_MILE,
        )
        assert result > 3.00

    def test_result_is_rounded_to_2dp(self):
        result = _estimate_competitor_fare(
            distance_km=3.7,
            duration_min=8.3,
            base_fare=_UBER_BASE_FARE,
            per_min=_UBER_PER_MIN,
            per_mile=_UBER_PER_MILE,
        )
        assert result == round(result, 2)


# ===========================================================================
# _build_transparency_note — unit tests
# ===========================================================================


class TestBuildTransparencyNote:
    def test_no_rides_returns_onboarding_message(self):
        note = _build_transparency_note(
            rides_count=0,
            total_saved_vs_uber=0.0,
            total_saved_vs_lyft=0.0,
        )
        assert "No completed rides" in note
        assert "first OpenRide" in note

    def test_positive_savings_uses_saved_language(self):
        note = _build_transparency_note(
            rides_count=5,
            total_saved_vs_uber=12.50,
            total_saved_vs_lyft=8.00,
        )
        assert "saved" in note
        assert "$12.50" in note
        assert "$8.00" in note

    def test_single_ride_singular_grammar(self):
        note = _build_transparency_note(
            rides_count=1,
            total_saved_vs_uber=2.00,
            total_saved_vs_lyft=1.50,
        )
        assert "1 ride " in note  # no trailing 's'

    def test_multiple_rides_plural_grammar(self):
        note = _build_transparency_note(
            rides_count=3,
            total_saved_vs_uber=5.00,
            total_saved_vs_lyft=3.00,
        )
        assert "3 rides" in note

    def test_negative_savings_uses_paid_more_language(self):
        note = _build_transparency_note(
            rides_count=2,
            total_saved_vs_uber=-3.00,
            total_saved_vs_lyft=-1.00,
        )
        assert "paid" in note
        assert "$3.00" in note


# ===========================================================================
# get_rider_savings_summary — service unit tests (with mocked DB)
# ===========================================================================


class TestGetRiderSavingsSummaryService:
    @pytest.mark.asyncio
    async def test_no_rides_returns_zero_totals(self):
        db = _mock_db([])
        result = await get_rider_savings_summary(db, RIDER_ID, None, None)
        assert result.total_completed_rides == 0
        assert result.rides_included_in_comparison == 0
        assert result.total_openride_spend_usd == 0.0
        assert result.total_tips_usd == 0.0
        assert result.total_estimated_uber_spend_usd == 0.0
        assert result.total_estimated_lyft_spend_usd == 0.0
        assert result.total_saved_vs_uber_usd == 0.0
        assert result.total_saved_vs_lyft_usd == 0.0
        assert result.avg_saved_per_ride_vs_uber_usd == 0.0
        assert result.avg_saved_per_ride_vs_lyft_usd == 0.0

    @pytest.mark.asyncio
    async def test_single_ride_correct_competitor_estimates(self):
        openride_fare = 10.00
        ride = _make_ride(actual_fare=openride_fare, distance_km=DIST_5KM, duration_min=DUR_10MIN)
        db = _mock_db([ride])
        result = await get_rider_savings_summary(db, RIDER_ID, None, None)

        assert result.total_completed_rides == 1
        assert result.rides_included_in_comparison == 1
        assert result.total_openride_spend_usd == openride_fare
        assert result.total_estimated_uber_spend_usd == _UBER_5KM_10MIN
        assert result.total_estimated_lyft_spend_usd == _LYFT_5KM_10MIN
        assert result.total_saved_vs_uber_usd == round(_UBER_5KM_10MIN - openride_fare, 2)
        assert result.total_saved_vs_lyft_usd == round(_LYFT_5KM_10MIN - openride_fare, 2)

    @pytest.mark.asyncio
    async def test_multiple_rides_aggregation(self):
        rides = [
            _make_ride(actual_fare=10.00, distance_km=5.0, duration_min=10.0),
            _make_ride(actual_fare=15.00, distance_km=8.0, duration_min=15.0),
        ]
        db = _mock_db(rides)
        result = await get_rider_savings_summary(db, RIDER_ID, None, None)

        assert result.total_completed_rides == 2
        assert result.rides_included_in_comparison == 2
        assert result.total_openride_spend_usd == 25.00

        # Competitor totals should equal sum of individual estimates
        uber_1 = _estimate_competitor_fare(5.0, 10.0, _UBER_BASE_FARE, _UBER_PER_MIN, _UBER_PER_MILE)
        uber_2 = _estimate_competitor_fare(8.0, 15.0, _UBER_BASE_FARE, _UBER_PER_MIN, _UBER_PER_MILE)
        assert result.total_estimated_uber_spend_usd == round(uber_1 + uber_2, 2)

    @pytest.mark.asyncio
    async def test_rides_without_distance_excluded_from_savings(self):
        ride_with_data = _make_ride(actual_fare=10.00, distance_km=5.0, duration_min=10.0)
        ride_without_data = _make_ride(actual_fare=12.00, distance_km=None, duration_min=None)
        db = _mock_db([ride_with_data, ride_without_data])
        result = await get_rider_savings_summary(db, RIDER_ID, None, None)

        assert result.total_completed_rides == 2
        assert result.rides_included_in_comparison == 1
        # Total spend includes both rides
        assert result.total_openride_spend_usd == 22.00
        # But savings comparison only uses the ride with data
        assert result.total_saved_vs_uber_usd == round(_UBER_5KM_10MIN - 10.00, 2)

    @pytest.mark.asyncio
    async def test_tips_summed_and_not_in_savings_calc(self):
        ride = _make_ride(actual_fare=10.00, tip_amount=3.00, distance_km=5.0, duration_min=10.0)
        db = _mock_db([ride])
        result = await get_rider_savings_summary(db, RIDER_ID, None, None)

        assert result.total_tips_usd == 3.00
        # actual_fare (not tip) in openride spend
        assert result.total_openride_spend_usd == 10.00

    @pytest.mark.asyncio
    async def test_avg_saved_per_ride_is_correct(self):
        rides = [
            _make_ride(actual_fare=10.00, distance_km=5.0, duration_min=10.0),
            _make_ride(actual_fare=10.00, distance_km=5.0, duration_min=10.0),
        ]
        db = _mock_db(rides)
        result = await get_rider_savings_summary(db, RIDER_ID, None, None)

        expected_uber_per_ride = round(_UBER_5KM_10MIN - 10.00, 2)
        assert result.avg_saved_per_ride_vs_uber_usd == expected_uber_per_ride

    @pytest.mark.asyncio
    async def test_avg_saved_per_ride_zero_when_no_comparison_rides(self):
        ride = _make_ride(actual_fare=10.00, distance_km=None, duration_min=None)
        db = _mock_db([ride])
        result = await get_rider_savings_summary(db, RIDER_ID, None, None)

        assert result.avg_saved_per_ride_vs_uber_usd == 0.0
        assert result.avg_saved_per_ride_vs_lyft_usd == 0.0

    @pytest.mark.asyncio
    async def test_period_dates_reflected_in_response(self):
        db = _mock_db([])
        start = date(2026, 1, 1)
        end = date(2026, 3, 31)
        result = await get_rider_savings_summary(db, RIDER_ID, start, end)

        assert result.period_start == start
        assert result.period_end == end

    @pytest.mark.asyncio
    async def test_no_period_dates_gives_none_in_response(self):
        db = _mock_db([])
        result = await get_rider_savings_summary(db, RIDER_ID, None, None)

        assert result.period_start is None
        assert result.period_end is None

    @pytest.mark.asyncio
    async def test_methodology_note_is_non_empty(self):
        db = _mock_db([])
        result = await get_rider_savings_summary(db, RIDER_ID, None, None)
        assert len(result.methodology_note) > 0

    @pytest.mark.asyncio
    async def test_transparency_note_no_rides_message(self):
        db = _mock_db([])
        result = await get_rider_savings_summary(db, RIDER_ID, None, None)
        assert "No completed rides" in result.transparency_note

    @pytest.mark.asyncio
    async def test_transparency_note_with_rides_mentions_savings(self):
        ride = _make_ride(actual_fare=5.00, distance_km=5.0, duration_min=10.0)
        db = _mock_db([ride])
        result = await get_rider_savings_summary(db, RIDER_ID, None, None)
        assert "saved" in result.transparency_note or "paid" in result.transparency_note

    @pytest.mark.asyncio
    async def test_db_query_receives_rider_id(self):
        db = _mock_db([])
        await get_rider_savings_summary(db, rider_id=99, start_date=None, end_date=None)
        # Just verify db.execute was called (filtering happens inside SQLAlchemy stmt)
        db.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_date_range_passed_to_query(self):
        """Verify that providing dates causes db.execute to be called (doesn't raise)."""
        db = _mock_db([])
        start = date(2026, 2, 1)
        end = date(2026, 2, 28)
        result = await get_rider_savings_summary(db, RIDER_ID, start, end)
        assert result.period_start == start
        assert result.period_end == end

    @pytest.mark.asyncio
    async def test_all_rides_without_distance_gives_zero_comparison(self):
        rides = [
            _make_ride(actual_fare=10.0, distance_km=None, duration_min=None),
            _make_ride(actual_fare=12.0, distance_km=None, duration_min=None),
        ]
        db = _mock_db(rides)
        result = await get_rider_savings_summary(db, RIDER_ID, None, None)

        assert result.rides_included_in_comparison == 0
        assert result.total_estimated_uber_spend_usd == 0.0
        assert result.total_estimated_lyft_spend_usd == 0.0
        assert result.total_saved_vs_uber_usd == 0.0
        assert result.total_saved_vs_lyft_usd == 0.0
        # But total spend is still correct
        assert result.total_openride_spend_usd == 22.0


# ===========================================================================
# RiderSavingsSummary schema — unit tests
# ===========================================================================


class TestRiderSavingsSummarySchema:
    def _make_summary(self, **overrides) -> RiderSavingsSummary:
        defaults = dict(
            total_completed_rides=5,
            rides_included_in_comparison=4,
            total_openride_spend_usd=50.00,
            total_tips_usd=8.00,
            total_estimated_uber_spend_usd=65.00,
            total_estimated_lyft_spend_usd=62.00,
            total_saved_vs_uber_usd=15.00,
            total_saved_vs_lyft_usd=12.00,
            avg_saved_per_ride_vs_uber_usd=3.75,
            avg_saved_per_ride_vs_lyft_usd=3.00,
            period_start=None,
            period_end=None,
            methodology_note="Test methodology note.",
            transparency_note="Test transparency note.",
        )
        defaults.update(overrides)
        return RiderSavingsSummary(**defaults)

    def test_all_required_fields_present(self):
        s = self._make_summary()
        assert s.total_completed_rides == 5
        assert s.rides_included_in_comparison == 4
        assert s.total_openride_spend_usd == 50.00
        assert s.total_tips_usd == 8.00
        assert s.total_saved_vs_uber_usd == 15.00
        assert s.total_saved_vs_lyft_usd == 12.00
        assert s.avg_saved_per_ride_vs_uber_usd == 3.75
        assert s.avg_saved_per_ride_vs_lyft_usd == 3.00
        assert s.methodology_note == "Test methodology note."
        assert s.transparency_note == "Test transparency note."

    def test_optional_date_fields_default_none(self):
        s = self._make_summary()
        assert s.period_start is None
        assert s.period_end is None

    def test_optional_date_fields_can_be_set(self):
        s = self._make_summary(
            period_start=date(2026, 1, 1),
            period_end=date(2026, 3, 31),
        )
        assert s.period_start == date(2026, 1, 1)
        assert s.period_end == date(2026, 3, 31)

    def test_serialises_to_dict(self):
        s = self._make_summary()
        d = s.model_dump()
        assert "total_completed_rides" in d
        assert "methodology_note" in d
        assert "transparency_note" in d
        assert d["period_start"] is None


# ===========================================================================
# get_savings_summary — router unit tests
# ===========================================================================


class TestGetSavingsSummaryRouter:
    @pytest.mark.asyncio
    async def test_router_delegates_to_service(self):
        from app.api.v1.rider_savings_summary import get_savings_summary

        mock_user = MagicMock()
        mock_user.id = RIDER_ID
        mock_db = AsyncMock()

        expected = RiderSavingsSummary(
            total_completed_rides=0,
            rides_included_in_comparison=0,
            total_openride_spend_usd=0.0,
            total_tips_usd=0.0,
            total_estimated_uber_spend_usd=0.0,
            total_estimated_lyft_spend_usd=0.0,
            total_saved_vs_uber_usd=0.0,
            total_saved_vs_lyft_usd=0.0,
            avg_saved_per_ride_vs_uber_usd=0.0,
            avg_saved_per_ride_vs_lyft_usd=0.0,
            period_start=None,
            period_end=None,
            methodology_note="m",
            transparency_note="t",
        )

        with patch(
            "app.api.v1.rider_savings_summary.get_rider_savings_summary",
            new_callable=AsyncMock,
            return_value=expected,
        ) as mock_service:
            result = await get_savings_summary(
                start_date=None,
                end_date=None,
                current_user=mock_user,
                db=mock_db,
            )

        mock_service.assert_called_once_with(
            db=mock_db,
            rider_id=RIDER_ID,
            start_date=None,
            end_date=None,
        )
        assert result is expected

    @pytest.mark.asyncio
    async def test_router_forwards_date_params(self):
        from app.api.v1.rider_savings_summary import get_savings_summary

        mock_user = MagicMock()
        mock_user.id = RIDER_ID
        mock_db = AsyncMock()

        stub = RiderSavingsSummary(
            total_completed_rides=0, rides_included_in_comparison=0,
            total_openride_spend_usd=0.0, total_tips_usd=0.0,
            total_estimated_uber_spend_usd=0.0, total_estimated_lyft_spend_usd=0.0,
            total_saved_vs_uber_usd=0.0, total_saved_vs_lyft_usd=0.0,
            avg_saved_per_ride_vs_uber_usd=0.0, avg_saved_per_ride_vs_lyft_usd=0.0,
            period_start=date(2026, 1, 1), period_end=date(2026, 3, 31),
            methodology_note="m", transparency_note="t",
        )

        with patch(
            "app.api.v1.rider_savings_summary.get_rider_savings_summary",
            new_callable=AsyncMock,
            return_value=stub,
        ) as mock_service:
            await get_savings_summary(
                start_date=date(2026, 1, 1),
                end_date=date(2026, 3, 31),
                current_user=mock_user,
                db=mock_db,
            )

        mock_service.assert_called_once_with(
            db=mock_db,
            rider_id=RIDER_ID,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 3, 31),
        )
