import pytest
from datetime import datetime, timezone
from httpx import AsyncClient
from geoalchemy2.functions import ST_MakePoint
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.driver import DriverProfile
from app.models.payment import Payment, PaymentStatus
from app.models.ride import Ride, RideStatus
from app.models.user import User
from tests.conftest import auth_header

pytestmark = pytest.mark.integration


async def _seed_ride(
    db: AsyncSession, rider: User, driver: User, status: RideStatus = RideStatus.COMPLETED,
) -> Ride:
    ride = Ride(
        rider_id=rider.id,
        driver_id=driver.id,
        status=status,
        pickup_location=ST_MakePoint(-73.9857, 40.7484, 4326),
        dropoff_location=ST_MakePoint(-73.9712, 40.7614, 4326),
        pickup_address="350 5th Ave",
        dropoff_address="30 Rock",
        estimated_fare=15.50,
        actual_fare=15.50 if status == RideStatus.COMPLETED else None,
        distance_km=2.1,
        duration_min=8.5,
        completed_at=datetime.now(timezone.utc) if status == RideStatus.COMPLETED else None,
    )
    db.add(ride)
    await db.flush()
    return ride


async def _seed_payment(db: AsyncSession, ride: Ride) -> Payment:
    payment = Payment(
        ride_id=ride.id,
        amount=ride.actual_fare or ride.estimated_fare,
        platform_fee=0.0,
        driver_payout=ride.actual_fare or ride.estimated_fare,
        status=PaymentStatus.COMPLETED,
    )
    db.add(payment)
    await db.flush()
    return payment


async def test_admin_rides_list(
    client: AsyncClient, db: AsyncSession,
    rider: User, driver_user: User, driver_profile,
    admin_token: str,
):
    await _seed_ride(db, rider, driver_user)
    await _seed_ride(db, rider, driver_user, RideStatus.CANCELLED)

    resp = await client.get("/api/v1/admin/rides", headers=auth_header(admin_token))
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 2
    assert len(data["items"]) >= 2


async def test_admin_rides_filter_by_status(
    client: AsyncClient, db: AsyncSession,
    rider: User, driver_user: User, driver_profile,
    admin_token: str,
):
    await _seed_ride(db, rider, driver_user, RideStatus.COMPLETED)
    await _seed_ride(db, rider, driver_user, RideStatus.CANCELLED)

    resp = await client.get(
        "/api/v1/admin/rides?status=completed", headers=auth_header(admin_token),
    )
    assert resp.status_code == 200
    for item in resp.json()["items"]:
        assert item["status"] == "completed"


async def test_admin_ride_detail(
    client: AsyncClient, db: AsyncSession,
    rider: User, driver_user: User, driver_profile,
    admin_token: str,
):
    ride = await _seed_ride(db, rider, driver_user)
    resp = await client.get(
        f"/api/v1/admin/rides/{ride.id}", headers=auth_header(admin_token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == ride.id
    assert data["rider_name"] == "Test Rider"
    assert data["driver_name"] == "Test Driver"


async def test_admin_drivers_list(
    client: AsyncClient, db: AsyncSession,
    driver_user: User, driver_profile,
    admin_token: str,
):
    resp = await client.get("/api/v1/admin/drivers", headers=auth_header(admin_token))
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1


async def test_admin_approve_driver(
    client: AsyncClient, db: AsyncSession,
    driver_user: User, driver_profile,
    admin_token: str,
):
    driver_profile.is_approved = False
    await db.flush()

    resp = await client.post(
        f"/api/v1/admin/drivers/{driver_profile.id}/approve",
        headers=auth_header(admin_token),
    )
    assert resp.status_code == 200
    assert resp.json()["is_approved"] is True


async def test_admin_suspend_driver(
    client: AsyncClient, db: AsyncSession,
    driver_user: User, driver_profile,
    admin_token: str,
):
    resp = await client.post(
        f"/api/v1/admin/drivers/{driver_profile.id}/suspend",
        headers=auth_header(admin_token),
        json={"reason": "Failed background check"},
    )
    assert resp.status_code == 200


async def test_admin_stats(
    client: AsyncClient, db: AsyncSession,
    rider: User, driver_user: User, driver_profile,
    admin_token: str,
):
    ride = await _seed_ride(db, rider, driver_user)
    await _seed_payment(db, ride)

    resp = await client.get("/api/v1/admin/stats", headers=auth_header(admin_token))
    assert resp.status_code == 200
    data = resp.json()
    assert "total_users" in data
    assert "completed_today" in data


async def test_admin_payments_list(
    client: AsyncClient, db: AsyncSession,
    rider: User, driver_user: User, driver_profile,
    admin_token: str,
):
    ride = await _seed_ride(db, rider, driver_user)
    await _seed_payment(db, ride)

    resp = await client.get("/api/v1/admin/payments", headers=auth_header(admin_token))
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1


async def test_admin_settings_get_and_update(
    client: AsyncClient, admin_token: str,
):
    resp = await client.get("/api/v1/admin/settings", headers=auth_header(admin_token))
    assert resp.status_code == 200
    data = resp.json()
    assert "base_fare" in data

    resp = await client.put(
        "/api/v1/admin/settings",
        headers=auth_header(admin_token),
        json={"base_fare": 3.00, "per_km_rate": 2.00},
    )
    assert resp.status_code == 200
    assert resp.json()["base_fare"] == 3.00


async def test_non_admin_denied(
    client: AsyncClient, rider_token: str,
):
    resp = await client.get("/api/v1/admin/rides", headers=auth_header(rider_token))
    assert resp.status_code == 403


async def test_admin_revenue_stats(
    client: AsyncClient, db: AsyncSession,
    rider: User, driver_user: User, driver_profile,
    admin_token: str,
):
    ride = await _seed_ride(db, rider, driver_user)
    await _seed_payment(db, ride)

    resp = await client.get(
        "/api/v1/admin/stats/revenue?period=week", headers=auth_header(admin_token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
