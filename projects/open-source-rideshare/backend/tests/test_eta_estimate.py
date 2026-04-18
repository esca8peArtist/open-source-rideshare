"""Tests for GET /rides/eta/estimate — public pre-booking ETA endpoint.

Covers (>= 10 cases):
1.  No drivers available → fallback pickup ETA 15, confidence "low", count 0
2.  1 driver available → confidence "medium"
3.  3+ drivers available → confidence "high", nearest selected correctly
4.  trip_duration minimum of 2 minutes enforced for very short trips
5.  pickup ETA rounds up (ceil) not floor
6.  nearest_driver_distance_km matches the actually closest driver
7.  All 4 coords required — missing pickup_lat → 422
8.  All 4 coords required — missing pickup_lng → 422
9.  All 4 coords required — missing dropoff_lat → 422
10. All 4 coords required — missing dropoff_lng → 422
11. Out-of-range latitude rejected → 422
12. Out-of-range longitude rejected → 422
13. No auth required — succeeds without Authorization header
14. Full response shape validation
"""

from __future__ import annotations

import math
from unittest.mock import AsyncMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

BASE_PARAMS = {
    "pickup_lat": 40.7128,
    "pickup_lng": -74.0060,
    "dropoff_lat": 40.7580,
    "dropoff_lng": -73.9855,
}

# Driver fixtures used across multiple tests.
# Distances from pickup (40.7128, -74.0060):
#   driver_close: ~1.2 km north
#   driver_medium: ~3.5 km north
#   driver_far: ~8.0 km north
_DRIVER_CLOSE = {"driver_id": 1, "distance_km": 1.2, "vehicle_type": "sedan"}
_DRIVER_MEDIUM = {"driver_id": 2, "distance_km": 3.5, "vehicle_type": "suv"}
_DRIVER_FAR = {"driver_id": 3, "distance_km": 8.0, "vehicle_type": "sedan"}


async def _get_client():
    """Return a test HTTP client with the FastAPI app and no-op DB override."""
    from httpx import ASGITransport, AsyncClient
    from app.main import app
    from app.db.database import get_db

    app.dependency_overrides[get_db] = lambda: AsyncMock()
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    return client, app


# ---------------------------------------------------------------------------
# 1. No drivers available — fallback ETA 15, confidence "low", count 0
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_no_drivers_returns_fallback_eta_and_low_confidence():
    with patch(
        "app.api.v1.eta_estimate.get_nearby_available_drivers_km",
        new=AsyncMock(return_value=[]),
    ):
        client, app = await _get_client()
        async with client:
            resp = await client.get("/api/v1/rides/eta/estimate", params=BASE_PARAMS)
    app.dependency_overrides.clear()

    assert resp.status_code == 200
    data = resp.json()
    assert data["pickup_eta_minutes"] == 15
    assert data["confidence"] == "low"
    assert data["available_driver_count"] == 0
    assert data["nearest_driver_distance_km"] is None


# ---------------------------------------------------------------------------
# 2. 1 driver available → confidence "medium"
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_one_driver_confidence_medium():
    with patch(
        "app.api.v1.eta_estimate.get_nearby_available_drivers_km",
        new=AsyncMock(return_value=[_DRIVER_CLOSE]),
    ):
        client, app = await _get_client()
        async with client:
            resp = await client.get("/api/v1/rides/eta/estimate", params=BASE_PARAMS)
    app.dependency_overrides.clear()

    assert resp.status_code == 200
    data = resp.json()
    assert data["confidence"] == "medium"
    assert data["available_driver_count"] == 1


# ---------------------------------------------------------------------------
# 3. 3+ drivers → confidence "high", nearest selected
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_three_drivers_confidence_high_nearest_selected():
    # Service returns drivers sorted by distance ascending (per service contract).
    drivers = [_DRIVER_CLOSE, _DRIVER_MEDIUM, _DRIVER_FAR]
    with patch(
        "app.api.v1.eta_estimate.get_nearby_available_drivers_km",
        new=AsyncMock(return_value=drivers),
    ):
        client, app = await _get_client()
        async with client:
            resp = await client.get("/api/v1/rides/eta/estimate", params=BASE_PARAMS)
    app.dependency_overrides.clear()

    assert resp.status_code == 200
    data = resp.json()
    assert data["confidence"] == "high"
    assert data["available_driver_count"] == 3
    # Nearest driver is _DRIVER_CLOSE at 1.2 km.
    assert data["nearest_driver_distance_km"] == pytest.approx(1.2)


# ---------------------------------------------------------------------------
# 4. trip_duration minimum 2 minutes
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_trip_duration_minimum_two_minutes():
    # Pickup and dropoff are essentially the same point → raw duration would be 0.
    identical_params = {
        "pickup_lat": 40.7128,
        "pickup_lng": -74.0060,
        "dropoff_lat": 40.7128,
        "dropoff_lng": -74.0060,
    }
    with patch(
        "app.api.v1.eta_estimate.get_nearby_available_drivers_km",
        new=AsyncMock(return_value=[_DRIVER_CLOSE]),
    ):
        client, app = await _get_client()
        async with client:
            resp = await client.get("/api/v1/rides/eta/estimate", params=identical_params)
    app.dependency_overrides.clear()

    assert resp.status_code == 200
    data = resp.json()
    assert data["trip_duration_minutes"] >= 2


# ---------------------------------------------------------------------------
# 5. Pickup ETA rounds up (ceil), not floor
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_pickup_eta_rounds_up():
    # 1.0 km at 30 km/h → 1/30 * 60 = 2.0 minutes exactly (ceil(2.0) = 2).
    # 0.5 km at 30 km/h → 0.5/30 * 60 = 1.0 minute (ceil(1.0) = 1).
    # Use a distance that produces a fractional minute to prove ceil.
    # 1.1 km at 30 km/h → 1.1/30*60 = 2.2 → ceil → 3.
    driver = {"driver_id": 10, "distance_km": 1.1, "vehicle_type": "sedan"}
    with patch(
        "app.api.v1.eta_estimate.get_nearby_available_drivers_km",
        new=AsyncMock(return_value=[driver]),
    ):
        client, app = await _get_client()
        async with client:
            resp = await client.get("/api/v1/rides/eta/estimate", params=BASE_PARAMS)
    app.dependency_overrides.clear()

    assert resp.status_code == 200
    data = resp.json()
    expected = math.ceil(1.1 / 30.0 * 60.0)
    assert data["pickup_eta_minutes"] == expected


# ---------------------------------------------------------------------------
# 6. nearest_driver_distance_km matches the closest driver
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_nearest_driver_distance_km_is_closest():
    # Two drivers; service returns them sorted ascending — first is closest.
    drivers = [
        {"driver_id": 5, "distance_km": 2.3, "vehicle_type": "sedan"},
        {"driver_id": 6, "distance_km": 7.8, "vehicle_type": "suv"},
    ]
    with patch(
        "app.api.v1.eta_estimate.get_nearby_available_drivers_km",
        new=AsyncMock(return_value=drivers),
    ):
        client, app = await _get_client()
        async with client:
            resp = await client.get("/api/v1/rides/eta/estimate", params=BASE_PARAMS)
    app.dependency_overrides.clear()

    assert resp.status_code == 200
    data = resp.json()
    assert data["nearest_driver_distance_km"] == pytest.approx(2.3)


# ---------------------------------------------------------------------------
# 7-10. All 4 coords required — each missing one returns 422
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_missing_pickup_lat_returns_422():
    params = {k: v for k, v in BASE_PARAMS.items() if k != "pickup_lat"}
    client, app = await _get_client()
    async with client:
        resp = await client.get("/api/v1/rides/eta/estimate", params=params)
    app.dependency_overrides.clear()
    assert resp.status_code == 422


@pytest.mark.anyio
async def test_missing_pickup_lng_returns_422():
    params = {k: v for k, v in BASE_PARAMS.items() if k != "pickup_lng"}
    client, app = await _get_client()
    async with client:
        resp = await client.get("/api/v1/rides/eta/estimate", params=params)
    app.dependency_overrides.clear()
    assert resp.status_code == 422


@pytest.mark.anyio
async def test_missing_dropoff_lat_returns_422():
    params = {k: v for k, v in BASE_PARAMS.items() if k != "dropoff_lat"}
    client, app = await _get_client()
    async with client:
        resp = await client.get("/api/v1/rides/eta/estimate", params=params)
    app.dependency_overrides.clear()
    assert resp.status_code == 422


@pytest.mark.anyio
async def test_missing_dropoff_lng_returns_422():
    params = {k: v for k, v in BASE_PARAMS.items() if k != "dropoff_lng"}
    client, app = await _get_client()
    async with client:
        resp = await client.get("/api/v1/rides/eta/estimate", params=params)
    app.dependency_overrides.clear()
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# 11-12. Out-of-range coords rejected → 422
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_out_of_range_lat_returns_422():
    params = {**BASE_PARAMS, "pickup_lat": 91.0}
    client, app = await _get_client()
    async with client:
        resp = await client.get("/api/v1/rides/eta/estimate", params=params)
    app.dependency_overrides.clear()
    assert resp.status_code == 422


@pytest.mark.anyio
async def test_out_of_range_lng_returns_422():
    params = {**BASE_PARAMS, "dropoff_lng": 181.0}
    client, app = await _get_client()
    async with client:
        resp = await client.get("/api/v1/rides/eta/estimate", params=params)
    app.dependency_overrides.clear()
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# 13. No auth required
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_no_auth_required():
    with patch(
        "app.api.v1.eta_estimate.get_nearby_available_drivers_km",
        new=AsyncMock(return_value=[]),
    ):
        client, app = await _get_client()
        async with client:
            resp = await client.get(
                "/api/v1/rides/eta/estimate",
                params=BASE_PARAMS,
                # Deliberately no Authorization header.
            )
    app.dependency_overrides.clear()
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# 14. Full response shape
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_full_response_shape():
    with patch(
        "app.api.v1.eta_estimate.get_nearby_available_drivers_km",
        new=AsyncMock(return_value=[_DRIVER_CLOSE, _DRIVER_MEDIUM]),
    ):
        client, app = await _get_client()
        async with client:
            resp = await client.get("/api/v1/rides/eta/estimate", params=BASE_PARAMS)
    app.dependency_overrides.clear()

    assert resp.status_code == 200
    data = resp.json()

    # All required keys present.
    assert "pickup_eta_minutes" in data
    assert "trip_duration_minutes" in data
    assert "nearest_driver_distance_km" in data
    assert "available_driver_count" in data
    assert "confidence" in data

    # Types and constraints.
    assert isinstance(data["pickup_eta_minutes"], int)
    assert isinstance(data["trip_duration_minutes"], int)
    assert isinstance(data["available_driver_count"], int)
    assert data["confidence"] in ("high", "medium", "low")
    assert data["pickup_eta_minutes"] >= 1
    assert data["trip_duration_minutes"] >= 2
    assert data["available_driver_count"] == 2
    assert data["confidence"] == "medium"
