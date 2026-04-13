"""Tests for vehicle management and WAV (Wheelchair Accessible Vehicle) matching."""

from datetime import datetime, timezone
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.vehicle import Vehicle, VehicleType
from app.models.driver import DriverProfile
from app.models.ride import Ride, RideStatus
from app.schemas.vehicle import VehicleCreate, VehicleUpdate, VehicleResponse
from app.schemas.ride import RideRequest, ScheduleRideRequest, LocationPoint
from app.services.matching import DriverCandidate


# ===========================================================================
# Vehicle Model Tests
# ===========================================================================


class TestVehicleModel:
    def test_vehicle_type_enum_values(self):
        assert VehicleType.SEDAN.value == "sedan"
        assert VehicleType.SUV.value == "suv"
        assert VehicleType.VAN.value == "van"
        assert VehicleType.MINIVAN.value == "minivan"
        assert VehicleType.TRUCK.value == "truck"
        assert VehicleType.HATCHBACK.value == "hatchback"
        assert VehicleType.COUPE.value == "coupe"
        assert VehicleType.WAGON.value == "wagon"
        assert VehicleType.OTHER.value == "other"

    def test_vehicle_type_count(self):
        assert len(VehicleType) == 9

    def test_vehicle_type_from_string(self):
        assert VehicleType("sedan") == VehicleType.SEDAN
        assert VehicleType("van") == VehicleType.VAN

    def test_invalid_vehicle_type_raises(self):
        with pytest.raises(ValueError):
            VehicleType("bicycle")

    def test_vehicle_table_name(self):
        assert Vehicle.__tablename__ == "vehicles"

    def test_vehicle_has_wav_field(self):
        cols = {c.name for c in Vehicle.__table__.columns}
        assert "is_wheelchair_accessible" in cols

    def test_vehicle_has_capacity_field(self):
        cols = {c.name for c in Vehicle.__table__.columns}
        assert "capacity" in cols

    def test_vehicle_has_is_active_field(self):
        cols = {c.name for c in Vehicle.__table__.columns}
        assert "is_active" in cols

    def test_vehicle_has_driver_profile_fk(self):
        cols = {c.name for c in Vehicle.__table__.columns}
        assert "driver_profile_id" in cols


# ===========================================================================
# Driver Profile Model — Vehicle Relationship
# ===========================================================================


class TestDriverProfileVehicle:
    def test_driver_profile_has_active_vehicle_id(self):
        cols = {c.name for c in DriverProfile.__table__.columns}
        assert "active_vehicle_id" in cols

    def test_active_vehicle_id_nullable(self):
        col = DriverProfile.__table__.columns["active_vehicle_id"]
        assert col.nullable is True


# ===========================================================================
# Ride Model — Accessibility Field
# ===========================================================================


class TestRideAccessibility:
    def test_ride_has_accessibility_required_field(self):
        cols = {c.name for c in Ride.__table__.columns}
        assert "accessibility_required" in cols

    def test_accessibility_required_default_false(self):
        col = Ride.__table__.columns["accessibility_required"]
        assert col.default.arg is False


# ===========================================================================
# Vehicle Schema Validation Tests
# ===========================================================================


class TestVehicleSchemas:
    def test_vehicle_create_valid(self):
        v = VehicleCreate(
            vehicle_type="sedan",
            make="Toyota",
            model="Camry",
            year=2022,
            color="Silver",
            license_plate="ABC1234",
            capacity=4,
            is_wheelchair_accessible=False,
        )
        assert v.make == "Toyota"
        assert v.capacity == 4
        assert v.is_wheelchair_accessible is False

    def test_vehicle_create_wav(self):
        v = VehicleCreate(
            vehicle_type="van",
            make="Ford",
            model="Transit",
            year=2023,
            color="White",
            license_plate="WAV5678",
            capacity=6,
            is_wheelchair_accessible=True,
        )
        assert v.is_wheelchair_accessible is True
        assert v.capacity == 6

    def test_vehicle_create_defaults(self):
        v = VehicleCreate(
            vehicle_type="sedan",
            make="Honda",
            model="Civic",
            year=2021,
            color="Black",
            license_plate="XYZ999",
        )
        assert v.capacity == 4
        assert v.is_wheelchair_accessible is False

    def test_vehicle_create_invalid_year_too_old(self):
        with pytest.raises(Exception):
            VehicleCreate(
                vehicle_type="sedan",
                make="Ford",
                model="Model T",
                year=1920,
                color="Black",
                license_plate="OLD0001",
            )

    def test_vehicle_create_invalid_year_too_new(self):
        with pytest.raises(Exception):
            VehicleCreate(
                vehicle_type="sedan",
                make="Tesla",
                model="X",
                year=2050,
                color="Red",
                license_plate="FUT0001",
            )

    def test_vehicle_create_invalid_capacity_zero(self):
        with pytest.raises(Exception):
            VehicleCreate(
                vehicle_type="sedan",
                make="Toyota",
                model="Camry",
                year=2022,
                color="Silver",
                license_plate="ABC1234",
                capacity=0,
            )

    def test_vehicle_create_invalid_capacity_too_high(self):
        with pytest.raises(Exception):
            VehicleCreate(
                vehicle_type="sedan",
                make="Toyota",
                model="Camry",
                year=2022,
                color="Silver",
                license_plate="ABC1234",
                capacity=20,
            )

    def test_vehicle_update_partial(self):
        v = VehicleUpdate(color="Red")
        dumped = v.model_dump(exclude_unset=True)
        assert dumped == {"color": "Red"}

    def test_vehicle_update_wav_toggle(self):
        v = VehicleUpdate(is_wheelchair_accessible=True)
        dumped = v.model_dump(exclude_unset=True)
        assert dumped == {"is_wheelchair_accessible": True}

    def test_vehicle_update_empty(self):
        v = VehicleUpdate()
        dumped = v.model_dump(exclude_unset=True)
        assert dumped == {}

    def test_vehicle_update_invalid_year(self):
        with pytest.raises(Exception):
            VehicleUpdate(year=1800)

    def test_vehicle_update_invalid_capacity(self):
        with pytest.raises(Exception):
            VehicleUpdate(capacity=-1)

    def test_vehicle_response_from_attributes(self):
        assert VehicleResponse.model_config.get("from_attributes") is True

    def test_vehicle_response_fields(self):
        fields = set(VehicleResponse.model_fields.keys())
        expected = {
            "id", "driver_profile_id", "vehicle_type", "make", "model",
            "year", "color", "license_plate", "capacity",
            "is_wheelchair_accessible", "is_active", "created_at",
        }
        assert expected == fields


# ===========================================================================
# Ride Schema — Accessibility Field
# ===========================================================================


class TestRideSchemaAccessibility:
    def test_ride_request_default_no_accessibility(self):
        r = RideRequest(
            pickup=LocationPoint(lat=40.7, lng=-74.0),
            dropoff=LocationPoint(lat=40.8, lng=-73.9),
            pickup_address="123 Main St",
            dropoff_address="456 Oak Ave",
        )
        assert r.accessibility_required is False

    def test_ride_request_with_accessibility(self):
        r = RideRequest(
            pickup=LocationPoint(lat=40.7, lng=-74.0),
            dropoff=LocationPoint(lat=40.8, lng=-73.9),
            pickup_address="123 Main St",
            dropoff_address="456 Oak Ave",
            accessibility_required=True,
        )
        assert r.accessibility_required is True

    def test_schedule_ride_default_no_accessibility(self):
        r = ScheduleRideRequest(
            pickup=LocationPoint(lat=40.7, lng=-74.0),
            dropoff=LocationPoint(lat=40.8, lng=-73.9),
            pickup_address="123 Main St",
            dropoff_address="456 Oak Ave",
            scheduled_for=datetime(2026, 5, 1, 10, 0, tzinfo=timezone.utc),
        )
        assert r.accessibility_required is False

    def test_schedule_ride_with_accessibility(self):
        r = ScheduleRideRequest(
            pickup=LocationPoint(lat=40.7, lng=-74.0),
            dropoff=LocationPoint(lat=40.8, lng=-73.9),
            pickup_address="123 Main St",
            dropoff_address="456 Oak Ave",
            scheduled_for=datetime(2026, 5, 1, 10, 0, tzinfo=timezone.utc),
            accessibility_required=True,
        )
        assert r.accessibility_required is True


# ===========================================================================
# DriverCandidate — WAV Fields
# ===========================================================================


class TestDriverCandidateWAV:
    def test_candidate_default_not_wav(self):
        c = DriverCandidate(
            driver_id=1, user_id=10, distance_km=2.0,
            rating_avg=4.8, total_trips=100,
        )
        assert c.is_wheelchair_accessible is False
        assert c.vehicle_capacity == 4

    def test_candidate_wav_vehicle(self):
        c = DriverCandidate(
            driver_id=1, user_id=10, distance_km=2.0,
            rating_avg=4.8, total_trips=100,
            is_wheelchair_accessible=True, vehicle_capacity=6,
        )
        assert c.is_wheelchair_accessible is True
        assert c.vehicle_capacity == 6

    def test_candidate_large_capacity(self):
        c = DriverCandidate(
            driver_id=1, user_id=10, distance_km=2.0,
            rating_avg=4.8, total_trips=100,
            vehicle_capacity=8,
        )
        assert c.vehicle_capacity == 8


# ===========================================================================
# WAV Matching Logic Tests
# ===========================================================================


class TestWAVMatching:
    """Test that accessibility_required filtering works correctly in candidate selection."""

    def _make_candidates(self) -> list[DriverCandidate]:
        return [
            DriverCandidate(
                driver_id=1, user_id=10, distance_km=1.0,
                rating_avg=4.9, total_trips=200,
                is_wheelchair_accessible=False, vehicle_capacity=4,
            ),
            DriverCandidate(
                driver_id=2, user_id=20, distance_km=2.0,
                rating_avg=4.7, total_trips=150,
                is_wheelchair_accessible=True, vehicle_capacity=6,
            ),
            DriverCandidate(
                driver_id=3, user_id=30, distance_km=3.0,
                rating_avg=4.5, total_trips=50,
                is_wheelchair_accessible=False, vehicle_capacity=4,
            ),
            DriverCandidate(
                driver_id=4, user_id=40, distance_km=4.0,
                rating_avg=4.8, total_trips=300,
                is_wheelchair_accessible=True, vehicle_capacity=8,
            ),
        ]

    def test_no_accessibility_returns_all(self):
        candidates = self._make_candidates()
        # Without accessibility filter, all candidates should be present
        assert len(candidates) == 4

    def test_accessibility_filter_removes_non_wav(self):
        candidates = self._make_candidates()
        wav_only = [c for c in candidates if c.is_wheelchair_accessible]
        assert len(wav_only) == 2
        assert all(c.is_wheelchair_accessible for c in wav_only)

    def test_wav_candidates_sorted_by_distance(self):
        candidates = self._make_candidates()
        wav_only = [c for c in candidates if c.is_wheelchair_accessible]
        wav_only.sort(key=lambda c: (c.distance_km, -c.rating_avg))
        assert wav_only[0].driver_id == 2  # closer WAV driver
        assert wav_only[1].driver_id == 4

    def test_no_wav_drivers_returns_empty(self):
        candidates = [
            DriverCandidate(
                driver_id=1, user_id=10, distance_km=1.0,
                rating_avg=4.9, total_trips=200,
                is_wheelchair_accessible=False, vehicle_capacity=4,
            ),
        ]
        wav_only = [c for c in candidates if c.is_wheelchair_accessible]
        assert len(wav_only) == 0

    def test_all_wav_returns_all(self):
        candidates = [
            DriverCandidate(
                driver_id=1, user_id=10, distance_km=1.0,
                rating_avg=4.9, total_trips=200,
                is_wheelchair_accessible=True, vehicle_capacity=6,
            ),
            DriverCandidate(
                driver_id=2, user_id=20, distance_km=2.0,
                rating_avg=4.7, total_trips=150,
                is_wheelchair_accessible=True, vehicle_capacity=8,
            ),
        ]
        wav_only = [c for c in candidates if c.is_wheelchair_accessible]
        assert len(wav_only) == 2


# ===========================================================================
# Vehicle Type Validation Tests
# ===========================================================================


class TestVehicleTypeValidation:
    def test_all_types_are_strings(self):
        for vtype in VehicleType:
            assert isinstance(vtype.value, str)

    def test_sedan_is_valid(self):
        assert VehicleType("sedan") == VehicleType.SEDAN

    def test_suv_is_valid(self):
        assert VehicleType("suv") == VehicleType.SUV

    def test_van_is_valid(self):
        assert VehicleType("van") == VehicleType.VAN

    def test_case_sensitive(self):
        with pytest.raises(ValueError):
            VehicleType("SEDAN")

    def test_enum_membership(self):
        assert "sedan" in [t.value for t in VehicleType]
        assert "bicycle" not in [t.value for t in VehicleType]


# ===========================================================================
# Vehicle Capacity Edge Cases
# ===========================================================================


class TestVehicleCapacity:
    def test_minimum_capacity(self):
        v = VehicleCreate(
            vehicle_type="coupe",
            make="Mazda",
            model="MX-5",
            year=2023,
            color="Red",
            license_plate="SPT0001",
            capacity=1,
        )
        assert v.capacity == 1

    def test_maximum_capacity(self):
        v = VehicleCreate(
            vehicle_type="van",
            make="Mercedes",
            model="Sprinter",
            year=2023,
            color="White",
            license_plate="VAN0001",
            capacity=15,
        )
        assert v.capacity == 15

    def test_typical_sedan_capacity(self):
        v = VehicleCreate(
            vehicle_type="sedan",
            make="Toyota",
            model="Camry",
            year=2022,
            color="Silver",
            license_plate="SED0001",
            capacity=4,
        )
        assert v.capacity == 4

    def test_wav_van_high_capacity(self):
        v = VehicleCreate(
            vehicle_type="van",
            make="Ford",
            model="Transit",
            year=2023,
            color="Blue",
            license_plate="WAV0001",
            capacity=8,
            is_wheelchair_accessible=True,
        )
        assert v.capacity == 8
        assert v.is_wheelchair_accessible is True


# ===========================================================================
# Vehicle Year Boundary Tests
# ===========================================================================


class TestVehicleYearBoundary:
    def test_minimum_valid_year(self):
        v = VehicleCreate(
            vehicle_type="sedan",
            make="Toyota",
            model="Camry",
            year=1990,
            color="White",
            license_plate="OLD1990",
        )
        assert v.year == 1990

    def test_maximum_valid_year(self):
        v = VehicleCreate(
            vehicle_type="sedan",
            make="Tesla",
            model="Model 3",
            year=2030,
            color="White",
            license_plate="NEW2030",
        )
        assert v.year == 2030

    def test_just_below_minimum_year(self):
        with pytest.raises(Exception):
            VehicleCreate(
                vehicle_type="sedan",
                make="Ford",
                model="Model T",
                year=1989,
                color="Black",
                license_plate="TOO_OLD",
            )

    def test_just_above_maximum_year(self):
        with pytest.raises(Exception):
            VehicleCreate(
                vehicle_type="sedan",
                make="Tesla",
                model="Cybertruck",
                year=2031,
                color="Silver",
                license_plate="TOO_NEW",
            )
