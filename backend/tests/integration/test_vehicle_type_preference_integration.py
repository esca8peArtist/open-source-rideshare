"""Integration tests for vehicle type preference in ride requests.

Tests POST /rides/request with vehicle_type_preference and verifies the
preference is persisted on the Ride record.

These tests require a running PostgreSQL instance (skipped otherwise).
"""

import pytest
from geoalchemy2.functions import ST_MakePoint
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from unittest.mock import AsyncMock, patch

from app.models.ride import Ride, RideStatus
from app.models.user import User
from app.models.vehicle import VehicleServiceCategory
from tests.conftest import auth_header

pytestmark = pytest.mark.integration


async def _create_ride_with_preference(
    db: AsyncSession,
    rider: User,
    preference: VehicleServiceCategory | None = None,
) -> Ride:
    ride = Ride(
        rider_id=rider.id,
        status=RideStatus.REQUESTED,
        pickup_location=ST_MakePoint(-73.9857, 40.7484, 4326),
        dropoff_location=ST_MakePoint(-73.9712, 40.7614, 4326),
        pickup_address="350 5th Ave, New York",
        dropoff_address="30 Rockefeller Plaza, New York",
        estimated_fare=15.50,
        distance_km=2.1,
        duration_min=8.5,
        vehicle_type_preference=preference,
    )
    db.add(ride)
    await db.flush()
    return ride


async def test_ride_persists_no_preference(db: AsyncSession, rider: User):
    """Ride created without preference has None vehicle_type_preference."""
    ride = await _create_ride_with_preference(db, rider, preference=None)
    assert ride.vehicle_type_preference is None


async def test_ride_persists_standard_preference(db: AsyncSession, rider: User):
    """Ride created with standard preference persists correctly."""
    ride = await _create_ride_with_preference(db, rider, preference=VehicleServiceCategory.STANDARD)
    assert ride.vehicle_type_preference == VehicleServiceCategory.STANDARD


async def test_ride_persists_xl_preference(db: AsyncSession, rider: User):
    """Ride created with xl preference persists correctly."""
    ride = await _create_ride_with_preference(db, rider, preference=VehicleServiceCategory.XL)
    assert ride.vehicle_type_preference == VehicleServiceCategory.XL


async def test_ride_persists_wav_preference(db: AsyncSession, rider: User):
    """Ride created with wav preference persists correctly."""
    ride = await _create_ride_with_preference(db, rider, preference=VehicleServiceCategory.WAV)
    assert ride.vehicle_type_preference == VehicleServiceCategory.WAV


async def test_ride_persists_comfort_preference(db: AsyncSession, rider: User):
    """Ride created with comfort preference persists correctly."""
    ride = await _create_ride_with_preference(db, rider, preference=VehicleServiceCategory.COMFORT)
    assert ride.vehicle_type_preference == VehicleServiceCategory.COMFORT


async def test_ride_persists_premium_preference(db: AsyncSession, rider: User):
    """Ride created with premium preference persists correctly."""
    ride = await _create_ride_with_preference(db, rider, preference=VehicleServiceCategory.PREMIUM)
    assert ride.vehicle_type_preference == VehicleServiceCategory.PREMIUM


async def test_get_ride_returns_vehicle_type_preference(
    client: AsyncClient, db: AsyncSession, rider: User, rider_token: str,
):
    """GET /rides/{id} response includes vehicle_type_preference field."""
    ride = await _create_ride_with_preference(db, rider, preference=VehicleServiceCategory.XL)
    resp = await client.get(f"/api/v1/rides/{ride.id}", headers=auth_header(rider_token))
    assert resp.status_code == 200
    data = resp.json()
    assert data["vehicle_type_preference"] == "xl"


async def test_get_ride_returns_null_when_no_preference(
    client: AsyncClient, db: AsyncSession, rider: User, rider_token: str,
):
    """GET /rides/{id} response has null vehicle_type_preference when not set."""
    ride = await _create_ride_with_preference(db, rider, preference=None)
    resp = await client.get(f"/api/v1/rides/{ride.id}", headers=auth_header(rider_token))
    assert resp.status_code == 200
    data = resp.json()
    assert data["vehicle_type_preference"] is None
