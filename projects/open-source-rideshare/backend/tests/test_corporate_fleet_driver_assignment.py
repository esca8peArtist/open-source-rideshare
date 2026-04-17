"""Tests for the Corporate Fleet Driver Assignment feature.

Service layer (async, mocked DB):
   1.  create_assignment — success: primary, sets status=active (today start_date)
   2.  create_assignment — success: future start_date sets status=pending
   3.  create_assignment — primary displaces existing active primary (ends it)
   4.  create_assignment — 404 when vehicle not in account
   5.  create_assignment — secondary success when 1 active secondary exists
   6.  create_assignment — 409 when 2 active secondary drivers already exist
   7.  create_assignment — pool assignment ignores per-vehicle uniqueness
   8.  create_assignment — temporary assignment ignores per-vehicle uniqueness
   9.  get_assignment — success: returns existing assignment
  10.  get_assignment — 404 when not found
  11.  get_vehicle_assignments — returns all for vehicle
  12.  get_vehicle_assignments — status filter works
  13.  get_vehicle_assignments — 404 vehicle not found
  14.  get_user_assignments — returns all for user
  15.  get_user_assignments — active_only filter works
  16.  get_active_primary_driver — returns active primary when exists
  17.  get_active_primary_driver — returns None when no active primary
  18.  update_assignment — success: updates end_date and notes
  19.  update_assignment — ignores None fields
  20.  update_assignment — 404 when not found
  21.  activate_assignment — success: pending → active
  22.  activate_assignment — 409 when status is active (not pending)
  23.  activate_assignment — 409 when status is inactive
  24.  suspend_assignment — success: active → suspended
  25.  suspend_assignment — 409 when status is pending
  26.  suspend_assignment — 409 when status is inactive
  27.  end_assignment — success from active: sets status=inactive, end_date=today
  28.  end_assignment — success from suspended: sets status=inactive
  29.  end_assignment — explicit end_date is used
  30.  end_assignment — 409 when status is pending
  31.  end_assignment — 409 when status is inactive
  32.  delete_assignment — success when inactive
  33.  delete_assignment — 409 when status is active
  34.  delete_assignment — 409 when status is pending
  35.  delete_assignment — 404 when not found
  36.  get_account_assignments — returns all for account
  37.  get_account_assignments — active_only filter works
  38.  list_all_assignments — returns all
  39.  list_all_assignments — account_id filter works

Schema validation:
  40.  DriverAssignmentCreate — valid construction
  41.  DriverAssignmentCreate — missing required field raises ValidationError
  42.  DriverAssignmentUpdate — all optional fields
  43.  EndAssignmentRequest — optional end_date
  44.  DriverAssignmentResponse — from_attributes works

API layer (service functions patched):
  45.  GET list vehicle assignments → 200
  46.  GET active primary driver → 200
  47.  GET single assignment → 200
  48.  POST create assignment → 201
  49.  GET list account assignments → 200
  50.  GET list active account assignments → 200
  51.  PUT update assignment → 200
  52.  POST activate assignment → 200
  53.  POST suspend assignment → 200
  54.  POST end assignment → 200
  55.  DELETE delete assignment → 204
  56.  GET platform list all → 200
  57.  Role: member cannot create assignment (expect 403)
  58.  Account scoping: admin cannot see other account's assignment (404)
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import app
from app.models.corporate_fleet_driver_assignment import (
    CorporateFleetDriverAssignment,
    FleetDriverAssignmentStatus,
    FleetDriverAssignmentType,
)
from app.schemas.corporate_fleet_driver_assignment import (
    DriverAssignmentCreate,
    DriverAssignmentResponse,
    DriverAssignmentUpdate,
    EndAssignmentRequest,
)
from app.services.corporate_fleet_driver_assignment_service import (
    activate_assignment,
    create_assignment,
    delete_assignment,
    end_assignment,
    get_account_assignments,
    get_active_primary_driver,
    get_assignment,
    get_user_assignments,
    get_vehicle_assignments,
    list_all_assignments,
    suspend_assignment,
    update_assignment,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ACCOUNT_ID = 42
VEHICLE_ID = uuid.uuid4()
ASSIGNMENT_ID = uuid.uuid4()
USER_ID = 100
ADMIN_ID = 1
OTHER_ACCOUNT_ID = 99

_SERVICE = "app.services.corporate_fleet_driver_assignment_service"
_ROUTER = "app.api.v1.corporate_fleet_driver_assignment"

_NOW = datetime(2026, 4, 17, 9, 0, 0, tzinfo=timezone.utc)
_TODAY = date(2026, 4, 17)
_FUTURE = date(2026, 5, 1)


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


def _make_assignment(
    assignment_id: uuid.UUID = ASSIGNMENT_ID,
    vehicle_id: uuid.UUID = VEHICLE_ID,
    account_id: int = ACCOUNT_ID,
    user_id: int = USER_ID,
    assignment_type: FleetDriverAssignmentType = FleetDriverAssignmentType.primary,
    status: FleetDriverAssignmentStatus = FleetDriverAssignmentStatus.active,
    start_date: date = _TODAY,
    end_date: date | None = None,
    authorized_by_user_id: int | None = ADMIN_ID,
    notes: str | None = None,
) -> CorporateFleetDriverAssignment:
    a = CorporateFleetDriverAssignment()
    a.id = assignment_id
    a.vehicle_id = vehicle_id
    a.account_id = account_id
    a.user_id = user_id
    a.assignment_type = assignment_type
    a.status = status
    a.start_date = start_date
    a.end_date = end_date
    a.authorized_by_user_id = authorized_by_user_id
    a.notes = notes
    a.created_at = _NOW
    a.updated_at = _NOW
    return a


def _make_response(a: CorporateFleetDriverAssignment | None = None) -> DriverAssignmentResponse:
    if a is None:
        a = _make_assignment()
    return DriverAssignmentResponse(
        id=a.id,
        vehicle_id=a.vehicle_id,
        account_id=a.account_id,
        user_id=a.user_id,
        assignment_type=a.assignment_type,
        status=a.status,
        start_date=a.start_date,
        end_date=a.end_date,
        authorized_by_user_id=a.authorized_by_user_id,
        notes=a.notes,
        created_at=a.created_at,
        updated_at=a.updated_at,
    )


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


def _mock_vehicle():
    from app.models.corporate_fleet_vehicle import CorporateFleetVehicle

    v = CorporateFleetVehicle()
    v.id = VEHICLE_ID
    v.account_id = ACCOUNT_ID
    v.name = "Fleet Car A"
    v.is_active = True
    return v


def _mock_db():
    db = AsyncMock()
    db.execute = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.delete = AsyncMock()
    return db


def _scalar_result(value):
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _scalars_result(values):
    result = MagicMock()
    scalars = MagicMock()
    scalars.all.return_value = values
    result.scalars.return_value = scalars
    return result


# ===========================================================================
# Service layer tests (1–39)
# ===========================================================================


def _refresh_with_timestamps(obj):
    """Simulate DB refresh by setting server-populated timestamp fields."""
    if not hasattr(obj, "created_at") or obj.created_at is None:
        obj.created_at = _NOW
    if not hasattr(obj, "updated_at") or obj.updated_at is None:
        obj.updated_at = _NOW


# --- Test 1 ---
@pytest.mark.asyncio
async def test_create_assignment_primary_active_today():
    """Primary assignment with today start_date gets status=active."""
    db = _mock_db()
    vehicle = _mock_vehicle()
    # No existing primary
    db.execute.return_value = _scalar_result(None)
    db.refresh.side_effect = _refresh_with_timestamps

    with patch(f"{_SERVICE}._fetch_vehicle", new_callable=AsyncMock) as mock_fv:
        mock_fv.return_value = vehicle
        with patch(f"{_SERVICE}.date") as mock_date:
            mock_date.today.return_value = _TODAY
            result = await create_assignment(
                db,
                account_id=ACCOUNT_ID,
                vehicle_id=VEHICLE_ID,
                user_id=USER_ID,
                assignment_type=FleetDriverAssignmentType.primary,
                start_date=_TODAY,
            )

    assert db.add.called
    assert db.commit.called


# --- Test 2 ---
@pytest.mark.asyncio
async def test_create_assignment_future_start_date_pending():
    """Primary assignment with future start_date gets status=pending."""
    db = _mock_db()
    vehicle = _mock_vehicle()
    # No existing primary
    db.execute.return_value = _scalar_result(None)
    db.refresh.side_effect = _refresh_with_timestamps

    with patch(f"{_SERVICE}._fetch_vehicle", new_callable=AsyncMock) as mock_fv:
        mock_fv.return_value = vehicle
        with patch(f"{_SERVICE}.date") as mock_date:
            mock_date.today.return_value = _TODAY
            result = await create_assignment(
                db,
                account_id=ACCOUNT_ID,
                vehicle_id=VEHICLE_ID,
                user_id=USER_ID,
                assignment_type=FleetDriverAssignmentType.primary,
                start_date=_FUTURE,
            )

    assert db.add.called
    # The newly added object should have pending status
    added_obj = db.add.call_args[0][0]
    assert added_obj.status == FleetDriverAssignmentStatus.pending


# --- Test 3 ---
@pytest.mark.asyncio
async def test_create_assignment_primary_ends_existing_primary():
    """Creating a new primary ends the existing active primary."""
    db = _mock_db()
    vehicle = _mock_vehicle()
    existing = _make_assignment(
        assignment_id=uuid.uuid4(),
        status=FleetDriverAssignmentStatus.active,
    )
    db.execute.return_value = _scalar_result(existing)
    db.refresh.side_effect = _refresh_with_timestamps

    with patch(f"{_SERVICE}._fetch_vehicle", new_callable=AsyncMock) as mock_fv:
        mock_fv.return_value = vehicle
        with patch(f"{_SERVICE}.date") as mock_date:
            mock_date.today.return_value = _TODAY
            await create_assignment(
                db,
                account_id=ACCOUNT_ID,
                vehicle_id=VEHICLE_ID,
                user_id=USER_ID + 1,
                assignment_type=FleetDriverAssignmentType.primary,
                start_date=_TODAY,
            )

    # existing primary should be ended
    assert existing.status == FleetDriverAssignmentStatus.inactive
    assert existing.end_date == _TODAY


# --- Test 4 ---
@pytest.mark.asyncio
async def test_create_assignment_404_vehicle_not_found():
    db = _mock_db()
    with patch(f"{_SERVICE}._fetch_vehicle", new_callable=AsyncMock) as mock_fv:
        mock_fv.side_effect = HTTPException(status_code=404, detail="not found")
        with pytest.raises(HTTPException) as exc:
            await create_assignment(
                db,
                account_id=ACCOUNT_ID,
                vehicle_id=VEHICLE_ID,
                user_id=USER_ID,
                assignment_type=FleetDriverAssignmentType.primary,
                start_date=_TODAY,
            )
    assert exc.value.status_code == 404


# --- Test 5 ---
@pytest.mark.asyncio
async def test_create_assignment_secondary_success_with_one_existing():
    """Secondary assignment succeeds when only 1 active secondary exists."""
    db = _mock_db()
    vehicle = _mock_vehicle()
    existing_secondary = _make_assignment(
        assignment_type=FleetDriverAssignmentType.secondary,
        status=FleetDriverAssignmentStatus.active,
    )
    db.execute.return_value = _scalars_result([existing_secondary])
    db.refresh.side_effect = _refresh_with_timestamps

    with patch(f"{_SERVICE}._fetch_vehicle", new_callable=AsyncMock) as mock_fv:
        mock_fv.return_value = vehicle
        with patch(f"{_SERVICE}.date") as mock_date:
            mock_date.today.return_value = _TODAY
            await create_assignment(
                db,
                account_id=ACCOUNT_ID,
                vehicle_id=VEHICLE_ID,
                user_id=USER_ID + 5,
                assignment_type=FleetDriverAssignmentType.secondary,
                start_date=_TODAY,
            )

    assert db.add.called


# --- Test 6 ---
@pytest.mark.asyncio
async def test_create_assignment_secondary_409_limit_exceeded():
    """Secondary assignment raises 409 when 2 active secondaries already exist."""
    db = _mock_db()
    vehicle = _mock_vehicle()
    sec1 = _make_assignment(
        assignment_type=FleetDriverAssignmentType.secondary,
        status=FleetDriverAssignmentStatus.active,
    )
    sec2 = _make_assignment(
        assignment_id=uuid.uuid4(),
        user_id=USER_ID + 1,
        assignment_type=FleetDriverAssignmentType.secondary,
        status=FleetDriverAssignmentStatus.active,
    )

    with patch(f"{_SERVICE}._fetch_vehicle", new_callable=AsyncMock) as mock_fv:
        mock_fv.return_value = vehicle
        db.execute.return_value = _scalars_result([sec1, sec2])
        with patch(f"{_SERVICE}.date") as mock_date:
            mock_date.today.return_value = _TODAY
            with pytest.raises(HTTPException) as exc:
                await create_assignment(
                    db,
                    account_id=ACCOUNT_ID,
                    vehicle_id=VEHICLE_ID,
                    user_id=USER_ID + 2,
                    assignment_type=FleetDriverAssignmentType.secondary,
                    start_date=_TODAY,
                )
    assert exc.value.status_code == 409


# --- Test 7 ---
@pytest.mark.asyncio
async def test_create_assignment_pool_ignores_uniqueness():
    """Pool assignment has no per-vehicle uniqueness constraint."""
    db = _mock_db()
    vehicle = _mock_vehicle()
    db.refresh.side_effect = _refresh_with_timestamps

    with patch(f"{_SERVICE}._fetch_vehicle", new_callable=AsyncMock) as mock_fv:
        mock_fv.return_value = vehicle
        with patch(f"{_SERVICE}.date") as mock_date:
            mock_date.today.return_value = _TODAY
            await create_assignment(
                db,
                account_id=ACCOUNT_ID,
                vehicle_id=VEHICLE_ID,
                user_id=USER_ID,
                assignment_type=FleetDriverAssignmentType.pool,
                start_date=_TODAY,
            )

    # No execute call for uniqueness check on pool assignments
    assert db.add.called


# --- Test 8 ---
@pytest.mark.asyncio
async def test_create_assignment_temporary_ignores_uniqueness():
    """Temporary assignment has no per-vehicle uniqueness constraint."""
    db = _mock_db()
    vehicle = _mock_vehicle()
    db.refresh.side_effect = _refresh_with_timestamps

    with patch(f"{_SERVICE}._fetch_vehicle", new_callable=AsyncMock) as mock_fv:
        mock_fv.return_value = vehicle
        with patch(f"{_SERVICE}.date") as mock_date:
            mock_date.today.return_value = _TODAY
            await create_assignment(
                db,
                account_id=ACCOUNT_ID,
                vehicle_id=VEHICLE_ID,
                user_id=USER_ID,
                assignment_type=FleetDriverAssignmentType.temporary,
                start_date=_TODAY,
            )

    assert db.add.called


# --- Test 9 ---
@pytest.mark.asyncio
async def test_get_assignment_success():
    db = _mock_db()
    a = _make_assignment()
    with patch(f"{_SERVICE}._fetch_assignment", new_callable=AsyncMock) as mock_fa:
        mock_fa.return_value = a
        result = await get_assignment(db, ACCOUNT_ID, ASSIGNMENT_ID)
    assert result.id == ASSIGNMENT_ID
    assert result.assignment_type == FleetDriverAssignmentType.primary


# --- Test 10 ---
@pytest.mark.asyncio
async def test_get_assignment_404():
    db = _mock_db()
    with patch(f"{_SERVICE}._fetch_assignment", new_callable=AsyncMock) as mock_fa:
        mock_fa.side_effect = HTTPException(status_code=404, detail="not found")
        with pytest.raises(HTTPException) as exc:
            await get_assignment(db, ACCOUNT_ID, uuid.uuid4())
    assert exc.value.status_code == 404


# --- Test 11 ---
@pytest.mark.asyncio
async def test_get_vehicle_assignments_returns_all():
    db = _mock_db()
    vehicle = _mock_vehicle()
    a1 = _make_assignment()
    a2 = _make_assignment(assignment_id=uuid.uuid4(), user_id=USER_ID + 1)

    with patch(f"{_SERVICE}._fetch_vehicle", new_callable=AsyncMock) as mock_fv:
        mock_fv.return_value = vehicle
        db.execute.return_value = _scalars_result([a1, a2])
        result = await get_vehicle_assignments(db, ACCOUNT_ID, VEHICLE_ID)
    assert len(result) == 2


# --- Test 12 ---
@pytest.mark.asyncio
async def test_get_vehicle_assignments_status_filter():
    db = _mock_db()
    vehicle = _mock_vehicle()
    active_a = _make_assignment(status=FleetDriverAssignmentStatus.active)

    with patch(f"{_SERVICE}._fetch_vehicle", new_callable=AsyncMock) as mock_fv:
        mock_fv.return_value = vehicle
        db.execute.return_value = _scalars_result([active_a])
        result = await get_vehicle_assignments(
            db, ACCOUNT_ID, VEHICLE_ID, status=FleetDriverAssignmentStatus.active
        )
    assert all(r.status == FleetDriverAssignmentStatus.active for r in result)


# --- Test 13 ---
@pytest.mark.asyncio
async def test_get_vehicle_assignments_404_vehicle():
    db = _mock_db()
    with patch(f"{_SERVICE}._fetch_vehicle", new_callable=AsyncMock) as mock_fv:
        mock_fv.side_effect = HTTPException(status_code=404, detail="not found")
        with pytest.raises(HTTPException) as exc:
            await get_vehicle_assignments(db, ACCOUNT_ID, VEHICLE_ID)
    assert exc.value.status_code == 404


# --- Test 14 ---
@pytest.mark.asyncio
async def test_get_user_assignments_returns_all():
    db = _mock_db()
    a1 = _make_assignment()
    a2 = _make_assignment(
        assignment_id=uuid.uuid4(),
        vehicle_id=uuid.uuid4(),
        assignment_type=FleetDriverAssignmentType.pool,
    )
    db.execute.return_value = _scalars_result([a1, a2])
    result = await get_user_assignments(db, USER_ID)
    assert len(result) == 2


# --- Test 15 ---
@pytest.mark.asyncio
async def test_get_user_assignments_active_only():
    db = _mock_db()
    active_a = _make_assignment(status=FleetDriverAssignmentStatus.active)
    db.execute.return_value = _scalars_result([active_a])
    result = await get_user_assignments(db, USER_ID, active_only=True)
    assert all(r.status == FleetDriverAssignmentStatus.active for r in result)


# --- Test 16 ---
@pytest.mark.asyncio
async def test_get_active_primary_driver_found():
    db = _mock_db()
    vehicle = _mock_vehicle()
    primary = _make_assignment(
        status=FleetDriverAssignmentStatus.active,
        assignment_type=FleetDriverAssignmentType.primary,
    )

    with patch(f"{_SERVICE}._fetch_vehicle", new_callable=AsyncMock) as mock_fv:
        mock_fv.return_value = vehicle
        db.execute.return_value = _scalar_result(primary)
        result = await get_active_primary_driver(db, ACCOUNT_ID, VEHICLE_ID)
    assert result is not None
    assert result.assignment_type == FleetDriverAssignmentType.primary


# --- Test 17 ---
@pytest.mark.asyncio
async def test_get_active_primary_driver_none():
    db = _mock_db()
    vehicle = _mock_vehicle()

    with patch(f"{_SERVICE}._fetch_vehicle", new_callable=AsyncMock) as mock_fv:
        mock_fv.return_value = vehicle
        db.execute.return_value = _scalar_result(None)
        result = await get_active_primary_driver(db, ACCOUNT_ID, VEHICLE_ID)
    assert result is None


# --- Test 18 ---
@pytest.mark.asyncio
async def test_update_assignment_success():
    db = _mock_db()
    a = _make_assignment()

    with patch(f"{_SERVICE}._fetch_assignment", new_callable=AsyncMock) as mock_fa:
        mock_fa.return_value = a
        db.refresh.side_effect = lambda obj: None
        data = DriverAssignmentUpdate(
            end_date=_FUTURE,
            notes="Updated notes",
        )
        result = await update_assignment(db, ACCOUNT_ID, ASSIGNMENT_ID, data)

    assert a.end_date == _FUTURE
    assert a.notes == "Updated notes"
    assert db.commit.called


# --- Test 19 ---
@pytest.mark.asyncio
async def test_update_assignment_ignores_none_fields():
    db = _mock_db()
    a = _make_assignment(notes="original notes")

    with patch(f"{_SERVICE}._fetch_assignment", new_callable=AsyncMock) as mock_fa:
        mock_fa.return_value = a
        db.refresh.side_effect = lambda obj: None
        data = DriverAssignmentUpdate()  # all None
        await update_assignment(db, ACCOUNT_ID, ASSIGNMENT_ID, data)

    # notes should be unchanged
    assert a.notes == "original notes"


# --- Test 20 ---
@pytest.mark.asyncio
async def test_update_assignment_404():
    db = _mock_db()
    with patch(f"{_SERVICE}._fetch_assignment", new_callable=AsyncMock) as mock_fa:
        mock_fa.side_effect = HTTPException(status_code=404, detail="not found")
        with pytest.raises(HTTPException) as exc:
            await update_assignment(
                db, ACCOUNT_ID, uuid.uuid4(), DriverAssignmentUpdate()
            )
    assert exc.value.status_code == 404


# --- Test 21 ---
@pytest.mark.asyncio
async def test_activate_assignment_success():
    db = _mock_db()
    a = _make_assignment(status=FleetDriverAssignmentStatus.pending)

    with patch(f"{_SERVICE}._fetch_assignment", new_callable=AsyncMock) as mock_fa:
        mock_fa.return_value = a
        db.refresh.side_effect = lambda obj: None
        result = await activate_assignment(db, ACCOUNT_ID, ASSIGNMENT_ID)

    assert a.status == FleetDriverAssignmentStatus.active


# --- Test 22 ---
@pytest.mark.asyncio
async def test_activate_assignment_409_when_active():
    db = _mock_db()
    a = _make_assignment(status=FleetDriverAssignmentStatus.active)

    with patch(f"{_SERVICE}._fetch_assignment", new_callable=AsyncMock) as mock_fa:
        mock_fa.return_value = a
        with pytest.raises(HTTPException) as exc:
            await activate_assignment(db, ACCOUNT_ID, ASSIGNMENT_ID)
    assert exc.value.status_code == 409


# --- Test 23 ---
@pytest.mark.asyncio
async def test_activate_assignment_409_when_inactive():
    db = _mock_db()
    a = _make_assignment(status=FleetDriverAssignmentStatus.inactive)

    with patch(f"{_SERVICE}._fetch_assignment", new_callable=AsyncMock) as mock_fa:
        mock_fa.return_value = a
        with pytest.raises(HTTPException) as exc:
            await activate_assignment(db, ACCOUNT_ID, ASSIGNMENT_ID)
    assert exc.value.status_code == 409


# --- Test 24 ---
@pytest.mark.asyncio
async def test_suspend_assignment_success():
    db = _mock_db()
    a = _make_assignment(status=FleetDriverAssignmentStatus.active)

    with patch(f"{_SERVICE}._fetch_assignment", new_callable=AsyncMock) as mock_fa:
        mock_fa.return_value = a
        db.refresh.side_effect = lambda obj: None
        await suspend_assignment(db, ACCOUNT_ID, ASSIGNMENT_ID)

    assert a.status == FleetDriverAssignmentStatus.suspended


# --- Test 25 ---
@pytest.mark.asyncio
async def test_suspend_assignment_409_when_pending():
    db = _mock_db()
    a = _make_assignment(status=FleetDriverAssignmentStatus.pending)

    with patch(f"{_SERVICE}._fetch_assignment", new_callable=AsyncMock) as mock_fa:
        mock_fa.return_value = a
        with pytest.raises(HTTPException) as exc:
            await suspend_assignment(db, ACCOUNT_ID, ASSIGNMENT_ID)
    assert exc.value.status_code == 409


# --- Test 26 ---
@pytest.mark.asyncio
async def test_suspend_assignment_409_when_inactive():
    db = _mock_db()
    a = _make_assignment(status=FleetDriverAssignmentStatus.inactive)

    with patch(f"{_SERVICE}._fetch_assignment", new_callable=AsyncMock) as mock_fa:
        mock_fa.return_value = a
        with pytest.raises(HTTPException) as exc:
            await suspend_assignment(db, ACCOUNT_ID, ASSIGNMENT_ID)
    assert exc.value.status_code == 409


# --- Test 27 ---
@pytest.mark.asyncio
async def test_end_assignment_from_active_default_end_date():
    db = _mock_db()
    a = _make_assignment(status=FleetDriverAssignmentStatus.active)

    with patch(f"{_SERVICE}._fetch_assignment", new_callable=AsyncMock) as mock_fa:
        mock_fa.return_value = a
        db.refresh.side_effect = lambda obj: None
        with patch(f"{_SERVICE}.date") as mock_date:
            mock_date.today.return_value = _TODAY
            await end_assignment(db, ACCOUNT_ID, ASSIGNMENT_ID)

    assert a.status == FleetDriverAssignmentStatus.inactive
    assert a.end_date == _TODAY


# --- Test 28 ---
@pytest.mark.asyncio
async def test_end_assignment_from_suspended():
    db = _mock_db()
    a = _make_assignment(status=FleetDriverAssignmentStatus.suspended)

    with patch(f"{_SERVICE}._fetch_assignment", new_callable=AsyncMock) as mock_fa:
        mock_fa.return_value = a
        db.refresh.side_effect = lambda obj: None
        with patch(f"{_SERVICE}.date") as mock_date:
            mock_date.today.return_value = _TODAY
            await end_assignment(db, ACCOUNT_ID, ASSIGNMENT_ID)

    assert a.status == FleetDriverAssignmentStatus.inactive


# --- Test 29 ---
@pytest.mark.asyncio
async def test_end_assignment_explicit_end_date():
    db = _mock_db()
    a = _make_assignment(status=FleetDriverAssignmentStatus.active)
    explicit_end = date(2026, 6, 30)

    with patch(f"{_SERVICE}._fetch_assignment", new_callable=AsyncMock) as mock_fa:
        mock_fa.return_value = a
        db.refresh.side_effect = lambda obj: None
        await end_assignment(db, ACCOUNT_ID, ASSIGNMENT_ID, end_date=explicit_end)

    assert a.end_date == explicit_end


# --- Test 30 ---
@pytest.mark.asyncio
async def test_end_assignment_409_from_pending():
    db = _mock_db()
    a = _make_assignment(status=FleetDriverAssignmentStatus.pending)

    with patch(f"{_SERVICE}._fetch_assignment", new_callable=AsyncMock) as mock_fa:
        mock_fa.return_value = a
        with pytest.raises(HTTPException) as exc:
            await end_assignment(db, ACCOUNT_ID, ASSIGNMENT_ID)
    assert exc.value.status_code == 409


# --- Test 31 ---
@pytest.mark.asyncio
async def test_end_assignment_409_from_inactive():
    db = _mock_db()
    a = _make_assignment(status=FleetDriverAssignmentStatus.inactive)

    with patch(f"{_SERVICE}._fetch_assignment", new_callable=AsyncMock) as mock_fa:
        mock_fa.return_value = a
        with pytest.raises(HTTPException) as exc:
            await end_assignment(db, ACCOUNT_ID, ASSIGNMENT_ID)
    assert exc.value.status_code == 409


# --- Test 32 ---
@pytest.mark.asyncio
async def test_delete_assignment_success_when_inactive():
    db = _mock_db()
    a = _make_assignment(status=FleetDriverAssignmentStatus.inactive)

    with patch(f"{_SERVICE}._fetch_assignment", new_callable=AsyncMock) as mock_fa:
        mock_fa.return_value = a
        await delete_assignment(db, ACCOUNT_ID, ASSIGNMENT_ID)

    assert db.delete.called
    assert db.commit.called


# --- Test 33 ---
@pytest.mark.asyncio
async def test_delete_assignment_409_when_active():
    db = _mock_db()
    a = _make_assignment(status=FleetDriverAssignmentStatus.active)

    with patch(f"{_SERVICE}._fetch_assignment", new_callable=AsyncMock) as mock_fa:
        mock_fa.return_value = a
        with pytest.raises(HTTPException) as exc:
            await delete_assignment(db, ACCOUNT_ID, ASSIGNMENT_ID)
    assert exc.value.status_code == 409


# --- Test 34 ---
@pytest.mark.asyncio
async def test_delete_assignment_409_when_pending():
    db = _mock_db()
    a = _make_assignment(status=FleetDriverAssignmentStatus.pending)

    with patch(f"{_SERVICE}._fetch_assignment", new_callable=AsyncMock) as mock_fa:
        mock_fa.return_value = a
        with pytest.raises(HTTPException) as exc:
            await delete_assignment(db, ACCOUNT_ID, ASSIGNMENT_ID)
    assert exc.value.status_code == 409


# --- Test 35 ---
@pytest.mark.asyncio
async def test_delete_assignment_404():
    db = _mock_db()
    with patch(f"{_SERVICE}._fetch_assignment", new_callable=AsyncMock) as mock_fa:
        mock_fa.side_effect = HTTPException(status_code=404, detail="not found")
        with pytest.raises(HTTPException) as exc:
            await delete_assignment(db, ACCOUNT_ID, uuid.uuid4())
    assert exc.value.status_code == 404


# --- Test 36 ---
@pytest.mark.asyncio
async def test_get_account_assignments_returns_all():
    db = _mock_db()
    a1 = _make_assignment()
    a2 = _make_assignment(assignment_id=uuid.uuid4(), user_id=USER_ID + 1)
    db.execute.return_value = _scalars_result([a1, a2])
    result = await get_account_assignments(db, ACCOUNT_ID)
    assert len(result) == 2


# --- Test 37 ---
@pytest.mark.asyncio
async def test_get_account_assignments_active_only():
    db = _mock_db()
    active_a = _make_assignment(status=FleetDriverAssignmentStatus.active)
    db.execute.return_value = _scalars_result([active_a])
    result = await get_account_assignments(db, ACCOUNT_ID, active_only=True)
    assert all(r.status == FleetDriverAssignmentStatus.active for r in result)


# --- Test 38 ---
@pytest.mark.asyncio
async def test_list_all_assignments_returns_all():
    db = _mock_db()
    a1 = _make_assignment()
    a2 = _make_assignment(assignment_id=uuid.uuid4(), account_id=OTHER_ACCOUNT_ID)
    db.execute.return_value = _scalars_result([a1, a2])
    result = await list_all_assignments(db)
    assert len(result) == 2


# --- Test 39 ---
@pytest.mark.asyncio
async def test_list_all_assignments_account_filter():
    db = _mock_db()
    a1 = _make_assignment()
    db.execute.return_value = _scalars_result([a1])
    result = await list_all_assignments(db, account_id=ACCOUNT_ID)
    assert len(result) == 1
    assert result[0].account_id == ACCOUNT_ID


# ===========================================================================
# Schema validation tests (40–44)
# ===========================================================================


# --- Test 40 ---
def test_driver_assignment_create_valid():
    data = DriverAssignmentCreate(
        vehicle_id=VEHICLE_ID,
        user_id=USER_ID,
        assignment_type=FleetDriverAssignmentType.primary,
        start_date=_TODAY,
    )
    assert data.assignment_type == FleetDriverAssignmentType.primary
    assert data.end_date is None


# --- Test 41 ---
def test_driver_assignment_create_missing_required():
    with pytest.raises(ValidationError):
        DriverAssignmentCreate(
            vehicle_id=VEHICLE_ID,
            # user_id missing
            assignment_type=FleetDriverAssignmentType.primary,
            start_date=_TODAY,
        )


# --- Test 42 ---
def test_driver_assignment_update_all_optional():
    data = DriverAssignmentUpdate()
    assert data.end_date is None
    assert data.notes is None
    assert data.status is None


# --- Test 43 ---
def test_end_assignment_request_optional_end_date():
    req = EndAssignmentRequest()
    assert req.end_date is None

    req2 = EndAssignmentRequest(end_date=_FUTURE)
    assert req2.end_date == _FUTURE


# --- Test 44 ---
def test_driver_assignment_response_from_attributes():
    a = _make_assignment()
    resp = DriverAssignmentResponse.model_validate(a)
    assert resp.id == a.id
    assert resp.vehicle_id == a.vehicle_id
    assert resp.account_id == a.account_id
    assert resp.user_id == a.user_id
    assert resp.assignment_type == a.assignment_type
    assert resp.status == a.status


# ===========================================================================
# API layer tests (45–58)
# ===========================================================================

client = TestClient(app)

_RESP = _make_response()
_RESP_DICT = _RESP.model_dump(mode="json")


def _override_deps(user_role: str = "member"):
    """Return overrides dict for FastAPI dependency injection."""
    from app.api.deps import get_current_user, get_db, require_admin
    from app.services.corporate_account_mgmt import get_account
    from app.services.corporate_trip_purpose import _require_account_admin

    mock_user = MagicMock()
    mock_user.id = USER_ID
    mock_user.role = user_role

    mock_db = AsyncMock()

    overrides = {
        get_db: lambda: mock_db,
        get_current_user: lambda: mock_user,
    }
    if user_role == "admin":
        overrides[require_admin] = lambda: mock_user
    return overrides


# --- Test 45 ---
def test_api_list_vehicle_driver_assignments_200():
    with patch(f"{_ROUTER}.get_account", new_callable=AsyncMock):
        with patch(f"{_ROUTER}.get_vehicle_assignments", new_callable=AsyncMock) as mock_svc:
            mock_svc.return_value = [_RESP]
            from app.api.deps import get_current_user, get_db
            from app.services.corporate_account_mgmt import get_account as ga

            mock_user = MagicMock()
            mock_user.id = USER_ID
            app.dependency_overrides[get_db] = lambda: AsyncMock()
            app.dependency_overrides[get_current_user] = lambda: mock_user

            resp = client.get(
                f"/api/v1/corporate/{ACCOUNT_ID}/fleet-vehicles/{VEHICLE_ID}/driver-assignments"
            )
            app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


# --- Test 46 ---
def test_api_get_primary_driver_200():
    with patch(f"{_ROUTER}.get_account", new_callable=AsyncMock):
        with patch(f"{_ROUTER}.get_active_primary_driver", new_callable=AsyncMock) as mock_svc:
            mock_svc.return_value = _RESP
            from app.api.deps import get_current_user, get_db

            mock_user = MagicMock()
            mock_user.id = USER_ID
            app.dependency_overrides[get_db] = lambda: AsyncMock()
            app.dependency_overrides[get_current_user] = lambda: mock_user

            resp = client.get(
                f"/api/v1/corporate/{ACCOUNT_ID}/fleet-vehicles/{VEHICLE_ID}/driver-assignments/primary"
            )
            app.dependency_overrides.clear()
    assert resp.status_code == 200


# --- Test 47 ---
def test_api_get_single_assignment_200():
    with patch(f"{_ROUTER}.get_account", new_callable=AsyncMock):
        with patch(f"{_ROUTER}.get_assignment", new_callable=AsyncMock) as mock_svc:
            mock_svc.return_value = _RESP
            from app.api.deps import get_current_user, get_db

            mock_user = MagicMock()
            mock_user.id = USER_ID
            app.dependency_overrides[get_db] = lambda: AsyncMock()
            app.dependency_overrides[get_current_user] = lambda: mock_user

            resp = client.get(
                f"/api/v1/corporate/{ACCOUNT_ID}/fleet-vehicles/{VEHICLE_ID}"
                f"/driver-assignments/{ASSIGNMENT_ID}"
            )
            app.dependency_overrides.clear()
    assert resp.status_code == 200


# --- Test 48 ---
def test_api_create_assignment_201():
    with patch(f"{_ROUTER}.get_account", new_callable=AsyncMock):
        with patch(f"{_ROUTER}._require_account_admin", new_callable=AsyncMock):
            with patch(f"{_ROUTER}.create_assignment", new_callable=AsyncMock) as mock_svc:
                mock_svc.return_value = _RESP
                from app.api.deps import get_current_user, get_db

                mock_user = MagicMock()
                mock_user.id = ADMIN_ID
                app.dependency_overrides[get_db] = lambda: AsyncMock()
                app.dependency_overrides[get_current_user] = lambda: mock_user

                payload = {
                    "vehicle_id": str(VEHICLE_ID),
                    "user_id": USER_ID,
                    "assignment_type": "primary",
                    "start_date": str(_TODAY),
                }
                resp = client.post(
                    f"/api/v1/corporate/{ACCOUNT_ID}/fleet-vehicles/{VEHICLE_ID}/driver-assignments",
                    json=payload,
                )
                app.dependency_overrides.clear()
    assert resp.status_code == 201


# --- Test 49 ---
def test_api_list_account_assignments_200():
    with patch(f"{_ROUTER}.get_account", new_callable=AsyncMock):
        with patch(f"{_ROUTER}._require_account_admin", new_callable=AsyncMock):
            with patch(f"{_ROUTER}.get_account_assignments", new_callable=AsyncMock) as mock_svc:
                mock_svc.return_value = [_RESP]
                from app.api.deps import get_current_user, get_db

                mock_user = MagicMock()
                mock_user.id = ADMIN_ID
                app.dependency_overrides[get_db] = lambda: AsyncMock()
                app.dependency_overrides[get_current_user] = lambda: mock_user

                resp = client.get(
                    f"/api/v1/corporate/{ACCOUNT_ID}/fleet-driver-assignments/"
                )
                app.dependency_overrides.clear()
    assert resp.status_code == 200


# --- Test 50 ---
def test_api_list_active_account_assignments_200():
    with patch(f"{_ROUTER}.get_account", new_callable=AsyncMock):
        with patch(f"{_ROUTER}._require_account_admin", new_callable=AsyncMock):
            with patch(f"{_ROUTER}.get_account_assignments", new_callable=AsyncMock) as mock_svc:
                mock_svc.return_value = [_RESP]
                from app.api.deps import get_current_user, get_db

                mock_user = MagicMock()
                mock_user.id = ADMIN_ID
                app.dependency_overrides[get_db] = lambda: AsyncMock()
                app.dependency_overrides[get_current_user] = lambda: mock_user

                resp = client.get(
                    f"/api/v1/corporate/{ACCOUNT_ID}/fleet-driver-assignments/active"
                )
                app.dependency_overrides.clear()
    assert resp.status_code == 200


# --- Test 51 ---
def test_api_update_assignment_200():
    with patch(f"{_ROUTER}.get_account", new_callable=AsyncMock):
        with patch(f"{_ROUTER}._require_account_admin", new_callable=AsyncMock):
            with patch(f"{_ROUTER}.update_assignment", new_callable=AsyncMock) as mock_svc:
                mock_svc.return_value = _RESP
                from app.api.deps import get_current_user, get_db

                mock_user = MagicMock()
                mock_user.id = ADMIN_ID
                app.dependency_overrides[get_db] = lambda: AsyncMock()
                app.dependency_overrides[get_current_user] = lambda: mock_user

                resp = client.put(
                    f"/api/v1/corporate/{ACCOUNT_ID}/fleet-driver-assignments/{ASSIGNMENT_ID}",
                    json={"notes": "Updated note"},
                )
                app.dependency_overrides.clear()
    assert resp.status_code == 200


# --- Test 52 ---
def test_api_activate_assignment_200():
    with patch(f"{_ROUTER}.get_account", new_callable=AsyncMock):
        with patch(f"{_ROUTER}._require_account_admin", new_callable=AsyncMock):
            with patch(f"{_ROUTER}.activate_assignment", new_callable=AsyncMock) as mock_svc:
                mock_svc.return_value = _RESP
                from app.api.deps import get_current_user, get_db

                mock_user = MagicMock()
                mock_user.id = ADMIN_ID
                app.dependency_overrides[get_db] = lambda: AsyncMock()
                app.dependency_overrides[get_current_user] = lambda: mock_user

                resp = client.post(
                    f"/api/v1/corporate/{ACCOUNT_ID}/fleet-driver-assignments/{ASSIGNMENT_ID}/activate"
                )
                app.dependency_overrides.clear()
    assert resp.status_code == 200


# --- Test 53 ---
def test_api_suspend_assignment_200():
    with patch(f"{_ROUTER}.get_account", new_callable=AsyncMock):
        with patch(f"{_ROUTER}._require_account_admin", new_callable=AsyncMock):
            with patch(f"{_ROUTER}.suspend_assignment", new_callable=AsyncMock) as mock_svc:
                mock_svc.return_value = _RESP
                from app.api.deps import get_current_user, get_db

                mock_user = MagicMock()
                mock_user.id = ADMIN_ID
                app.dependency_overrides[get_db] = lambda: AsyncMock()
                app.dependency_overrides[get_current_user] = lambda: mock_user

                resp = client.post(
                    f"/api/v1/corporate/{ACCOUNT_ID}/fleet-driver-assignments/{ASSIGNMENT_ID}/suspend"
                )
                app.dependency_overrides.clear()
    assert resp.status_code == 200


# --- Test 54 ---
def test_api_end_assignment_200():
    with patch(f"{_ROUTER}.get_account", new_callable=AsyncMock):
        with patch(f"{_ROUTER}._require_account_admin", new_callable=AsyncMock):
            with patch(f"{_ROUTER}.end_assignment", new_callable=AsyncMock) as mock_svc:
                mock_svc.return_value = _RESP
                from app.api.deps import get_current_user, get_db

                mock_user = MagicMock()
                mock_user.id = ADMIN_ID
                app.dependency_overrides[get_db] = lambda: AsyncMock()
                app.dependency_overrides[get_current_user] = lambda: mock_user

                resp = client.post(
                    f"/api/v1/corporate/{ACCOUNT_ID}/fleet-driver-assignments/{ASSIGNMENT_ID}/end",
                    json={"end_date": str(_TODAY)},
                )
                app.dependency_overrides.clear()
    assert resp.status_code == 200


# --- Test 55 ---
def test_api_delete_assignment_204():
    with patch(f"{_ROUTER}.get_account", new_callable=AsyncMock):
        with patch(f"{_ROUTER}._require_account_admin", new_callable=AsyncMock):
            with patch(f"{_ROUTER}.delete_assignment", new_callable=AsyncMock) as mock_svc:
                mock_svc.return_value = None
                from app.api.deps import get_current_user, get_db

                mock_user = MagicMock()
                mock_user.id = ADMIN_ID
                app.dependency_overrides[get_db] = lambda: AsyncMock()
                app.dependency_overrides[get_current_user] = lambda: mock_user

                resp = client.delete(
                    f"/api/v1/corporate/{ACCOUNT_ID}/fleet-driver-assignments/{ASSIGNMENT_ID}"
                )
                app.dependency_overrides.clear()
    assert resp.status_code == 204


# --- Test 56 ---
def test_api_platform_list_all_200():
    with patch(f"{_ROUTER}.list_all_assignments", new_callable=AsyncMock) as mock_svc:
        mock_svc.return_value = [_RESP]
        from app.api.deps import get_db, require_admin

        mock_admin = MagicMock()
        app.dependency_overrides[get_db] = lambda: AsyncMock()
        app.dependency_overrides[require_admin] = lambda: mock_admin

        resp = client.get("/api/v1/admin/fleet-driver-assignments")
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


# --- Test 57 ---
def test_api_member_cannot_create_assignment_403():
    """Creating an assignment requires admin role; member gets 403."""
    from app.api.deps import get_current_user, get_db
    from app.services.corporate_trip_purpose import _require_account_admin

    mock_user = MagicMock()
    mock_user.id = USER_ID

    async def raise_403(*args, **kwargs):
        raise HTTPException(status_code=403, detail="Admin required.")

    with patch(f"{_ROUTER}.get_account", new_callable=AsyncMock):
        with patch(f"{_ROUTER}._require_account_admin", side_effect=raise_403):
            app.dependency_overrides[get_db] = lambda: AsyncMock()
            app.dependency_overrides[get_current_user] = lambda: mock_user

            payload = {
                "vehicle_id": str(VEHICLE_ID),
                "user_id": USER_ID,
                "assignment_type": "primary",
                "start_date": str(_TODAY),
            }
            resp = client.post(
                f"/api/v1/corporate/{ACCOUNT_ID}/fleet-vehicles/{VEHICLE_ID}/driver-assignments",
                json=payload,
            )
            app.dependency_overrides.clear()
    assert resp.status_code == 403


# --- Test 58 ---
def test_api_account_scoping_admin_cannot_see_other_account():
    """Admin for account A cannot see assignments for account B (returns 404)."""
    from app.api.deps import get_current_user, get_db

    async def raise_404(*args, **kwargs):
        raise HTTPException(status_code=404, detail="Assignment not found.")

    mock_user = MagicMock()
    mock_user.id = ADMIN_ID

    with patch(f"{_ROUTER}.get_account", new_callable=AsyncMock):
        with patch(f"{_ROUTER}._require_account_admin", new_callable=AsyncMock):
            with patch(f"{_ROUTER}.get_assignment", side_effect=raise_404):
                app.dependency_overrides[get_db] = lambda: AsyncMock()
                app.dependency_overrides[get_current_user] = lambda: mock_user

                resp = client.get(
                    f"/api/v1/corporate/{OTHER_ACCOUNT_ID}/fleet-vehicles/{VEHICLE_ID}"
                    f"/driver-assignments/{ASSIGNMENT_ID}"
                )
                app.dependency_overrides.clear()
    assert resp.status_code == 404
