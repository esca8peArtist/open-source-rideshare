"""Tests for ride pooling: models, schemas, matching service, and fare calculation."""

from datetime import datetime, timezone

import pytest

from app.models.pool import LegStatus, PoolLeg, PoolStatus, RidePool
from app.schemas.pool import (
    PoolEstimateRequest,
    PoolEstimateResponse,
    PoolLegResponse,
    PoolLegStatusUpdate,
    PoolResponse,
    PoolRideRequest,
    PoolRideResponse,
    PoolSearchResult,
)
from app.services.pool_matching import (
    DISCOUNT_BY_RIDERS,
    MAX_DETOUR_PERCENT,
    POOL_SEARCH_RADIUS_KM,
    _direction_similarity,
    _direction_vector,
    _haversine_km,
    calculate_pool_fare,
)


# ---- Haversine Distance Tests ----


class TestHaversine:
    def test_same_point_returns_zero(self):
        assert _haversine_km(40.0, -74.0, 40.0, -74.0) == 0.0

    def test_known_distance_nyc_to_la(self):
        # NYC (40.7128, -74.0060) to LA (34.0522, -118.2437) ~ 3,944 km
        dist = _haversine_km(40.7128, -74.0060, 34.0522, -118.2437)
        assert 3900 < dist < 4000

    def test_short_distance(self):
        # Two points about 1 km apart
        dist = _haversine_km(40.7128, -74.0060, 40.7218, -74.0060)
        assert 0.9 < dist < 1.1

    def test_symmetry(self):
        d1 = _haversine_km(40.0, -74.0, 41.0, -75.0)
        d2 = _haversine_km(41.0, -75.0, 40.0, -74.0)
        assert abs(d1 - d2) < 0.001


# ---- Direction Vector Tests ----


class TestDirectionVector:
    def test_northward(self):
        dx, dy = _direction_vector(40.0, -74.0, 41.0, -74.0)
        assert dx == pytest.approx(0.0, abs=0.01)
        assert dy == pytest.approx(1.0, abs=0.01)

    def test_eastward(self):
        dx, dy = _direction_vector(40.0, -74.0, 40.0, -73.0)
        assert dx == pytest.approx(1.0, abs=0.01)
        assert dy == pytest.approx(0.0, abs=0.01)

    def test_same_point_returns_zero(self):
        dx, dy = _direction_vector(40.0, -74.0, 40.0, -74.0)
        assert dx == 0.0
        assert dy == 0.0

    def test_normalized(self):
        dx, dy = _direction_vector(40.0, -74.0, 41.0, -73.0)
        import math
        mag = math.sqrt(dx * dx + dy * dy)
        assert mag == pytest.approx(1.0, abs=0.001)


# ---- Direction Similarity Tests ----


class TestDirectionSimilarity:
    def test_same_direction(self):
        v = (1.0, 0.0)
        assert _direction_similarity(v, v) == pytest.approx(1.0)

    def test_opposite_direction(self):
        v1 = (1.0, 0.0)
        v2 = (-1.0, 0.0)
        assert _direction_similarity(v1, v2) == pytest.approx(-1.0)

    def test_perpendicular(self):
        v1 = (1.0, 0.0)
        v2 = (0.0, 1.0)
        assert _direction_similarity(v1, v2) == pytest.approx(0.0)

    def test_similar_direction(self):
        # ~45 degree angle, cos(45) ≈ 0.707
        import math
        v1 = (1.0, 0.0)
        v2 = (math.cos(math.radians(45)), math.sin(math.radians(45)))
        sim = _direction_similarity(v1, v2)
        assert 0.7 < sim < 0.72


# ---- Pool Fare Calculation Tests ----


class TestPoolFareCalculation:
    def test_no_discount(self):
        solo, pool, savings = calculate_pool_fare(10.0, 15.0, 0.0)
        assert pool == solo
        assert savings == 0.0

    def test_two_rider_discount(self):
        solo, pool, savings = calculate_pool_fare(10.0, 15.0, 25.0)
        assert pool == pytest.approx(solo * 0.75, abs=0.01)
        assert savings == pytest.approx(solo * 0.25, abs=0.01)
        assert solo == pool + savings

    def test_three_rider_discount(self):
        solo, pool, savings = calculate_pool_fare(10.0, 15.0, 35.0)
        assert pool == pytest.approx(solo * 0.65, abs=0.01)
        assert savings == pytest.approx(solo * 0.35, abs=0.01)

    def test_short_ride(self):
        solo, pool, savings = calculate_pool_fare(1.0, 3.0, 25.0)
        assert pool < solo
        assert pool > 0
        assert savings > 0

    def test_long_ride(self):
        solo, pool, savings = calculate_pool_fare(50.0, 60.0, 25.0)
        assert pool < solo
        assert savings > 0


# ---- Discount Tier Tests ----


class TestDiscountTiers:
    def test_solo_no_discount(self):
        assert DISCOUNT_BY_RIDERS[1] == 0.0

    def test_two_riders_25_percent(self):
        assert DISCOUNT_BY_RIDERS[2] == 25.0

    def test_three_riders_35_percent(self):
        assert DISCOUNT_BY_RIDERS[3] == 35.0


# ---- Configuration Constants Tests ----


class TestPoolConstants:
    def test_max_detour_positive(self):
        assert MAX_DETOUR_PERCENT > 0

    def test_search_radius_positive(self):
        assert POOL_SEARCH_RADIUS_KM > 0


# ---- Schema Tests ----


class TestPoolRideRequest:
    def test_valid_request(self):
        req = PoolRideRequest(
            pickup={"lat": 40.7128, "lng": -74.0060},
            dropoff={"lat": 40.7580, "lng": -73.9855},
            pickup_address="123 Main St",
            dropoff_address="Times Square",
        )
        assert req.pickup.lat == 40.7128
        assert req.dropoff_address == "Times Square"

    def test_missing_address_raises(self):
        with pytest.raises(Exception):
            PoolRideRequest(
                pickup={"lat": 40.7128, "lng": -74.0060},
                dropoff={"lat": 40.7580, "lng": -73.9855},
                # missing addresses
            )


class TestPoolEstimateRequest:
    def test_valid_estimate(self):
        req = PoolEstimateRequest(
            pickup={"lat": 40.7128, "lng": -74.0060},
            dropoff={"lat": 40.7580, "lng": -73.9855},
        )
        assert req.promo_code is None

    def test_with_promo(self):
        req = PoolEstimateRequest(
            pickup={"lat": 40.7128, "lng": -74.0060},
            dropoff={"lat": 40.7580, "lng": -73.9855},
            promo_code="POOL10",
        )
        assert req.promo_code == "POOL10"


class TestPoolEstimateResponse:
    def test_full_response(self):
        resp = PoolEstimateResponse(
            solo_fare=20.0,
            pool_fare=15.0,
            discount_percent=25.0,
            savings=5.0,
            distance_km=8.5,
            duration_min=22.0,
        )
        assert resp.savings == 5.0
        assert resp.currency == "USD"

    def test_savings_math(self):
        resp = PoolEstimateResponse(
            solo_fare=20.0,
            pool_fare=15.0,
            discount_percent=25.0,
            savings=5.0,
            distance_km=8.5,
            duration_min=22.0,
        )
        assert resp.solo_fare - resp.pool_fare == resp.savings


class TestPoolRideResponse:
    def test_full_response(self):
        resp = PoolRideResponse(
            ride_id=1,
            pool_id=10,
            status="forming",
            estimated_fare=20.0,
            pool_fare=15.0,
            discount_percent=25.0,
            pickup_address="123 Main St",
            dropoff_address="456 Oak Ave",
            riders_in_pool=2,
            max_riders=3,
        )
        assert resp.pool_id == 10
        assert resp.riders_in_pool == 2
        assert resp.max_riders == 3

    def test_new_pool_single_rider(self):
        resp = PoolRideResponse(
            ride_id=1,
            pool_id=10,
            status="forming",
            estimated_fare=20.0,
            pool_fare=20.0,
            discount_percent=0.0,
            pickup_address="123 Main St",
            dropoff_address="456 Oak Ave",
            riders_in_pool=1,
            max_riders=3,
        )
        assert resp.riders_in_pool == 1
        assert resp.discount_percent == 0.0


class TestPoolResponse:
    def test_empty_pool(self):
        resp = PoolResponse(
            id=1,
            status="forming",
            max_riders=3,
            current_riders=0,
            legs=[],
            created_at=datetime.now(timezone.utc),
        )
        assert resp.current_riders == 0
        assert resp.legs == []

    def test_pool_with_legs(self):
        now = datetime.now(timezone.utc)
        leg = PoolLegResponse(
            id=1,
            ride_id=10,
            pickup_address="A St",
            dropoff_address="B St",
            pickup_order=1,
            dropoff_order=1,
            fare_discount_percent=25.0,
            status="waiting_pickup",
        )
        resp = PoolResponse(
            id=1,
            status="matched",
            max_riders=3,
            current_riders=2,
            legs=[leg],
            created_at=now,
            matched_at=now,
        )
        assert resp.current_riders == 2
        assert len(resp.legs) == 1
        assert resp.legs[0].fare_discount_percent == 25.0


class TestPoolLegResponse:
    def test_waiting_leg(self):
        leg = PoolLegResponse(
            id=1,
            ride_id=10,
            pickup_address="Start",
            dropoff_address="End",
            pickup_order=1,
            dropoff_order=1,
            fare_discount_percent=25.0,
            status="waiting_pickup",
        )
        assert leg.status == "waiting_pickup"
        assert leg.picked_up_at is None

    def test_completed_leg(self):
        now = datetime.now(timezone.utc)
        leg = PoolLegResponse(
            id=1,
            ride_id=10,
            pickup_address="Start",
            dropoff_address="End",
            pickup_order=1,
            dropoff_order=2,
            fare_discount_percent=35.0,
            status="dropped_off",
            picked_up_at=now,
            dropped_off_at=now,
        )
        assert leg.status == "dropped_off"
        assert leg.picked_up_at is not None


class TestPoolLegStatusUpdate:
    def test_valid(self):
        update = PoolLegStatusUpdate(leg_id=42)
        assert update.leg_id == 42


class TestPoolSearchResult:
    def test_good_match(self):
        result = PoolSearchResult(
            pool_id=1,
            current_riders=1,
            detour_km=0.5,
            detour_percent=5.0,
            discount_percent=25.0,
            estimated_pool_fare=15.0,
        )
        assert result.detour_percent < MAX_DETOUR_PERCENT
        assert result.discount_percent == 25.0

    def test_near_limit_detour(self):
        result = PoolSearchResult(
            pool_id=1,
            current_riders=2,
            detour_km=3.8,
            detour_percent=38.0,
            discount_percent=35.0,
            estimated_pool_fare=13.0,
        )
        assert result.detour_percent < MAX_DETOUR_PERCENT


# ---- Model Enum Tests ----


class TestPoolStatus:
    def test_all_statuses(self):
        assert PoolStatus.FORMING == "forming"
        assert PoolStatus.MATCHED == "matched"
        assert PoolStatus.IN_PROGRESS == "in_progress"
        assert PoolStatus.COMPLETED == "completed"
        assert PoolStatus.CANCELLED == "cancelled"

    def test_status_count(self):
        assert len(PoolStatus) == 5


class TestLegStatus:
    def test_all_statuses(self):
        assert LegStatus.WAITING_PICKUP == "waiting_pickup"
        assert LegStatus.PICKED_UP == "picked_up"
        assert LegStatus.DROPPED_OFF == "dropped_off"
        assert LegStatus.CANCELLED == "cancelled"

    def test_status_count(self):
        assert len(LegStatus) == 4


# ---- Edge Case Tests ----


class TestPoolEdgeCases:
    def test_haversine_antipodal_points(self):
        # Roughly half the earth's circumference
        dist = _haversine_km(0.0, 0.0, 0.0, 180.0)
        assert 20000 < dist < 20100

    def test_direction_vector_very_close_points(self):
        # Points ~1 meter apart
        dx, dy = _direction_vector(40.0, -74.0, 40.000009, -74.0)
        assert dy > 0  # Moving north

    def test_pool_fare_zero_distance(self):
        solo, pool, savings = calculate_pool_fare(0.0, 0.0, 25.0)
        # Should use minimum fare
        assert solo > 0
        assert pool < solo

    def test_pool_fare_100_percent_discount(self):
        solo, pool, savings = calculate_pool_fare(10.0, 15.0, 100.0)
        assert pool == 0.0
        assert savings == solo

    def test_opposite_directions_low_similarity(self):
        # Riders going in opposite directions should not match
        v1 = _direction_vector(40.7, -74.0, 40.8, -74.0)  # North
        v2 = _direction_vector(40.7, -74.0, 40.6, -74.0)  # South
        sim = _direction_similarity(v1, v2)
        assert sim < 0  # Negative similarity = opposite directions
