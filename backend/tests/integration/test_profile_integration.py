"""Integration tests for user profile and driver profile endpoints.

Requires PostgreSQL test database (docker-compose up test-db).
"""

import pytest
from httpx import AsyncClient

from tests.conftest import auth_header

pytestmark = pytest.mark.integration


# --- GET /auth/me ---

async def test_get_me_as_rider(client: AsyncClient, rider_token: str):
    resp = await client.get("/api/v1/auth/me", headers=auth_header(rider_token))
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Test Rider"
    assert data["phone"] == "+15551000001"
    assert data["email"] == "rider@test.com"
    assert data["role"] == "rider"
    assert data["is_active"] is True


async def test_get_me_as_driver(client: AsyncClient, driver_token: str):
    resp = await client.get("/api/v1/auth/me", headers=auth_header(driver_token))
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Test Driver"
    assert data["role"] == "driver"


async def test_get_me_unauthenticated(client: AsyncClient):
    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code == 403


# --- PUT /auth/me ---

async def test_update_me_name(client: AsyncClient, rider_token: str):
    resp = await client.put(
        "/api/v1/auth/me",
        json={"name": "Updated Rider"},
        headers=auth_header(rider_token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Updated Rider"
    assert data["email"] == "rider@test.com"


async def test_update_me_email(client: AsyncClient, rider_token: str):
    resp = await client.put(
        "/api/v1/auth/me",
        json={"email": "newemail@test.com"},
        headers=auth_header(rider_token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["email"] == "newemail@test.com"


async def test_update_me_both_fields(client: AsyncClient, rider_token: str):
    resp = await client.put(
        "/api/v1/auth/me",
        json={"name": "Both Updated", "email": "both@test.com"},
        headers=auth_header(rider_token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Both Updated"
    assert data["email"] == "both@test.com"


async def test_update_me_unauthenticated(client: AsyncClient):
    resp = await client.put("/api/v1/auth/me", json={"name": "Hacker"})
    assert resp.status_code == 403


# --- GET /driver/profile ---

async def test_get_driver_profile(
    client: AsyncClient, driver_token: str, driver_profile,
):
    resp = await client.get(
        "/api/v1/driver/profile",
        headers=auth_header(driver_token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["vehicle_make"] == "Toyota"
    assert data["vehicle_model"] == "Camry"
    assert data["vehicle_year"] == 2022
    assert data["license_plate"] == "TEST-123"
    assert data["is_approved"] is True
    assert data["rating_avg"] == 4.8
    assert data["total_trips"] == 50


async def test_get_driver_profile_not_found(client: AsyncClient):
    # Register a fresh driver with no profile
    reg = await client.post("/api/v1/auth/register", json={
        "phone": "+15559990100",
        "name": "No Profile Driver",
        "password": "pass123",
        "role": "driver",
    })
    token = reg.json()["access_token"]
    resp = await client.get(
        "/api/v1/driver/profile",
        headers=auth_header(token),
    )
    assert resp.status_code == 404


async def test_get_driver_profile_forbidden_for_rider(
    client: AsyncClient, rider_token: str,
):
    resp = await client.get(
        "/api/v1/driver/profile",
        headers=auth_header(rider_token),
    )
    assert resp.status_code == 403


# --- PUT /driver/profile ---

async def test_update_driver_profile_partial(
    client: AsyncClient, driver_token: str, driver_profile,
):
    resp = await client.put(
        "/api/v1/driver/profile",
        json={"vehicle_color": "Red"},
        headers=auth_header(driver_token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["vehicle_color"] == "Red"
    assert data["vehicle_make"] == "Toyota"  # unchanged


async def test_update_driver_profile_full(
    client: AsyncClient, driver_token: str, driver_profile,
):
    resp = await client.put(
        "/api/v1/driver/profile",
        json={
            "vehicle_type": "suv",
            "vehicle_make": "Honda",
            "vehicle_model": "CR-V",
            "vehicle_year": 2024,
            "vehicle_color": "Blue",
            "license_plate": "NEW-789",
        },
        headers=auth_header(driver_token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["vehicle_type"] == "suv"
    assert data["vehicle_make"] == "Honda"
    assert data["license_plate"] == "NEW-789"


async def test_update_driver_profile_not_found(client: AsyncClient):
    reg = await client.post("/api/v1/auth/register", json={
        "phone": "+15559990101",
        "name": "No Profile Driver 2",
        "password": "pass123",
        "role": "driver",
    })
    token = reg.json()["access_token"]
    resp = await client.put(
        "/api/v1/driver/profile",
        json={"vehicle_color": "Red"},
        headers=auth_header(token),
    )
    assert resp.status_code == 404


async def test_update_driver_profile_forbidden_for_rider(
    client: AsyncClient, rider_token: str,
):
    resp = await client.put(
        "/api/v1/driver/profile",
        json={"vehicle_color": "Red"},
        headers=auth_header(rider_token),
    )
    assert resp.status_code == 403
