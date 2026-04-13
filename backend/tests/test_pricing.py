from datetime import datetime, timezone

import pytest

from app.services.pricing import (
    FareBreakdown,
    calculate_fare,
    calculate_fare_breakdown,
    get_pricing_params,
    get_time_multipliers,
    set_pricing_overrides,
    set_time_multipliers,
    _pricing_overrides,
    _time_multipliers,
)


@pytest.fixture(autouse=True)
def _reset_pricing_state():
    """Reset all runtime pricing state between tests."""
    _pricing_overrides.clear()
    _time_multipliers.clear()
    yield
    _pricing_overrides.clear()
    _time_multipliers.clear()


# --- Basic fare calculation (backward compat) ---

def test_calculate_fare_basic():
    fare = calculate_fare(distance_km=10.0, duration_min=15.0)
    # 2.50 + (10 * 1.50) + (15 * 0.25) = 2.50 + 15.00 + 3.75 = 21.25
    assert fare == 21.25


def test_calculate_fare_minimum():
    fare = calculate_fare(distance_km=0.5, duration_min=2.0)
    # 2.50 + 0.75 + 0.50 = 3.75 → below minimum of 5.00
    assert fare == 5.00


def test_calculate_fare_zero_distance():
    fare = calculate_fare(distance_km=0.0, duration_min=0.0)
    # 2.50 + 0 + 0 = 2.50 → below minimum
    assert fare == 5.00


def test_calculate_fare_long_trip():
    fare = calculate_fare(distance_km=30.0, duration_min=45.0)
    # 2.50 + 45.00 + 11.25 = 58.75
    assert fare == 58.75


# --- Fare breakdown ---

def test_breakdown_returns_dataclass():
    bd = calculate_fare_breakdown(10.0, 15.0)
    assert isinstance(bd, FareBreakdown)
    assert bd.base == 2.50
    assert bd.distance == 15.00
    assert bd.time == 3.75
    assert bd.multiplier == 1.0
    assert bd.multiplier_label is None
    assert bd.subtotal == 21.25
    assert bd.platform_fee == 0.0
    assert bd.total == 21.25


def test_breakdown_minimum_fare():
    bd = calculate_fare_breakdown(0.0, 0.0)
    assert bd.subtotal == 5.00
    assert bd.total == 5.00


def test_breakdown_matches_calculate_fare():
    for dist, dur in [(5, 10), (15, 20), (0.1, 1), (50, 60)]:
        bd = calculate_fare_breakdown(dist, dur)
        assert bd.total == calculate_fare(dist, dur)


# --- Time-of-day multipliers ---

def test_no_multiplier_by_default():
    bd = calculate_fare_breakdown(10.0, 15.0, at_time=datetime(2026, 1, 1, 23, 0, tzinfo=timezone.utc))
    assert bd.multiplier == 1.0
    assert bd.multiplier_label is None


def test_same_day_multiplier():
    set_time_multipliers([{"start_hour": 7, "end_hour": 9, "multiplier": 1.15, "label": "Morning rush"}])
    # 8 AM — inside the window
    bd = calculate_fare_breakdown(10.0, 15.0, at_time=datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc))
    assert bd.multiplier == 1.15
    assert bd.multiplier_label == "Morning rush"
    # base fare components: (2.50 + 15.00 + 3.75) * 1.15 = 24.4375 → 24.44
    assert bd.subtotal == 24.44


def test_same_day_multiplier_outside_window():
    set_time_multipliers([{"start_hour": 7, "end_hour": 9, "multiplier": 1.15, "label": "Morning rush"}])
    bd = calculate_fare_breakdown(10.0, 15.0, at_time=datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc))
    assert bd.multiplier == 1.0
    assert bd.multiplier_label is None


def test_cross_midnight_multiplier_before_midnight():
    set_time_multipliers([{"start_hour": 22, "end_hour": 6, "multiplier": 1.25, "label": "Late night"}])
    bd = calculate_fare_breakdown(10.0, 15.0, at_time=datetime(2026, 1, 1, 23, 30, tzinfo=timezone.utc))
    assert bd.multiplier == 1.25
    assert bd.multiplier_label == "Late night"


def test_cross_midnight_multiplier_after_midnight():
    set_time_multipliers([{"start_hour": 22, "end_hour": 6, "multiplier": 1.25, "label": "Late night"}])
    bd = calculate_fare_breakdown(10.0, 15.0, at_time=datetime(2026, 1, 2, 3, 0, tzinfo=timezone.utc))
    assert bd.multiplier == 1.25


def test_cross_midnight_multiplier_outside_window():
    set_time_multipliers([{"start_hour": 22, "end_hour": 6, "multiplier": 1.25, "label": "Late night"}])
    bd = calculate_fare_breakdown(10.0, 15.0, at_time=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc))
    assert bd.multiplier == 1.0


def test_multiple_multipliers_first_match_wins():
    set_time_multipliers([
        {"start_hour": 7, "end_hour": 9, "multiplier": 1.15, "label": "Morning rush"},
        {"start_hour": 17, "end_hour": 19, "multiplier": 1.2, "label": "Evening rush"},
    ])
    bd = calculate_fare_breakdown(10.0, 10.0, at_time=datetime(2026, 1, 1, 18, 0, tzinfo=timezone.utc))
    assert bd.multiplier == 1.2
    assert bd.multiplier_label == "Evening rush"


def test_minimum_fare_with_multiplier():
    """Multiplier applies before minimum fare check."""
    set_time_multipliers([{"start_hour": 0, "end_hour": 24, "multiplier": 0.5, "label": "Promo"}])
    bd = calculate_fare_breakdown(0.5, 2.0, at_time=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc))
    # (2.50 + 0.75 + 0.50) * 0.5 = 1.875 → below minimum of 5.00
    assert bd.subtotal == 5.00


def test_get_time_multipliers():
    set_time_multipliers([{"start_hour": 22, "end_hour": 6, "multiplier": 1.25, "label": "Late night"}])
    result = get_time_multipliers()
    assert len(result) == 1
    assert result[0]["start_hour"] == 22
    assert result[0]["multiplier"] == 1.25


def test_set_time_multipliers_replaces():
    set_time_multipliers([{"start_hour": 7, "end_hour": 9, "multiplier": 1.15, "label": "A"}])
    set_time_multipliers([{"start_hour": 17, "end_hour": 19, "multiplier": 1.2, "label": "B"}])
    result = get_time_multipliers()
    assert len(result) == 1
    assert result[0]["label"] == "B"


# --- Pricing overrides (admin-configurable) ---

def test_default_pricing_params():
    params = get_pricing_params()
    assert params["base_fare"] == 2.50
    assert params["per_km_rate"] == 1.50
    assert params["per_minute_rate"] == 0.25
    assert params["minimum_fare"] == 5.00
    assert params["platform_fee_percent"] == 0.0


def test_pricing_override_base_fare():
    set_pricing_overrides({"base_fare": 3.00})
    bd = calculate_fare_breakdown(10.0, 15.0)
    assert bd.base == 3.00
    # 3.00 + 15.00 + 3.75 = 21.75
    assert bd.total == 21.75


def test_pricing_override_per_km_rate():
    set_pricing_overrides({"per_km_rate": 2.00})
    bd = calculate_fare_breakdown(10.0, 15.0)
    assert bd.distance == 20.00


def test_pricing_override_minimum_fare():
    set_pricing_overrides({"minimum_fare": 10.00})
    bd = calculate_fare_breakdown(0.0, 0.0)
    assert bd.subtotal == 10.00
    assert bd.total == 10.00


def test_pricing_override_platform_fee():
    set_pricing_overrides({"platform_fee_percent": 5.0})
    bd = calculate_fare_breakdown(10.0, 15.0)
    # subtotal = 21.25, fee = 21.25 * 0.05 = 1.0625 → 1.06
    assert bd.platform_fee == 1.06
    assert bd.total == 22.31


def test_multiple_overrides():
    set_pricing_overrides({"base_fare": 5.00, "per_km_rate": 2.00, "platform_fee_percent": 10.0})
    bd = calculate_fare_breakdown(10.0, 10.0)
    # 5.00 + 20.00 + 2.50 = 27.50
    assert bd.subtotal == 27.50
    # fee = 27.50 * 0.10 = 2.75
    assert bd.platform_fee == 2.75
    assert bd.total == 30.25


# --- Combined: overrides + multipliers ---

def test_override_and_multiplier_combined():
    set_pricing_overrides({"base_fare": 3.00, "platform_fee_percent": 5.0})
    set_time_multipliers([{"start_hour": 22, "end_hour": 6, "multiplier": 1.25, "label": "Late night"}])
    bd = calculate_fare_breakdown(10.0, 15.0, at_time=datetime(2026, 1, 1, 23, 0, tzinfo=timezone.utc))
    # (3.00 + 15.00 + 3.75) * 1.25 = 27.1875 → 27.19
    assert bd.subtotal == 27.19
    # fee = 27.19 * 0.05 = 1.3595 → 1.36
    assert bd.platform_fee == 1.36
    assert bd.total == 28.55


# --- Edge cases ---

def test_very_short_trip():
    bd = calculate_fare_breakdown(0.1, 1.0)
    # 2.50 + 0.15 + 0.25 = 2.90 → below minimum
    assert bd.subtotal == 5.00


def test_very_long_trip():
    bd = calculate_fare_breakdown(100.0, 120.0)
    # 2.50 + 150.00 + 30.00 = 182.50
    assert bd.total == 182.50


def test_fractional_distance_and_time():
    bd = calculate_fare_breakdown(3.7, 8.3)
    # 2.50 + 5.55 + 2.075 = 10.125 → base=2.50, dist=5.55, time=2.08
    assert bd.base == 2.50
    assert bd.distance == 5.55
    assert bd.time == 2.08
    # subtotal rounds: (2.50 + 5.55 + 2.075) * 1.0 = 10.125 → 10.12 (round)
    assert bd.subtotal == 10.12
