import pytest
from httpx import AsyncClient

from tests.conftest import auth_header

pytestmark = pytest.mark.integration


async def test_register_rider(client: AsyncClient):
    resp = await client.post("/api/v1/auth/register", json={
        "phone": "+15559990001",
        "name": "New Rider",
        "password": "securepass123",
        "role": "rider",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"


async def test_register_driver(client: AsyncClient):
    resp = await client.post("/api/v1/auth/register", json={
        "phone": "+15559990002",
        "name": "New Driver",
        "password": "securepass123",
        "role": "driver",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert "access_token" in data


async def test_register_duplicate_phone(client: AsyncClient):
    phone = "+15559990003"
    await client.post("/api/v1/auth/register", json={
        "phone": phone, "name": "First", "password": "pass123", "role": "rider",
    })
    resp = await client.post("/api/v1/auth/register", json={
        "phone": phone, "name": "Second", "password": "pass456", "role": "rider",
    })
    assert resp.status_code == 400
    assert "already registered" in resp.json()["detail"]


async def test_login_success(client: AsyncClient):
    phone = "+15559990004"
    await client.post("/api/v1/auth/register", json={
        "phone": phone, "name": "Login User", "password": "mypassword", "role": "rider",
    })
    resp = await client.post("/api/v1/auth/login", json={
        "phone": phone, "password": "mypassword",
    })
    assert resp.status_code == 200
    assert "access_token" in resp.json()


async def test_login_wrong_password(client: AsyncClient):
    phone = "+15559990005"
    await client.post("/api/v1/auth/register", json={
        "phone": phone, "name": "Wrong Pass", "password": "correct", "role": "rider",
    })
    resp = await client.post("/api/v1/auth/login", json={
        "phone": phone, "password": "incorrect",
    })
    assert resp.status_code == 401


async def test_login_nonexistent_user(client: AsyncClient):
    resp = await client.post("/api/v1/auth/login", json={
        "phone": "+15550000000", "password": "whatever",
    })
    assert resp.status_code == 401


async def test_refresh_token(client: AsyncClient):
    resp = await client.post("/api/v1/auth/register", json={
        "phone": "+15559990006", "name": "Refresh User", "password": "pass123", "role": "rider",
    })
    refresh = resp.json()["refresh_token"]

    resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert "refresh_token" in data


async def test_refresh_with_access_token_fails(client: AsyncClient):
    resp = await client.post("/api/v1/auth/register", json={
        "phone": "+15559990007", "name": "Bad Refresh", "password": "pass123", "role": "rider",
    })
    access = resp.json()["access_token"]

    resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": access})
    assert resp.status_code == 401


async def test_authenticated_endpoint_requires_token(client: AsyncClient):
    resp = await client.get("/api/v1/rides/999")
    assert resp.status_code == 403


async def test_authenticated_endpoint_with_valid_token(
    client: AsyncClient, rider_token: str,
):
    resp = await client.get("/api/v1/rides/999", headers=auth_header(rider_token))
    assert resp.status_code == 404
