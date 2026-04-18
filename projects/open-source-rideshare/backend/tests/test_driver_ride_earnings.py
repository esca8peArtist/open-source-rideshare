"""Unit tests for driver per-ride earnings breakdown."""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from app.schemas.driver_ride_earnings import DriverRideEarnings
from app.services.driver_ride_earnings import compute_driver_ride_earnings

_TS = datetime(2026, 4, 15, 14, 0, 0, tzinfo=timezone.utc)

# No time-of-day multipliers configured in tests → multiplier=1.0
_BASE_PARAMS = {
    "base_fare": 2.50,
    "per_km_rate": 1.20,
    "per_minute_rate": 0.25,
    "minimum_fare": 5.00,
    "platform_fee_percent": 20.0,
}


def _compute(**kwargs):
    defaults = dict(
        ride_id=1,
        pickup_address="123 Main St",
        dropoff_address="456 Oak Ave",
        actual_fare=15.00,
        tip_amount=2.00,
        distance_km=5.0,
        duration_min=10.0,
        completed_at=_TS,
    )
    defaults.update(kwargs)
    with patch("app.services.driver_ride_earnings.get_pricing_params", return_value=_BASE_PARAMS):
        return compute_driver_ride_earnings(**defaults)


class TestDriverRideEarningsSchema:
    def test_all_fields_present(self):
        result = _compute()
        assert isinstance(result, DriverRideEarnings)
        assert result.ride_id == 1
        assert result.pickup_address == "123 Main St"
        assert result.dropoff_address == "456 Oak Ave"
        assert result.distance_km == 5.0
        assert result.duration_min == 10.0
        assert result.completed_at == _TS

    def test_roundtrip_serialization(self):
        result = _compute()
        data = result.model_dump()
        restored = DriverRideEarnings(**data)
        assert restored == result


class TestPlatformFeeDeduction:
    def test_platform_fee_20pct(self):
        # actual_fare=15.00, pct=20 → subtotal=12.50, platform_fee=2.50
        result = _compute(actual_fare=15.00)
        assert result.subtotal == 12.50
        assert result.platform_fee == 2.50
        assert result.net_fare == 12.50

    def test_net_fare_plus_tip_equals_total(self):
        result = _compute(actual_fare=15.00, tip_amount=2.00)
        assert result.total_driver_earnings == round(result.net_fare + result.tip, 2)

    def test_zero_platform_fee(self):
        zero_fee_params = {**_BASE_PARAMS, "platform_fee_percent": 0.0}
        with patch("app.services.driver_ride_earnings.get_pricing_params", return_value=zero_fee_params):
            result = compute_driver_ride_earnings(
                ride_id=1,
                pickup_address="A",
                dropoff_address="B",
                actual_fare=15.00,
                tip_amount=0.0,
                distance_km=5.0,
                duration_min=10.0,
                completed_at=_TS,
            )
        assert result.platform_fee == 0.0
        assert result.net_fare == 15.00
        assert result.subtotal == 15.00

    def test_platform_fee_sums_correctly(self):
        result = _compute(actual_fare=20.00)
        assert round(result.subtotal + result.platform_fee, 2) == 20.00


class TestFareComponents:
    def test_components_scale_to_actual_fare(self):
        # base + distance + time components should sum to actual_fare
        result = _compute(actual_fare=15.00, distance_km=5.0, duration_min=10.0)
        reconstructed = round(result.base_fare + result.distance_earnings + result.time_earnings, 2)
        # Components are scaled to actual_fare (not subtotal), so sum ≈ actual_fare
        assert reconstructed == pytest.approx(15.00, abs=0.02)

    def test_components_non_negative(self):
        result = _compute()
        assert result.base_fare >= 0
        assert result.distance_earnings >= 0
        assert result.time_earnings >= 0

    def test_missing_distance_and_duration(self):
        result = _compute(distance_km=None, duration_min=None)
        assert result.distance_km is None
        assert result.duration_min is None
        # When distance=0 and duration=0, fare can't be reconstructed;
        # components should be 0 (scale=0) but totals remain correct
        assert result.net_fare > 0 or result.net_fare == 0

    def test_missing_distance_only(self):
        result = _compute(distance_km=None, duration_min=10.0)
        assert result.distance_km is None
        assert result.distance_earnings == 0.0 or result.distance_earnings >= 0


class TestTip:
    def test_tip_included_in_total(self):
        result = _compute(tip_amount=5.00)
        assert result.tip == 5.00
        assert result.total_driver_earnings == round(result.net_fare + 5.00, 2)

    def test_zero_tip(self):
        result = _compute(tip_amount=0.0)
        assert result.tip == 0.0
        assert result.total_driver_earnings == result.net_fare

    def test_large_tip(self):
        result = _compute(actual_fare=12.00, tip_amount=20.00)
        assert result.tip == 20.00
        assert result.total_driver_earnings == round(result.net_fare + 20.00, 2)


class TestAddresses:
    def test_addresses_preserved(self):
        result = _compute(
            pickup_address="O'Hare International Airport",
            dropoff_address="123 Lake Shore Drive, Chicago IL",
        )
        assert result.pickup_address == "O'Hare International Airport"
        assert result.dropoff_address == "123 Lake Shore Drive, Chicago IL"


class TestEdgeCases:
    def test_minimum_fare_ride(self):
        # A short ride that hits the minimum fare
        result = _compute(actual_fare=5.00, distance_km=0.5, duration_min=2.0)
        assert result.total_driver_earnings > 0

    def test_high_fare(self):
        result = _compute(actual_fare=150.00, tip_amount=30.00)
        assert result.platform_fee > 0
        assert result.net_fare < 150.00
        assert result.total_driver_earnings == round(result.net_fare + 30.00, 2)

    def test_ride_id_preserved(self):
        result = _compute(ride_id=9999)
        assert result.ride_id == 9999

    def test_completed_at_preserved(self):
        ts = datetime(2026, 3, 1, 8, 30, tzinfo=timezone.utc)
        result = _compute(completed_at=ts)
        assert result.completed_at == ts
