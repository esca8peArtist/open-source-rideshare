import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.driver import DriverProfile
from app.models.user import User
from tests.conftest import auth_header

pytestmark = pytest.mark.integration


async def test_create_driver_profile(
    client: AsyncClient, db: AsyncSession, driver_user: User, driver_token: str,
):
    resp = await client.post(
        "/api/v1/driver/profile",
        headers=auth_header(driver_token),
        json={
            "vehicle_type": "suv",
            "vehicle_make": "Honda",
            "vehicle_model": "CR-V",
            "vehicle_year": 2023,
            "vehicle_color": "Blue",
            "license_plate": "NEW-456",
            "license_number": "DL-NEW-789",
            "insurance_policy": "INS-NEW",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["vehicle_make"] == "Honda"
    assert data["is_approved"] is False
    assert data["is_online"] is False
    assert data["rating_avg"] == 5.0


async def test_create_duplicate_profile_fails(
    client: AsyncClient, driver_user: User, driver_profile,
    driver_token: str,
):
    resp = await client.post(
        "/api/v1/driver/profile",
        headers=auth_header(driver_token),
        json={
            "vehicle_type": "sedan",
            "vehicle_make": "Ford",
            "vehicle_model": "Focus",
            "vehicle_year": 2021,
            "vehicle_color": "Red",
            "license_plate": "DUP-123",
            "license_number": "DL-DUP",
        },
    )
    assert resp.status_code == 409


async def test_rider_cannot_create_driver_profile(
    client: AsyncClient, rider_token: str,
):
    resp = await client.post(
        "/api/v1/driver/profile",
        headers=auth_header(rider_token),
        json={
            "vehicle_type": "sedan",
            "vehicle_make": "Toyota",
            "vehicle_model": "Corolla",
            "vehicle_year": 2022,
            "vehicle_color": "White",
            "license_plate": "RIDE-123",
            "license_number": "DL-RIDE",
        },
    )
    assert resp.status_code == 403


async def test_go_online_approved_driver(
    client: AsyncClient, driver_user: User, driver_profile,
    driver_token: str,
):
    resp = await client.post(
        "/api/v1/driver/go-online", headers=auth_header(driver_token),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "online"


async def test_go_online_unapproved_driver(
    client: AsyncClient, db: AsyncSession, driver_user: User, driver_profile,
    driver_token: str,
):
    driver_profile.is_approved = False
    await db.flush()

    resp = await client.post(
        "/api/v1/driver/go-online", headers=auth_header(driver_token),
    )
    assert resp.status_code == 403
    assert "not yet approved" in resp.json()["detail"]


async def test_go_offline(
    client: AsyncClient, driver_user: User, driver_profile,
    driver_token: str,
):
    driver_profile.is_online = True

    resp = await client.post(
        "/api/v1/driver/go-offline", headers=auth_header(driver_token),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "offline"


async def test_go_online_without_profile(
    client: AsyncClient, db: AsyncSession, driver_user: User,
    driver_token: str,
):
    resp = await client.post(
        "/api/v1/driver/go-online", headers=auth_header(driver_token),
    )
    assert resp.status_code == 404


async def test_earnings_empty(
    client: AsyncClient, driver_user: User, driver_profile,
    driver_token: str,
):
    resp = await client.get(
        "/api/v1/driver/earnings?period=week", headers=auth_header(driver_token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["summary"]["trip_count"] == 0
    assert data["summary"]["total_earnings"] == 0.0
    assert data["trips"] == []


async def test_earnings_with_completed_rides(
    client: AsyncClient, db: AsyncSession,
    rider: User, driver_user: User, driver_profile,
    driver_token: str,
):
    from datetime import datetime, timezone
    from geoalchemy2.functions import ST_MakePoint
    from app.models.ride import Ride, RideStatus
    from app.models.payment import Payment, PaymentStatus

    ride = Ride(
        rider_id=rider.id,
        driver_id=driver_user.id,
        status=RideStatus.COMPLETED,
        pickup_location=ST_MakePoint(-73.9857, 40.7484, 4326),
        dropoff_location=ST_MakePoint(-73.9712, 40.7614, 4326),
        pickup_address="Penn Station",
        dropoff_address="Grand Central",
        estimated_fare=12.00,
        actual_fare=12.00,
        distance_km=1.8,
        duration_min=7.0,
        completed_at=datetime.now(timezone.utc),
    )
    db.add(ride)
    await db.flush()

    payment = Payment(
        ride_id=ride.id,
        amount=12.00,
        platform_fee=0.0,
        driver_payout=12.00,
        status=PaymentStatus.COMPLETED,
        tip_amount=2.00,
    )
    db.add(payment)
    await db.flush()

    resp = await client.get(
        "/api/v1/driver/earnings?period=week", headers=auth_header(driver_token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["summary"]["trip_count"] == 1
    assert data["summary"]["total_fares"] == 12.00
    assert data["summary"]["total_tips"] == 2.00
    assert data["summary"]["total_earnings"] == 14.00
    assert len(data["trips"]) == 1
    assert data["trips"][0]["pickup_address"] == "Penn Station"
