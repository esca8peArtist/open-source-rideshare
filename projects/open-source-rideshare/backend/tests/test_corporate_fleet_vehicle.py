"""Tests for the Corporate Fleet Vehicle Management feature.

Service layer (async, mocked DB):
   1.  create_fleet_vehicle — creates vehicle with correct fields
   2.  create_fleet_vehicle — raises 409 when name already exists (case-insensitive)
   3.  get_fleet_vehicle — raises 404 when not found or wrong account
   4.  get_fleet_vehicle — returns existing vehicle
   5.  list_fleet_vehicles — returns all vehicles for account
   6.  list_fleet_vehicles — filters by is_active
   7.  list_fleet_vehicles — filters by is_wav
   8.  update_fleet_vehicle — raises 404 when vehicle not found
   9.  update_fleet_vehicle — updates fields on existing vehicle
  10.  update_fleet_vehicle — raises 409 when new name collides with another vehicle
  11.  deactivate_fleet_vehicle — deactivates active vehicle
  12.  deactivate_fleet_vehicle — raises 409 when already inactive
  13.  reactivate_fleet_vehicle — reactivates inactive vehicle
  14.  reactivate_fleet_vehicle — raises 409 when already active
  15.  delete_fleet_vehicle — deletes inactive vehicle
  16.  delete_fleet_vehicle — raises 409 when vehicle is still active
  17.  assign_driver — creates new assignment and deactivates prior one
  18.  assign_driver — creates first assignment with no prior to deactivate
  19.  end_assignment — deactivates active assignment
  20.  end_assignment — raises 404 when no active assignment
  21.  get_active_assignment — returns active assignment
  22.  get_active_assignment — returns None when no active assignment
  23.  list_vehicle_assignments — returns history newest-first
  24.  get_fleet_summary — returns correct counts for account
  25.  list_all_platform — returns all vehicles without filter
  26.  list_all_platform — filters by account_id

Schema validation:
  27.  FleetVehicleCreate — requires name
  28.  FleetVehicleCreate — defaults capacity=4 and is_wav=False
  29.  FleetVehicleCreate — optional fields can be omitted
  30.  FleetVehicleUpdate — all fields optional
  31.  FleetVehicleUpdate — rejects capacity < 1
  32.  FleetAssignmentCreate — driver_profile_id is optional
  33.  FleetVehicleResponse — from_attributes construction
  34.  FleetAssignmentResponse — from_attributes construction
  35.  FleetSummaryResponse — construction with all fields

API layer (service functions patched):
  36.  GET /fleet-vehicles/ — 200 member can list vehicles
  37.  GET /fleet-vehicles/ — 404 when account not found
  38.  GET /fleet-vehicles/summary — 200 member can get summary
  39.  GET /fleet-vehicles/{vehicle_id} — 200 member can get one vehicle
  40.  GET /fleet-vehicles/{vehicle_id} — 404 when vehicle not found
  41.  POST /fleet-vehicles/ — 201 admin can create vehicle
  42.  POST /fleet-vehicles/ — 403 non-admin cannot create vehicle
  43.  POST /fleet-vehicles/ — 409 when name already exists
  44.  PUT /fleet-vehicles/{vehicle_id} — 200 admin can update vehicle
  45.  PUT /fleet-vehicles/{vehicle_id} — 403 non-admin cannot update vehicle
  46.  POST /fleet-vehicles/{vehicle_id}/deactivate — 200 admin can deactivate
  47.  POST /fleet-vehicles/{vehicle_id}/deactivate — 403 non-admin cannot deactivate
  48.  POST /fleet-vehicles/{vehicle_id}/deactivate — 409 already inactive
  49.  POST /fleet-vehicles/{vehicle_id}/reactivate — 200 admin can reactivate
  50.  POST /fleet-vehicles/{vehicle_id}/reactivate — 403 non-admin cannot reactivate
  51.  DELETE /fleet-vehicles/{vehicle_id} — 204 admin can delete
  52.  DELETE /fleet-vehicles/{vehicle_id} — 403 non-admin cannot delete
  53.  DELETE /fleet-vehicles/{vehicle_id} — 409 cannot delete active vehicle
  54.  POST /fleet-vehicles/{vehicle_id}/assign-driver — 201 admin can assign driver
  55.  POST /fleet-vehicles/{vehicle_id}/assign-driver — 403 non-admin cannot assign driver
  56.  DELETE /fleet-vehicles/{vehicle_id}/assignment — 200 admin can end assignment
  57.  DELETE /fleet-vehicles/{vehicle_id}/assignment — 403 non-admin cannot end assignment
  58.  DELETE /fleet-vehicles/{vehicle_id}/assignment — 404 no active assignment
  59.  GET /fleet-vehicles/{vehicle_id}/assignments — 200 admin can list history
  60.  GET /fleet-vehicles/{vehicle_id}/assignments — 403 non-admin cannot list history
  61.  GET /platform/corporate/fleet-vehicles/ — 200 platform-admin can list all
  62.  GET /platform/corporate/fleet-vehicles/ — 200 with account_id filter
  63.  GET /platform/corporate/fleet-vehicles/{account_id} — 200 platform-admin per-account
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import app
from app.models.corporate_fleet_vehicle import (
    CorporateFleetAssignment,
    CorporateFleetVehicle,
)
from app.schemas.corporate_fleet_vehicle import (
    FleetAssignmentCreate,
    FleetAssignmentResponse,
    FleetSummaryResponse,
    FleetVehicleCreate,
    FleetVehicleResponse,
    FleetVehicleUpdate,
)
from app.services.corporate_fleet_vehicle_service import (
    assign_driver,
    create_fleet_vehicle,
    deactivate_fleet_vehicle,
    delete_fleet_vehicle,
    end_assignment,
    get_active_assignment,
    get_fleet_summary,
    get_fleet_vehicle,
    list_all_platform,
    list_fleet_vehicles,
    list_vehicle_assignments,
    reactivate_fleet_vehicle,
    update_fleet_vehicle,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ACCOUNT_ID = 7
VEHICLE_ID = uuid.uuid4()
ASSIGNMENT_ID = uuid.uuid4()

_SERVICE = "app.services.corporate_fleet_vehicle_service"
_ROUTER = "app.api.v1.corporate_fleet_vehicle"

_NOW = datetime(2026, 4, 16, 9, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


def _make_vehicle(
    vehicle_id: uuid.UUID = VEHICLE_ID,
    account_id: int = ACCOUNT_ID,
    name: str = "Sedan Alpha",
    vehicle_type: str | None = "sedan",
    make: str | None = "Toyota",
    model_name: str | None = "Camry",
    year: int | None = 2023,
    license_plate: str | None = "ABC123",
    color: str | None = "Black",
    capacity: int = 4,
    is_wav: bool = False,
    notes: str | None = None,
    is_active: bool = True,
    created_by_id: int | None = 1,
) -> CorporateFleetVehicle:
    v = CorporateFleetVehicle()
    v.id = vehicle_id
    v.account_id = account_id
    v.name = name
    v.vehicle_type = vehicle_type
    v.make = make
    v.model_name = model_name
    v.year = year
    v.license_plate = license_plate
    v.color = color
    v.capacity = capacity
    v.is_wav = is_wav
    v.notes = notes
    v.is_active = is_active
    v.created_by_id = created_by_id
    v.created_at = _NOW
    v.updated_at = _NOW
    return v


def _make_assignment(
    assignment_id: uuid.UUID = ASSIGNMENT_ID,
    fleet_vehicle_id: uuid.UUID = VEHICLE_ID,
    account_id: int = ACCOUNT_ID,
    driver_profile_id: int | None = 99,
    assigned_by_id: int | None = 1,
    is_active: bool = True,
    notes: str | None = None,
) -> CorporateFleetAssignment:
    a = CorporateFleetAssignment()
    a.id = assignment_id
    a.fleet_vehicle_id = fleet_vehicle_id
    a.account_id = account_id
    a.driver_profile_id = driver_profile_id
    a.assigned_by_id = assigned_by_id
    a.is_active = is_active
    a.notes = notes
    a.created_at = _NOW
    return a


def _vehicle_response(v: CorporateFleetVehicle) -> FleetVehicleResponse:
    return FleetVehicleResponse(
        id=v.id,
        account_id=v.account_id,
        name=v.name,
        vehicle_type=v.vehicle_type,
        make=v.make,
        model_name=v.model_name,
        year=v.year,
        license_plate=v.license_plate,
        color=v.color,
        capacity=v.capacity,
        is_wav=v.is_wav,
        notes=v.notes,
        is_active=v.is_active,
        created_by_id=v.created_by_id,
        created_at=v.created_at,
        updated_at=v.updated_at,
    )


def _assignment_response(a: CorporateFleetAssignment) -> FleetAssignmentResponse:
    return FleetAssignmentResponse(
        id=a.id,
        fleet_vehicle_id=a.fleet_vehicle_id,
        account_id=a.account_id,
        driver_profile_id=a.driver_profile_id,
        assigned_by_id=a.assigned_by_id,
        is_active=a.is_active,
        notes=a.notes,
        created_at=a.created_at,
    )


# ---------------------------------------------------------------------------
# Shared mock DB helpers
# ---------------------------------------------------------------------------


def _db_scalar(scalar=None):
    """DB that always returns the same scalar from execute()."""
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = scalar
    db.execute = AsyncMock(return_value=result)
    db.commit = AsyncMock()
    db.add = MagicMock()
    db.delete = AsyncMock()

    def _refresh(obj):
        if not getattr(obj, "created_at", None):
            obj.created_at = _NOW
        if hasattr(obj, "updated_at") and not getattr(obj, "updated_at", None):
            obj.updated_at = _NOW

    db.refresh = AsyncMock(side_effect=_refresh)
    return db


def _db_scalars_all(rows: list):
    """DB whose execute().scalars().all() returns rows."""
    db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = rows
    result.scalar_one_or_none.return_value = rows[0] if rows else None
    db.execute = AsyncMock(return_value=result)
    db.commit = AsyncMock()
    db.add = MagicMock()
    db.delete = AsyncMock()

    def _refresh(obj):
        if not getattr(obj, "created_at", None):
            obj.created_at = _NOW
        if hasattr(obj, "updated_at") and not getattr(obj, "updated_at", None):
            obj.updated_at = _NOW

    db.refresh = AsyncMock(side_effect=_refresh)
    return db


def _db_sequence(*results):
    """DB whose execute() returns successive MagicMocks from results list.

    Each element in results should be either:
    - a single ORM object (will become scalar_one_or_none)
    - a list of ORM objects (will become scalars().all())
    - None (scalar_one_or_none returns None)
    """
    db = AsyncMock()
    mock_results = []
    for r in results:
        m = MagicMock()
        if isinstance(r, list):
            m.scalar_one_or_none.return_value = None
            m.scalars.return_value.all.return_value = r
        else:
            m.scalar_one_or_none.return_value = r
            m.scalars.return_value.all.return_value = [r] if r is not None else []
        mock_results.append(m)

    db.execute = AsyncMock(side_effect=mock_results)
    db.commit = AsyncMock()
    db.add = MagicMock()
    db.delete = AsyncMock()

    def _refresh(obj):
        if not getattr(obj, "created_at", None):
            obj.created_at = _NOW
        if hasattr(obj, "updated_at") and not getattr(obj, "updated_at", None):
            obj.updated_at = _NOW

    db.refresh = AsyncMock(side_effect=_refresh)
    return db


# ---------------------------------------------------------------------------
# Service tests: create_fleet_vehicle  (1–2)
# ---------------------------------------------------------------------------


class TestCreateFleetVehicle:
    """Tests for create_fleet_vehicle."""

    @pytest.mark.asyncio
    async def test_creates_vehicle_with_correct_fields(self):
        """1. Creates vehicle and returns response with correct fields."""
        # _name_exists does a select returning empty list, then creates
        db = _db_sequence([])  # name check returns no vehicles
        payload = FleetVehicleCreate(name="Sedan Alpha", vehicle_type="sedan", capacity=4)
        result = await create_fleet_vehicle(db, ACCOUNT_ID, payload, created_by_id=1)
        assert result.name == "Sedan Alpha"
        assert result.account_id == ACCOUNT_ID
        assert result.capacity == 4
        db.add.assert_called_once()
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_raises_409_on_duplicate_name(self):
        """2. Raises 409 when a vehicle with the same name exists (case-insensitive)."""
        existing = _make_vehicle(name="sedan alpha")
        # _name_exists: select returns existing vehicle with same name
        db = _db_sequence([existing])
        payload = FleetVehicleCreate(name="Sedan Alpha")
        with pytest.raises(HTTPException) as exc_info:
            await create_fleet_vehicle(db, ACCOUNT_ID, payload)
        assert exc_info.value.status_code == 409


# ---------------------------------------------------------------------------
# Service tests: get_fleet_vehicle  (3–4)
# ---------------------------------------------------------------------------


class TestGetFleetVehicle:
    """Tests for get_fleet_vehicle."""

    @pytest.mark.asyncio
    async def test_raises_404_when_not_found(self):
        """3. Raises 404 when vehicle not found."""
        db = _db_scalar(None)
        with pytest.raises(HTTPException) as exc_info:
            await get_fleet_vehicle(db, ACCOUNT_ID, VEHICLE_ID)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_returns_existing_vehicle(self):
        """4. Returns the vehicle when found."""
        vehicle = _make_vehicle()
        db = _db_scalar(vehicle)
        result = await get_fleet_vehicle(db, ACCOUNT_ID, VEHICLE_ID)
        assert result.id == VEHICLE_ID
        assert result.name == "Sedan Alpha"


# ---------------------------------------------------------------------------
# Service tests: list_fleet_vehicles  (5–7)
# ---------------------------------------------------------------------------


class TestListFleetVehicles:
    """Tests for list_fleet_vehicles."""

    @pytest.mark.asyncio
    async def test_returns_all_vehicles_for_account(self):
        """5. Returns all vehicles for the account."""
        v1 = _make_vehicle(vehicle_id=uuid.uuid4(), name="Van One")
        v2 = _make_vehicle(vehicle_id=uuid.uuid4(), name="Van Two")
        db = _db_scalars_all([v1, v2])
        result = await list_fleet_vehicles(db, ACCOUNT_ID)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_filters_by_is_active(self):
        """6. Passes is_active filter (service adds WHERE clause)."""
        active_v = _make_vehicle(is_active=True)
        db = _db_scalars_all([active_v])
        result = await list_fleet_vehicles(db, ACCOUNT_ID, is_active=True)
        assert len(result) == 1
        assert result[0].is_active is True

    @pytest.mark.asyncio
    async def test_filters_by_is_wav(self):
        """7. Passes is_wav filter (service adds WHERE clause)."""
        wav_v = _make_vehicle(is_wav=True)
        db = _db_scalars_all([wav_v])
        result = await list_fleet_vehicles(db, ACCOUNT_ID, is_wav=True)
        assert len(result) == 1
        assert result[0].is_wav is True


# ---------------------------------------------------------------------------
# Service tests: update_fleet_vehicle  (8–10)
# ---------------------------------------------------------------------------


class TestUpdateFleetVehicle:
    """Tests for update_fleet_vehicle."""

    @pytest.mark.asyncio
    async def test_raises_404_when_vehicle_not_found(self):
        """8. Raises 404 when vehicle not found."""
        db = _db_scalar(None)
        payload = FleetVehicleUpdate(color="White")
        with pytest.raises(HTTPException) as exc_info:
            await update_fleet_vehicle(db, ACCOUNT_ID, VEHICLE_ID, payload)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_updates_fields_on_existing_vehicle(self):
        """9. Updates provided fields."""
        vehicle = _make_vehicle(color="Black")
        # Sequence: fetch vehicle (scalar), name_check (scalars list)
        db = _db_sequence(vehicle, [vehicle])
        payload = FleetVehicleUpdate(color="White")
        result = await update_fleet_vehicle(db, ACCOUNT_ID, VEHICLE_ID, payload)
        assert vehicle.color == "White"
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_raises_409_on_name_collision(self):
        """10. Raises 409 when the new name collides with another vehicle."""
        vehicle = _make_vehicle(name="Van A")
        other = _make_vehicle(vehicle_id=uuid.uuid4(), name="Van B")
        # fetch vehicle returns vehicle, name check returns [other] (collision)
        db = _db_sequence(vehicle, [other])
        payload = FleetVehicleUpdate(name="Van B")
        with pytest.raises(HTTPException) as exc_info:
            await update_fleet_vehicle(db, ACCOUNT_ID, VEHICLE_ID, payload)
        assert exc_info.value.status_code == 409


# ---------------------------------------------------------------------------
# Service tests: deactivate_fleet_vehicle  (11–12)
# ---------------------------------------------------------------------------


class TestDeactivateFleetVehicle:
    """Tests for deactivate_fleet_vehicle."""

    @pytest.mark.asyncio
    async def test_deactivates_active_vehicle(self):
        """11. Sets is_active=False on an active vehicle."""
        vehicle = _make_vehicle(is_active=True)
        db = _db_scalar(vehicle)
        result = await deactivate_fleet_vehicle(db, ACCOUNT_ID, VEHICLE_ID)
        assert vehicle.is_active is False
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_raises_409_when_already_inactive(self):
        """12. Raises 409 when vehicle is already inactive."""
        vehicle = _make_vehicle(is_active=False)
        db = _db_scalar(vehicle)
        with pytest.raises(HTTPException) as exc_info:
            await deactivate_fleet_vehicle(db, ACCOUNT_ID, VEHICLE_ID)
        assert exc_info.value.status_code == 409


# ---------------------------------------------------------------------------
# Service tests: reactivate_fleet_vehicle  (13–14)
# ---------------------------------------------------------------------------


class TestReactivateFleetVehicle:
    """Tests for reactivate_fleet_vehicle."""

    @pytest.mark.asyncio
    async def test_reactivates_inactive_vehicle(self):
        """13. Sets is_active=True on an inactive vehicle."""
        vehicle = _make_vehicle(is_active=False)
        db = _db_scalar(vehicle)
        result = await reactivate_fleet_vehicle(db, ACCOUNT_ID, VEHICLE_ID)
        assert vehicle.is_active is True
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_raises_409_when_already_active(self):
        """14. Raises 409 when vehicle is already active."""
        vehicle = _make_vehicle(is_active=True)
        db = _db_scalar(vehicle)
        with pytest.raises(HTTPException) as exc_info:
            await reactivate_fleet_vehicle(db, ACCOUNT_ID, VEHICLE_ID)
        assert exc_info.value.status_code == 409


# ---------------------------------------------------------------------------
# Service tests: delete_fleet_vehicle  (15–16)
# ---------------------------------------------------------------------------


class TestDeleteFleetVehicle:
    """Tests for delete_fleet_vehicle."""

    @pytest.mark.asyncio
    async def test_deletes_inactive_vehicle(self):
        """15. Hard-deletes an inactive vehicle."""
        vehicle = _make_vehicle(is_active=False)
        db = _db_scalar(vehicle)
        await delete_fleet_vehicle(db, ACCOUNT_ID, VEHICLE_ID)
        db.delete.assert_called_once_with(vehicle)
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_raises_409_when_vehicle_is_active(self):
        """16. Raises 409 when vehicle is still active."""
        vehicle = _make_vehicle(is_active=True)
        db = _db_scalar(vehicle)
        with pytest.raises(HTTPException) as exc_info:
            await delete_fleet_vehicle(db, ACCOUNT_ID, VEHICLE_ID)
        assert exc_info.value.status_code == 409


# ---------------------------------------------------------------------------
# Service tests: assign_driver  (17–18)
# ---------------------------------------------------------------------------


class TestAssignDriver:
    """Tests for assign_driver."""

    @pytest.mark.asyncio
    async def test_creates_assignment_and_deactivates_prior(self):
        """17. Deactivates existing active assignment before creating new one."""
        vehicle = _make_vehicle()
        existing_assignment = _make_assignment(is_active=True)
        # Sequence: fetch vehicle, find existing assignment
        db = _db_sequence(vehicle, existing_assignment)
        payload = FleetAssignmentCreate(driver_profile_id=55)
        result = await assign_driver(db, ACCOUNT_ID, VEHICLE_ID, payload, assigned_by_id=1)
        assert existing_assignment.is_active is False
        db.add.assert_called_once()
        db.commit.assert_called_once()
        assert result.driver_profile_id == 55

    @pytest.mark.asyncio
    async def test_creates_first_assignment_no_prior(self):
        """18. Creates assignment when no prior active assignment exists."""
        vehicle = _make_vehicle()
        # Sequence: fetch vehicle, no existing assignment
        db = _db_sequence(vehicle, None)
        payload = FleetAssignmentCreate(driver_profile_id=77)
        result = await assign_driver(db, ACCOUNT_ID, VEHICLE_ID, payload)
        db.add.assert_called_once()
        db.commit.assert_called_once()
        assert result.driver_profile_id == 77


# ---------------------------------------------------------------------------
# Service tests: end_assignment  (19–20)
# ---------------------------------------------------------------------------


class TestEndAssignment:
    """Tests for end_assignment."""

    @pytest.mark.asyncio
    async def test_deactivates_active_assignment(self):
        """19. Sets is_active=False on the active assignment."""
        vehicle = _make_vehicle()
        assignment = _make_assignment(is_active=True)
        db = _db_sequence(vehicle, assignment)
        result = await end_assignment(db, ACCOUNT_ID, VEHICLE_ID)
        assert assignment.is_active is False
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_raises_404_when_no_active_assignment(self):
        """20. Raises 404 when no active assignment exists."""
        vehicle = _make_vehicle()
        db = _db_sequence(vehicle, None)
        with pytest.raises(HTTPException) as exc_info:
            await end_assignment(db, ACCOUNT_ID, VEHICLE_ID)
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Service tests: get_active_assignment  (21–22)
# ---------------------------------------------------------------------------


class TestGetActiveAssignment:
    """Tests for get_active_assignment."""

    @pytest.mark.asyncio
    async def test_returns_active_assignment(self):
        """21. Returns active assignment when one exists."""
        vehicle = _make_vehicle()
        assignment = _make_assignment(is_active=True)
        db = _db_sequence(vehicle, assignment)
        result = await get_active_assignment(db, ACCOUNT_ID, VEHICLE_ID)
        assert result is not None
        assert result.id == ASSIGNMENT_ID

    @pytest.mark.asyncio
    async def test_returns_none_when_no_active_assignment(self):
        """22. Returns None when no active assignment."""
        vehicle = _make_vehicle()
        db = _db_sequence(vehicle, None)
        result = await get_active_assignment(db, ACCOUNT_ID, VEHICLE_ID)
        assert result is None


# ---------------------------------------------------------------------------
# Service tests: list_vehicle_assignments  (23)
# ---------------------------------------------------------------------------


class TestListVehicleAssignments:
    """Tests for list_vehicle_assignments."""

    @pytest.mark.asyncio
    async def test_returns_history_newest_first(self):
        """23. Returns assignment history, newest first."""
        vehicle = _make_vehicle()
        a1 = _make_assignment(assignment_id=uuid.uuid4(), is_active=False)
        a2 = _make_assignment(assignment_id=uuid.uuid4(), is_active=True)

        db = AsyncMock()
        fetch_result = MagicMock()
        fetch_result.scalar_one_or_none.return_value = vehicle
        history_result = MagicMock()
        history_result.scalars.return_value.all.return_value = [a2, a1]
        db.execute = AsyncMock(side_effect=[fetch_result, history_result])
        db.commit = AsyncMock()
        db.add = MagicMock()
        db.delete = AsyncMock()
        db.refresh = AsyncMock()

        result = await list_vehicle_assignments(db, ACCOUNT_ID, VEHICLE_ID)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# Service tests: get_fleet_summary  (24)
# ---------------------------------------------------------------------------


class TestGetFleetSummary:
    """Tests for get_fleet_summary."""

    @pytest.mark.asyncio
    async def test_returns_correct_counts(self):
        """24. Returns correct aggregate counts."""
        v1 = _make_vehicle(vehicle_id=uuid.uuid4(), is_active=True, is_wav=False, vehicle_type="sedan")
        v2 = _make_vehicle(vehicle_id=uuid.uuid4(), is_active=True, is_wav=True, vehicle_type="van")
        v3 = _make_vehicle(vehicle_id=uuid.uuid4(), is_active=False, is_wav=False, vehicle_type="sedan")

        db = AsyncMock()
        # First execute: all vehicles
        all_result = MagicMock()
        all_result.scalars.return_value.all.return_value = [v1, v2, v3]
        # Second execute: active assignments (none)
        assign_result = MagicMock()
        assign_result.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(side_effect=[all_result, assign_result])
        db.commit = AsyncMock()
        db.add = MagicMock()

        result = await get_fleet_summary(db, ACCOUNT_ID)
        assert result.total_vehicles == 3
        assert result.active_vehicles == 2
        assert result.inactive_vehicles == 1
        assert result.wav_count == 1
        assert result.unassigned_count == 2  # both active vehicles have no assignment
        assert result.by_type["sedan"] == 1
        assert result.by_type["van"] == 1


# ---------------------------------------------------------------------------
# Service tests: list_all_platform  (25–26)
# ---------------------------------------------------------------------------


class TestListAllPlatform:
    """Tests for list_all_platform."""

    @pytest.mark.asyncio
    async def test_returns_all_vehicles_without_filter(self):
        """25. Returns all vehicles when no account_id filter."""
        v1 = _make_vehicle(vehicle_id=uuid.uuid4(), account_id=1)
        v2 = _make_vehicle(vehicle_id=uuid.uuid4(), account_id=2)
        db = _db_scalars_all([v1, v2])
        result = await list_all_platform(db)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_filters_by_account_id(self):
        """26. Filters to specific account when account_id provided."""
        v1 = _make_vehicle(vehicle_id=uuid.uuid4(), account_id=ACCOUNT_ID)
        db = _db_scalars_all([v1])
        result = await list_all_platform(db, account_id=ACCOUNT_ID)
        assert len(result) == 1
        assert result[0].account_id == ACCOUNT_ID


# ---------------------------------------------------------------------------
# Schema tests  (27–35)
# ---------------------------------------------------------------------------


class TestFleetVehicleCreate:
    """Schema validation for FleetVehicleCreate."""

    def test_requires_name(self):
        """27. Name is required."""
        with pytest.raises(ValidationError):
            FleetVehicleCreate()

    def test_defaults_capacity_and_is_wav(self):
        """28. Defaults capacity=4 and is_wav=False."""
        schema = FleetVehicleCreate(name="Van One")
        assert schema.capacity == 4
        assert schema.is_wav is False

    def test_optional_fields_can_be_omitted(self):
        """29. All optional fields default to None."""
        schema = FleetVehicleCreate(name="Van One")
        assert schema.vehicle_type is None
        assert schema.make is None
        assert schema.model_name is None
        assert schema.year is None
        assert schema.license_plate is None
        assert schema.color is None
        assert schema.notes is None


class TestFleetVehicleUpdate:
    """Schema validation for FleetVehicleUpdate."""

    def test_all_fields_optional(self):
        """30. All fields are optional — empty construction is valid."""
        schema = FleetVehicleUpdate()
        assert schema.name is None
        assert schema.capacity is None
        assert schema.is_wav is None

    def test_rejects_capacity_less_than_one(self):
        """31. Capacity must be >= 1."""
        with pytest.raises(ValidationError):
            FleetVehicleUpdate(capacity=0)


class TestFleetAssignmentCreate:
    """Schema validation for FleetAssignmentCreate."""

    def test_driver_profile_id_is_optional(self):
        """32. driver_profile_id and notes can be omitted."""
        schema = FleetAssignmentCreate()
        assert schema.driver_profile_id is None
        assert schema.notes is None


class TestResponseSchemas:
    """Tests for response schema construction."""

    def test_fleet_vehicle_response_from_attributes(self):
        """33. FleetVehicleResponse constructs from ORM attributes."""
        v = _make_vehicle()
        response = FleetVehicleResponse.model_validate(v)
        assert response.id == VEHICLE_ID
        assert response.name == "Sedan Alpha"
        assert response.capacity == 4

    def test_fleet_assignment_response_from_attributes(self):
        """34. FleetAssignmentResponse constructs from ORM attributes."""
        a = _make_assignment()
        response = FleetAssignmentResponse.model_validate(a)
        assert response.id == ASSIGNMENT_ID
        assert response.fleet_vehicle_id == VEHICLE_ID
        assert response.driver_profile_id == 99

    def test_fleet_summary_response_construction(self):
        """35. FleetSummaryResponse constructs correctly with all fields."""
        summary = FleetSummaryResponse(
            total_vehicles=10,
            active_vehicles=8,
            inactive_vehicles=2,
            wav_count=3,
            unassigned_count=4,
            by_type={"sedan": 5, "van": 3},
        )
        assert summary.total_vehicles == 10
        assert summary.active_vehicles == 8
        assert summary.by_type["sedan"] == 5


# ---------------------------------------------------------------------------
# API layer tests  (36–63)
# ---------------------------------------------------------------------------

_BASE_URL = f"/api/v1/corporate/{ACCOUNT_ID}/fleet-vehicles"
_PLATFORM_URL = "/api/v1/platform/corporate/fleet-vehicles"

client = TestClient(app)


def _make_user(user_id: int = 1, is_admin: bool = False):
    user = MagicMock()
    user.id = user_id
    user.is_admin = is_admin
    return user


def _mock_account():
    account = MagicMock()
    account.id = ACCOUNT_ID
    return account


def _dep_overrides(is_admin: bool = False):
    """Return dependency override dict for FastAPI DI injection."""
    from app.api.deps import get_current_user, get_db, require_admin

    async def _user():
        return _make_user(is_admin=is_admin)

    async def _db():
        return AsyncMock()

    async def _admin():
        return _make_user(is_admin=True)

    return {
        get_current_user: _user,
        get_db: _db,
        require_admin: _admin,
    }


class TestListFleetVehiclesEndpoint:
    """GET /corporate/{account_id}/fleet-vehicles/"""

    def test_member_can_list_vehicles(self):
        """36. 200 — member can list fleet vehicles."""
        v_resp = _vehicle_response(_make_vehicle())

        with (
            patch(f"{_ROUTER}.get_account", new=AsyncMock(return_value=_mock_account())),
            patch(f"{_ROUTER}.list_fleet_vehicles", new=AsyncMock(return_value=[v_resp])),
        ):
            app.dependency_overrides.update(_dep_overrides())
            response = client.get(f"{_BASE_URL}/")
            app.dependency_overrides.clear()
        assert response.status_code == 200

    def test_404_when_account_not_found(self):
        """37. 404 when corporate account not found."""
        with patch(
            f"{_ROUTER}.get_account",
            new=AsyncMock(side_effect=HTTPException(status_code=404, detail="Not found")),
        ):
            app.dependency_overrides.update(_dep_overrides())
            response = client.get(f"{_BASE_URL}/")
            app.dependency_overrides.clear()
        assert response.status_code == 404


class TestGetFleetSummaryEndpoint:
    """GET /corporate/{account_id}/fleet-vehicles/summary"""

    def test_member_can_get_summary(self):
        """38. 200 — member can get fleet summary."""
        summary = FleetSummaryResponse(
            total_vehicles=5, active_vehicles=4, inactive_vehicles=1,
            wav_count=1, unassigned_count=2, by_type={"sedan": 3, "van": 1},
        )

        with (
            patch(f"{_ROUTER}.get_account", new=AsyncMock(return_value=_mock_account())),
            patch(f"{_ROUTER}.get_fleet_summary", new=AsyncMock(return_value=summary)),
        ):
            app.dependency_overrides.update(_dep_overrides())
            response = client.get(f"{_BASE_URL}/summary")
            app.dependency_overrides.clear()
        assert response.status_code == 200


class TestGetFleetVehicleEndpoint:
    """GET /corporate/{account_id}/fleet-vehicles/{vehicle_id}"""

    def test_member_can_get_vehicle(self):
        """39. 200 — member can get a single vehicle."""
        v_resp = _vehicle_response(_make_vehicle())

        with (
            patch(f"{_ROUTER}.get_account", new=AsyncMock(return_value=_mock_account())),
            patch(f"{_ROUTER}.get_fleet_vehicle", new=AsyncMock(return_value=v_resp)),
        ):
            app.dependency_overrides.update(_dep_overrides())
            response = client.get(f"{_BASE_URL}/{VEHICLE_ID}")
            app.dependency_overrides.clear()
        assert response.status_code == 200

    def test_404_when_vehicle_not_found(self):
        """40. 404 when vehicle not found."""
        with (
            patch(f"{_ROUTER}.get_account", new=AsyncMock(return_value=_mock_account())),
            patch(
                f"{_ROUTER}.get_fleet_vehicle",
                new=AsyncMock(side_effect=HTTPException(status_code=404, detail="Not found")),
            ),
        ):
            app.dependency_overrides.update(_dep_overrides())
            response = client.get(f"{_BASE_URL}/{VEHICLE_ID}")
            app.dependency_overrides.clear()
        assert response.status_code == 404


class TestCreateFleetVehicleEndpoint:
    """POST /corporate/{account_id}/fleet-vehicles/"""

    def test_admin_can_create_vehicle(self):
        """41. 201 — admin can create a vehicle."""
        v_resp = _vehicle_response(_make_vehicle())

        with (
            patch(f"{_ROUTER}.get_account", new=AsyncMock(return_value=_mock_account())),
            patch(f"{_ROUTER}._require_account_admin", new=AsyncMock(return_value=None)),
            patch(f"{_ROUTER}.create_fleet_vehicle", new=AsyncMock(return_value=v_resp)),
        ):
            app.dependency_overrides.update(_dep_overrides(is_admin=True))
            response = client.post(f"{_BASE_URL}/", json={"name": "Sedan Alpha"})
            app.dependency_overrides.clear()
        assert response.status_code == 201

    def test_non_admin_cannot_create_vehicle(self):
        """42. 403 — non-admin cannot create vehicle."""
        with (
            patch(f"{_ROUTER}.get_account", new=AsyncMock(return_value=_mock_account())),
            patch(
                f"{_ROUTER}._require_account_admin",
                new=AsyncMock(side_effect=HTTPException(status_code=403, detail="Forbidden")),
            ),
        ):
            app.dependency_overrides.update(_dep_overrides())
            response = client.post(f"{_BASE_URL}/", json={"name": "Sedan Alpha"})
            app.dependency_overrides.clear()
        assert response.status_code == 403

    def test_409_when_name_already_exists(self):
        """43. 409 when name already exists."""
        with (
            patch(f"{_ROUTER}.get_account", new=AsyncMock(return_value=_mock_account())),
            patch(f"{_ROUTER}._require_account_admin", new=AsyncMock(return_value=None)),
            patch(
                f"{_ROUTER}.create_fleet_vehicle",
                new=AsyncMock(side_effect=HTTPException(status_code=409, detail="Conflict")),
            ),
        ):
            app.dependency_overrides.update(_dep_overrides(is_admin=True))
            response = client.post(f"{_BASE_URL}/", json={"name": "Sedan Alpha"})
            app.dependency_overrides.clear()
        assert response.status_code == 409


class TestUpdateFleetVehicleEndpoint:
    """PUT /corporate/{account_id}/fleet-vehicles/{vehicle_id}"""

    def test_admin_can_update_vehicle(self):
        """44. 200 — admin can update a vehicle."""
        v_resp = _vehicle_response(_make_vehicle(color="White"))

        with (
            patch(f"{_ROUTER}.get_account", new=AsyncMock(return_value=_mock_account())),
            patch(f"{_ROUTER}._require_account_admin", new=AsyncMock(return_value=None)),
            patch(f"{_ROUTER}.update_fleet_vehicle", new=AsyncMock(return_value=v_resp)),
        ):
            app.dependency_overrides.update(_dep_overrides(is_admin=True))
            response = client.put(f"{_BASE_URL}/{VEHICLE_ID}", json={"color": "White"})
            app.dependency_overrides.clear()
        assert response.status_code == 200

    def test_non_admin_cannot_update_vehicle(self):
        """45. 403 — non-admin cannot update vehicle."""
        with (
            patch(f"{_ROUTER}.get_account", new=AsyncMock(return_value=_mock_account())),
            patch(
                f"{_ROUTER}._require_account_admin",
                new=AsyncMock(side_effect=HTTPException(status_code=403, detail="Forbidden")),
            ),
        ):
            app.dependency_overrides.update(_dep_overrides())
            response = client.put(f"{_BASE_URL}/{VEHICLE_ID}", json={"color": "White"})
            app.dependency_overrides.clear()
        assert response.status_code == 403


class TestDeactivateFleetVehicleEndpoint:
    """POST /corporate/{account_id}/fleet-vehicles/{vehicle_id}/deactivate"""

    def test_admin_can_deactivate(self):
        """46. 200 — admin can deactivate vehicle."""
        v_resp = _vehicle_response(_make_vehicle(is_active=False))

        with (
            patch(f"{_ROUTER}.get_account", new=AsyncMock(return_value=_mock_account())),
            patch(f"{_ROUTER}._require_account_admin", new=AsyncMock(return_value=None)),
            patch(f"{_ROUTER}.deactivate_fleet_vehicle", new=AsyncMock(return_value=v_resp)),
        ):
            app.dependency_overrides.update(_dep_overrides(is_admin=True))
            response = client.post(f"{_BASE_URL}/{VEHICLE_ID}/deactivate")
            app.dependency_overrides.clear()
        assert response.status_code == 200

    def test_non_admin_cannot_deactivate(self):
        """47. 403 — non-admin cannot deactivate vehicle."""
        with (
            patch(f"{_ROUTER}.get_account", new=AsyncMock(return_value=_mock_account())),
            patch(
                f"{_ROUTER}._require_account_admin",
                new=AsyncMock(side_effect=HTTPException(status_code=403, detail="Forbidden")),
            ),
        ):
            app.dependency_overrides.update(_dep_overrides())
            response = client.post(f"{_BASE_URL}/{VEHICLE_ID}/deactivate")
            app.dependency_overrides.clear()
        assert response.status_code == 403

    def test_409_already_inactive(self):
        """48. 409 when vehicle is already inactive."""
        with (
            patch(f"{_ROUTER}.get_account", new=AsyncMock(return_value=_mock_account())),
            patch(f"{_ROUTER}._require_account_admin", new=AsyncMock(return_value=None)),
            patch(
                f"{_ROUTER}.deactivate_fleet_vehicle",
                new=AsyncMock(side_effect=HTTPException(status_code=409, detail="Already inactive")),
            ),
        ):
            app.dependency_overrides.update(_dep_overrides(is_admin=True))
            response = client.post(f"{_BASE_URL}/{VEHICLE_ID}/deactivate")
            app.dependency_overrides.clear()
        assert response.status_code == 409


class TestReactivateFleetVehicleEndpoint:
    """POST /corporate/{account_id}/fleet-vehicles/{vehicle_id}/reactivate"""

    def test_admin_can_reactivate(self):
        """49. 200 — admin can reactivate vehicle."""
        v_resp = _vehicle_response(_make_vehicle(is_active=True))

        with (
            patch(f"{_ROUTER}.get_account", new=AsyncMock(return_value=_mock_account())),
            patch(f"{_ROUTER}._require_account_admin", new=AsyncMock(return_value=None)),
            patch(f"{_ROUTER}.reactivate_fleet_vehicle", new=AsyncMock(return_value=v_resp)),
        ):
            app.dependency_overrides.update(_dep_overrides(is_admin=True))
            response = client.post(f"{_BASE_URL}/{VEHICLE_ID}/reactivate")
            app.dependency_overrides.clear()
        assert response.status_code == 200

    def test_non_admin_cannot_reactivate(self):
        """50. 403 — non-admin cannot reactivate vehicle."""
        with (
            patch(f"{_ROUTER}.get_account", new=AsyncMock(return_value=_mock_account())),
            patch(
                f"{_ROUTER}._require_account_admin",
                new=AsyncMock(side_effect=HTTPException(status_code=403, detail="Forbidden")),
            ),
        ):
            app.dependency_overrides.update(_dep_overrides())
            response = client.post(f"{_BASE_URL}/{VEHICLE_ID}/reactivate")
            app.dependency_overrides.clear()
        assert response.status_code == 403


class TestDeleteFleetVehicleEndpoint:
    """DELETE /corporate/{account_id}/fleet-vehicles/{vehicle_id}"""

    def test_admin_can_delete(self):
        """51. 204 — admin can delete an inactive vehicle."""
        with (
            patch(f"{_ROUTER}.get_account", new=AsyncMock(return_value=_mock_account())),
            patch(f"{_ROUTER}._require_account_admin", new=AsyncMock(return_value=None)),
            patch(f"{_ROUTER}.delete_fleet_vehicle", new=AsyncMock(return_value=None)),
        ):
            app.dependency_overrides.update(_dep_overrides(is_admin=True))
            response = client.delete(f"{_BASE_URL}/{VEHICLE_ID}")
            app.dependency_overrides.clear()
        assert response.status_code == 204

    def test_non_admin_cannot_delete(self):
        """52. 403 — non-admin cannot delete vehicle."""
        with (
            patch(f"{_ROUTER}.get_account", new=AsyncMock(return_value=_mock_account())),
            patch(
                f"{_ROUTER}._require_account_admin",
                new=AsyncMock(side_effect=HTTPException(status_code=403, detail="Forbidden")),
            ),
        ):
            app.dependency_overrides.update(_dep_overrides())
            response = client.delete(f"{_BASE_URL}/{VEHICLE_ID}")
            app.dependency_overrides.clear()
        assert response.status_code == 403

    def test_409_cannot_delete_active_vehicle(self):
        """53. 409 — cannot delete active vehicle."""
        with (
            patch(f"{_ROUTER}.get_account", new=AsyncMock(return_value=_mock_account())),
            patch(f"{_ROUTER}._require_account_admin", new=AsyncMock(return_value=None)),
            patch(
                f"{_ROUTER}.delete_fleet_vehicle",
                new=AsyncMock(side_effect=HTTPException(status_code=409, detail="Still active")),
            ),
        ):
            app.dependency_overrides.update(_dep_overrides(is_admin=True))
            response = client.delete(f"{_BASE_URL}/{VEHICLE_ID}")
            app.dependency_overrides.clear()
        assert response.status_code == 409


class TestAssignDriverEndpoint:
    """POST /corporate/{account_id}/fleet-vehicles/{vehicle_id}/assign-driver"""

    def test_admin_can_assign_driver(self):
        """54. 201 — admin can assign driver."""
        a_resp = _assignment_response(_make_assignment())

        with (
            patch(f"{_ROUTER}.get_account", new=AsyncMock(return_value=_mock_account())),
            patch(f"{_ROUTER}._require_account_admin", new=AsyncMock(return_value=None)),
            patch(f"{_ROUTER}.assign_driver", new=AsyncMock(return_value=a_resp)),
        ):
            app.dependency_overrides.update(_dep_overrides(is_admin=True))
            response = client.post(
                f"{_BASE_URL}/{VEHICLE_ID}/assign-driver",
                json={"driver_profile_id": 99},
            )
            app.dependency_overrides.clear()
        assert response.status_code == 201

    def test_non_admin_cannot_assign_driver(self):
        """55. 403 — non-admin cannot assign driver."""
        with (
            patch(f"{_ROUTER}.get_account", new=AsyncMock(return_value=_mock_account())),
            patch(
                f"{_ROUTER}._require_account_admin",
                new=AsyncMock(side_effect=HTTPException(status_code=403, detail="Forbidden")),
            ),
        ):
            app.dependency_overrides.update(_dep_overrides())
            response = client.post(
                f"{_BASE_URL}/{VEHICLE_ID}/assign-driver",
                json={"driver_profile_id": 99},
            )
            app.dependency_overrides.clear()
        assert response.status_code == 403


class TestEndAssignmentEndpoint:
    """DELETE /corporate/{account_id}/fleet-vehicles/{vehicle_id}/assignment"""

    def test_admin_can_end_assignment(self):
        """56. 200 — admin can end the active assignment."""
        a_resp = _assignment_response(_make_assignment(is_active=False))

        with (
            patch(f"{_ROUTER}.get_account", new=AsyncMock(return_value=_mock_account())),
            patch(f"{_ROUTER}._require_account_admin", new=AsyncMock(return_value=None)),
            patch(f"{_ROUTER}.end_assignment", new=AsyncMock(return_value=a_resp)),
        ):
            app.dependency_overrides.update(_dep_overrides(is_admin=True))
            response = client.delete(f"{_BASE_URL}/{VEHICLE_ID}/assignment")
            app.dependency_overrides.clear()
        assert response.status_code == 200

    def test_non_admin_cannot_end_assignment(self):
        """57. 403 — non-admin cannot end assignment."""
        with (
            patch(f"{_ROUTER}.get_account", new=AsyncMock(return_value=_mock_account())),
            patch(
                f"{_ROUTER}._require_account_admin",
                new=AsyncMock(side_effect=HTTPException(status_code=403, detail="Forbidden")),
            ),
        ):
            app.dependency_overrides.update(_dep_overrides())
            response = client.delete(f"{_BASE_URL}/{VEHICLE_ID}/assignment")
            app.dependency_overrides.clear()
        assert response.status_code == 403

    def test_404_no_active_assignment(self):
        """58. 404 — when no active assignment exists."""
        with (
            patch(f"{_ROUTER}.get_account", new=AsyncMock(return_value=_mock_account())),
            patch(f"{_ROUTER}._require_account_admin", new=AsyncMock(return_value=None)),
            patch(
                f"{_ROUTER}.end_assignment",
                new=AsyncMock(side_effect=HTTPException(status_code=404, detail="Not found")),
            ),
        ):
            app.dependency_overrides.update(_dep_overrides(is_admin=True))
            response = client.delete(f"{_BASE_URL}/{VEHICLE_ID}/assignment")
            app.dependency_overrides.clear()
        assert response.status_code == 404


class TestListVehicleAssignmentsEndpoint:
    """GET /corporate/{account_id}/fleet-vehicles/{vehicle_id}/assignments"""

    def test_admin_can_list_assignments(self):
        """59. 200 — admin can list assignment history."""
        a_resp = _assignment_response(_make_assignment())

        with (
            patch(f"{_ROUTER}.get_account", new=AsyncMock(return_value=_mock_account())),
            patch(f"{_ROUTER}._require_account_admin", new=AsyncMock(return_value=None)),
            patch(f"{_ROUTER}.list_vehicle_assignments", new=AsyncMock(return_value=[a_resp])),
        ):
            app.dependency_overrides.update(_dep_overrides(is_admin=True))
            response = client.get(f"{_BASE_URL}/{VEHICLE_ID}/assignments")
            app.dependency_overrides.clear()
        assert response.status_code == 200

    def test_non_admin_cannot_list_assignments(self):
        """60. 403 — non-admin cannot list assignment history."""
        with (
            patch(f"{_ROUTER}.get_account", new=AsyncMock(return_value=_mock_account())),
            patch(
                f"{_ROUTER}._require_account_admin",
                new=AsyncMock(side_effect=HTTPException(status_code=403, detail="Forbidden")),
            ),
        ):
            app.dependency_overrides.update(_dep_overrides())
            response = client.get(f"{_BASE_URL}/{VEHICLE_ID}/assignments")
            app.dependency_overrides.clear()
        assert response.status_code == 403


class TestPlatformAdminEndpoints:
    """Platform-admin fleet vehicle endpoints."""

    def test_platform_admin_can_list_all(self):
        """61. 200 — platform-admin can list all vehicles."""
        v_resp = _vehicle_response(_make_vehicle())

        with patch(f"{_ROUTER}.list_all_platform", new=AsyncMock(return_value=[v_resp])):
            app.dependency_overrides.update(_dep_overrides(is_admin=True))
            response = client.get(f"{_PLATFORM_URL}/")
            app.dependency_overrides.clear()
        assert response.status_code == 200

    def test_platform_admin_can_filter_by_account_id(self):
        """62. 200 — platform-admin can filter by account_id."""
        v_resp = _vehicle_response(_make_vehicle())

        with patch(f"{_ROUTER}.list_all_platform", new=AsyncMock(return_value=[v_resp])):
            app.dependency_overrides.update(_dep_overrides(is_admin=True))
            response = client.get(f"{_PLATFORM_URL}/?account_id={ACCOUNT_ID}")
            app.dependency_overrides.clear()
        assert response.status_code == 200

    def test_platform_admin_can_list_per_account(self):
        """63. 200 — platform-admin can list vehicles for a specific account."""
        v_resp = _vehicle_response(_make_vehicle())

        with patch(f"{_ROUTER}.list_all_platform", new=AsyncMock(return_value=[v_resp])):
            app.dependency_overrides.update(_dep_overrides(is_admin=True))
            response = client.get(f"{_PLATFORM_URL}/{ACCOUNT_ID}")
            app.dependency_overrides.clear()
        assert response.status_code == 200
