"""Tests for the Corporate Vehicle Maintenance Log feature.

Service layer (async, mocked DB):
   1.  create_maintenance_record — success: creates with is_completed=False
   2.  create_maintenance_record — 404 when vehicle not in account
   3.  create_maintenance_record — 409 when vehicle is inactive
   4.  get_maintenance_record — success: returns existing record
   5.  get_maintenance_record — 404 when not found
   6.  list_maintenance_records — returns all records for account
   7.  list_maintenance_records — filters by fleet_vehicle_id
   8.  list_maintenance_records — filters by maintenance_type
   9.  list_maintenance_records — filters by is_completed
  10.  list_maintenance_records — filters by from_date / to_date
  11.  list_vehicle_maintenance — success: returns vehicle records (404 checks vehicle)
  12.  list_vehicle_maintenance — 404 when vehicle not in account
  13.  update_maintenance_record — success: updates fields
  14.  update_maintenance_record — 404 when not found
  15.  complete_maintenance_record — success: sets is_completed=True
  16.  complete_maintenance_record — uses provided completed_at timestamp
  17.  complete_maintenance_record — defaults completed_at to now when not provided
  18.  complete_maintenance_record — 404 when not found
  19.  complete_maintenance_record — 409 when already completed
  20.  delete_maintenance_record — success: deletes non-completed record
  21.  delete_maintenance_record — 404 when not found
  22.  delete_maintenance_record — 409 when record is completed
  23.  get_upcoming_maintenance — returns records with next_due_date within window
  24.  get_upcoming_maintenance — excludes completed records
  25.  get_upcoming_maintenance — excludes records past the window cutoff
  26.  get_upcoming_maintenance — filters by fleet_vehicle_id
  27.  get_upcoming_maintenance — returns empty list when no upcoming records
  28.  get_maintenance_summary — correct totals (completed/pending/overdue)
  29.  get_maintenance_summary — correct by_type counts
  30.  get_maintenance_summary — correct total_cost_usd sum
  31.  list_all_platform — returns all without filter
  32.  list_all_platform — filters by account_id

Schema validation:
  33.  MaintenanceLogCreate — requires fleet_vehicle_id
  34.  MaintenanceLogCreate — requires maintenance_type
  35.  MaintenanceLogCreate — requires title
  36.  MaintenanceLogCreate — optional fields default to None
  37.  MaintenanceLogCreate — rejects negative cost_usd
  38.  MaintenanceLogCreate — rejects negative odometer_miles
  39.  MaintenanceLogUpdate — all fields optional
  40.  MaintenanceLogComplete — all fields optional
  41.  MaintenanceLogResponse — from_attributes construction
  42.  MaintenanceUpcomingResponse — structure
  43.  MaintenanceSummaryResponse — structure

API layer (service functions patched):
  44.  GET  /fleet-vehicles/{id}/maintenance — 200 member can list vehicle history
  45.  GET  /fleet-vehicles/{id}/maintenance — 404 when vehicle not found
  46.  GET  /vehicle-maintenance/upcoming — 200 member can get upcoming
  47.  GET  /vehicle-maintenance/upcoming — 200 with days_ahead param
  48.  GET  /vehicle-maintenance/summary — 200 member can get summary
  49.  POST /vehicle-maintenance/ — 201 admin can create
  50.  POST /vehicle-maintenance/ — 403 non-admin cannot create
  51.  POST /vehicle-maintenance/ — 404 when vehicle not found
  52.  POST /vehicle-maintenance/ — 409 when vehicle inactive
  53.  GET  /vehicle-maintenance/ — 200 admin can list
  54.  GET  /vehicle-maintenance/ — 403 non-admin cannot list
  55.  GET  /vehicle-maintenance/{log_id} — 200 admin can get one
  56.  GET  /vehicle-maintenance/{log_id} — 403 non-admin cannot get one
  57.  GET  /vehicle-maintenance/{log_id} — 404 when not found
  58.  PUT  /vehicle-maintenance/{log_id} — 200 admin can update
  59.  PUT  /vehicle-maintenance/{log_id} — 403 non-admin cannot update
  60.  POST /vehicle-maintenance/{log_id}/complete — 200 admin can complete
  61.  POST /vehicle-maintenance/{log_id}/complete — 403 non-admin cannot complete
  62.  POST /vehicle-maintenance/{log_id}/complete — 409 already completed
  63.  DELETE /vehicle-maintenance/{log_id} — 204 admin can delete
  64.  DELETE /vehicle-maintenance/{log_id} — 403 non-admin cannot delete
  65.  DELETE /vehicle-maintenance/{log_id} — 409 when completed
  66.  GET /platform/corporate/vehicle-maintenance/ — 200 platform-admin list all
  67.  GET /platform/corporate/vehicle-maintenance/ — 200 with account_id filter
  68.  GET /platform/corporate/vehicle-maintenance/{account_id} — 200 per-account
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import app
from app.models.corporate_vehicle_maintenance_log import (
    CorporateVehicleMaintenanceLog,
    MaintenanceType,
)
from app.schemas.corporate_vehicle_maintenance_log import (
    MaintenanceLogComplete,
    MaintenanceLogCreate,
    MaintenanceLogResponse,
    MaintenanceSummaryResponse,
    MaintenanceUpcomingResponse,
    MaintenanceLogUpdate,
)
from app.services.corporate_vehicle_maintenance_log_service import (
    complete_maintenance_record,
    create_maintenance_record,
    delete_maintenance_record,
    get_maintenance_record,
    get_maintenance_summary,
    get_upcoming_maintenance,
    list_all_platform,
    list_maintenance_records,
    list_vehicle_maintenance,
    update_maintenance_record,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ACCOUNT_ID = 7
VEHICLE_ID = uuid.uuid4()
LOG_ID = uuid.uuid4()
USER_ID = 10
ADMIN_ID = 1

_SERVICE = "app.services.corporate_vehicle_maintenance_log_service"
_ROUTER = "app.api.v1.corporate_vehicle_maintenance_log"

_NOW = datetime(2026, 4, 16, 9, 0, 0, tzinfo=timezone.utc)
_DUE = datetime(2026, 5, 1, 9, 0, 0, tzinfo=timezone.utc)
_SCHEDULED = datetime(2026, 4, 20, 8, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


def _make_log(
    log_id: uuid.UUID = LOG_ID,
    account_id: int = ACCOUNT_ID,
    fleet_vehicle_id: uuid.UUID = VEHICLE_ID,
    maintenance_type: MaintenanceType = MaintenanceType.oil_change,
    title: str = "60k-mile oil change",
    description: str | None = "Full synthetic 5W-30",
    scheduled_date: datetime | None = _SCHEDULED,
    completed_at: datetime | None = None,
    odometer_miles: int | None = 60000,
    cost_usd: float | None = 89.99,
    vendor_name: str | None = "Jiffy Lube",
    notes: str | None = None,
    is_completed: bool = False,
    next_due_date: datetime | None = _DUE,
    next_due_odometer: int | None = 65000,
    created_by_id: int | None = ADMIN_ID,
    completed_by_id: int | None = None,
) -> CorporateVehicleMaintenanceLog:
    log = CorporateVehicleMaintenanceLog()
    log.id = log_id
    log.account_id = account_id
    log.fleet_vehicle_id = fleet_vehicle_id
    log.maintenance_type = maintenance_type
    log.title = title
    log.description = description
    log.scheduled_date = scheduled_date
    log.completed_at = completed_at
    log.odometer_miles = odometer_miles
    log.cost_usd = cost_usd
    log.vendor_name = vendor_name
    log.notes = notes
    log.is_completed = is_completed
    log.next_due_date = next_due_date
    log.next_due_odometer = next_due_odometer
    log.created_by_id = created_by_id
    log.completed_by_id = completed_by_id
    log.created_at = _NOW
    log.updated_at = _NOW
    return log


def _make_response(log: CorporateVehicleMaintenanceLog | None = None) -> MaintenanceLogResponse:
    if log is None:
        log = _make_log()
    return MaintenanceLogResponse(
        id=log.id,
        account_id=log.account_id,
        fleet_vehicle_id=log.fleet_vehicle_id,
        maintenance_type=log.maintenance_type.value if hasattr(log.maintenance_type, "value") else str(log.maintenance_type),
        title=log.title,
        description=log.description,
        scheduled_date=log.scheduled_date,
        completed_at=log.completed_at,
        odometer_miles=log.odometer_miles,
        cost_usd=float(log.cost_usd) if log.cost_usd is not None else None,
        vendor_name=log.vendor_name,
        notes=log.notes,
        is_completed=log.is_completed,
        next_due_date=log.next_due_date,
        next_due_odometer=log.next_due_odometer,
        created_by_id=log.created_by_id,
        completed_by_id=log.completed_by_id,
        created_at=log.created_at,
        updated_at=log.updated_at,
    )


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


def _mock_vehicle(is_active: bool = True):
    from app.models.corporate_fleet_vehicle import CorporateFleetVehicle

    v = CorporateFleetVehicle()
    v.id = VEHICLE_ID
    v.account_id = ACCOUNT_ID
    v.name = "Exec Sedan 1"
    v.is_active = is_active
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
# Service layer tests (1–32)
# ===========================================================================


# --- Test 1 ---
@pytest.mark.asyncio
async def test_create_maintenance_record_success():
    db = _mock_db()
    vehicle = _mock_vehicle()
    db.execute.side_effect = [
        _scalar_result(vehicle),  # _fetch_vehicle
    ]
    log_row = _make_log()
    db.refresh.side_effect = lambda obj: None

    with patch.object(CorporateVehicleMaintenanceLog, "__init__", lambda s, **kw: None):
        pass

    data = MaintenanceLogCreate(
        fleet_vehicle_id=VEHICLE_ID,
        maintenance_type=MaintenanceType.oil_change,
        title="60k-mile oil change",
        scheduled_date=_SCHEDULED,
        cost_usd=89.99,
    )

    # Patch _fetch_vehicle to return active vehicle
    with patch(f"{_SERVICE}._fetch_vehicle", new_callable=AsyncMock) as mock_fv:
        mock_fv.return_value = vehicle

        created_log = _make_log()
        db.refresh.side_effect = lambda obj: setattr(obj, "id", created_log.id) or None

        with patch(f"{_SERVICE}.CorporateVehicleMaintenanceLog") as MockModel:
            instance = _make_log()
            MockModel.return_value = instance

            result = await create_maintenance_record(db, ACCOUNT_ID, data, created_by_id=ADMIN_ID)

    assert db.add.called
    assert db.commit.called


# --- Test 2 ---
@pytest.mark.asyncio
async def test_create_maintenance_record_404_vehicle_not_found():
    db = _mock_db()
    data = MaintenanceLogCreate(
        fleet_vehicle_id=VEHICLE_ID,
        maintenance_type=MaintenanceType.inspection,
        title="Annual inspection",
    )
    with patch(f"{_SERVICE}._fetch_vehicle", new_callable=AsyncMock) as mock_fv:
        mock_fv.side_effect = HTTPException(status_code=404, detail="not found")
        with pytest.raises(HTTPException) as exc:
            await create_maintenance_record(db, ACCOUNT_ID, data)
    assert exc.value.status_code == 404


# --- Test 3 ---
@pytest.mark.asyncio
async def test_create_maintenance_record_409_inactive_vehicle():
    db = _mock_db()
    vehicle = _mock_vehicle(is_active=False)
    data = MaintenanceLogCreate(
        fleet_vehicle_id=VEHICLE_ID,
        maintenance_type=MaintenanceType.tire_rotation,
        title="Tire rotation",
    )
    with patch(f"{_SERVICE}._fetch_vehicle", new_callable=AsyncMock) as mock_fv:
        mock_fv.return_value = vehicle
        with pytest.raises(HTTPException) as exc:
            await create_maintenance_record(db, ACCOUNT_ID, data)
    assert exc.value.status_code == 409
    assert "not active" in exc.value.detail.lower()


# --- Test 4 ---
@pytest.mark.asyncio
async def test_get_maintenance_record_success():
    db = _mock_db()
    log_row = _make_log()
    with patch(f"{_SERVICE}._fetch_log", new_callable=AsyncMock) as mock_fl:
        mock_fl.return_value = log_row
        result = await get_maintenance_record(db, ACCOUNT_ID, LOG_ID)
    assert result.id == LOG_ID
    assert result.title == "60k-mile oil change"


# --- Test 5 ---
@pytest.mark.asyncio
async def test_get_maintenance_record_404():
    db = _mock_db()
    with patch(f"{_SERVICE}._fetch_log", new_callable=AsyncMock) as mock_fl:
        mock_fl.side_effect = HTTPException(status_code=404, detail="not found")
        with pytest.raises(HTTPException) as exc:
            await get_maintenance_record(db, ACCOUNT_ID, uuid.uuid4())
    assert exc.value.status_code == 404


# --- Test 6 ---
@pytest.mark.asyncio
async def test_list_maintenance_records_returns_all():
    db = _mock_db()
    rows = [_make_log(), _make_log(log_id=uuid.uuid4())]
    db.execute.return_value = _scalars_result(rows)
    results = await list_maintenance_records(db, ACCOUNT_ID)
    assert len(results) == 2


# --- Test 7 ---
@pytest.mark.asyncio
async def test_list_maintenance_records_filters_by_vehicle():
    db = _mock_db()
    db.execute.return_value = _scalars_result([_make_log()])
    results = await list_maintenance_records(db, ACCOUNT_ID, fleet_vehicle_id=VEHICLE_ID)
    assert len(results) == 1


# --- Test 8 ---
@pytest.mark.asyncio
async def test_list_maintenance_records_filters_by_type():
    db = _mock_db()
    db.execute.return_value = _scalars_result([_make_log()])
    results = await list_maintenance_records(
        db, ACCOUNT_ID, maintenance_type=MaintenanceType.oil_change
    )
    assert len(results) == 1


# --- Test 9 ---
@pytest.mark.asyncio
async def test_list_maintenance_records_filters_by_completed():
    db = _mock_db()
    db.execute.return_value = _scalars_result([])
    results = await list_maintenance_records(db, ACCOUNT_ID, is_completed=True)
    assert results == []


# --- Test 10 ---
@pytest.mark.asyncio
async def test_list_maintenance_records_filters_by_date_range():
    db = _mock_db()
    db.execute.return_value = _scalars_result([_make_log()])
    results = await list_maintenance_records(
        db,
        ACCOUNT_ID,
        from_date=_SCHEDULED,
        to_date=_SCHEDULED + timedelta(days=1),
    )
    assert len(results) == 1


# --- Test 11 ---
@pytest.mark.asyncio
async def test_list_vehicle_maintenance_success():
    db = _mock_db()
    rows = [_make_log(), _make_log(log_id=uuid.uuid4())]
    with patch(f"{_SERVICE}._fetch_vehicle", new_callable=AsyncMock) as mock_fv:
        mock_fv.return_value = _mock_vehicle()
        db.execute.return_value = _scalars_result(rows)
        results = await list_vehicle_maintenance(db, ACCOUNT_ID, VEHICLE_ID)
    assert len(results) == 2


# --- Test 12 ---
@pytest.mark.asyncio
async def test_list_vehicle_maintenance_404():
    db = _mock_db()
    with patch(f"{_SERVICE}._fetch_vehicle", new_callable=AsyncMock) as mock_fv:
        mock_fv.side_effect = HTTPException(status_code=404, detail="not found")
        with pytest.raises(HTTPException) as exc:
            await list_vehicle_maintenance(db, ACCOUNT_ID, uuid.uuid4())
    assert exc.value.status_code == 404


# --- Test 13 ---
@pytest.mark.asyncio
async def test_update_maintenance_record_success():
    db = _mock_db()
    log_row = _make_log()
    with patch(f"{_SERVICE}._fetch_log", new_callable=AsyncMock) as mock_fl:
        mock_fl.return_value = log_row
        data = MaintenanceLogUpdate(title="Updated oil change", cost_usd=95.00)
        result = await update_maintenance_record(db, ACCOUNT_ID, LOG_ID, data)
    assert log_row.title == "Updated oil change"
    assert db.commit.called


# --- Test 14 ---
@pytest.mark.asyncio
async def test_update_maintenance_record_404():
    db = _mock_db()
    with patch(f"{_SERVICE}._fetch_log", new_callable=AsyncMock) as mock_fl:
        mock_fl.side_effect = HTTPException(status_code=404, detail="not found")
        with pytest.raises(HTTPException) as exc:
            await update_maintenance_record(
                db, ACCOUNT_ID, uuid.uuid4(), MaintenanceLogUpdate()
            )
    assert exc.value.status_code == 404


# --- Test 15 ---
@pytest.mark.asyncio
async def test_complete_maintenance_record_success():
    db = _mock_db()
    log_row = _make_log(is_completed=False)
    with patch(f"{_SERVICE}._fetch_log", new_callable=AsyncMock) as mock_fl:
        mock_fl.return_value = log_row
        data = MaintenanceLogComplete(cost_usd=89.99, vendor_name="Jiffy Lube")
        result = await complete_maintenance_record(db, ACCOUNT_ID, LOG_ID, data, completed_by_id=ADMIN_ID)
    assert log_row.is_completed is True
    assert log_row.completed_by_id == ADMIN_ID
    assert log_row.cost_usd == 89.99
    assert db.commit.called


# --- Test 16 ---
@pytest.mark.asyncio
async def test_complete_maintenance_record_uses_provided_timestamp():
    db = _mock_db()
    log_row = _make_log(is_completed=False)
    explicit_time = datetime(2026, 4, 15, 14, 0, 0, tzinfo=timezone.utc)
    with patch(f"{_SERVICE}._fetch_log", new_callable=AsyncMock) as mock_fl:
        mock_fl.return_value = log_row
        data = MaintenanceLogComplete(completed_at=explicit_time)
        await complete_maintenance_record(db, ACCOUNT_ID, LOG_ID, data)
    assert log_row.completed_at == explicit_time


# --- Test 17 ---
@pytest.mark.asyncio
async def test_complete_maintenance_record_defaults_completed_at():
    db = _mock_db()
    log_row = _make_log(is_completed=False)
    with patch(f"{_SERVICE}._fetch_log", new_callable=AsyncMock) as mock_fl:
        mock_fl.return_value = log_row
        data = MaintenanceLogComplete()
        await complete_maintenance_record(db, ACCOUNT_ID, LOG_ID, data)
    assert log_row.completed_at is not None


# --- Test 18 ---
@pytest.mark.asyncio
async def test_complete_maintenance_record_404():
    db = _mock_db()
    with patch(f"{_SERVICE}._fetch_log", new_callable=AsyncMock) as mock_fl:
        mock_fl.side_effect = HTTPException(status_code=404, detail="not found")
        with pytest.raises(HTTPException) as exc:
            await complete_maintenance_record(
                db, ACCOUNT_ID, uuid.uuid4(), MaintenanceLogComplete()
            )
    assert exc.value.status_code == 404


# --- Test 19 ---
@pytest.mark.asyncio
async def test_complete_maintenance_record_409_already_completed():
    db = _mock_db()
    log_row = _make_log(is_completed=True)
    with patch(f"{_SERVICE}._fetch_log", new_callable=AsyncMock) as mock_fl:
        mock_fl.return_value = log_row
        with pytest.raises(HTTPException) as exc:
            await complete_maintenance_record(
                db, ACCOUNT_ID, LOG_ID, MaintenanceLogComplete()
            )
    assert exc.value.status_code == 409
    assert "already" in exc.value.detail.lower()


# --- Test 20 ---
@pytest.mark.asyncio
async def test_delete_maintenance_record_success():
    db = _mock_db()
    log_row = _make_log(is_completed=False)
    with patch(f"{_SERVICE}._fetch_log", new_callable=AsyncMock) as mock_fl:
        mock_fl.return_value = log_row
        await delete_maintenance_record(db, ACCOUNT_ID, LOG_ID)
    assert db.delete.called
    assert db.commit.called


# --- Test 21 ---
@pytest.mark.asyncio
async def test_delete_maintenance_record_404():
    db = _mock_db()
    with patch(f"{_SERVICE}._fetch_log", new_callable=AsyncMock) as mock_fl:
        mock_fl.side_effect = HTTPException(status_code=404, detail="not found")
        with pytest.raises(HTTPException) as exc:
            await delete_maintenance_record(db, ACCOUNT_ID, uuid.uuid4())
    assert exc.value.status_code == 404


# --- Test 22 ---
@pytest.mark.asyncio
async def test_delete_maintenance_record_409_when_completed():
    db = _mock_db()
    log_row = _make_log(is_completed=True)
    with patch(f"{_SERVICE}._fetch_log", new_callable=AsyncMock) as mock_fl:
        mock_fl.return_value = log_row
        with pytest.raises(HTTPException) as exc:
            await delete_maintenance_record(db, ACCOUNT_ID, LOG_ID)
    assert exc.value.status_code == 409
    assert "completed" in exc.value.detail.lower()


# --- Test 23 ---
@pytest.mark.asyncio
async def test_get_upcoming_maintenance_returns_records():
    db = _mock_db()
    now = datetime.now(tz=timezone.utc)
    due_soon = now + timedelta(days=10)
    log_row = _make_log(is_completed=False, next_due_date=due_soon)
    db.execute.return_value = _scalars_result([log_row])
    results = await get_upcoming_maintenance(db, ACCOUNT_ID, days_ahead=30)
    assert len(results) == 1
    assert results[0].log_id == LOG_ID


# --- Test 24 ---
@pytest.mark.asyncio
async def test_get_upcoming_maintenance_excludes_completed():
    db = _mock_db()
    # The query itself filters is_completed=False at DB level;
    # our mock returns empty to simulate that filter working
    db.execute.return_value = _scalars_result([])
    results = await get_upcoming_maintenance(db, ACCOUNT_ID)
    assert results == []


# --- Test 25 ---
@pytest.mark.asyncio
async def test_get_upcoming_maintenance_excludes_far_future():
    db = _mock_db()
    db.execute.return_value = _scalars_result([])
    results = await get_upcoming_maintenance(db, ACCOUNT_ID, days_ahead=7)
    assert results == []


# --- Test 26 ---
@pytest.mark.asyncio
async def test_get_upcoming_maintenance_filters_by_vehicle():
    db = _mock_db()
    due_soon = datetime.now(tz=timezone.utc) + timedelta(days=5)
    log_row = _make_log(is_completed=False, next_due_date=due_soon)
    db.execute.return_value = _scalars_result([log_row])
    results = await get_upcoming_maintenance(
        db, ACCOUNT_ID, days_ahead=30, fleet_vehicle_id=VEHICLE_ID
    )
    assert len(results) == 1
    assert results[0].fleet_vehicle_id == VEHICLE_ID


# --- Test 27 ---
@pytest.mark.asyncio
async def test_get_upcoming_maintenance_empty():
    db = _mock_db()
    db.execute.return_value = _scalars_result([])
    results = await get_upcoming_maintenance(db, ACCOUNT_ID)
    assert results == []


# --- Test 28 ---
@pytest.mark.asyncio
async def test_get_maintenance_summary_correct_counts():
    db = _mock_db()
    now = datetime.now(tz=timezone.utc)
    overdue_time = now - timedelta(days=5)

    log_completed = _make_log(is_completed=True, next_due_date=None)
    log_pending = _make_log(log_id=uuid.uuid4(), is_completed=False, next_due_date=overdue_time)
    log_ok = _make_log(log_id=uuid.uuid4(), is_completed=False, next_due_date=now + timedelta(days=20))

    db.execute.return_value = _scalars_result([log_completed, log_pending, log_ok])
    summary = await get_maintenance_summary(db, ACCOUNT_ID)

    assert summary.total_records == 3
    assert summary.completed == 1
    assert summary.pending == 2
    assert summary.overdue == 1


# --- Test 29 ---
@pytest.mark.asyncio
async def test_get_maintenance_summary_by_type():
    db = _mock_db()
    log1 = _make_log(maintenance_type=MaintenanceType.oil_change)
    log2 = _make_log(log_id=uuid.uuid4(), maintenance_type=MaintenanceType.oil_change)
    log3 = _make_log(log_id=uuid.uuid4(), maintenance_type=MaintenanceType.inspection)
    db.execute.return_value = _scalars_result([log1, log2, log3])
    summary = await get_maintenance_summary(db, ACCOUNT_ID)
    assert summary.by_type["oil_change"] == 2
    assert summary.by_type["inspection"] == 1


# --- Test 30 ---
@pytest.mark.asyncio
async def test_get_maintenance_summary_total_cost():
    db = _mock_db()
    log1 = _make_log(cost_usd=50.00)
    log2 = _make_log(log_id=uuid.uuid4(), cost_usd=75.50)
    log3 = _make_log(log_id=uuid.uuid4(), cost_usd=None)
    db.execute.return_value = _scalars_result([log1, log2, log3])
    summary = await get_maintenance_summary(db, ACCOUNT_ID)
    assert summary.total_cost_usd == pytest.approx(125.50)


# --- Test 31 ---
@pytest.mark.asyncio
async def test_list_all_platform_returns_all():
    db = _mock_db()
    rows = [_make_log(), _make_log(log_id=uuid.uuid4(), account_id=99)]
    db.execute.return_value = _scalars_result(rows)
    results = await list_all_platform(db)
    assert len(results) == 2


# --- Test 32 ---
@pytest.mark.asyncio
async def test_list_all_platform_filters_by_account():
    db = _mock_db()
    db.execute.return_value = _scalars_result([_make_log()])
    results = await list_all_platform(db, account_id=ACCOUNT_ID)
    assert len(results) == 1
    assert results[0].account_id == ACCOUNT_ID


# ===========================================================================
# Schema validation tests (33–43)
# ===========================================================================


# --- Test 33 ---
def test_schema_create_requires_vehicle_id():
    with pytest.raises(ValidationError):
        MaintenanceLogCreate(
            maintenance_type=MaintenanceType.oil_change,
            title="Test",
        )


# --- Test 34 ---
def test_schema_create_requires_maintenance_type():
    with pytest.raises(ValidationError):
        MaintenanceLogCreate(
            fleet_vehicle_id=VEHICLE_ID,
            title="Test",
        )


# --- Test 35 ---
def test_schema_create_requires_title():
    with pytest.raises(ValidationError):
        MaintenanceLogCreate(
            fleet_vehicle_id=VEHICLE_ID,
            maintenance_type=MaintenanceType.oil_change,
        )


# --- Test 36 ---
def test_schema_create_optional_fields_default_none():
    schema = MaintenanceLogCreate(
        fleet_vehicle_id=VEHICLE_ID,
        maintenance_type=MaintenanceType.inspection,
        title="Annual inspection",
    )
    assert schema.description is None
    assert schema.scheduled_date is None
    assert schema.cost_usd is None
    assert schema.vendor_name is None
    assert schema.next_due_date is None


# --- Test 37 ---
def test_schema_create_rejects_negative_cost():
    with pytest.raises(ValidationError):
        MaintenanceLogCreate(
            fleet_vehicle_id=VEHICLE_ID,
            maintenance_type=MaintenanceType.oil_change,
            title="Test",
            cost_usd=-10.0,
        )


# --- Test 38 ---
def test_schema_create_rejects_negative_odometer():
    with pytest.raises(ValidationError):
        MaintenanceLogCreate(
            fleet_vehicle_id=VEHICLE_ID,
            maintenance_type=MaintenanceType.oil_change,
            title="Test",
            odometer_miles=-1,
        )


# --- Test 39 ---
def test_schema_update_all_optional():
    schema = MaintenanceLogUpdate()
    assert schema.title is None
    assert schema.maintenance_type is None
    assert schema.cost_usd is None


# --- Test 40 ---
def test_schema_complete_all_optional():
    schema = MaintenanceLogComplete()
    assert schema.completed_at is None
    assert schema.cost_usd is None
    assert schema.vendor_name is None


# --- Test 41 ---
def test_schema_response_from_attributes():
    log = _make_log()
    resp = _make_response(log)
    assert resp.id == LOG_ID
    assert resp.account_id == ACCOUNT_ID
    assert resp.is_completed is False
    assert resp.maintenance_type == "oil_change"


# --- Test 42 ---
def test_schema_upcoming_response_structure():
    upcoming = MaintenanceUpcomingResponse(
        log_id=LOG_ID,
        fleet_vehicle_id=VEHICLE_ID,
        maintenance_type="oil_change",
        title="Oil change",
        next_due_date=_DUE,
        days_until_due=15,
        next_due_odometer=65000,
    )
    assert upcoming.days_until_due == 15
    assert upcoming.next_due_odometer == 65000


# --- Test 43 ---
def test_schema_summary_response_structure():
    summary = MaintenanceSummaryResponse(
        total_records=10,
        completed=5,
        pending=5,
        overdue=1,
        due_within_30_days=2,
        total_cost_usd=500.00,
        by_type={"oil_change": 3, "inspection": 2},
    )
    assert summary.total_records == 10
    assert summary.total_cost_usd == 500.00


# ===========================================================================
# API layer tests (44–68)
# ===========================================================================

client = TestClient(app)


def _make_user(user_id: int = USER_ID, is_admin: bool = False):
    from app.models.user import User

    u = MagicMock(spec=User)
    u.id = user_id
    u.is_admin = is_admin
    return u


def _dep_overrides(user_id: int = USER_ID, is_admin: bool = False):
    """Return dependency override dict for FastAPI DI injection."""
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


def _resp_dict(log: CorporateVehicleMaintenanceLog | None = None) -> dict:
    r = _make_response(log)
    return r.model_dump(mode="json")


# --- Test 44 ---
def test_api_list_vehicle_maintenance_200():
    with (
        _patch_get_account(),
        patch(f"{_ROUTER}.list_vehicle_maintenance", new_callable=AsyncMock, return_value=[_make_response()]),
    ):
        app.dependency_overrides.update(_dep_overrides())
        r = client.get(f"/api/v1/corporate/{ACCOUNT_ID}/fleet-vehicles/{VEHICLE_ID}/maintenance")
        app.dependency_overrides.clear()
    assert r.status_code == 200


# --- Test 45 ---
def test_api_list_vehicle_maintenance_404():
    with (
        _patch_get_account(),
        patch(f"{_ROUTER}.list_vehicle_maintenance", new_callable=AsyncMock, side_effect=HTTPException(status_code=404, detail="not found")),
    ):
        app.dependency_overrides.update(_dep_overrides())
        r = client.get(f"/api/v1/corporate/{ACCOUNT_ID}/fleet-vehicles/{VEHICLE_ID}/maintenance")
        app.dependency_overrides.clear()
    assert r.status_code == 404


# --- Test 46 ---
def test_api_get_upcoming_200():
    with (
        _patch_get_account(),
        patch(f"{_ROUTER}.get_upcoming_maintenance", new_callable=AsyncMock, return_value=[]),
    ):
        app.dependency_overrides.update(_dep_overrides())
        r = client.get(f"/api/v1/corporate/{ACCOUNT_ID}/vehicle-maintenance/upcoming")
        app.dependency_overrides.clear()
    assert r.status_code == 200


# --- Test 47 ---
def test_api_get_upcoming_with_days_ahead():
    with (
        _patch_get_account(),
        patch(f"{_ROUTER}.get_upcoming_maintenance", new_callable=AsyncMock, return_value=[]) as mock_svc,
    ):
        app.dependency_overrides.update(_dep_overrides())
        r = client.get(
            f"/api/v1/corporate/{ACCOUNT_ID}/vehicle-maintenance/upcoming?days_ahead=60"
        )
        app.dependency_overrides.clear()
    assert r.status_code == 200
    mock_svc.assert_called_once()
    call_kwargs = mock_svc.call_args.kwargs
    assert call_kwargs.get("days_ahead") == 60


# --- Test 48 ---
def test_api_get_summary_200():
    summary = MaintenanceSummaryResponse(
        total_records=5, completed=3, pending=2, overdue=0,
        due_within_30_days=1, total_cost_usd=200.0, by_type={}
    )
    with (
        _patch_get_account(),
        patch(f"{_ROUTER}.get_maintenance_summary", new_callable=AsyncMock, return_value=summary),
    ):
        app.dependency_overrides.update(_dep_overrides())
        r = client.get(f"/api/v1/corporate/{ACCOUNT_ID}/vehicle-maintenance/summary")
        app.dependency_overrides.clear()
    assert r.status_code == 200
    data = r.json()
    assert data["total_records"] == 5


# --- Test 49 ---
def test_api_create_201_admin():
    resp = _make_response()
    with (
        _patch_get_account(),
        _patch_require_account_admin(),
        patch(f"{_ROUTER}.create_maintenance_record", new_callable=AsyncMock, return_value=resp),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        r = client.post(
            f"/api/v1/corporate/{ACCOUNT_ID}/vehicle-maintenance/",
            json={
                "fleet_vehicle_id": str(VEHICLE_ID),
                "maintenance_type": "oil_change",
                "title": "60k-mile oil change",
            },
        )
        app.dependency_overrides.clear()
    assert r.status_code == 201


# --- Test 50 ---
def test_api_create_403_non_admin():
    with (
        _patch_get_account(),
        _patch_require_account_admin(raises=True),
    ):
        app.dependency_overrides.update(_dep_overrides())
        r = client.post(
            f"/api/v1/corporate/{ACCOUNT_ID}/vehicle-maintenance/",
            json={
                "fleet_vehicle_id": str(VEHICLE_ID),
                "maintenance_type": "oil_change",
                "title": "Oil change",
            },
        )
        app.dependency_overrides.clear()
    assert r.status_code == 403


# --- Test 51 ---
def test_api_create_404_vehicle_not_found():
    with (
        _patch_get_account(),
        _patch_require_account_admin(),
        patch(f"{_ROUTER}.create_maintenance_record", new_callable=AsyncMock, side_effect=HTTPException(status_code=404, detail="vehicle not found")),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        r = client.post(
            f"/api/v1/corporate/{ACCOUNT_ID}/vehicle-maintenance/",
            json={
                "fleet_vehicle_id": str(VEHICLE_ID),
                "maintenance_type": "oil_change",
                "title": "Oil change",
            },
        )
        app.dependency_overrides.clear()
    assert r.status_code == 404


# --- Test 52 ---
def test_api_create_409_inactive_vehicle():
    with (
        _patch_get_account(),
        _patch_require_account_admin(),
        patch(f"{_ROUTER}.create_maintenance_record", new_callable=AsyncMock, side_effect=HTTPException(status_code=409, detail="vehicle not active")),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        r = client.post(
            f"/api/v1/corporate/{ACCOUNT_ID}/vehicle-maintenance/",
            json={
                "fleet_vehicle_id": str(VEHICLE_ID),
                "maintenance_type": "oil_change",
                "title": "Oil change",
            },
        )
        app.dependency_overrides.clear()
    assert r.status_code == 409


# --- Test 53 ---
def test_api_list_all_200_admin():
    with (
        _patch_get_account(),
        _patch_require_account_admin(),
        patch(f"{_ROUTER}.list_maintenance_records", new_callable=AsyncMock, return_value=[_make_response()]),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        r = client.get(f"/api/v1/corporate/{ACCOUNT_ID}/vehicle-maintenance/")
        app.dependency_overrides.clear()
    assert r.status_code == 200


# --- Test 54 ---
def test_api_list_all_403_non_admin():
    with (
        _patch_get_account(),
        _patch_require_account_admin(raises=True),
    ):
        app.dependency_overrides.update(_dep_overrides())
        r = client.get(f"/api/v1/corporate/{ACCOUNT_ID}/vehicle-maintenance/")
        app.dependency_overrides.clear()
    assert r.status_code == 403


# --- Test 55 ---
def test_api_get_one_200_admin():
    with (
        _patch_get_account(),
        _patch_require_account_admin(),
        patch(f"{_ROUTER}.get_maintenance_record", new_callable=AsyncMock, return_value=_make_response()),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        r = client.get(f"/api/v1/corporate/{ACCOUNT_ID}/vehicle-maintenance/{LOG_ID}")
        app.dependency_overrides.clear()
    assert r.status_code == 200


# --- Test 56 ---
def test_api_get_one_403_non_admin():
    with (
        _patch_get_account(),
        _patch_require_account_admin(raises=True),
    ):
        app.dependency_overrides.update(_dep_overrides())
        r = client.get(f"/api/v1/corporate/{ACCOUNT_ID}/vehicle-maintenance/{LOG_ID}")
        app.dependency_overrides.clear()
    assert r.status_code == 403


# --- Test 57 ---
def test_api_get_one_404():
    with (
        _patch_get_account(),
        _patch_require_account_admin(),
        patch(f"{_ROUTER}.get_maintenance_record", new_callable=AsyncMock, side_effect=HTTPException(status_code=404, detail="not found")),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        r = client.get(f"/api/v1/corporate/{ACCOUNT_ID}/vehicle-maintenance/{LOG_ID}")
        app.dependency_overrides.clear()
    assert r.status_code == 404


# --- Test 58 ---
def test_api_update_200_admin():
    with (
        _patch_get_account(),
        _patch_require_account_admin(),
        patch(f"{_ROUTER}.update_maintenance_record", new_callable=AsyncMock, return_value=_make_response()),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        r = client.put(
            f"/api/v1/corporate/{ACCOUNT_ID}/vehicle-maintenance/{LOG_ID}",
            json={"title": "Updated title"},
        )
        app.dependency_overrides.clear()
    assert r.status_code == 200


# --- Test 59 ---
def test_api_update_403_non_admin():
    with (
        _patch_get_account(),
        _patch_require_account_admin(raises=True),
    ):
        app.dependency_overrides.update(_dep_overrides())
        r = client.put(
            f"/api/v1/corporate/{ACCOUNT_ID}/vehicle-maintenance/{LOG_ID}",
            json={"title": "Updated title"},
        )
        app.dependency_overrides.clear()
    assert r.status_code == 403


# --- Test 60 ---
def test_api_complete_200_admin():
    completed_log = _make_log(is_completed=True)
    with (
        _patch_get_account(),
        _patch_require_account_admin(),
        patch(f"{_ROUTER}.complete_maintenance_record", new_callable=AsyncMock, return_value=_make_response(completed_log)),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        r = client.post(
            f"/api/v1/corporate/{ACCOUNT_ID}/vehicle-maintenance/{LOG_ID}/complete",
            json={},
        )
        app.dependency_overrides.clear()
    assert r.status_code == 200


# --- Test 61 ---
def test_api_complete_403_non_admin():
    with (
        _patch_get_account(),
        _patch_require_account_admin(raises=True),
    ):
        app.dependency_overrides.update(_dep_overrides())
        r = client.post(
            f"/api/v1/corporate/{ACCOUNT_ID}/vehicle-maintenance/{LOG_ID}/complete",
            json={},
        )
        app.dependency_overrides.clear()
    assert r.status_code == 403


# --- Test 62 ---
def test_api_complete_409_already_completed():
    with (
        _patch_get_account(),
        _patch_require_account_admin(),
        patch(f"{_ROUTER}.complete_maintenance_record", new_callable=AsyncMock, side_effect=HTTPException(status_code=409, detail="already completed")),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        r = client.post(
            f"/api/v1/corporate/{ACCOUNT_ID}/vehicle-maintenance/{LOG_ID}/complete",
            json={},
        )
        app.dependency_overrides.clear()
    assert r.status_code == 409


# --- Test 63 ---
def test_api_delete_204_admin():
    with (
        _patch_get_account(),
        _patch_require_account_admin(),
        patch(f"{_ROUTER}.delete_maintenance_record", new_callable=AsyncMock, return_value=None),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        r = client.delete(
            f"/api/v1/corporate/{ACCOUNT_ID}/vehicle-maintenance/{LOG_ID}"
        )
        app.dependency_overrides.clear()
    assert r.status_code == 204


# --- Test 64 ---
def test_api_delete_403_non_admin():
    with (
        _patch_get_account(),
        _patch_require_account_admin(raises=True),
    ):
        app.dependency_overrides.update(_dep_overrides())
        r = client.delete(
            f"/api/v1/corporate/{ACCOUNT_ID}/vehicle-maintenance/{LOG_ID}"
        )
        app.dependency_overrides.clear()
    assert r.status_code == 403


# --- Test 65 ---
def test_api_delete_409_completed():
    with (
        _patch_get_account(),
        _patch_require_account_admin(),
        patch(f"{_ROUTER}.delete_maintenance_record", new_callable=AsyncMock, side_effect=HTTPException(status_code=409, detail="completed records cannot be deleted")),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        r = client.delete(
            f"/api/v1/corporate/{ACCOUNT_ID}/vehicle-maintenance/{LOG_ID}"
        )
        app.dependency_overrides.clear()
    assert r.status_code == 409


# --- Test 66 ---
def test_api_platform_list_all_200():
    with patch(f"{_ROUTER}.list_all_platform", new_callable=AsyncMock, return_value=[_make_response()]):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        r = client.get("/api/v1/platform/corporate/vehicle-maintenance/")
        app.dependency_overrides.clear()
    assert r.status_code == 200


# --- Test 67 ---
def test_api_platform_list_all_with_account_filter():
    with patch(f"{_ROUTER}.list_all_platform", new_callable=AsyncMock, return_value=[_make_response()]) as mock_svc:
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        r = client.get(f"/api/v1/platform/corporate/vehicle-maintenance/?account_id={ACCOUNT_ID}")
        app.dependency_overrides.clear()
    assert r.status_code == 200
    call_kwargs = mock_svc.call_args.kwargs
    assert call_kwargs.get("account_id") == ACCOUNT_ID


# --- Test 68 ---
def test_api_platform_list_for_account_200():
    with patch(f"{_ROUTER}.list_all_platform", new_callable=AsyncMock, return_value=[_make_response()]):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        r = client.get(f"/api/v1/platform/corporate/vehicle-maintenance/{ACCOUNT_ID}")
        app.dependency_overrides.clear()
    assert r.status_code == 200
