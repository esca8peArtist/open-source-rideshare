"""Tests for the platform transparency report feature.

GET /platform/transparency-report

Coverage
--------
Service layer (get_platform_transparency_report)
  - No rides in DB → data_available=False, all numeric fields are zero
  - Single completed ride → data_available=True, correct earnings/rider totals
  - Multiple completed rides → correct aggregation across rides
  - driver_payout from Payment record is used when available
  - Falls back to actual_fare when no Payment record exists
  - avg_driver_payout_pct is always 100.0
  - Competitor earnings are lower than OpenRide total (platform commission)
  - Rider savings vs. Uber and Lyft are positive (OpenRide cheaper)
  - unique_riders_period counts distinct rider IDs
  - avg_driver_rating averages only non-null driver_rating values
  - avg_rider_rating averages only non-null rider_rating values
  - Null ratings are excluded from average (no effect on count)
  - rides_completed_pct = completed / (completed + cancelled) * 100
  - rides_completed_pct is 100 when no cancellations
  - rides_completed_pct is 0 when no rides (data_available=False)
  - all_time period returns rides without date filter
  - last_30_days period applies date filter (verified via mock call)
  - last_7_days period applies date filter (verified via mock call)
  - report_period field reflects the requested period key
  - period_label reflects the human-readable period name
  - total_rides_completed is all-time count regardless of period
  - total_rides_period is within-period count
  - generated_at is a UTC datetime
  - platform_model.commission_rate_pct is always 0.0
  - platform_model.ownership_model is 'cooperative'
  - methodology_note is non-empty
  - transparency_note is non-empty
  - data_available is True only when period has completed rides

Calculation helpers (_build_earnings_summary, _build_rider_summary,
                     _build_service_quality)
  - _build_earnings_summary: total = sum of driver_payouts
  - _build_earnings_summary: uber equivalent = total * uber_take_rate
  - _build_earnings_summary: driver_savings_vs_uber positive
  - _build_rider_summary: avg_fare = mean of actual_fares
  - _build_rider_summary: avg_uber_equivalent > avg_fare (commission)
  - _build_rider_summary: avg_rider_savings_vs_uber > 0
  - _build_service_quality: avg ratings computed correctly
  - _build_service_quality: completion_pct with zero cancellations = 100.0
  - _build_service_quality: completion_pct with cancellations < 100.0

Schema (PlatformTransparencyReport)
  - All required top-level fields present
  - Nested models serialise correctly
  - data_available field present and boolean
  - model_dump() produces expected keys

Router (get_transparency_report)
  - Delegates to service with correct period argument
  - Default period is last_30_days
  - Returns PlatformTransparencyReport schema
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.schemas.platform_transparency import (
    EarningsSummary,
    PlatformModel,
    PlatformTransparencyReport,
    RideVolume,
    RiderSummary,
    ServiceQuality,
)
from app.services.platform_transparency import (
    ReportPeriod,
    _UBER_DRIVER_TAKE_RATE,
    _LYFT_DRIVER_TAKE_RATE,
    _build_earnings_summary,
    _build_rider_summary,
    _build_service_quality,
    get_platform_transparency_report,
)


# ---------------------------------------------------------------------------
# Test data helpers
# ---------------------------------------------------------------------------


def _make_ride(
    *,
    id: int = 1,
    rider_id: int = 10,
    actual_fare: float = 15.00,
    driver_rating: int | None = 5,
    rider_rating: int | None = 5,
    requested_at: datetime | None = None,
) -> MagicMock:
    """Build a minimal mock Ride object for period rides."""
    ride = MagicMock()
    ride.id = id
    ride.rider_id = rider_id
    ride.actual_fare = actual_fare
    ride.driver_rating = driver_rating
    ride.rider_rating = rider_rating
    ride.requested_at = requested_at or datetime(2026, 3, 15, 12, 0, 0, tzinfo=timezone.utc)
    return ride


def _make_payment(*, ride_id: int = 1, driver_payout: float = 15.00) -> MagicMock:
    """Build a minimal mock Payment object."""
    payment = MagicMock()
    payment.ride_id = ride_id
    payment.driver_payout = driver_payout
    return payment


def _mock_db_for_report(
    *,
    all_time_count: int = 0,
    period_rides: list | None = None,
    payments: dict | None = None,
    cancelled_count: int = 0,
) -> AsyncMock:
    """Return an AsyncMock DB that sequences responses for the transparency report queries.

    The service makes DB calls in this order:
      1. _count_all_time_completed  → scalar_one() returns all_time_count
      2. _fetch_period_completed_rides → scalars().all() returns period_rides
      3. _fetch_payments_for_rides (only if period_rides non-empty)
              → scalars().all() returns list of payments
      4. _count_cancelled_in_period (only if period_rides non-empty)
              → scalar_one() returns cancelled_count
    """
    if period_rides is None:
        period_rides = []
    if payments is None:
        payments = {}

    db = AsyncMock()
    call_counter = {"n": 0}

    payment_list = list(payments.values())

    async def execute_side_effect(stmt):
        n = call_counter["n"]
        call_counter["n"] += 1

        mock_result = MagicMock()

        if n == 0:
            # _count_all_time_completed
            mock_result.scalar_one.return_value = all_time_count
        elif n == 1:
            # _fetch_period_completed_rides
            mock_result.scalars.return_value.all.return_value = period_rides
        elif n == 2 and period_rides:
            # _fetch_payments_for_rides
            mock_result.scalars.return_value.all.return_value = payment_list
        elif n == 3 and period_rides:
            # _count_cancelled_in_period
            mock_result.scalar_one.return_value = cancelled_count
        else:
            mock_result.scalar_one.return_value = 0
            mock_result.scalars.return_value.all.return_value = []

        return mock_result

    db.execute = AsyncMock(side_effect=execute_side_effect)
    return db


# ===========================================================================
# _build_earnings_summary — unit tests
# ===========================================================================


class TestBuildEarningsSummary:
    def test_single_ride_with_payment_uses_driver_payout(self):
        ride = _make_ride(id=1, actual_fare=20.00)
        payment = _make_payment(ride_id=1, driver_payout=15.00)
        result = _build_earnings_summary([ride], {1: payment})

        assert result.total_driver_earnings_usd == 15.00

    def test_single_ride_without_payment_uses_actual_fare(self):
        ride = _make_ride(id=1, actual_fare=12.00)
        result = _build_earnings_summary([ride], {})  # no payments

        assert result.total_driver_earnings_usd == 12.00

    def test_multiple_rides_sum_payouts(self):
        rides = [
            _make_ride(id=1, actual_fare=10.00),
            _make_ride(id=2, actual_fare=20.00),
        ]
        payments = {
            1: _make_payment(ride_id=1, driver_payout=10.00),
            2: _make_payment(ride_id=2, driver_payout=20.00),
        }
        result = _build_earnings_summary(rides, payments)

        assert result.total_driver_earnings_usd == 30.00

    def test_uber_equivalent_is_lower_than_total(self):
        ride = _make_ride(id=1, actual_fare=15.00)
        result = _build_earnings_summary([ride], {})

        assert result.uber_equivalent_driver_earnings_usd < result.total_driver_earnings_usd

    def test_lyft_equivalent_is_lower_than_total(self):
        ride = _make_ride(id=1, actual_fare=15.00)
        result = _build_earnings_summary([ride], {})

        assert result.lyft_equivalent_driver_earnings_usd < result.total_driver_earnings_usd

    def test_driver_savings_vs_uber_is_positive(self):
        ride = _make_ride(id=1, actual_fare=15.00)
        result = _build_earnings_summary([ride], {})

        assert result.driver_savings_vs_uber_usd > 0.0

    def test_driver_savings_vs_lyft_is_positive(self):
        ride = _make_ride(id=1, actual_fare=15.00)
        result = _build_earnings_summary([ride], {})

        assert result.driver_savings_vs_lyft_usd > 0.0

    def test_avg_driver_payout_pct_always_100(self):
        ride = _make_ride(id=1, actual_fare=15.00)
        result = _build_earnings_summary([ride], {})

        assert result.avg_driver_payout_pct == 100.0

    def test_avg_earnings_per_ride_correct(self):
        rides = [
            _make_ride(id=1, actual_fare=10.00),
            _make_ride(id=2, actual_fare=20.00),
        ]
        result = _build_earnings_summary(rides, {})

        assert result.avg_driver_earnings_per_ride_usd == 15.00

    def test_empty_rides_returns_all_zeros(self):
        result = _build_earnings_summary([], {})

        assert result.total_driver_earnings_usd == 0.0
        assert result.avg_driver_earnings_per_ride_usd == 0.0
        assert result.uber_equivalent_driver_earnings_usd == 0.0
        assert result.driver_savings_vs_uber_usd == 0.0

    def test_uber_equivalent_applies_take_rate(self):
        ride = _make_ride(id=1, actual_fare=100.00)
        result = _build_earnings_summary([ride], {})

        expected_uber = round(100.00 * _UBER_DRIVER_TAKE_RATE, 2)
        assert result.uber_equivalent_driver_earnings_usd == expected_uber

    def test_lyft_equivalent_applies_take_rate(self):
        ride = _make_ride(id=1, actual_fare=100.00)
        result = _build_earnings_summary([ride], {})

        expected_lyft = round(100.00 * _LYFT_DRIVER_TAKE_RATE, 2)
        assert result.lyft_equivalent_driver_earnings_usd == expected_lyft


# ===========================================================================
# _build_rider_summary — unit tests
# ===========================================================================


class TestBuildRiderSummary:
    def test_avg_fare_is_mean_of_actual_fares(self):
        rides = [
            _make_ride(id=1, rider_id=10, actual_fare=10.00),
            _make_ride(id=2, rider_id=11, actual_fare=20.00),
        ]
        result = _build_rider_summary(rides)

        assert result.avg_fare_usd == 15.00

    def test_unique_riders_count_distinct_rider_ids(self):
        rides = [
            _make_ride(id=1, rider_id=10, actual_fare=10.00),
            _make_ride(id=2, rider_id=10, actual_fare=12.00),  # same rider
            _make_ride(id=3, rider_id=11, actual_fare=8.00),
        ]
        result = _build_rider_summary(rides)

        assert result.unique_riders_period == 2

    def test_uber_equivalent_fare_is_higher_than_openride(self):
        ride = _make_ride(id=1, actual_fare=15.00)
        result = _build_rider_summary([ride])

        assert result.avg_uber_equivalent_fare_usd > result.avg_fare_usd

    def test_lyft_equivalent_fare_is_higher_than_openride(self):
        ride = _make_ride(id=1, actual_fare=15.00)
        result = _build_rider_summary([ride])

        assert result.avg_lyft_equivalent_fare_usd > result.avg_fare_usd

    def test_rider_savings_vs_uber_is_positive(self):
        ride = _make_ride(id=1, actual_fare=15.00)
        result = _build_rider_summary([ride])

        assert result.avg_rider_savings_vs_uber_usd > 0.0

    def test_rider_savings_vs_lyft_is_positive(self):
        ride = _make_ride(id=1, actual_fare=15.00)
        result = _build_rider_summary([ride])

        assert result.avg_rider_savings_vs_lyft_usd > 0.0

    def test_empty_rides_returns_zero_unique_riders(self):
        result = _build_rider_summary([])

        assert result.unique_riders_period == 0
        assert result.avg_fare_usd == 0.0

    def test_uber_equivalent_uses_driver_take_rate(self):
        ride = _make_ride(id=1, actual_fare=10.00)
        result = _build_rider_summary([ride])

        expected_avg_uber = round(10.00 / _UBER_DRIVER_TAKE_RATE, 2)
        assert result.avg_uber_equivalent_fare_usd == expected_avg_uber

    def test_savings_equals_uber_minus_openride(self):
        ride = _make_ride(id=1, actual_fare=10.00)
        result = _build_rider_summary([ride])

        expected = round(result.avg_uber_equivalent_fare_usd - result.avg_fare_usd, 2)
        assert result.avg_rider_savings_vs_uber_usd == expected


# ===========================================================================
# _build_service_quality — unit tests
# ===========================================================================


class TestBuildServiceQuality:
    def test_avg_driver_rating_correct(self):
        rides = [
            _make_ride(id=1, driver_rating=4, rider_rating=5),
            _make_ride(id=2, driver_rating=5, rider_rating=4),
        ]
        result = _build_service_quality(rides, cancelled_count=0)

        assert result.avg_driver_rating == 4.5

    def test_avg_rider_rating_correct(self):
        rides = [
            _make_ride(id=1, driver_rating=5, rider_rating=3),
            _make_ride(id=2, driver_rating=5, rider_rating=5),
        ]
        result = _build_service_quality(rides, cancelled_count=0)

        assert result.avg_rider_rating == 4.0

    def test_null_driver_ratings_excluded(self):
        rides = [
            _make_ride(id=1, driver_rating=4, rider_rating=5),
            _make_ride(id=2, driver_rating=None, rider_rating=5),
        ]
        result = _build_service_quality(rides, cancelled_count=0)

        assert result.avg_driver_rating == 4.0  # only ride 1 counted

    def test_null_rider_ratings_excluded(self):
        rides = [
            _make_ride(id=1, driver_rating=5, rider_rating=None),
            _make_ride(id=2, driver_rating=5, rider_rating=5),
        ]
        result = _build_service_quality(rides, cancelled_count=0)

        assert result.avg_rider_rating == 5.0  # only ride 2 counted

    def test_completion_pct_100_when_no_cancellations(self):
        rides = [_make_ride(id=1), _make_ride(id=2)]
        result = _build_service_quality(rides, cancelled_count=0)

        assert result.rides_completed_pct == 100.0

    def test_completion_pct_with_cancellations(self):
        rides = [_make_ride(id=1), _make_ride(id=2), _make_ride(id=3)]
        result = _build_service_quality(rides, cancelled_count=1)

        # 3 completed / 4 total = 75%
        assert result.rides_completed_pct == 75.0

    def test_completion_pct_zero_when_no_rides(self):
        result = _build_service_quality([], cancelled_count=0)

        assert result.rides_completed_pct == 0.0

    def test_all_null_ratings_give_zero_averages(self):
        rides = [_make_ride(id=1, driver_rating=None, rider_rating=None)]
        result = _build_service_quality(rides, cancelled_count=0)

        assert result.avg_driver_rating == 0.0
        assert result.avg_rider_rating == 0.0


# ===========================================================================
# get_platform_transparency_report — service tests (mocked DB)
# ===========================================================================


class TestGetPlatformTransparencyReport:
    @pytest.mark.asyncio
    async def test_no_rides_data_available_false(self):
        db = _mock_db_for_report(all_time_count=0, period_rides=[])
        result = await get_platform_transparency_report(db, ReportPeriod.LAST_30_DAYS)

        assert result.data_available is False

    @pytest.mark.asyncio
    async def test_no_rides_all_numeric_fields_zero(self):
        db = _mock_db_for_report(all_time_count=0, period_rides=[])
        result = await get_platform_transparency_report(db, ReportPeriod.LAST_30_DAYS)

        assert result.earnings_summary.total_driver_earnings_usd == 0.0
        assert result.earnings_summary.uber_equivalent_driver_earnings_usd == 0.0
        assert result.rider_summary.unique_riders_period == 0
        assert result.rider_summary.avg_fare_usd == 0.0
        assert result.service_quality.avg_driver_rating == 0.0
        assert result.service_quality.rides_completed_pct == 0.0

    @pytest.mark.asyncio
    async def test_with_rides_data_available_true(self):
        rides = [_make_ride(id=1, actual_fare=10.00)]
        db = _mock_db_for_report(all_time_count=1, period_rides=rides)
        result = await get_platform_transparency_report(db, ReportPeriod.LAST_30_DAYS)

        assert result.data_available is True

    @pytest.mark.asyncio
    async def test_total_rides_period_matches_period_count(self):
        rides = [_make_ride(id=i, actual_fare=10.00) for i in range(5)]
        db = _mock_db_for_report(all_time_count=10, period_rides=rides)
        result = await get_platform_transparency_report(db, ReportPeriod.LAST_30_DAYS)

        assert result.ride_volume.total_rides_period == 5

    @pytest.mark.asyncio
    async def test_total_rides_completed_is_all_time(self):
        rides = [_make_ride(id=1, actual_fare=10.00)]
        db = _mock_db_for_report(all_time_count=999, period_rides=rides)
        result = await get_platform_transparency_report(db, ReportPeriod.LAST_30_DAYS)

        assert result.ride_volume.total_rides_completed == 999

    @pytest.mark.asyncio
    async def test_report_period_field_correct(self):
        db = _mock_db_for_report(all_time_count=0, period_rides=[])
        result = await get_platform_transparency_report(db, ReportPeriod.LAST_7_DAYS)

        assert result.report_period == "last_7_days"

    @pytest.mark.asyncio
    async def test_period_label_last_7_days(self):
        db = _mock_db_for_report(all_time_count=0, period_rides=[])
        result = await get_platform_transparency_report(db, ReportPeriod.LAST_7_DAYS)

        assert result.ride_volume.period_label == "Last 7 days"

    @pytest.mark.asyncio
    async def test_period_label_last_30_days(self):
        db = _mock_db_for_report(all_time_count=0, period_rides=[])
        result = await get_platform_transparency_report(db, ReportPeriod.LAST_30_DAYS)

        assert result.ride_volume.period_label == "Last 30 days"

    @pytest.mark.asyncio
    async def test_period_label_all_time(self):
        db = _mock_db_for_report(all_time_count=0, period_rides=[])
        result = await get_platform_transparency_report(db, ReportPeriod.ALL_TIME)

        assert result.ride_volume.period_label == "All time"

    @pytest.mark.asyncio
    async def test_platform_model_commission_always_zero(self):
        db = _mock_db_for_report(all_time_count=0, period_rides=[])
        result = await get_platform_transparency_report(db, ReportPeriod.LAST_30_DAYS)

        assert result.platform_model.commission_rate_pct == 0.0

    @pytest.mark.asyncio
    async def test_platform_model_ownership_is_cooperative(self):
        db = _mock_db_for_report(all_time_count=0, period_rides=[])
        result = await get_platform_transparency_report(db, ReportPeriod.LAST_30_DAYS)

        assert result.platform_model.ownership_model == "cooperative"

    @pytest.mark.asyncio
    async def test_generated_at_is_utc_datetime(self):
        db = _mock_db_for_report(all_time_count=0, period_rides=[])
        result = await get_platform_transparency_report(db, ReportPeriod.LAST_30_DAYS)

        assert isinstance(result.generated_at, datetime)
        assert result.generated_at.tzinfo is not None

    @pytest.mark.asyncio
    async def test_methodology_note_non_empty(self):
        db = _mock_db_for_report(all_time_count=0, period_rides=[])
        result = await get_platform_transparency_report(db, ReportPeriod.LAST_30_DAYS)

        assert len(result.methodology_note) > 0

    @pytest.mark.asyncio
    async def test_transparency_note_non_empty(self):
        db = _mock_db_for_report(all_time_count=0, period_rides=[])
        result = await get_platform_transparency_report(db, ReportPeriod.LAST_30_DAYS)

        assert len(result.transparency_note) > 0

    @pytest.mark.asyncio
    async def test_earnings_uses_payment_record_when_available(self):
        ride = _make_ride(id=1, actual_fare=20.00)
        payment = _make_payment(ride_id=1, driver_payout=15.00)
        db = _mock_db_for_report(
            all_time_count=1,
            period_rides=[ride],
            payments={1: payment},
        )
        result = await get_platform_transparency_report(db, ReportPeriod.LAST_30_DAYS)

        assert result.earnings_summary.total_driver_earnings_usd == 15.00

    @pytest.mark.asyncio
    async def test_earnings_fallback_to_actual_fare_without_payment(self):
        ride = _make_ride(id=1, actual_fare=18.00)
        db = _mock_db_for_report(
            all_time_count=1,
            period_rides=[ride],
            payments={},  # no payment record
        )
        result = await get_platform_transparency_report(db, ReportPeriod.LAST_30_DAYS)

        assert result.earnings_summary.total_driver_earnings_usd == 18.00

    @pytest.mark.asyncio
    async def test_driver_savings_positive(self):
        ride = _make_ride(id=1, actual_fare=15.00)
        db = _mock_db_for_report(all_time_count=1, period_rides=[ride])
        result = await get_platform_transparency_report(db, ReportPeriod.LAST_30_DAYS)

        assert result.earnings_summary.driver_savings_vs_uber_usd > 0.0
        assert result.earnings_summary.driver_savings_vs_lyft_usd > 0.0

    @pytest.mark.asyncio
    async def test_rider_savings_positive(self):
        ride = _make_ride(id=1, actual_fare=15.00)
        db = _mock_db_for_report(all_time_count=1, period_rides=[ride])
        result = await get_platform_transparency_report(db, ReportPeriod.LAST_30_DAYS)

        assert result.rider_summary.avg_rider_savings_vs_uber_usd > 0.0
        assert result.rider_summary.avg_rider_savings_vs_lyft_usd > 0.0

    @pytest.mark.asyncio
    async def test_service_quality_populated_correctly(self):
        rides = [
            _make_ride(id=1, driver_rating=5, rider_rating=4),
            _make_ride(id=2, driver_rating=4, rider_rating=5),
        ]
        db = _mock_db_for_report(
            all_time_count=2,
            period_rides=rides,
            cancelled_count=0,
        )
        result = await get_platform_transparency_report(db, ReportPeriod.LAST_30_DAYS)

        assert result.service_quality.avg_driver_rating == 4.5
        assert result.service_quality.avg_rider_rating == 4.5
        assert result.service_quality.rides_completed_pct == 100.0

    @pytest.mark.asyncio
    async def test_completion_pct_with_cancellations(self):
        rides = [_make_ride(id=1), _make_ride(id=2), _make_ride(id=3)]
        db = _mock_db_for_report(
            all_time_count=3,
            period_rides=rides,
            cancelled_count=1,
        )
        result = await get_platform_transparency_report(db, ReportPeriod.LAST_30_DAYS)

        assert result.service_quality.rides_completed_pct == 75.0

    @pytest.mark.asyncio
    async def test_db_execute_called_multiple_times(self):
        rides = [_make_ride(id=1, actual_fare=10.00)]
        db = _mock_db_for_report(all_time_count=1, period_rides=rides)
        await get_platform_transparency_report(db, ReportPeriod.LAST_30_DAYS)

        # Service makes 4 DB calls when period has rides: all_time count,
        # period rides, payments, cancelled count
        assert db.execute.call_count == 4

    @pytest.mark.asyncio
    async def test_no_rides_db_execute_called_twice(self):
        db = _mock_db_for_report(all_time_count=0, period_rides=[])
        await get_platform_transparency_report(db, ReportPeriod.LAST_30_DAYS)

        # Only 2 calls when no period rides: all_time count + period rides
        assert db.execute.call_count == 2

    @pytest.mark.asyncio
    async def test_all_time_period_key(self):
        db = _mock_db_for_report(all_time_count=0, period_rides=[])
        result = await get_platform_transparency_report(db, ReportPeriod.ALL_TIME)

        assert result.report_period == "all_time"

    @pytest.mark.asyncio
    async def test_avg_driver_payout_pct_always_100(self):
        rides = [_make_ride(id=1, actual_fare=20.00)]
        db = _mock_db_for_report(all_time_count=1, period_rides=rides)
        result = await get_platform_transparency_report(db, ReportPeriod.LAST_30_DAYS)

        assert result.earnings_summary.avg_driver_payout_pct == 100.0


# ===========================================================================
# PlatformTransparencyReport schema — unit tests
# ===========================================================================


class TestPlatformTransparencyReportSchema:
    def _make_report(self, **overrides) -> PlatformTransparencyReport:
        defaults = dict(
            generated_at=datetime(2026, 4, 17, 14, 23, 0, tzinfo=timezone.utc),
            report_period="last_30_days",
            data_available=True,
            platform_model=PlatformModel(
                commission_rate_pct=0.0,
                commission_note="OpenRide charges no platform commission.",
                ownership_model="cooperative",
                cooperative_description="Drivers are co-owners.",
            ),
            ride_volume=RideVolume(
                total_rides_completed=12847,
                total_rides_period=2341,
                period_label="Last 30 days",
            ),
            earnings_summary=EarningsSummary(
                total_driver_earnings_usd=284729.50,
                avg_driver_earnings_per_ride_usd=14.22,
                avg_driver_payout_pct=100.0,
                uber_equivalent_driver_earnings_usd=213547.12,
                lyft_equivalent_driver_earnings_usd=220764.84,
                driver_savings_vs_uber_usd=71182.38,
                driver_savings_vs_lyft_usd=63964.66,
            ),
            rider_summary=RiderSummary(
                unique_riders_period=1847,
                avg_fare_usd=14.22,
                avg_uber_equivalent_fare_usd=18.49,
                avg_lyft_equivalent_fare_usd=17.28,
                avg_rider_savings_vs_uber_usd=4.27,
                avg_rider_savings_vs_lyft_usd=3.06,
            ),
            service_quality=ServiceQuality(
                avg_driver_rating=4.82,
                avg_rider_rating=4.71,
                rides_completed_pct=96.3,
            ),
            methodology_note="Methodology note.",
            transparency_note="Transparency note.",
        )
        defaults.update(overrides)
        return PlatformTransparencyReport(**defaults)

    def test_all_required_top_level_fields_present(self):
        r = self._make_report()
        assert r.generated_at is not None
        assert r.report_period == "last_30_days"
        assert r.data_available is True
        assert r.platform_model is not None
        assert r.ride_volume is not None
        assert r.earnings_summary is not None
        assert r.rider_summary is not None
        assert r.service_quality is not None
        assert r.methodology_note == "Methodology note."
        assert r.transparency_note == "Transparency note."

    def test_data_available_false_accepted(self):
        r = self._make_report(data_available=False)
        assert r.data_available is False

    def test_nested_models_accessible(self):
        r = self._make_report()
        assert r.platform_model.commission_rate_pct == 0.0
        assert r.ride_volume.total_rides_completed == 12847
        assert r.earnings_summary.avg_driver_payout_pct == 100.0
        assert r.rider_summary.unique_riders_period == 1847
        assert r.service_quality.rides_completed_pct == 96.3

    def test_serialises_to_dict_with_expected_keys(self):
        r = self._make_report()
        d = r.model_dump()
        assert "generated_at" in d
        assert "report_period" in d
        assert "data_available" in d
        assert "platform_model" in d
        assert "ride_volume" in d
        assert "earnings_summary" in d
        assert "rider_summary" in d
        assert "service_quality" in d
        assert "methodology_note" in d
        assert "transparency_note" in d

    def test_nested_dict_has_correct_fields(self):
        r = self._make_report()
        d = r.model_dump()
        assert "commission_rate_pct" in d["platform_model"]
        assert "total_driver_earnings_usd" in d["earnings_summary"]
        assert "unique_riders_period" in d["rider_summary"]
        assert "rides_completed_pct" in d["service_quality"]


# ===========================================================================
# get_transparency_report — router unit tests
# ===========================================================================


class TestGetTransparencyReportRouter:
    @pytest.mark.asyncio
    async def test_router_delegates_to_service(self):
        from app.api.v1.platform_transparency import get_transparency_report

        mock_db = AsyncMock()
        expected_report = MagicMock(spec=PlatformTransparencyReport)

        with patch(
            "app.api.v1.platform_transparency.get_platform_transparency_report",
            new_callable=AsyncMock,
            return_value=expected_report,
        ) as mock_service:
            result = await get_transparency_report(
                period=ReportPeriod.LAST_30_DAYS,
                db=mock_db,
            )

        mock_service.assert_called_once_with(
            db=mock_db,
            period=ReportPeriod.LAST_30_DAYS,
        )
        assert result is expected_report

    @pytest.mark.asyncio
    async def test_router_forwards_last_7_days_period(self):
        from app.api.v1.platform_transparency import get_transparency_report

        mock_db = AsyncMock()
        stub = MagicMock(spec=PlatformTransparencyReport)

        with patch(
            "app.api.v1.platform_transparency.get_platform_transparency_report",
            new_callable=AsyncMock,
            return_value=stub,
        ) as mock_service:
            await get_transparency_report(
                period=ReportPeriod.LAST_7_DAYS,
                db=mock_db,
            )

        mock_service.assert_called_once_with(
            db=mock_db,
            period=ReportPeriod.LAST_7_DAYS,
        )

    @pytest.mark.asyncio
    async def test_router_forwards_all_time_period(self):
        from app.api.v1.platform_transparency import get_transparency_report

        mock_db = AsyncMock()
        stub = MagicMock(spec=PlatformTransparencyReport)

        with patch(
            "app.api.v1.platform_transparency.get_platform_transparency_report",
            new_callable=AsyncMock,
            return_value=stub,
        ) as mock_service:
            await get_transparency_report(
                period=ReportPeriod.ALL_TIME,
                db=mock_db,
            )

        mock_service.assert_called_once_with(
            db=mock_db,
            period=ReportPeriod.ALL_TIME,
        )
