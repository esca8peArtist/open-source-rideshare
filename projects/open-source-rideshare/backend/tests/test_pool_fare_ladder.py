"""Tests for the pool fare ladder feature.

Covers:
- get_pool_fare_ladder:     tier count, ordering, solo tier, pool tiers,
                            fare math, discount math, savings math,
                            recommended_tier, distance/duration fields,
                            max_pool_wait_minutes, short-trip recommendation
- _build_recommendation:   short trip (<$8), two tiers, three tiers,
                            no pool tiers edge case
- GET /pricing/pool-fare-ladder endpoint:
                            valid request -> 200, response shape, tier count,
                            no auth required, solo tier is_solo flag,
                            bad lat/lon -> 422, missing required params -> 422,
                            lat out of range -> 422, lng out of range -> 422
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.pool_fare_ladder import FareTier, PoolFareLadderResponse
from app.services.pool_fare_ladder import _build_recommendation, get_pool_fare_ladder
from app.services.pool_matching import DISCOUNT_BY_RIDERS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PICKUP = (37.7749, -122.4194)
_DROPOFF = (37.7849, -122.4094)   # ~1.2 km away — short trip
_LONG_DROPOFF = (37.8800, -122.4094)  # ~12 km away — longer trip

client = TestClient(app)


def _ladder(pickup=_PICKUP, dropoff=_DROPOFF):
    return get_pool_fare_ladder(pickup[0], pickup[1], dropoff[0], dropoff[1])


# ---------------------------------------------------------------------------
# get_pool_fare_ladder — service unit tests
# ---------------------------------------------------------------------------


class TestGetPoolFareLadder:
    def test_returns_response_type(self):
        result = _ladder()
        assert isinstance(result, PoolFareLadderResponse)

    def test_tier_count_matches_discount_by_riders(self):
        result = _ladder()
        assert len(result.tiers) == len(DISCOUNT_BY_RIDERS)

    def test_tiers_ordered_by_riders_ascending(self):
        result = _ladder()
        rider_counts = [t.riders for t in result.tiers]
        assert rider_counts == sorted(rider_counts)

    def test_first_tier_is_solo(self):
        result = _ladder()
        assert result.tiers[0].is_solo is True
        assert result.tiers[0].riders == 1

    def test_pool_tiers_are_not_solo(self):
        result = _ladder()
        for tier in result.tiers[1:]:
            assert tier.is_solo is False

    def test_solo_tier_label(self):
        result = _ladder()
        assert result.tiers[0].label == "Solo"

    def test_pool_tier_labels(self):
        result = _ladder()
        for tier in result.tiers[1:]:
            assert tier.label == f"{tier.riders} riders"

    def test_solo_discount_is_zero(self):
        result = _ladder()
        solo = result.tiers[0]
        assert solo.discount_percent == pytest.approx(0.0)

    def test_solo_savings_is_zero(self):
        result = _ladder()
        solo = result.tiers[0]
        assert solo.savings == pytest.approx(0.0)

    def test_pool_tiers_have_positive_discount(self):
        result = _ladder(dropoff=_LONG_DROPOFF)
        for tier in result.tiers[1:]:
            assert tier.discount_percent > 0

    def test_pool_tiers_have_positive_savings(self):
        result = _ladder(dropoff=_LONG_DROPOFF)
        for tier in result.tiers[1:]:
            assert tier.savings > 0

    def test_pool_fare_less_than_solo_fare(self):
        result = _ladder(dropoff=_LONG_DROPOFF)
        solo_fare = result.tiers[0].fare
        for tier in result.tiers[1:]:
            assert tier.fare < solo_fare

    def test_more_riders_means_lower_fare(self):
        result = _ladder(dropoff=_LONG_DROPOFF)
        pool_fares = [t.fare for t in result.tiers[1:]]
        assert pool_fares == sorted(pool_fares, reverse=True)  # fares decrease as rider count grows

    def test_discount_matches_discount_by_riders(self):
        result = _ladder()
        for tier in result.tiers:
            expected = DISCOUNT_BY_RIDERS[tier.riders]
            assert tier.discount_percent == pytest.approx(expected)

    def test_savings_equals_solo_minus_pool(self):
        result = _ladder(dropoff=_LONG_DROPOFF)
        solo_fare = result.tiers[0].fare
        for tier in result.tiers[1:]:
            expected_savings = round(solo_fare - tier.fare, 2)
            assert tier.savings == pytest.approx(expected_savings, abs=0.02)

    def test_recommended_tier_is_not_solo(self):
        result = _ladder(dropoff=_LONG_DROPOFF)
        assert result.recommended_tier != 1

    def test_recommended_tier_in_discount_by_riders(self):
        result = _ladder()
        assert result.recommended_tier in DISCOUNT_BY_RIDERS

    def test_distance_km_positive(self):
        result = _ladder()
        assert result.distance_km > 0

    def test_estimated_duration_min_positive(self):
        result = _ladder()
        assert result.estimated_duration_min > 0

    def test_max_pool_wait_minutes_positive(self):
        result = _ladder()
        assert result.max_pool_wait_minutes > 0

    def test_coordinates_echoed_back(self):
        result = _ladder(_PICKUP, _LONG_DROPOFF)
        assert result.pickup_lat == pytest.approx(_PICKUP[0])
        assert result.pickup_lng == pytest.approx(_PICKUP[1])
        assert result.dropoff_lat == pytest.approx(_LONG_DROPOFF[0])
        assert result.dropoff_lng == pytest.approx(_LONG_DROPOFF[1])

    def test_recommendation_is_string(self):
        result = _ladder()
        assert isinstance(result.recommendation, str)
        assert len(result.recommendation) > 0

    def test_same_origin_destination_zero_distance(self):
        result = get_pool_fare_ladder(37.7749, -122.4194, 37.7749, -122.4194)
        assert result.distance_km == pytest.approx(0.0, abs=0.01)


# ---------------------------------------------------------------------------
# _build_recommendation — pure unit tests
# ---------------------------------------------------------------------------


def _make_tier(riders: int, fare: float, discount: float, savings: float, is_solo: bool) -> FareTier:
    return FareTier(
        riders=riders,
        label="Solo" if is_solo else f"{riders} riders",
        fare=fare,
        discount_percent=discount,
        savings=savings,
        is_solo=is_solo,
    )


class TestBuildRecommendation:
    def test_no_tiers_returns_unavailable(self):
        assert _build_recommendation([]) == "Pool fare data unavailable."

    def test_only_solo_returns_unavailable(self):
        solo = _make_tier(1, 5.0, 0.0, 0.0, True)
        assert _build_recommendation([solo]) == "Pool fare data unavailable."

    def test_short_trip_mentions_savings(self):
        solo = _make_tier(1, 6.0, 0.0, 0.0, True)
        pool2 = _make_tier(2, 4.5, 25.0, 1.5, False)
        pool3 = _make_tier(3, 3.9, 35.0, 2.1, False)
        rec = _build_recommendation([solo, pool2, pool3])
        assert "$2.10" in rec or "2.10" in rec
        assert "35" in rec

    def test_long_trip_two_tiers_mentions_wait(self):
        solo = _make_tier(1, 20.0, 0.0, 0.0, True)
        pool2 = _make_tier(2, 15.0, 25.0, 5.0, False)
        rec = _build_recommendation([solo, pool2])
        assert "5.00" in rec or "$5.00" in rec
        assert "25" in rec

    def test_long_trip_three_tiers_mentions_max_savings(self):
        solo = _make_tier(1, 20.0, 0.0, 0.0, True)
        pool2 = _make_tier(2, 15.0, 25.0, 5.0, False)
        pool3 = _make_tier(3, 13.0, 35.0, 7.0, False)
        rec = _build_recommendation([solo, pool2, pool3])
        assert "7.00" in rec or "$7.00" in rec
        assert "35" in rec

    def test_recommendation_is_non_empty_string(self):
        solo = _make_tier(1, 15.0, 0.0, 0.0, True)
        pool = _make_tier(2, 11.25, 25.0, 3.75, False)
        rec = _build_recommendation([solo, pool])
        assert isinstance(rec, str)
        assert len(rec) > 10


# ---------------------------------------------------------------------------
# GET /pricing/pool-fare-ladder — endpoint integration tests
# ---------------------------------------------------------------------------


VALID_PARAMS = {
    "pickup_lat": 37.7749,
    "pickup_lng": -122.4194,
    "dropoff_lat": 37.8800,
    "dropoff_lng": -122.4094,
}


class TestPoolFareLadderEndpoint:
    def test_valid_request_returns_200(self):
        resp = client.get("/api/v1/pricing/pool-fare-ladder", params=VALID_PARAMS)
        assert resp.status_code == 200

    def test_response_has_tiers(self):
        resp = client.get("/api/v1/pricing/pool-fare-ladder", params=VALID_PARAMS)
        data = resp.json()
        assert "tiers" in data
        assert len(data["tiers"]) == len(DISCOUNT_BY_RIDERS)

    def test_response_has_recommendation(self):
        resp = client.get("/api/v1/pricing/pool-fare-ladder", params=VALID_PARAMS)
        data = resp.json()
        assert "recommendation" in data
        assert len(data["recommendation"]) > 0

    def test_response_has_coordinates(self):
        resp = client.get("/api/v1/pricing/pool-fare-ladder", params=VALID_PARAMS)
        data = resp.json()
        assert data["pickup_lat"] == pytest.approx(37.7749)
        assert data["pickup_lng"] == pytest.approx(-122.4194)

    def test_response_has_distance(self):
        resp = client.get("/api/v1/pricing/pool-fare-ladder", params=VALID_PARAMS)
        data = resp.json()
        assert data["distance_km"] > 0

    def test_response_has_recommended_tier(self):
        resp = client.get("/api/v1/pricing/pool-fare-ladder", params=VALID_PARAMS)
        data = resp.json()
        assert "recommended_tier" in data
        assert isinstance(data["recommended_tier"], int)

    def test_response_has_max_pool_wait_minutes(self):
        resp = client.get("/api/v1/pricing/pool-fare-ladder", params=VALID_PARAMS)
        data = resp.json()
        assert data["max_pool_wait_minutes"] > 0

    def test_no_auth_required(self):
        resp = client.get("/api/v1/pricing/pool-fare-ladder", params=VALID_PARAMS)
        assert resp.status_code != 401
        assert resp.status_code != 403

    def test_solo_tier_is_first(self):
        resp = client.get("/api/v1/pricing/pool-fare-ladder", params=VALID_PARAMS)
        tiers = resp.json()["tiers"]
        assert tiers[0]["is_solo"] is True
        assert tiers[0]["riders"] == 1

    def test_pool_tiers_not_solo(self):
        resp = client.get("/api/v1/pricing/pool-fare-ladder", params=VALID_PARAMS)
        tiers = resp.json()["tiers"]
        for tier in tiers[1:]:
            assert tier["is_solo"] is False

    def test_pool_fares_less_than_solo(self):
        resp = client.get("/api/v1/pricing/pool-fare-ladder", params=VALID_PARAMS)
        tiers = resp.json()["tiers"]
        solo_fare = tiers[0]["fare"]
        for tier in tiers[1:]:
            assert tier["fare"] < solo_fare

    def test_missing_pickup_lat_returns_422(self):
        params = {k: v for k, v in VALID_PARAMS.items() if k != "pickup_lat"}
        resp = client.get("/api/v1/pricing/pool-fare-ladder", params=params)
        assert resp.status_code == 422

    def test_missing_pickup_lng_returns_422(self):
        params = {k: v for k, v in VALID_PARAMS.items() if k != "pickup_lng"}
        resp = client.get("/api/v1/pricing/pool-fare-ladder", params=params)
        assert resp.status_code == 422

    def test_missing_dropoff_lat_returns_422(self):
        params = {k: v for k, v in VALID_PARAMS.items() if k != "dropoff_lat"}
        resp = client.get("/api/v1/pricing/pool-fare-ladder", params=params)
        assert resp.status_code == 422

    def test_missing_dropoff_lng_returns_422(self):
        params = {k: v for k, v in VALID_PARAMS.items() if k != "dropoff_lng"}
        resp = client.get("/api/v1/pricing/pool-fare-ladder", params=params)
        assert resp.status_code == 422

    def test_pickup_lat_too_high_returns_422(self):
        resp = client.get("/api/v1/pricing/pool-fare-ladder", params={
            **VALID_PARAMS, "pickup_lat": 91.0,
        })
        assert resp.status_code == 422

    def test_pickup_lat_too_low_returns_422(self):
        resp = client.get("/api/v1/pricing/pool-fare-ladder", params={
            **VALID_PARAMS, "pickup_lat": -91.0,
        })
        assert resp.status_code == 422

    def test_pickup_lng_too_high_returns_422(self):
        resp = client.get("/api/v1/pricing/pool-fare-ladder", params={
            **VALID_PARAMS, "pickup_lng": 181.0,
        })
        assert resp.status_code == 422

    def test_pickup_lng_too_low_returns_422(self):
        resp = client.get("/api/v1/pricing/pool-fare-ladder", params={
            **VALID_PARAMS, "pickup_lng": -181.0,
        })
        assert resp.status_code == 422

    def test_dropoff_lat_too_high_returns_422(self):
        resp = client.get("/api/v1/pricing/pool-fare-ladder", params={
            **VALID_PARAMS, "dropoff_lat": 91.0,
        })
        assert resp.status_code == 422

    def test_dropoff_lng_too_low_returns_422(self):
        resp = client.get("/api/v1/pricing/pool-fare-ladder", params={
            **VALID_PARAMS, "dropoff_lng": -181.0,
        })
        assert resp.status_code == 422

    def test_savings_are_non_negative(self):
        resp = client.get("/api/v1/pricing/pool-fare-ladder", params=VALID_PARAMS)
        tiers = resp.json()["tiers"]
        for tier in tiers:
            assert tier["savings"] >= 0

    def test_discounts_non_negative(self):
        resp = client.get("/api/v1/pricing/pool-fare-ladder", params=VALID_PARAMS)
        tiers = resp.json()["tiers"]
        for tier in tiers:
            assert tier["discount_percent"] >= 0

    def test_same_origin_destination(self):
        resp = client.get("/api/v1/pricing/pool-fare-ladder", params={
            "pickup_lat": 37.7749,
            "pickup_lng": -122.4194,
            "dropoff_lat": 37.7749,
            "dropoff_lng": -122.4194,
        })
        assert resp.status_code == 200

    def test_international_coordinates(self):
        resp = client.get("/api/v1/pricing/pool-fare-ladder", params={
            "pickup_lat": 51.5074,
            "pickup_lng": -0.1278,
            "dropoff_lat": 51.5200,
            "dropoff_lng": -0.1000,
        })
        assert resp.status_code == 200

    def test_tiers_ordered_ascending_by_riders(self):
        resp = client.get("/api/v1/pricing/pool-fare-ladder", params=VALID_PARAMS)
        tiers = resp.json()["tiers"]
        rider_counts = [t["riders"] for t in tiers]
        assert rider_counts == sorted(rider_counts)
