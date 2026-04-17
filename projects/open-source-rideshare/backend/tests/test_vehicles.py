"""Tests for the vehicle management endpoint.

Covers:
  - VehicleType enum (all 9 string values)
  - VehicleServiceCategory enum (all 5 string values)
  - Vehicle ORM model (table name, columns, defaults)
  - add_vehicle endpoint (success, max-vehicle limit, invalid type)
  - list_vehicles endpoint (happy path)
  - get_vehicle endpoint (found, 404)
  - update_vehicle endpoint (success, 404, invalid type)
  - remove_vehicle endpoint (soft-delete, clears active_vehicle_id, 404)
  - set_active_vehicle endpoint (success, 404 if inactive/missing)
  - VehicleCreate / VehicleUpdate / VehicleResponse schema validation

No live database is used. All DB interactions are mocked with AsyncMock /
MagicMock, following the pattern established in test_cancellation_policies.py
and test_vehicle_management.py.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.models.vehicle import Vehicle, VehicleServiceCategory, VehicleType
from app.schemas.vehicle import VehicleCreate, VehicleResponse, VehicleUpdate

_UTC = timezone.utc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(_UTC)


def _make_vehicle(
    vehicle_id: int = 1,
    driver_profile_id: int = 10,
    vehicle_type: VehicleType = VehicleType.SEDAN,
    service_category: VehicleServiceCategory = VehicleServiceCategory.STANDARD,
    make: str = "Toyota",
    model: str = "Camry",
    year: int = 2022,
    color: str = "Blue",
    license_plate: str = "ABC-123",
    capacity: int = 4,
    is_wheelchair_accessible: bool = False,
    is_active: bool = True,
) -> MagicMock:
    """Build a Vehicle ORM mock with sensible defaults."""
    v = MagicMock(spec=Vehicle)
    v.id = vehicle_id
    v.driver_profile_id = driver_profile_id
    v.vehicle_type = vehicle_type
    v.service_category = service_category
    v.make = make
    v.model = model
    v.year = year
    v.color = color
    v.license_plate = license_plate
    v.capacity = capacity
    v.is_wheelchair_accessible = is_wheelchair_accessible
    v.is_active = is_active
    v.created_at = _now()
    v.updated_at = _now()
    return v


def _make_profile(
    profile_id: int = 10,
    user_id: int = 1,
    active_vehicle_id: int | None = None,
) -> MagicMock:
    """Build a DriverProfile ORM mock."""
    from app.models.driver import DriverProfile

    p = MagicMock(spec=DriverProfile)
    p.id = profile_id
    p.user_id = user_id
    p.active_vehicle_id = active_vehicle_id
    return p


def _make_user(user_id: int = 1) -> MagicMock:
    """Build a User ORM mock."""
    from app.models.user import User

    u = MagicMock(spec=User)
    u.id = user_id
    return u


def _scalar_result(value) -> MagicMock:
    r = MagicMock()
    r.scalar_one_or_none.return_value = value
    return r


def _scalars_all_result(items: list) -> MagicMock:
    r = MagicMock()
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = items
    r.scalars.return_value = scalars_mock
    return r


def _db_sequence(*side_effects) -> AsyncMock:
    """DB mock whose execute() returns each MagicMock result in turn."""
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=list(side_effects))
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.delete = AsyncMock()
    return db


# ===========================================================================
# TestVehicleTypeEnum
# ===========================================================================


class TestVehicleTypeEnum:
    def test_sedan_value(self):
        assert VehicleType.SEDAN.value == "sedan"

    def test_suv_value(self):
        assert VehicleType.SUV.value == "suv"

    def test_van_value(self):
        assert VehicleType.VAN.value == "van"

    def test_minivan_value(self):
        assert VehicleType.MINIVAN.value == "minivan"

    def test_truck_value(self):
        assert VehicleType.TRUCK.value == "truck"

    def test_hatchback_value(self):
        assert VehicleType.HATCHBACK.value == "hatchback"

    def test_coupe_value(self):
        assert VehicleType.COUPE.value == "coupe"

    def test_wagon_value(self):
        assert VehicleType.WAGON.value == "wagon"

    def test_other_value(self):
        assert VehicleType.OTHER.value == "other"

    def test_nine_members(self):
        assert len(VehicleType) == 9

    def test_is_str_enum(self):
        assert isinstance(VehicleType.SEDAN, str)

    def test_from_string_sedan(self):
        assert VehicleType("sedan") == VehicleType.SEDAN

    def test_from_string_suv(self):
        assert VehicleType("suv") == VehicleType.SUV

    def test_invalid_type_raises(self):
        with pytest.raises(ValueError):
            VehicleType("bicycle")


# ===========================================================================
# TestVehicleServiceCategoryEnum
# ===========================================================================


class TestVehicleServiceCategoryEnum:
    def test_standard_value(self):
        assert VehicleServiceCategory.STANDARD.value == "standard"

    def test_comfort_value(self):
        assert VehicleServiceCategory.COMFORT.value == "comfort"

    def test_xl_value(self):
        assert VehicleServiceCategory.XL.value == "xl"

    def test_premium_value(self):
        assert VehicleServiceCategory.PREMIUM.value == "premium"

    def test_wav_value(self):
        assert VehicleServiceCategory.WAV.value == "wav"

    def test_five_members(self):
        assert len(VehicleServiceCategory) == 5

    def test_is_str_enum(self):
        assert isinstance(VehicleServiceCategory.STANDARD, str)

    def test_from_string_wav(self):
        assert VehicleServiceCategory("wav") == VehicleServiceCategory.WAV

    def test_invalid_category_raises(self):
        with pytest.raises(ValueError):
            VehicleServiceCategory("economy")


# ===========================================================================
# TestVehicleModel
# ===========================================================================


class TestVehicleModel:
    def _columns(self):
        return {c.name for c in Vehicle.__table__.columns}

    def test_table_name(self):
        assert Vehicle.__tablename__ == "vehicles"

    def test_has_id(self):
        assert "id" in self._columns()

    def test_has_driver_profile_id(self):
        assert "driver_profile_id" in self._columns()

    def test_has_vehicle_type(self):
        assert "vehicle_type" in self._columns()

    def test_has_service_category(self):
        assert "service_category" in self._columns()

    def test_has_make(self):
        assert "make" in self._columns()

    def test_has_model(self):
        assert "model" in self._columns()

    def test_has_year(self):
        assert "year" in self._columns()

    def test_has_color(self):
        assert "color" in self._columns()

    def test_has_license_plate(self):
        assert "license_plate" in self._columns()

    def test_has_capacity(self):
        assert "capacity" in self._columns()

    def test_has_is_wheelchair_accessible(self):
        assert "is_wheelchair_accessible" in self._columns()

    def test_has_is_active(self):
        assert "is_active" in self._columns()

    def test_has_created_at(self):
        assert "created_at" in self._columns()

    def test_has_updated_at(self):
        assert "updated_at" in self._columns()

    def test_driver_profile_id_indexed(self):
        col = Vehicle.__table__.columns["driver_profile_id"]
        assert col.index is True

    def test_capacity_default_four(self):
        col = Vehicle.__table__.columns["capacity"]
        assert col.default.arg == 4

    def test_is_active_default_true(self):
        col = Vehicle.__table__.columns["is_active"]
        assert col.default.arg is True

    def test_is_wheelchair_accessible_default_false(self):
        col = Vehicle.__table__.columns["is_wheelchair_accessible"]
        assert col.default.arg is False


# ===========================================================================
# TestAddVehicle
# ===========================================================================


class TestAddVehicle:
    @pytest.mark.asyncio
    async def test_success_first_vehicle_sets_active_vehicle_id(self):
        from app.api.v1.vehicles import add_vehicle

        user = _make_user()
        mock_profile = _make_profile(active_vehicle_id=None)
        mock_vehicle = _make_vehicle(vehicle_id=1)

        # execute calls: (1) profile fetch, (2) count active vehicles
        profile_result = _scalar_result(mock_profile)
        count_result = _scalars_all_result([])  # 0 active vehicles

        db = _db_sequence(profile_result, count_result)

        async def _refresh(obj):
            obj.id = mock_vehicle.id
            obj.driver_profile_id = mock_profile.id
            obj.vehicle_type = VehicleType.SEDAN
            obj.make = "Toyota"
            obj.model = "Camry"
            obj.year = 2022
            obj.color = "Blue"
            obj.license_plate = "ABC-123"
            obj.capacity = 4
            obj.is_wheelchair_accessible = False
            obj.is_active = True
            obj.created_at = mock_vehicle.created_at

        db.refresh = _refresh

        req = VehicleCreate(
            vehicle_type="sedan",
            make="Toyota",
            model="Camry",
            year=2022,
            color="Blue",
            license_plate="ABC-123",
        )

        result = await add_vehicle(req=req, user=user, db=db)

        assert result.id == 1
        # active_vehicle_id should be set to the new vehicle
        assert mock_profile.active_vehicle_id == 1

    @pytest.mark.asyncio
    async def test_success_when_active_vehicle_already_set(self):
        from app.api.v1.vehicles import add_vehicle

        user = _make_user()
        # Profile already has an active vehicle — should NOT override it
        mock_profile = _make_profile(active_vehicle_id=99)
        mock_vehicle = _make_vehicle(vehicle_id=2)

        profile_result = _scalar_result(mock_profile)
        count_result = _scalars_all_result([_make_vehicle(vehicle_id=99)])

        db = _db_sequence(profile_result, count_result)

        async def _refresh(obj):
            obj.id = mock_vehicle.id
            obj.driver_profile_id = mock_profile.id
            obj.vehicle_type = VehicleType.SUV
            obj.make = "Ford"
            obj.model = "Explorer"
            obj.year = 2021
            obj.color = "Red"
            obj.license_plate = "XYZ-789"
            obj.capacity = 7
            obj.is_wheelchair_accessible = False
            obj.is_active = True
            obj.created_at = mock_vehicle.created_at

        db.refresh = _refresh

        req = VehicleCreate(
            vehicle_type="suv",
            make="Ford",
            model="Explorer",
            year=2021,
            color="Red",
            license_plate="XYZ-789",
            capacity=7,
        )

        result = await add_vehicle(req=req, user=user, db=db)

        # active_vehicle_id should remain 99, not overridden
        assert mock_profile.active_vehicle_id == 99
        assert result.id == 2

    @pytest.mark.asyncio
    async def test_max_vehicles_raises_409(self):
        from app.api.v1.vehicles import add_vehicle

        user = _make_user()
        mock_profile = _make_profile(active_vehicle_id=1)

        # 5 active vehicles already
        existing_vehicles = [_make_vehicle(vehicle_id=i) for i in range(1, 6)]
        profile_result = _scalar_result(mock_profile)
        count_result = _scalars_all_result(existing_vehicles)

        db = _db_sequence(profile_result, count_result)

        req = VehicleCreate(
            vehicle_type="sedan",
            make="Honda",
            model="Civic",
            year=2020,
            color="White",
            license_plate="DEF-456",
        )

        with pytest.raises(HTTPException) as exc_info:
            await add_vehicle(req=req, user=user, db=db)

        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_invalid_vehicle_type_raises_422(self):
        from app.api.v1.vehicles import add_vehicle

        user = _make_user()
        mock_profile = _make_profile()
        profile_result = _scalar_result(mock_profile)
        count_result = _scalars_all_result([])

        db = _db_sequence(profile_result, count_result)

        # Bypass Pydantic schema validation to inject an invalid type
        req = MagicMock(spec=VehicleCreate)
        req.vehicle_type = "rocketship"
        req.make = "Acme"
        req.model = "X1"
        req.year = 2022
        req.color = "Green"
        req.license_plate = "GHI-101"
        req.capacity = 4
        req.is_wheelchair_accessible = False

        with pytest.raises(HTTPException) as exc_info:
            await add_vehicle(req=req, user=user, db=db)

        assert exc_info.value.status_code == 422

    @pytest.mark.asyncio
    async def test_driver_profile_not_found_raises_404(self):
        from app.api.v1.vehicles import add_vehicle

        user = _make_user()
        db = _db_sequence(_scalar_result(None))

        req = VehicleCreate(
            vehicle_type="sedan",
            make="Toyota",
            model="Camry",
            year=2022,
            color="Blue",
            license_plate="ABC-123",
        )

        with pytest.raises(HTTPException) as exc_info:
            await add_vehicle(req=req, user=user, db=db)

        assert exc_info.value.status_code == 404


# ===========================================================================
# TestListVehicles
# ===========================================================================


class TestListVehicles:
    @pytest.mark.asyncio
    async def test_returns_active_vehicle_list(self):
        from app.api.v1.vehicles import list_vehicles

        user = _make_user()
        mock_profile = _make_profile()
        vehicles = [_make_vehicle(vehicle_id=i) for i in range(1, 4)]

        profile_result = _scalar_result(mock_profile)
        vehicles_result = _scalars_all_result(vehicles)

        db = _db_sequence(profile_result, vehicles_result)

        result = await list_vehicles(user=user, db=db)

        assert isinstance(result, list)
        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_empty_vehicle_list(self):
        from app.api.v1.vehicles import list_vehicles

        user = _make_user()
        mock_profile = _make_profile()

        db = _db_sequence(_scalar_result(mock_profile), _scalars_all_result([]))

        result = await list_vehicles(user=user, db=db)

        assert result == []

    @pytest.mark.asyncio
    async def test_vehicle_response_structure(self):
        from app.api.v1.vehicles import list_vehicles

        user = _make_user()
        mock_profile = _make_profile()
        vehicle = _make_vehicle(vehicle_id=5, make="Honda", model="CR-V", year=2023)

        db = _db_sequence(
            _scalar_result(mock_profile),
            _scalars_all_result([vehicle]),
        )

        result = await list_vehicles(user=user, db=db)

        assert len(result) == 1
        assert result[0].make == "Honda"
        assert result[0].model == "CR-V"
        assert result[0].year == 2023

    @pytest.mark.asyncio
    async def test_profile_not_found_raises_404(self):
        from app.api.v1.vehicles import list_vehicles

        user = _make_user()
        db = _db_sequence(_scalar_result(None))

        with pytest.raises(HTTPException) as exc_info:
            await list_vehicles(user=user, db=db)

        assert exc_info.value.status_code == 404


# ===========================================================================
# TestGetVehicle
# ===========================================================================


class TestGetVehicle:
    @pytest.mark.asyncio
    async def test_success_returns_vehicle(self):
        from app.api.v1.vehicles import get_vehicle

        user = _make_user()
        mock_profile = _make_profile()
        mock_vehicle = _make_vehicle(vehicle_id=7, make="Kia", model="Sorento", year=2021)

        db = _db_sequence(
            _scalar_result(mock_profile),
            _scalar_result(mock_vehicle),
        )

        result = await get_vehicle(vehicle_id=7, user=user, db=db)

        assert result.id == 7
        assert result.make == "Kia"

    @pytest.mark.asyncio
    async def test_not_found_raises_404(self):
        from app.api.v1.vehicles import get_vehicle

        user = _make_user()
        mock_profile = _make_profile()

        db = _db_sequence(
            _scalar_result(mock_profile),
            _scalar_result(None),
        )

        with pytest.raises(HTTPException) as exc_info:
            await get_vehicle(vehicle_id=999, user=user, db=db)

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_profile_not_found_raises_404(self):
        from app.api.v1.vehicles import get_vehicle

        user = _make_user()
        db = _db_sequence(_scalar_result(None))

        with pytest.raises(HTTPException) as exc_info:
            await get_vehicle(vehicle_id=7, user=user, db=db)

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_returns_correct_vehicle_id(self):
        from app.api.v1.vehicles import get_vehicle

        user = _make_user()
        mock_profile = _make_profile()
        mock_vehicle = _make_vehicle(vehicle_id=42)

        db = _db_sequence(
            _scalar_result(mock_profile),
            _scalar_result(mock_vehicle),
        )

        result = await get_vehicle(vehicle_id=42, user=user, db=db)

        assert result.id == 42


# ===========================================================================
# TestUpdateVehicle
# ===========================================================================


class TestUpdateVehicle:
    @pytest.mark.asyncio
    async def test_success_updates_color(self):
        from app.api.v1.vehicles import update_vehicle

        user = _make_user()
        mock_profile = _make_profile()
        mock_vehicle = _make_vehicle(color="Blue")

        db = _db_sequence(
            _scalar_result(mock_profile),
            _scalar_result(mock_vehicle),
        )

        async def _refresh(obj):
            obj.color = "Red"

        db.refresh = _refresh

        req = VehicleUpdate(color="Red")
        result = await update_vehicle(vehicle_id=1, req=req, user=user, db=db)

        assert result.color == "Red"

    @pytest.mark.asyncio
    async def test_not_found_raises_404(self):
        from app.api.v1.vehicles import update_vehicle

        user = _make_user()
        mock_profile = _make_profile()

        db = _db_sequence(
            _scalar_result(mock_profile),
            _scalar_result(None),
        )

        req = VehicleUpdate(color="Green")
        with pytest.raises(HTTPException) as exc_info:
            await update_vehicle(vehicle_id=999, req=req, user=user, db=db)

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_invalid_vehicle_type_raises_422(self):
        from app.api.v1.vehicles import update_vehicle

        user = _make_user()
        mock_profile = _make_profile()
        mock_vehicle = _make_vehicle()

        db = _db_sequence(
            _scalar_result(mock_profile),
            _scalar_result(mock_vehicle),
        )

        # Bypass schema validation to inject invalid type directly
        req = MagicMock(spec=VehicleUpdate)
        req.model_dump.return_value = {"vehicle_type": "hovercraft"}

        with pytest.raises(HTTPException) as exc_info:
            await update_vehicle(vehicle_id=1, req=req, user=user, db=db)

        assert exc_info.value.status_code == 422

    @pytest.mark.asyncio
    async def test_db_commit_called_on_success(self):
        from app.api.v1.vehicles import update_vehicle

        user = _make_user()
        mock_profile = _make_profile()
        mock_vehicle = _make_vehicle()

        db = _db_sequence(
            _scalar_result(mock_profile),
            _scalar_result(mock_vehicle),
        )

        req = VehicleUpdate(make="Nissan")
        await update_vehicle(vehicle_id=1, req=req, user=user, db=db)

        db.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_valid_vehicle_type_update_succeeds(self):
        from app.api.v1.vehicles import update_vehicle

        user = _make_user()
        mock_profile = _make_profile()
        mock_vehicle = _make_vehicle(vehicle_type=VehicleType.SEDAN)

        db = _db_sequence(
            _scalar_result(mock_profile),
            _scalar_result(mock_vehicle),
        )

        async def _refresh(obj):
            obj.vehicle_type = VehicleType.SUV

        db.refresh = _refresh

        req = VehicleUpdate(vehicle_type="suv")
        result = await update_vehicle(vehicle_id=1, req=req, user=user, db=db)

        assert result.vehicle_type == "suv"


# ===========================================================================
# TestRemoveVehicle
# ===========================================================================


class TestRemoveVehicle:
    @pytest.mark.asyncio
    async def test_success_soft_deletes(self):
        from app.api.v1.vehicles import remove_vehicle

        user = _make_user()
        mock_profile = _make_profile(active_vehicle_id=99)
        mock_vehicle = _make_vehicle(vehicle_id=1, is_active=True)

        db = _db_sequence(
            _scalar_result(mock_profile),
            _scalar_result(mock_vehicle),
        )

        result = await remove_vehicle(vehicle_id=1, user=user, db=db)

        assert mock_vehicle.is_active is False
        assert result == {"status": "removed"}

    @pytest.mark.asyncio
    async def test_clears_active_vehicle_id_when_matches(self):
        from app.api.v1.vehicles import remove_vehicle

        user = _make_user()
        mock_profile = _make_profile(active_vehicle_id=1)
        mock_vehicle = _make_vehicle(vehicle_id=1)

        db = _db_sequence(
            _scalar_result(mock_profile),
            _scalar_result(mock_vehicle),
        )

        await remove_vehicle(vehicle_id=1, user=user, db=db)

        assert mock_profile.active_vehicle_id is None

    @pytest.mark.asyncio
    async def test_does_not_clear_active_vehicle_id_when_different(self):
        from app.api.v1.vehicles import remove_vehicle

        user = _make_user()
        mock_profile = _make_profile(active_vehicle_id=99)
        mock_vehicle = _make_vehicle(vehicle_id=1)

        db = _db_sequence(
            _scalar_result(mock_profile),
            _scalar_result(mock_vehicle),
        )

        await remove_vehicle(vehicle_id=1, user=user, db=db)

        assert mock_profile.active_vehicle_id == 99

    @pytest.mark.asyncio
    async def test_not_found_raises_404(self):
        from app.api.v1.vehicles import remove_vehicle

        user = _make_user()
        mock_profile = _make_profile()

        db = _db_sequence(
            _scalar_result(mock_profile),
            _scalar_result(None),
        )

        with pytest.raises(HTTPException) as exc_info:
            await remove_vehicle(vehicle_id=999, user=user, db=db)

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_db_commit_called(self):
        from app.api.v1.vehicles import remove_vehicle

        user = _make_user()
        mock_profile = _make_profile()
        mock_vehicle = _make_vehicle(vehicle_id=1)

        db = _db_sequence(
            _scalar_result(mock_profile),
            _scalar_result(mock_vehicle),
        )

        await remove_vehicle(vehicle_id=1, user=user, db=db)

        db.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_returns_status_removed(self):
        from app.api.v1.vehicles import remove_vehicle

        user = _make_user()
        mock_profile = _make_profile()
        mock_vehicle = _make_vehicle(vehicle_id=2)

        db = _db_sequence(
            _scalar_result(mock_profile),
            _scalar_result(mock_vehicle),
        )

        result = await remove_vehicle(vehicle_id=2, user=user, db=db)

        assert result["status"] == "removed"


# ===========================================================================
# TestSetActiveVehicle
# ===========================================================================


class TestSetActiveVehicle:
    @pytest.mark.asyncio
    async def test_success_sets_active_vehicle_id(self):
        from app.api.v1.vehicles import set_active_vehicle

        user = _make_user()
        mock_profile = _make_profile(active_vehicle_id=None)
        mock_vehicle = _make_vehicle(vehicle_id=5, is_active=True)

        db = _db_sequence(
            _scalar_result(mock_profile),
            _scalar_result(mock_vehicle),
        )

        result = await set_active_vehicle(vehicle_id=5, user=user, db=db)

        assert mock_profile.active_vehicle_id == 5
        assert result.id == 5

    @pytest.mark.asyncio
    async def test_not_found_raises_404(self):
        from app.api.v1.vehicles import set_active_vehicle

        user = _make_user()
        mock_profile = _make_profile()

        db = _db_sequence(
            _scalar_result(mock_profile),
            _scalar_result(None),
        )

        with pytest.raises(HTTPException) as exc_info:
            await set_active_vehicle(vehicle_id=999, user=user, db=db)

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_404_detail_mentions_inactive(self):
        from app.api.v1.vehicles import set_active_vehicle

        user = _make_user()
        mock_profile = _make_profile()

        db = _db_sequence(
            _scalar_result(mock_profile),
            _scalar_result(None),
        )

        with pytest.raises(HTTPException) as exc_info:
            await set_active_vehicle(vehicle_id=1, user=user, db=db)

        assert "inactive" in exc_info.value.detail.lower() or "not found" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_db_commit_called(self):
        from app.api.v1.vehicles import set_active_vehicle

        user = _make_user()
        mock_profile = _make_profile()
        mock_vehicle = _make_vehicle(vehicle_id=3, is_active=True)

        db = _db_sequence(
            _scalar_result(mock_profile),
            _scalar_result(mock_vehicle),
        )

        await set_active_vehicle(vehicle_id=3, user=user, db=db)

        db.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_returns_vehicle_response(self):
        from app.api.v1.vehicles import set_active_vehicle

        user = _make_user()
        mock_profile = _make_profile()
        mock_vehicle = _make_vehicle(vehicle_id=8, make="BMW", is_active=True)

        db = _db_sequence(
            _scalar_result(mock_profile),
            _scalar_result(mock_vehicle),
        )

        result = await set_active_vehicle(vehicle_id=8, user=user, db=db)

        assert isinstance(result, VehicleResponse)
        assert result.make == "BMW"


# ===========================================================================
# TestVehicleSchemas
# ===========================================================================


class TestVehicleSchemas:
    def test_create_year_below_1990_raises(self):
        with pytest.raises(ValidationError):
            VehicleCreate(
                vehicle_type="sedan",
                make="Toyota",
                model="Camry",
                year=1989,
                color="Blue",
                license_plate="ABC-123",
            )

    def test_create_year_above_2030_raises(self):
        with pytest.raises(ValidationError):
            VehicleCreate(
                vehicle_type="sedan",
                make="Toyota",
                model="Camry",
                year=2031,
                color="Blue",
                license_plate="ABC-123",
            )

    def test_create_valid_year(self):
        schema = VehicleCreate(
            vehicle_type="sedan",
            make="Toyota",
            model="Camry",
            year=2022,
            color="Blue",
            license_plate="ABC-123",
        )
        assert schema.year == 2022

    def test_create_year_boundary_1990(self):
        schema = VehicleCreate(
            vehicle_type="van",
            make="Dodge",
            model="Caravan",
            year=1990,
            color="White",
            license_plate="OLD-001",
        )
        assert schema.year == 1990

    def test_create_year_boundary_2030(self):
        schema = VehicleCreate(
            vehicle_type="suv",
            make="Tesla",
            model="Model X",
            year=2030,
            color="Black",
            license_plate="FUT-030",
        )
        assert schema.year == 2030

    def test_create_capacity_below_1_raises(self):
        with pytest.raises(ValidationError):
            VehicleCreate(
                vehicle_type="sedan",
                make="Toyota",
                model="Camry",
                year=2022,
                color="Blue",
                license_plate="ABC-123",
                capacity=0,
            )

    def test_create_capacity_above_15_raises(self):
        with pytest.raises(ValidationError):
            VehicleCreate(
                vehicle_type="van",
                make="Ford",
                model="Transit",
                year=2021,
                color="White",
                license_plate="BIG-999",
                capacity=16,
            )

    def test_create_valid_capacity(self):
        schema = VehicleCreate(
            vehicle_type="van",
            make="Ford",
            model="Transit",
            year=2021,
            color="White",
            license_plate="BIG-999",
            capacity=15,
        )
        assert schema.capacity == 15

    def test_create_capacity_boundary_1(self):
        schema = VehicleCreate(
            vehicle_type="sedan",
            make="Honda",
            model="Civic",
            year=2020,
            color="Red",
            license_plate="MIN-001",
            capacity=1,
        )
        assert schema.capacity == 1

    def test_create_default_capacity_is_four(self):
        schema = VehicleCreate(
            vehicle_type="sedan",
            make="Honda",
            model="Civic",
            year=2020,
            color="Red",
            license_plate="DEF-004",
        )
        assert schema.capacity == 4

    def test_create_default_wheelchair_accessible_false(self):
        schema = VehicleCreate(
            vehicle_type="sedan",
            make="Toyota",
            model="Camry",
            year=2022,
            color="Blue",
            license_plate="WAV-000",
        )
        assert schema.is_wheelchair_accessible is False

    def test_update_all_fields_optional(self):
        schema = VehicleUpdate()
        assert schema.vehicle_type is None
        assert schema.make is None
        assert schema.model is None
        assert schema.year is None
        assert schema.color is None
        assert schema.license_plate is None
        assert schema.capacity is None
        assert schema.is_wheelchair_accessible is None

    def test_update_year_below_1990_raises(self):
        with pytest.raises(ValidationError):
            VehicleUpdate(year=1985)

    def test_update_year_above_2030_raises(self):
        with pytest.raises(ValidationError):
            VehicleUpdate(year=2035)

    def test_update_valid_year(self):
        schema = VehicleUpdate(year=2025)
        assert schema.year == 2025

    def test_update_capacity_below_1_raises(self):
        with pytest.raises(ValidationError):
            VehicleUpdate(capacity=0)

    def test_update_capacity_above_15_raises(self):
        with pytest.raises(ValidationError):
            VehicleUpdate(capacity=20)

    def test_update_valid_capacity(self):
        schema = VehicleUpdate(capacity=8)
        assert schema.capacity == 8

    def test_update_none_year_is_valid(self):
        schema = VehicleUpdate(year=None)
        assert schema.year is None

    def test_update_none_capacity_is_valid(self):
        schema = VehicleUpdate(capacity=None)
        assert schema.capacity is None

    def test_response_from_dict(self):
        now = _now()
        resp = VehicleResponse(
            id=1,
            driver_profile_id=10,
            vehicle_type="sedan",
            make="Toyota",
            model="Camry",
            year=2022,
            color="Blue",
            license_plate="ABC-123",
            capacity=4,
            is_wheelchair_accessible=False,
            is_active=True,
            created_at=now,
        )
        assert resp.id == 1
        assert resp.vehicle_type == "sedan"
        assert resp.is_active is True

    def test_response_from_attributes_orm_mock(self):
        mock_vehicle = _make_vehicle(vehicle_id=3, make="Mazda")

        resp = VehicleResponse.model_validate(mock_vehicle)

        assert resp.id == 3
        assert resp.make == "Mazda"

    def test_response_wheelchair_accessible_true(self):
        now = _now()
        resp = VehicleResponse(
            id=2,
            driver_profile_id=10,
            vehicle_type="van",
            make="BraunAbility",
            model="Entervan",
            year=2023,
            color="White",
            license_plate="WAV-001",
            capacity=4,
            is_wheelchair_accessible=True,
            is_active=True,
            created_at=now,
        )
        assert resp.is_wheelchair_accessible is True
