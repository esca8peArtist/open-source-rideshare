import pytest
from httpx import AsyncClient
from unittest.mock import AsyncMock, patch

from geoalchemy2.functions import ST_MakePoint
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ride import Ride, RideStatus
from app.models.user import User
from tests.conftest import auth_header

pytestmark = pytest.mark.integration


async def _create_ride(db: AsyncSession, rider: User, driver: User | None = None) -> Ride:
    ride = Ride(
        rider_id=rider.id,
        driver_id=driver.id if driver else None,
        status=RideStatus.REQUESTED,
        pickup_location=ST_MakePoint(-73.9857, 40.7484, 4326),
        dropoff_location=ST_MakePoint(-73.9712, 40.7614, 4326),
        pickup_address="350 5th Ave, New York",
        dropoff_address="30 Rockefeller Plaza, New York",
        estimated_fare=15.50,
        distance_km=2.1,
        duration_min=8.5,
    )
    db.add(ride)
    await db.flush()
    return ride


async def test_get_ride_as_rider(
    client: AsyncClient, db: AsyncSession, rider: User, rider_token: str,
):
    ride = await _create_ride(db, rider)
    resp = await client.get(f"/api/v1/rides/{ride.id}", headers=auth_header(rider_token))
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == ride.id
    assert data["status"] == "requested"
    assert data["pickup_address"] == "350 5th Ave, New York"
    assert data["estimated_fare"] == 15.50


async def test_get_ride_unauthorized(
    client: AsyncClient, db: AsyncSession, rider: User, admin_token: str,
):
    ride = await _create_ride(db, rider)
    resp = await client.get(f"/api/v1/rides/{ride.id}", headers=auth_header(admin_token))
    assert resp.status_code == 403


async def test_get_ride_not_found(client: AsyncClient, rider_token: str):
    resp = await client.get("/api/v1/rides/99999", headers=auth_header(rider_token))
    assert resp.status_code == 404


async def test_accept_ride(
    client: AsyncClient, db: AsyncSession,
    rider: User, driver_user: User, driver_profile,
    driver_token: str,
):
    ride = await _create_ride(db, rider)
    resp = await client.post(
        f"/api/v1/rides/{ride.id}/accept", headers=auth_header(driver_token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "matched"
    assert data["matched_at"] is not None


async def test_accept_already_matched_ride(
    client: AsyncClient, db: AsyncSession,
    rider: User, driver_user: User, driver_profile,
    driver_token: str,
):
    ride = await _create_ride(db, rider)
    ride.status = RideStatus.MATCHED
    ride.driver_id = driver_user.id
    await db.flush()

    resp = await client.post(
        f"/api/v1/rides/{ride.id}/accept", headers=auth_header(driver_token),
    )
    assert resp.status_code == 409


async def test_full_ride_lifecycle(
    client: AsyncClient, db: AsyncSession,
    rider: User, driver_user: User, driver_profile,
    rider_token: str, driver_token: str,
):
    ride = await _create_ride(db, rider)

    resp = await client.post(
        f"/api/v1/rides/{ride.id}/accept", headers=auth_header(driver_token),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "matched"

    resp = await client.post(
        f"/api/v1/rides/{ride.id}/en-route", headers=auth_header(driver_token),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "driver_en_route"

    resp = await client.post(
        f"/api/v1/rides/{ride.id}/arrived", headers=auth_header(driver_token),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "arrived"

    resp = await client.post(
        f"/api/v1/rides/{ride.id}/start", headers=auth_header(driver_token),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "in_progress"

    resp = await client.post(
        f"/api/v1/rides/{ride.id}/complete", headers=auth_header(driver_token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "completed"
    assert data["fare"] == 15.50


async def test_cancel_ride_by_rider(
    client: AsyncClient, db: AsyncSession,
    rider: User, rider_token: str,
):
    ride = await _create_ride(db, rider)
    resp = await client.post(
        f"/api/v1/rides/{ride.id}/cancel",
        headers=auth_header(rider_token),
        json={"reason": "Changed my mind"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"


async def test_cancel_completed_ride_fails(
    client: AsyncClient, db: AsyncSession,
    rider: User, rider_token: str,
):
    ride = await _create_ride(db, rider)
    ride.status = RideStatus.COMPLETED
    await db.flush()

    resp = await client.post(
        f"/api/v1/rides/{ride.id}/cancel",
        headers=auth_header(rider_token),
        json={"reason": "Too late"},
    )
    assert resp.status_code == 409


async def test_rate_ride_as_rider(
    client: AsyncClient, db: AsyncSession,
    rider: User, driver_user: User, rider_token: str,
):
    ride = await _create_ride(db, rider, driver_user)
    ride.status = RideStatus.COMPLETED
    await db.flush()

    resp = await client.post(
        f"/api/v1/rides/{ride.id}/rate",
        headers=auth_header(rider_token),
        json={"rating": 5, "tip_amount": 3.00},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "rated"


async def test_rate_ride_as_driver(
    client: AsyncClient, db: AsyncSession,
    rider: User, driver_user: User, driver_token: str,
):
    ride = await _create_ride(db, rider, driver_user)
    ride.status = RideStatus.COMPLETED
    await db.flush()

    resp = await client.post(
        f"/api/v1/rides/{ride.id}/rate",
        headers=auth_header(driver_token),
        json={"rating": 4},
    )
    assert resp.status_code == 200


async def test_invalid_state_transition_en_route_from_requested(
    client: AsyncClient, db: AsyncSession,
    rider: User, driver_user: User, driver_profile,
    driver_token: str,
):
    ride = await _create_ride(db, rider, driver_user)
    resp = await client.post(
        f"/api/v1/rides/{ride.id}/en-route", headers=auth_header(driver_token),
    )
    assert resp.status_code == 409


async def test_complete_ride_not_in_progress(
    client: AsyncClient, db: AsyncSession,
    rider: User, driver_user: User, driver_profile,
    driver_token: str,
):
    ride = await _create_ride(db, rider, driver_user)
    ride.status = RideStatus.MATCHED
    await db.flush()

    resp = await client.post(
        f"/api/v1/rides/{ride.id}/complete", headers=auth_header(driver_token),
    )
    assert resp.status_code == 409
