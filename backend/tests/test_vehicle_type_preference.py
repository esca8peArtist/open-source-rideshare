"""Unit tests for vehicle type preference in ride requests and matching.

Covers:
- Ride model accepts vehicle_type_preference field
- RideRequest schema accepts and validates the field
- Matching engine filters by vehicle type preference
- Matching engine passes all vehicle types when no preference is set
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.vehicle import VehicleServiceCategory
from app.schemas.ride import RideRequest
from app.services.matching import DriverCandidate, MatchingEngine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_driver_profile(profile_id: int, user_id: int, is_online: bool = True, is_approved: bool = True):
    p = MagicMock()
    p.id = profile_id
    p.user_id = user_id
    p.is_online = is_online
    p.is_approved = is_approved
    p.rating_avg = 4.8
    p.total_trips = 100
    p.active_vehicle_id = None
    return p


def _make_vehicle(vehicle_id: int, profile_id: int, service_category: VehicleServiceCategory, is_wav: bool = False):
    v = MagicMock()
    v.id = vehicle_id
    v.driver_profile_id = profile_id
    v.service_category = service_category
    v.is_wheelchair_accessible = is_wav
    v.capacity = 4
    v.is_active = True
    return v


@pytest.fixture
def mock_redis():
    r = AsyncMock()
    r.geosearch = AsyncMock(return_value=[("1", 0.5), ("2", 1.0)])
    r.get = AsyncMock(return_value=b"available")
    return r


@pytest.fixture
def engine(mock_redis):
    return MatchingEngine(mock_redis)


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------

def test_ride_request_no_preference():
    req = RideRequest(
        pickup={"lat": 40.7, "lng": -74.0},
        dropoff={"lat": 40.75, "lng": -73.99},
        pickup_address="123 Main St",
        dropoff_address="456 Oak Ave",
    )
    assert req.vehicle_type_preference is None


def test_ride_request_with_standard_preference():
    req = RideRequest(
        pickup={"lat": 40.7, "lng": -74.0},
        dropoff={"lat": 40.75, "lng": -73.99},
        pickup_address="123 Main St",
        dropoff_address="456 Oak Ave",
        vehicle_type_preference="standard",
    )
    assert req.vehicle_type_preference == VehicleServiceCategory.STANDARD


def test_ride_request_with_xl_preference():
    req = RideRequest(
        pickup={"lat": 40.7, "lng": -74.0},
        dropoff={"lat": 40.75, "lng": -73.99},
        pickup_address="123 Main St",
        dropoff_address="456 Oak Ave",
        vehicle_type_preference="xl",
    )
    assert req.vehicle_type_preference == VehicleServiceCategory.XL


def test_ride_request_with_wav_preference():
    req = RideRequest(
        pickup={"lat": 40.7, "lng": -74.0},
        dropoff={"lat": 40.75, "lng": -73.99},
        pickup_address="123 Main St",
        dropoff_address="456 Oak Ave",
        vehicle_type_preference="wav",
    )
    assert req.vehicle_type_preference == VehicleServiceCategory.WAV


def test_ride_request_with_comfort_preference():
    req = RideRequest(
        pickup={"lat": 40.7, "lng": -74.0},
        dropoff={"lat": 40.75, "lng": -73.99},
        pickup_address="123 Main St",
        dropoff_address="456 Oak Ave",
        vehicle_type_preference="comfort",
    )
    assert req.vehicle_type_preference == VehicleServiceCategory.COMFORT


def test_ride_request_with_premium_preference():
    req = RideRequest(
        pickup={"lat": 40.7, "lng": -74.0},
        dropoff={"lat": 40.75, "lng": -73.99},
        pickup_address="123 Main St",
        dropoff_address="456 Oak Ave",
        vehicle_type_preference="premium",
    )
    assert req.vehicle_type_preference == VehicleServiceCategory.PREMIUM


def test_ride_request_invalid_preference():
    with pytest.raises(Exception):
        RideRequest(
            pickup={"lat": 40.7, "lng": -74.0},
            dropoff={"lat": 40.75, "lng": -73.99},
            pickup_address="123 Main St",
            dropoff_address="456 Oak Ave",
            vehicle_type_preference="helicopter",
        )


# ---------------------------------------------------------------------------
# Matching engine unit tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_find_candidates_no_preference_returns_all_vehicle_types(engine, mock_redis):
    """When no preference is set, all vehicle service categories are eligible."""
    profile_standard = _make_driver_profile(profile_id=1, user_id=1)
    profile_xl = _make_driver_profile(profile_id=2, user_id=2)
    profile_premium = _make_driver_profile(profile_id=3, user_id=3)

    vehicle_standard = _make_vehicle(10, 1, VehicleServiceCategory.STANDARD)
    vehicle_xl = _make_vehicle(11, 2, VehicleServiceCategory.XL)
    vehicle_premium = _make_vehicle(12, 3, VehicleServiceCategory.PREMIUM)

    mock_redis.geosearch = AsyncMock(return_value=[("1", 0.5), ("2", 1.0), ("3", 1.5)])
    mock_redis.get = AsyncMock(return_value=b"available")

    db = AsyncMock()

    profiles_result = MagicMock()
    profiles_result.scalars.return_value.all.return_value = [profile_standard, profile_xl, profile_premium]

    vehicles_result = MagicMock()
    vehicles_result.scalars.return_value.all.return_value = [vehicle_standard, vehicle_xl, vehicle_premium]

    db.execute = AsyncMock(side_effect=[profiles_result, vehicles_result])

    with patch.object(engine, "_get_availability_eligible_driver_ids", new=AsyncMock(return_value={1, 2, 3})):
        candidates = await engine.find_candidates(
            pickup_lat=40.7, pickup_lng=-74.0, db=db,
            vehicle_type_preference=None,
        )

    assert len(candidates) == 3
    categories = {c.vehicle_service_category for c in candidates}
    assert VehicleServiceCategory.STANDARD in categories
    assert VehicleServiceCategory.XL in categories
    assert VehicleServiceCategory.PREMIUM in categories


@pytest.mark.asyncio
async def test_find_candidates_standard_preference_filters_others(engine, mock_redis):
    """When preference is standard, only standard vehicles are returned."""
    profile_standard = _make_driver_profile(profile_id=1, user_id=1)
    profile_xl = _make_driver_profile(profile_id=2, user_id=2)

    vehicle_standard = _make_vehicle(10, 1, VehicleServiceCategory.STANDARD)
    vehicle_xl = _make_vehicle(11, 2, VehicleServiceCategory.XL)

    mock_redis.geosearch = AsyncMock(return_value=[("1", 0.5), ("2", 1.0)])

    db = AsyncMock()

    profiles_result = MagicMock()
    profiles_result.scalars.return_value.all.return_value = [profile_standard, profile_xl]

    vehicles_result = MagicMock()
    vehicles_result.scalars.return_value.all.return_value = [vehicle_standard, vehicle_xl]

    db.execute = AsyncMock(side_effect=[profiles_result, vehicles_result])

    with patch.object(engine, "_get_availability_eligible_driver_ids", new=AsyncMock(return_value={1, 2})):
        candidates = await engine.find_candidates(
            pickup_lat=40.7, pickup_lng=-74.0, db=db,
            vehicle_type_preference=VehicleServiceCategory.STANDARD,
        )

    assert len(candidates) == 1
    assert candidates[0].vehicle_service_category == VehicleServiceCategory.STANDARD


@pytest.mark.asyncio
async def test_find_candidates_xl_preference_filters_others(engine, mock_redis):
    """When preference is xl, only XL vehicles are returned."""
    profile_standard = _make_driver_profile(profile_id=1, user_id=1)
    profile_xl = _make_driver_profile(profile_id=2, user_id=2)

    vehicle_standard = _make_vehicle(10, 1, VehicleServiceCategory.STANDARD)
    vehicle_xl = _make_vehicle(11, 2, VehicleServiceCategory.XL)

    mock_redis.geosearch = AsyncMock(return_value=[("1", 0.5), ("2", 1.0)])

    db = AsyncMock()

    profiles_result = MagicMock()
    profiles_result.scalars.return_value.all.return_value = [profile_standard, profile_xl]

    vehicles_result = MagicMock()
    vehicles_result.scalars.return_value.all.return_value = [vehicle_standard, vehicle_xl]

    db.execute = AsyncMock(side_effect=[profiles_result, vehicles_result])

    with patch.object(engine, "_get_availability_eligible_driver_ids", new=AsyncMock(return_value={1, 2})):
        candidates = await engine.find_candidates(
            pickup_lat=40.7, pickup_lng=-74.0, db=db,
            vehicle_type_preference=VehicleServiceCategory.XL,
        )

    assert len(candidates) == 1
    assert candidates[0].vehicle_service_category == VehicleServiceCategory.XL


@pytest.mark.asyncio
async def test_find_candidates_wav_preference_filters_others(engine, mock_redis):
    """When preference is wav, only WAV vehicles are returned."""
    profile_standard = _make_driver_profile(profile_id=1, user_id=1)
    profile_wav = _make_driver_profile(profile_id=2, user_id=2)

    vehicle_standard = _make_vehicle(10, 1, VehicleServiceCategory.STANDARD, is_wav=False)
    vehicle_wav = _make_vehicle(11, 2, VehicleServiceCategory.WAV, is_wav=True)

    mock_redis.geosearch = AsyncMock(return_value=[("1", 0.5), ("2", 1.0)])

    db = AsyncMock()

    profiles_result = MagicMock()
    profiles_result.scalars.return_value.all.return_value = [profile_standard, profile_wav]

    vehicles_result = MagicMock()
    vehicles_result.scalars.return_value.all.return_value = [vehicle_standard, vehicle_wav]

    db.execute = AsyncMock(side_effect=[profiles_result, vehicles_result])

    with patch.object(engine, "_get_availability_eligible_driver_ids", new=AsyncMock(return_value={1, 2})):
        candidates = await engine.find_candidates(
            pickup_lat=40.7, pickup_lng=-74.0, db=db,
            vehicle_type_preference=VehicleServiceCategory.WAV,
        )

    assert len(candidates) == 1
    assert candidates[0].vehicle_service_category == VehicleServiceCategory.WAV


@pytest.mark.asyncio
async def test_find_candidates_preference_no_match_returns_empty(engine, mock_redis):
    """When preference is set but no drivers have that category, returns empty list."""
    profile_standard = _make_driver_profile(profile_id=1, user_id=1)
    vehicle_standard = _make_vehicle(10, 1, VehicleServiceCategory.STANDARD)

    mock_redis.geosearch = AsyncMock(return_value=[("1", 0.5)])

    db = AsyncMock()

    profiles_result = MagicMock()
    profiles_result.scalars.return_value.all.return_value = [profile_standard]

    vehicles_result = MagicMock()
    vehicles_result.scalars.return_value.all.return_value = [vehicle_standard]

    db.execute = AsyncMock(side_effect=[profiles_result, vehicles_result])

    with patch.object(engine, "_get_availability_eligible_driver_ids", new=AsyncMock(return_value={1})):
        candidates = await engine.find_candidates(
            pickup_lat=40.7, pickup_lng=-74.0, db=db,
            vehicle_type_preference=VehicleServiceCategory.PREMIUM,
        )

    assert candidates == []


@pytest.mark.asyncio
async def test_match_ride_passes_vehicle_type_preference(engine, mock_redis):
    """match_ride forwards vehicle_type_preference to find_candidates."""
    mock_ride = MagicMock()
    mock_ride.id = 1

    profile = _make_driver_profile(profile_id=1, user_id=1)
    vehicle = _make_vehicle(10, 1, VehicleServiceCategory.COMFORT)

    mock_redis.geosearch = AsyncMock(return_value=[("1", 0.5)])

    db = AsyncMock()

    profiles_result = MagicMock()
    profiles_result.scalars.return_value.all.return_value = [profile]

    vehicles_result = MagicMock()
    vehicles_result.scalars.return_value.all.return_value = [vehicle]

    db.execute = AsyncMock(side_effect=[profiles_result, vehicles_result])

    with patch.object(engine, "_get_availability_eligible_driver_ids", new=AsyncMock(return_value={1})):
        result = await engine.match_ride(
            mock_ride, 40.7, -74.0, db,
            vehicle_type_preference=VehicleServiceCategory.COMFORT,
        )

    assert result is not None
    assert result.vehicle_service_category == VehicleServiceCategory.COMFORT


@pytest.mark.asyncio
async def test_match_ride_wrong_category_excluded(engine, mock_redis):
    """match_ride returns None when the only driver has a non-matching category."""
    mock_ride = MagicMock()
    mock_ride.id = 1

    profile = _make_driver_profile(profile_id=1, user_id=1)
    vehicle = _make_vehicle(10, 1, VehicleServiceCategory.STANDARD)

    mock_redis.geosearch = AsyncMock(return_value=[("1", 0.5)])

    db = AsyncMock()

    profiles_result = MagicMock()
    profiles_result.scalars.return_value.all.return_value = [profile]

    vehicles_result = MagicMock()
    vehicles_result.scalars.return_value.all.return_value = [vehicle]

    db.execute = AsyncMock(side_effect=[profiles_result, vehicles_result])

    with patch.object(engine, "_get_availability_eligible_driver_ids", new=AsyncMock(return_value={1})):
        result = await engine.match_ride(
            mock_ride, 40.7, -74.0, db,
            vehicle_type_preference=VehicleServiceCategory.PREMIUM,
        )

    assert result is None


# ---------------------------------------------------------------------------
# VehicleServiceCategory enum coverage
# ---------------------------------------------------------------------------

def test_vehicle_service_category_values():
    assert VehicleServiceCategory.STANDARD == "standard"
    assert VehicleServiceCategory.COMFORT == "comfort"
    assert VehicleServiceCategory.XL == "xl"
    assert VehicleServiceCategory.PREMIUM == "premium"
    assert VehicleServiceCategory.WAV == "wav"
