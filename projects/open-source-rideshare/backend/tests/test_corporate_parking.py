"""Tests for Corporate Parking Management.

Service layer (async, mocked DB):
   1.  create_facility — success: creates facility
   2.  create_facility — 409 on duplicate name in account
   3.  create_facility — same name in different account is allowed
   4.  get_facility — success: returns facility
   5.  get_facility — 404 when not found
   6.  get_facility — 404 when account_id mismatch
   7.  list_facilities — returns all facilities for account
   8.  list_facilities — filters by is_active=True
   9.  list_facilities — filters by is_active=False
  10.  update_facility — success: updates name
  11.  update_facility — 404 when not found
  12.  update_facility — 409 on name collision
  13.  update_facility — same name (no change) does not 409
  14.  deactivate_facility — success: sets is_active=False
  15.  deactivate_facility — 404 when not found
  16.  deactivate_facility — 409 when already inactive
  17.  add_spot — success: creates spot with is_assigned=False
  18.  add_spot — 404 when facility not found
  19.  add_spot — 409 on duplicate spot_identifier in facility
  20.  get_spot — success: returns spot
  21.  get_spot — 404 when not found
  22.  list_spots — returns all spots for account
  23.  list_spots — filters by facility_id
  24.  list_spots — filters by spot_type
  25.  list_spots — filters by is_assigned=True
  26.  list_spots — filters by is_active=True
  27.  assign_spot_to_member — success: creates assignment, sets is_assigned=True
  28.  assign_spot_to_member — 404 when spot not found
  29.  assign_spot_to_member — 409 when spot already assigned
  30.  end_assignment — success: sets is_active=False, clears is_assigned
  31.  end_assignment — 404 when spot not found
  32.  end_assignment — 404 when no active assignment exists
  33.  get_member_parking — returns member's active assignments
  34.  get_member_parking — returns empty list when no assignments
  35.  get_facility_summary — returns correct counts
  36.  get_facility_summary — 404 when facility not found
  37.  list_all_platform — returns all facilities without filter
  38.  list_all_platform — filters by account_id

Schema validation:
  39.  FacilityCreate — requires name
  40.  FacilityCreate — rejects empty name
  41.  FacilityCreate — defaults facility_type to surface_lot
  42.  FacilityUpdate — all fields optional
  43.  SpotCreate — requires facility_id and spot_identifier
  44.  SpotCreate — defaults spot_type to standard
  45.  SpotCreate — rejects empty spot_identifier
  46.  AssignmentCreate — requires member_id and start_date
  47.  AssignmentCreate — end_date is optional (defaults to None)
  48.  FacilityResponse — from_attributes construction
  49.  SpotResponse — from_attributes construction
  50.  AssignmentResponse — from_attributes construction
  51.  FacilitySummaryResponse — structure

API layer (service functions patched):
  52.  GET  /parking/facilities — 200 member can list active facilities
  53.  GET  /parking/my-spots — 200 member can get own parking
  54.  POST /parking/facilities — 201 admin can create facility
  55.  POST /parking/facilities — 403 non-admin cannot create
  56.  POST /parking/facilities — 409 on duplicate name
  57.  GET  /parking/facilities/all — 200 admin can list all
  58.  GET  /parking/facilities/all — 403 non-admin blocked
  59.  GET  /parking/facilities/{id} — 200 admin can get facility
  60.  GET  /parking/facilities/{id} — 404 when not found
  61.  PUT  /parking/facilities/{id} — 200 admin can update
  62.  PUT  /parking/facilities/{id} — 403 non-admin blocked
  63.  POST /parking/facilities/{id}/deactivate — 200 admin can deactivate
  64.  POST /parking/facilities/{id}/deactivate — 409 already inactive
  65.  GET  /parking/facilities/{id}/summary — 200 admin can get summary
  66.  POST /parking/spots — 201 admin can add spot
  67.  POST /parking/spots — 403 non-admin blocked
  68.  GET  /parking/spots — 200 admin can list spots
  69.  GET  /parking/spots/{id} — 200 admin can get spot
  70.  POST /parking/spots/{id}/assign — 201 admin can assign
  71.  POST /parking/spots/{id}/assign — 409 spot already assigned
  72.  POST /parking/spots/{id}/end-assignment — 200 admin can end assignment
  73.  POST /parking/spots/{id}/end-assignment — 404 no active assignment
  74.  GET  /platform/corporate/parking/all — 200 platform-admin list all
  75.  GET  /platform/corporate/parking/all — 200 with account_id filter
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import app
from app.models.corporate_parking import (
    CorporateParkingAssignment,
    CorporateParkingFacility,
    CorporateParkingSpot,
    FacilityType,
    SpotType,
)
from app.schemas.corporate_parking import (
    AssignmentCreate,
    AssignmentResponse,
    FacilityCreate,
    FacilityResponse,
    FacilitySummaryResponse,
    FacilityUpdate,
    SpotCreate,
    SpotResponse,
)
from app.services.corporate_parking_service import (
    add_spot,
    assign_spot_to_member,
    create_facility,
    deactivate_facility,
    end_assignment,
    get_facility,
    get_facility_summary,
    get_member_parking,
    get_spot,
    list_all_platform,
    list_facilities,
    list_spots,
    update_facility,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ACCOUNT_ID = 7
FACILITY_ID = uuid.uuid4()
SPOT_ID = uuid.uuid4()
ASSIGNMENT_ID = uuid.uuid4()
USER_ID = 15
ADMIN_ID = 1
MEMBER_ID = 20

_SERVICE = "app.services.corporate_parking_service"
_ROUTER = "app.api.v1.corporate_parking"

_NOW = datetime(2026, 4, 16, 10, 0, 0, tzinfo=timezone.utc)
_TODAY = date(2026, 4, 16)


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


def _make_facility(
    facility_id: uuid.UUID = FACILITY_ID,
    account_id: int = ACCOUNT_ID,
    name: str = "Main Campus Garage",
    facility_type: FacilityType = FacilityType.parking_garage,
    is_active: bool = True,
    created_by_id: int | None = ADMIN_ID,
) -> CorporateParkingFacility:
    f = CorporateParkingFacility()
    f.id = facility_id
    f.account_id = account_id
    f.name = name
    f.description = "Primary employee parking structure"
    f.address_line1 = "100 Main St"
    f.address_line2 = None
    f.city = "Springfield"
    f.state = "IL"
    f.zip_code = "62701"
    f.lat = "39.7989"
    f.lng = "-89.6440"
    f.facility_type = facility_type
    f.notes = None
    f.is_active = is_active
    f.created_by_id = created_by_id
    f.created_at = _NOW
    f.updated_at = _NOW
    return f


def _make_spot(
    spot_id: uuid.UUID = SPOT_ID,
    account_id: int = ACCOUNT_ID,
    facility_id: uuid.UUID = FACILITY_ID,
    spot_identifier: str = "A-01",
    spot_type: SpotType = SpotType.standard,
    is_assigned: bool = False,
    is_active: bool = True,
) -> CorporateParkingSpot:
    s = CorporateParkingSpot()
    s.id = spot_id
    s.account_id = account_id
    s.facility_id = facility_id
    s.spot_identifier = spot_identifier
    s.spot_type = spot_type
    s.floor_level = "1"
    s.is_assigned = is_assigned
    s.notes = None
    s.is_active = is_active
    s.created_at = _NOW
    return s


def _make_assignment(
    assignment_id: uuid.UUID = ASSIGNMENT_ID,
    account_id: int = ACCOUNT_ID,
    spot_id: uuid.UUID = SPOT_ID,
    member_id: int = MEMBER_ID,
    is_active: bool = True,
    ended_at: datetime | None = None,
    ended_by_id: int | None = None,
) -> CorporateParkingAssignment:
    a = CorporateParkingAssignment()
    a.id = assignment_id
    a.account_id = account_id
    a.spot_id = spot_id
    a.member_id = member_id
    a.assigned_by_id = ADMIN_ID
    a.permit_number = "PERMIT-001"
    a.start_date = _TODAY
    a.end_date = None
    a.is_active = is_active
    a.notes = None
    a.ended_at = ended_at
    a.ended_by_id = ended_by_id
    a.created_at = _NOW
    return a


# ---------------------------------------------------------------------------
# DB mock helpers
# ---------------------------------------------------------------------------


def _scalar_result(value):
    """Return a mock result whose scalar_one_or_none() returns value."""
    r = MagicMock()
    r.scalar_one_or_none.return_value = value
    return r


def _scalar_one_result(value):
    """Return a mock result whose scalar_one() returns value."""
    r = MagicMock()
    r.scalar_one.return_value = value
    return r


def _scalars_result(rows: list):
    """Return a mock result whose scalars().all() returns rows."""
    r = MagicMock()
    r.scalars.return_value.all.return_value = rows
    return r


def _all_result(rows: list):
    """Return a mock result whose .all() returns rows."""
    r = MagicMock()
    r.all.return_value = rows
    return r


def _make_db(*side_effects):
    """Create an AsyncMock db that returns side_effects in order."""
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=list(side_effects))
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    db.add = MagicMock()
    return db


# ===========================================================================
# SERVICE LAYER TESTS
# ===========================================================================


# ---------------------------------------------------------------------------
# create_facility
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_facility_success():
    """create_facility creates facility when name is unique."""
    facility = _make_facility()
    db = _make_db(
        _scalar_result(None),  # duplicate check → no collision
    )
    db.refresh = AsyncMock(side_effect=lambda obj: setattr(obj, "id", FACILITY_ID) or None)

    async def _refresh(obj):
        obj.id = FACILITY_ID
        obj.account_id = ACCOUNT_ID
        obj.name = "Main Campus Garage"
        obj.description = "Primary employee parking structure"
        obj.address_line1 = "100 Main St"
        obj.address_line2 = None
        obj.city = "Springfield"
        obj.state = "IL"
        obj.zip_code = "62701"
        obj.lat = "39.7989"
        obj.lng = "-89.6440"
        obj.facility_type = FacilityType.parking_garage
        obj.notes = None
        obj.is_active = True
        obj.created_by_id = ADMIN_ID
        obj.created_at = _NOW
        obj.updated_at = _NOW

    db.refresh = _refresh
    data = FacilityCreate(name="Main Campus Garage", facility_type=FacilityType.parking_garage)
    result = await create_facility(db, ACCOUNT_ID, data, created_by_id=ADMIN_ID)
    assert result.name == "Main Campus Garage"
    assert result.is_active is True


@pytest.mark.asyncio
async def test_create_facility_409_duplicate_name():
    """create_facility raises 409 when a facility with the same name exists."""
    db = _make_db(
        _scalar_result(_make_facility()),  # duplicate found
    )
    data = FacilityCreate(name="Main Campus Garage")
    with pytest.raises(HTTPException) as exc:
        await create_facility(db, ACCOUNT_ID, data)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_create_facility_different_account_allowed():
    """create_facility allows same name in a different account."""
    db = _make_db(
        _scalar_result(None),  # no collision for account 99
    )

    async def _refresh(obj):
        obj.id = uuid.uuid4()
        obj.account_id = 99
        obj.name = "Main Campus Garage"
        obj.description = None
        obj.address_line1 = None
        obj.address_line2 = None
        obj.city = None
        obj.state = None
        obj.zip_code = None
        obj.lat = None
        obj.lng = None
        obj.facility_type = FacilityType.surface_lot
        obj.notes = None
        obj.is_active = True
        obj.created_by_id = None
        obj.created_at = _NOW
        obj.updated_at = _NOW

    db.refresh = _refresh
    data = FacilityCreate(name="Main Campus Garage")
    result = await create_facility(db, 99, data)
    assert result.account_id == 99


# ---------------------------------------------------------------------------
# get_facility
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_facility_success():
    facility = _make_facility()
    db = _make_db(_scalar_result(facility))
    result = await get_facility(db, FACILITY_ID, ACCOUNT_ID)
    assert result.id == FACILITY_ID


@pytest.mark.asyncio
async def test_get_facility_404_not_found():
    db = _make_db(_scalar_result(None))
    with pytest.raises(HTTPException) as exc:
        await get_facility(db, FACILITY_ID, ACCOUNT_ID)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_get_facility_404_wrong_account():
    db = _make_db(_scalar_result(None))
    with pytest.raises(HTTPException) as exc:
        await get_facility(db, FACILITY_ID, 999)
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# list_facilities
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_facilities_returns_all():
    facilities = [_make_facility(), _make_facility(facility_id=uuid.uuid4(), name="Lot B")]
    db = _make_db(_scalars_result(facilities))
    result = await list_facilities(db, ACCOUNT_ID)
    assert len(result) == 2


@pytest.mark.asyncio
async def test_list_facilities_filters_active():
    active = _make_facility()
    db = _make_db(_scalars_result([active]))
    result = await list_facilities(db, ACCOUNT_ID, is_active=True)
    assert all(r.is_active for r in result)


@pytest.mark.asyncio
async def test_list_facilities_filters_inactive():
    inactive = _make_facility(is_active=False)
    db = _make_db(_scalars_result([inactive]))
    result = await list_facilities(db, ACCOUNT_ID, is_active=False)
    assert all(not r.is_active for r in result)


# ---------------------------------------------------------------------------
# update_facility
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_facility_success():
    facility = _make_facility()
    db = _make_db(
        _scalar_result(facility),  # _fetch_facility
        _scalar_result(None),       # collision check
    )
    db.refresh = AsyncMock()

    async def _refresh(obj):
        pass  # attributes already set

    db.refresh = _refresh
    data = FacilityUpdate(name="Updated Garage", city="Chicago")
    result = await update_facility(db, FACILITY_ID, ACCOUNT_ID, data)
    assert result.name == "Updated Garage"
    assert result.city == "Chicago"


@pytest.mark.asyncio
async def test_update_facility_404():
    db = _make_db(_scalar_result(None))
    data = FacilityUpdate(name="X")
    with pytest.raises(HTTPException) as exc:
        await update_facility(db, FACILITY_ID, ACCOUNT_ID, data)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_update_facility_409_name_collision():
    facility = _make_facility()
    other = _make_facility(facility_id=uuid.uuid4(), name="New Name")
    db = _make_db(
        _scalar_result(facility),  # _fetch_facility
        _scalar_result(other),      # collision check → conflict
    )
    data = FacilityUpdate(name="New Name")
    with pytest.raises(HTTPException) as exc:
        await update_facility(db, FACILITY_ID, ACCOUNT_ID, data)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_update_facility_same_name_no_409():
    """Updating with the same name (no actual change) should not 409."""
    facility = _make_facility(name="Main Campus Garage")
    db = _make_db(_scalar_result(facility))  # _fetch_facility only; no collision check

    async def _refresh(obj):
        pass

    db.refresh = _refresh
    data = FacilityUpdate(city="Chicago")  # no name change
    # Should not raise
    result = await update_facility(db, FACILITY_ID, ACCOUNT_ID, data)
    assert result.city == "Chicago"


# ---------------------------------------------------------------------------
# deactivate_facility
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deactivate_facility_success():
    facility = _make_facility(is_active=True)
    db = _make_db(_scalar_result(facility))

    async def _refresh(obj):
        pass

    db.refresh = _refresh
    result = await deactivate_facility(db, FACILITY_ID, ACCOUNT_ID)
    assert result.is_active is False


@pytest.mark.asyncio
async def test_deactivate_facility_404():
    db = _make_db(_scalar_result(None))
    with pytest.raises(HTTPException) as exc:
        await deactivate_facility(db, FACILITY_ID, ACCOUNT_ID)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_deactivate_facility_409_already_inactive():
    facility = _make_facility(is_active=False)
    db = _make_db(_scalar_result(facility))
    with pytest.raises(HTTPException) as exc:
        await deactivate_facility(db, FACILITY_ID, ACCOUNT_ID)
    assert exc.value.status_code == 409


# ---------------------------------------------------------------------------
# add_spot
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_spot_success():
    facility = _make_facility()
    db = _make_db(
        _scalar_result(facility),  # _fetch_facility
        _scalar_result(None),       # duplicate check
    )

    async def _refresh(obj):
        obj.id = SPOT_ID
        obj.account_id = ACCOUNT_ID
        obj.facility_id = FACILITY_ID
        obj.spot_identifier = "A-01"
        obj.spot_type = SpotType.standard
        obj.floor_level = "1"
        obj.is_assigned = False
        obj.notes = None
        obj.is_active = True
        obj.created_at = _NOW

    db.refresh = _refresh
    data = SpotCreate(facility_id=FACILITY_ID, spot_identifier="A-01")
    result = await add_spot(db, ACCOUNT_ID, data)
    assert result.spot_identifier == "A-01"
    assert result.is_assigned is False


@pytest.mark.asyncio
async def test_add_spot_404_facility_not_found():
    db = _make_db(_scalar_result(None))
    data = SpotCreate(facility_id=FACILITY_ID, spot_identifier="A-01")
    with pytest.raises(HTTPException) as exc:
        await add_spot(db, ACCOUNT_ID, data)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_add_spot_409_duplicate_identifier():
    facility = _make_facility()
    existing_spot = _make_spot()
    db = _make_db(
        _scalar_result(facility),       # _fetch_facility
        _scalar_result(existing_spot),  # duplicate found
    )
    data = SpotCreate(facility_id=FACILITY_ID, spot_identifier="A-01")
    with pytest.raises(HTTPException) as exc:
        await add_spot(db, ACCOUNT_ID, data)
    assert exc.value.status_code == 409


# ---------------------------------------------------------------------------
# get_spot
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_spot_success():
    spot = _make_spot()
    db = _make_db(_scalar_result(spot))
    result = await get_spot(db, SPOT_ID, ACCOUNT_ID)
    assert result.id == SPOT_ID


@pytest.mark.asyncio
async def test_get_spot_404():
    db = _make_db(_scalar_result(None))
    with pytest.raises(HTTPException) as exc:
        await get_spot(db, SPOT_ID, ACCOUNT_ID)
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# list_spots
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_spots_returns_all():
    spots = [_make_spot(), _make_spot(spot_id=uuid.uuid4(), spot_identifier="B-02")]
    db = _make_db(_scalars_result(spots))
    result = await list_spots(db, ACCOUNT_ID)
    assert len(result) == 2


@pytest.mark.asyncio
async def test_list_spots_filters_facility():
    spot = _make_spot()
    db = _make_db(_scalars_result([spot]))
    result = await list_spots(db, ACCOUNT_ID, facility_id=FACILITY_ID)
    assert result[0].facility_id == FACILITY_ID


@pytest.mark.asyncio
async def test_list_spots_filters_spot_type():
    ev_spot = _make_spot(spot_type=SpotType.ev_charging)
    db = _make_db(_scalars_result([ev_spot]))
    result = await list_spots(db, ACCOUNT_ID, spot_type=SpotType.ev_charging)
    assert result[0].spot_type == SpotType.ev_charging


@pytest.mark.asyncio
async def test_list_spots_filters_is_assigned():
    assigned = _make_spot(is_assigned=True)
    db = _make_db(_scalars_result([assigned]))
    result = await list_spots(db, ACCOUNT_ID, is_assigned=True)
    assert result[0].is_assigned is True


@pytest.mark.asyncio
async def test_list_spots_filters_is_active():
    active = _make_spot(is_active=True)
    db = _make_db(_scalars_result([active]))
    result = await list_spots(db, ACCOUNT_ID, is_active=True)
    assert result[0].is_active is True


# ---------------------------------------------------------------------------
# assign_spot_to_member
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_assign_spot_success():
    spot = _make_spot(is_assigned=False)
    db = _make_db(_scalar_result(spot))

    async def _refresh(obj):
        obj.id = ASSIGNMENT_ID
        obj.account_id = ACCOUNT_ID
        obj.spot_id = SPOT_ID
        obj.member_id = MEMBER_ID
        obj.assigned_by_id = ADMIN_ID
        obj.permit_number = "PERMIT-001"
        obj.start_date = _TODAY
        obj.end_date = None
        obj.is_active = True
        obj.notes = None
        obj.ended_at = None
        obj.ended_by_id = None
        obj.created_at = _NOW

    db.refresh = _refresh
    data = AssignmentCreate(member_id=MEMBER_ID, start_date=_TODAY)
    result = await assign_spot_to_member(db, ACCOUNT_ID, SPOT_ID, data, assigned_by_id=ADMIN_ID)
    assert result.member_id == MEMBER_ID
    assert result.is_active is True
    assert spot.is_assigned is True  # side-effect applied


@pytest.mark.asyncio
async def test_assign_spot_404_spot_not_found():
    db = _make_db(_scalar_result(None))
    data = AssignmentCreate(member_id=MEMBER_ID, start_date=_TODAY)
    with pytest.raises(HTTPException) as exc:
        await assign_spot_to_member(db, ACCOUNT_ID, SPOT_ID, data)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_assign_spot_409_already_assigned():
    spot = _make_spot(is_assigned=True)
    db = _make_db(_scalar_result(spot))
    data = AssignmentCreate(member_id=MEMBER_ID, start_date=_TODAY)
    with pytest.raises(HTTPException) as exc:
        await assign_spot_to_member(db, ACCOUNT_ID, SPOT_ID, data)
    assert exc.value.status_code == 409


# ---------------------------------------------------------------------------
# end_assignment
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_end_assignment_success():
    spot = _make_spot(is_assigned=True)
    assignment = _make_assignment(is_active=True)
    db = _make_db(
        _scalar_result(spot),        # _fetch_spot
        _scalar_result(assignment),  # find active assignment
    )

    async def _refresh(obj):
        pass

    db.refresh = _refresh
    result = await end_assignment(db, ACCOUNT_ID, SPOT_ID, ended_by_id=ADMIN_ID)
    assert result.is_active is False
    assert result.ended_by_id == ADMIN_ID
    assert spot.is_assigned is False  # side-effect applied


@pytest.mark.asyncio
async def test_end_assignment_404_spot_not_found():
    db = _make_db(_scalar_result(None))
    with pytest.raises(HTTPException) as exc:
        await end_assignment(db, ACCOUNT_ID, SPOT_ID)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_end_assignment_404_no_active_assignment():
    spot = _make_spot(is_assigned=False)
    db = _make_db(
        _scalar_result(spot),  # _fetch_spot
        _scalar_result(None),  # no active assignment
    )
    with pytest.raises(HTTPException) as exc:
        await end_assignment(db, ACCOUNT_ID, SPOT_ID)
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# get_member_parking
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_member_parking_returns_active_assignments():
    assignment = _make_assignment()
    db = _make_db(_scalars_result([assignment]))
    result = await get_member_parking(db, ACCOUNT_ID, MEMBER_ID)
    assert len(result) == 1
    assert result[0].member_id == MEMBER_ID


@pytest.mark.asyncio
async def test_get_member_parking_empty():
    db = _make_db(_scalars_result([]))
    result = await get_member_parking(db, ACCOUNT_ID, MEMBER_ID)
    assert result == []


# ---------------------------------------------------------------------------
# get_facility_summary
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_facility_summary_returns_correct_counts():
    facility = _make_facility()
    db = AsyncMock()
    execute_results = [
        _scalar_result(facility),   # _fetch_facility
        _scalar_one_result(10),     # total spots
        _scalar_one_result(8),      # active spots
        _scalar_one_result(5),      # assigned active
        _all_result([               # by_spot_type
            (SpotType.standard, 6),
            (SpotType.ev_charging, 2),
        ]),
    ]
    db.execute = AsyncMock(side_effect=execute_results)
    db.flush = AsyncMock()
    db.refresh = AsyncMock()

    result = await get_facility_summary(db, ACCOUNT_ID, FACILITY_ID)
    assert result.total_spots == 10
    assert result.active_spots == 8
    assert result.assigned_spots == 5
    assert result.available_spots == 3
    assert result.by_spot_type["standard"] == 6
    assert result.by_spot_type["ev_charging"] == 2


@pytest.mark.asyncio
async def test_get_facility_summary_404():
    db = _make_db(_scalar_result(None))
    with pytest.raises(HTTPException) as exc:
        await get_facility_summary(db, ACCOUNT_ID, FACILITY_ID)
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# list_all_platform
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_all_platform_no_filter():
    facilities = [
        _make_facility(),
        _make_facility(facility_id=uuid.uuid4(), account_id=99, name="Remote Lot"),
    ]
    db = _make_db(_scalars_result(facilities))
    result = await list_all_platform(db)
    assert len(result) == 2


@pytest.mark.asyncio
async def test_list_all_platform_filters_by_account():
    facility = _make_facility()
    db = _make_db(_scalars_result([facility]))
    result = await list_all_platform(db, account_id=ACCOUNT_ID)
    assert len(result) == 1
    assert result[0].account_id == ACCOUNT_ID


# ===========================================================================
# SCHEMA VALIDATION TESTS
# ===========================================================================


def test_facility_create_requires_name():
    with pytest.raises(ValidationError):
        FacilityCreate()


def test_facility_create_rejects_empty_name():
    with pytest.raises(ValidationError):
        FacilityCreate(name="")


def test_facility_create_defaults_facility_type():
    fc = FacilityCreate(name="Test Lot")
    assert fc.facility_type == FacilityType.surface_lot


def test_facility_update_all_optional():
    fu = FacilityUpdate()
    assert fu.name is None
    assert fu.city is None


def test_spot_create_requires_facility_id_and_identifier():
    with pytest.raises(ValidationError):
        SpotCreate(spot_identifier="A-01")  # missing facility_id
    with pytest.raises(ValidationError):
        SpotCreate(facility_id=FACILITY_ID)  # missing spot_identifier


def test_spot_create_defaults_spot_type():
    sc = SpotCreate(facility_id=FACILITY_ID, spot_identifier="A-01")
    assert sc.spot_type == SpotType.standard


def test_spot_create_rejects_empty_identifier():
    with pytest.raises(ValidationError):
        SpotCreate(facility_id=FACILITY_ID, spot_identifier="")


def test_assignment_create_requires_member_id_and_start_date():
    with pytest.raises(ValidationError):
        AssignmentCreate(start_date=_TODAY)  # missing member_id


def test_assignment_create_end_date_optional():
    ac = AssignmentCreate(member_id=MEMBER_ID, start_date=_TODAY)
    assert ac.end_date is None


def test_facility_response_from_attributes():
    facility = _make_facility()
    resp = FacilityResponse.model_validate(facility)
    assert resp.id == FACILITY_ID
    assert resp.account_id == ACCOUNT_ID
    assert resp.name == "Main Campus Garage"
    assert resp.is_active is True


def test_spot_response_from_attributes():
    spot = _make_spot()
    resp = SpotResponse.model_validate(spot)
    assert resp.id == SPOT_ID
    assert resp.spot_identifier == "A-01"
    assert resp.is_assigned is False


def test_assignment_response_from_attributes():
    assignment = _make_assignment()
    resp = AssignmentResponse.model_validate(assignment)
    assert resp.id == ASSIGNMENT_ID
    assert resp.member_id == MEMBER_ID
    assert resp.is_active is True


def test_facility_summary_structure():
    s = FacilitySummaryResponse(
        facility_id=FACILITY_ID,
        total_spots=10,
        active_spots=8,
        assigned_spots=5,
        available_spots=3,
        by_spot_type={"standard": 6, "ev_charging": 2},
    )
    assert s.available_spots == 3
    assert s.by_spot_type["ev_charging"] == 2


# ===========================================================================
# API LAYER TESTS
# ===========================================================================

_BASE = f"/api/v1/corporate/{ACCOUNT_ID}/parking"

_client = TestClient(app)


def _make_user(user_id: int = USER_ID, is_admin: bool = False):
    from app.models.user import User as UserModel
    u = MagicMock(spec=UserModel)
    u.id = user_id
    u.is_admin = is_admin
    return u


def _dep_overrides(user_id: int = USER_ID, is_admin: bool = False):
    from app.api.deps import get_current_user, get_db, require_admin

    async def _user():
        return _make_user(user_id=user_id, is_admin=is_admin)

    async def _db():
        return AsyncMock()

    async def _admin():
        return _make_user(user_id=ADMIN_ID, is_admin=True)

    return {
        get_current_user: _user,
        get_db: _db,
        require_admin: _admin,
    }


def _patch_get_account():
    return patch(f"{_ROUTER}.get_account", new_callable=AsyncMock)


def _patch_require_account_admin(raises: bool = False):
    if raises:
        return patch(
            f"{_ROUTER}._require_account_admin",
            new_callable=AsyncMock,
            side_effect=HTTPException(status_code=403, detail="forbidden"),
        )
    return patch(f"{_ROUTER}._require_account_admin", new_callable=AsyncMock)


def _facility_payload():
    return FacilityResponse(
        id=FACILITY_ID,
        account_id=ACCOUNT_ID,
        name="Main Campus Garage",
        description=None,
        address_line1=None,
        address_line2=None,
        city=None,
        state=None,
        zip_code=None,
        lat=None,
        lng=None,
        facility_type=FacilityType.parking_garage,
        notes=None,
        is_active=True,
        created_by_id=ADMIN_ID,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _spot_payload():
    return SpotResponse(
        id=SPOT_ID,
        account_id=ACCOUNT_ID,
        facility_id=FACILITY_ID,
        spot_identifier="A-01",
        spot_type=SpotType.standard,
        floor_level=None,
        is_assigned=False,
        notes=None,
        is_active=True,
        created_at=_NOW,
    )


def _assignment_payload():
    return AssignmentResponse(
        id=ASSIGNMENT_ID,
        account_id=ACCOUNT_ID,
        spot_id=SPOT_ID,
        member_id=MEMBER_ID,
        assigned_by_id=ADMIN_ID,
        permit_number=None,
        start_date=_TODAY,
        end_date=None,
        is_active=True,
        notes=None,
        ended_at=None,
        ended_by_id=None,
        created_at=_NOW,
    )


# ---- Member endpoints ----


def test_api_list_active_facilities_200():
    """Member can list active facilities."""
    with (
        _patch_get_account(),
        patch(f"{_ROUTER}.list_facilities", new_callable=AsyncMock, return_value=[_facility_payload()]),
    ):
        app.dependency_overrides.update(_dep_overrides())
        resp = _client.get(f"{_BASE}/facilities")
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["name"] == "Main Campus Garage"


def test_api_get_my_spots_200():
    """Member can get own parking assignments."""
    with (
        _patch_get_account(),
        patch(f"{_ROUTER}.get_member_parking", new_callable=AsyncMock, return_value=[_assignment_payload()]),
    ):
        app.dependency_overrides.update(_dep_overrides())
        resp = _client.get(f"{_BASE}/my-spots")
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json()[0]["member_id"] == MEMBER_ID


# ---- Admin: create facility ----


def test_api_create_facility_201():
    """Admin can create a parking facility."""
    with (
        _patch_get_account(),
        _patch_require_account_admin(),
        patch(f"{_ROUTER}.create_facility", new_callable=AsyncMock, return_value=_facility_payload()),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        resp = _client.post(
            f"{_BASE}/facilities",
            json={"name": "Main Campus Garage", "facility_type": "parking_garage"},
        )
        app.dependency_overrides.clear()
    assert resp.status_code == 201
    assert resp.json()["name"] == "Main Campus Garage"


def test_api_create_facility_403_non_admin():
    """Non-admin cannot create a facility."""
    with (
        _patch_get_account(),
        _patch_require_account_admin(raises=True),
    ):
        app.dependency_overrides.update(_dep_overrides())
        resp = _client.post(f"{_BASE}/facilities", json={"name": "Main Campus Garage"})
        app.dependency_overrides.clear()
    assert resp.status_code == 403


def test_api_create_facility_409_duplicate():
    """create_facility returns 409 on name collision."""
    with (
        _patch_get_account(),
        _patch_require_account_admin(),
        patch(
            f"{_ROUTER}.create_facility",
            new_callable=AsyncMock,
            side_effect=HTTPException(status_code=409, detail="Duplicate name"),
        ),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        resp = _client.post(f"{_BASE}/facilities", json={"name": "Garage"})
        app.dependency_overrides.clear()
    assert resp.status_code == 409


# ---- Admin: list all facilities ----


def test_api_list_all_facilities_200():
    """Admin can list all facilities including inactive."""
    with (
        _patch_get_account(),
        _patch_require_account_admin(),
        patch(f"{_ROUTER}.list_facilities", new_callable=AsyncMock, return_value=[_facility_payload()]),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        resp = _client.get(f"{_BASE}/facilities/all")
        app.dependency_overrides.clear()
    assert resp.status_code == 200


def test_api_list_all_facilities_403_non_admin():
    """Non-admin cannot list all facilities."""
    with (
        _patch_get_account(),
        _patch_require_account_admin(raises=True),
    ):
        app.dependency_overrides.update(_dep_overrides())
        resp = _client.get(f"{_BASE}/facilities/all")
        app.dependency_overrides.clear()
    assert resp.status_code == 403


# ---- Admin: get facility ----


def test_api_get_facility_200():
    """Admin can get a specific facility."""
    with (
        _patch_get_account(),
        _patch_require_account_admin(),
        patch(f"{_ROUTER}.get_facility", new_callable=AsyncMock, return_value=_facility_payload()),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        resp = _client.get(f"{_BASE}/facilities/{FACILITY_ID}")
        app.dependency_overrides.clear()
    assert resp.status_code == 200


def test_api_get_facility_404():
    """404 when facility not found."""
    with (
        _patch_get_account(),
        _patch_require_account_admin(),
        patch(
            f"{_ROUTER}.get_facility",
            new_callable=AsyncMock,
            side_effect=HTTPException(status_code=404, detail="Not found"),
        ),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        resp = _client.get(f"{_BASE}/facilities/{FACILITY_ID}")
        app.dependency_overrides.clear()
    assert resp.status_code == 404


# ---- Admin: update facility ----


def test_api_update_facility_200():
    """Admin can update a facility."""
    with (
        _patch_get_account(),
        _patch_require_account_admin(),
        patch(f"{_ROUTER}.update_facility", new_callable=AsyncMock, return_value=_facility_payload()),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        resp = _client.put(f"{_BASE}/facilities/{FACILITY_ID}", json={"city": "Chicago"})
        app.dependency_overrides.clear()
    assert resp.status_code == 200


def test_api_update_facility_403():
    """Non-admin cannot update a facility."""
    with (
        _patch_get_account(),
        _patch_require_account_admin(raises=True),
    ):
        app.dependency_overrides.update(_dep_overrides())
        resp = _client.put(f"{_BASE}/facilities/{FACILITY_ID}", json={"city": "Chicago"})
        app.dependency_overrides.clear()
    assert resp.status_code == 403


# ---- Admin: deactivate ----


def test_api_deactivate_facility_200():
    """Admin can deactivate a facility."""
    inactive_payload = _facility_payload().model_copy(update={"is_active": False})
    with (
        _patch_get_account(),
        _patch_require_account_admin(),
        patch(f"{_ROUTER}.deactivate_facility", new_callable=AsyncMock, return_value=inactive_payload),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        resp = _client.post(f"{_BASE}/facilities/{FACILITY_ID}/deactivate")
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False


def test_api_deactivate_facility_409_already_inactive():
    """409 when facility already inactive."""
    with (
        _patch_get_account(),
        _patch_require_account_admin(),
        patch(
            f"{_ROUTER}.deactivate_facility",
            new_callable=AsyncMock,
            side_effect=HTTPException(status_code=409, detail="Already inactive"),
        ),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        resp = _client.post(f"{_BASE}/facilities/{FACILITY_ID}/deactivate")
        app.dependency_overrides.clear()
    assert resp.status_code == 409


# ---- Admin: facility summary ----


def test_api_get_facility_summary_200():
    """Admin can get facility summary."""
    summary = FacilitySummaryResponse(
        facility_id=FACILITY_ID,
        total_spots=10,
        active_spots=8,
        assigned_spots=5,
        available_spots=3,
        by_spot_type={"standard": 6},
    )
    with (
        _patch_get_account(),
        _patch_require_account_admin(),
        patch(f"{_ROUTER}.get_facility_summary", new_callable=AsyncMock, return_value=summary),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        resp = _client.get(f"{_BASE}/facilities/{FACILITY_ID}/summary")
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json()["available_spots"] == 3


# ---- Admin: spots ----


def test_api_add_spot_201():
    """Admin can add a spot."""
    with (
        _patch_get_account(),
        _patch_require_account_admin(),
        patch(f"{_ROUTER}.add_spot", new_callable=AsyncMock, return_value=_spot_payload()),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        resp = _client.post(
            f"{_BASE}/spots",
            json={"facility_id": str(FACILITY_ID), "spot_identifier": "A-01"},
        )
        app.dependency_overrides.clear()
    assert resp.status_code == 201


def test_api_add_spot_403():
    """Non-admin cannot add a spot."""
    with (
        _patch_get_account(),
        _patch_require_account_admin(raises=True),
    ):
        app.dependency_overrides.update(_dep_overrides())
        resp = _client.post(
            f"{_BASE}/spots",
            json={"facility_id": str(FACILITY_ID), "spot_identifier": "A-01"},
        )
        app.dependency_overrides.clear()
    assert resp.status_code == 403


def test_api_list_spots_200():
    """Admin can list spots."""
    with (
        _patch_get_account(),
        _patch_require_account_admin(),
        patch(f"{_ROUTER}.list_spots", new_callable=AsyncMock, return_value=[_spot_payload()]),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        resp = _client.get(f"{_BASE}/spots")
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_api_get_spot_200():
    """Admin can get a specific spot."""
    with (
        _patch_get_account(),
        _patch_require_account_admin(),
        patch(f"{_ROUTER}.get_spot", new_callable=AsyncMock, return_value=_spot_payload()),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        resp = _client.get(f"{_BASE}/spots/{SPOT_ID}")
        app.dependency_overrides.clear()
    assert resp.status_code == 200


# ---- Admin: assign / end-assignment ----


def test_api_assign_spot_201():
    """Admin can assign a spot."""
    with (
        _patch_get_account(),
        _patch_require_account_admin(),
        patch(
            f"{_ROUTER}.assign_spot_to_member",
            new_callable=AsyncMock,
            return_value=_assignment_payload(),
        ),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        resp = _client.post(
            f"{_BASE}/spots/{SPOT_ID}/assign",
            json={"member_id": MEMBER_ID, "start_date": str(_TODAY)},
        )
        app.dependency_overrides.clear()
    assert resp.status_code == 201


def test_api_assign_spot_409_already_assigned():
    """409 when spot is already assigned."""
    with (
        _patch_get_account(),
        _patch_require_account_admin(),
        patch(
            f"{_ROUTER}.assign_spot_to_member",
            new_callable=AsyncMock,
            side_effect=HTTPException(status_code=409, detail="Already assigned"),
        ),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        resp = _client.post(
            f"{_BASE}/spots/{SPOT_ID}/assign",
            json={"member_id": MEMBER_ID, "start_date": str(_TODAY)},
        )
        app.dependency_overrides.clear()
    assert resp.status_code == 409


def test_api_end_assignment_200():
    """Admin can end an assignment."""
    ended_payload = _assignment_payload().model_copy(update={"is_active": False})
    with (
        _patch_get_account(),
        _patch_require_account_admin(),
        patch(
            f"{_ROUTER}.end_assignment",
            new_callable=AsyncMock,
            return_value=ended_payload,
        ),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        resp = _client.post(f"{_BASE}/spots/{SPOT_ID}/end-assignment")
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False


def test_api_end_assignment_404_no_active():
    """404 when no active assignment exists."""
    with (
        _patch_get_account(),
        _patch_require_account_admin(),
        patch(
            f"{_ROUTER}.end_assignment",
            new_callable=AsyncMock,
            side_effect=HTTPException(status_code=404, detail="No active assignment"),
        ),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        resp = _client.post(f"{_BASE}/spots/{SPOT_ID}/end-assignment")
        app.dependency_overrides.clear()
    assert resp.status_code == 404


# ---- Platform-admin ----


def test_api_platform_list_all_200():
    """Platform admin can list all facilities."""
    with (
        patch(
            f"{_ROUTER}.list_all_platform",
            new_callable=AsyncMock,
            return_value=[_facility_payload()],
        ),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        resp = _client.get("/api/v1/platform/corporate/parking/all")
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_api_platform_list_all_with_account_filter():
    """Platform admin can filter by account_id."""
    with (
        patch(
            f"{_ROUTER}.list_all_platform",
            new_callable=AsyncMock,
            return_value=[_facility_payload()],
        ),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        resp = _client.get(f"/api/v1/platform/corporate/parking/all?account_id={ACCOUNT_ID}")
        app.dependency_overrides.clear()
    assert resp.status_code == 200
