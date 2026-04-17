"""Tests for the Corporate Fleet Maintenance Scheduling feature.

Service layer (async, mocked DB):
   1.  schedule_maintenance — success: creates with status=scheduled
   2.  schedule_maintenance — 404 when vehicle not in account
   3.  get_maintenance_record — success: returns existing record
   4.  get_maintenance_record — 404 when not found
   5.  update_maintenance_record — success: updates fields
   6.  update_maintenance_record — ignores None fields
   7.  complete_maintenance — success: sets status=completed, completed_date, cost, odometer
   8.  complete_maintenance — 404 when record not found
   9.  cancel_maintenance — success: sets status=cancelled
  10.  cancel_maintenance — 409 if already completed
  11.  cancel_maintenance — 409 if already cancelled
  12.  delete_maintenance_record — success: deletes record
  13.  delete_maintenance_record — 404 when not found
  14.  list_vehicle_maintenance — returns all for vehicle
  15.  list_vehicle_maintenance — status filter works
  16.  list_vehicle_maintenance — maintenance_type filter works
  17.  list_vehicle_maintenance — 404 vehicle not found
  18.  list_account_maintenance — returns all for account
  19.  list_account_maintenance — vehicle_id filter works
  20.  list_account_maintenance — status filter works
  21.  list_account_maintenance — maintenance_type filter works
  22.  get_overdue_maintenance — returns overdue records and marks them overdue
  23.  get_overdue_maintenance — ignores completed records
  24.  get_overdue_maintenance — returns empty list when none overdue
  25.  get_vehicle_maintenance_summary — counts and cost correct
  26.  get_vehicle_maintenance_summary — last_service_date and next_scheduled_date correct
  27.  get_vehicle_maintenance_summary — per_type breakdown correct
  28.  get_account_maintenance_summary — counts and cost correct
  29.  get_account_maintenance_summary — vehicles_with_overdue correct
  30.  list_all_platform — returns all
  31.  list_all_platform — account_id filter works

Schema validation:
  32.  MaintenanceRecordCreate — valid construction
  33.  MaintenanceRecordCreate — missing required field raises ValidationError
  34.  MaintenanceRecordUpdate — all optional
  35.  MaintenanceRecordResponse — from_attributes works
  36.  VehicleMaintenanceSummaryResponse — valid structure
  37.  AccountMaintenanceSummaryResponse — valid structure

API layer (service functions patched):
  38.  GET list vehicle maintenance → 200
  39.  GET vehicle maintenance summary → 200
  40.  GET single record (via vehicle path) → 200
  41.  POST schedule maintenance → 201
  42.  GET list account maintenance → 200
  43.  GET overdue → 200
  44.  PUT update → 200
  45.  POST complete → 200
  46.  POST cancel → 200
  47.  DELETE delete → 204
  48.  GET account maintenance summary → 200
  49.  GET platform list all → 200
  50.  GET platform list by account → 200
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
from app.models.corporate_fleet_maintenance import (
    CorporateFleetMaintenanceRecord,
    FleetMaintenanceStatus,
    FleetMaintenanceType,
)
from app.schemas.corporate_fleet_maintenance import (
    AccountMaintenanceSummaryResponse,
    MaintenanceRecordCreate,
    MaintenanceRecordResponse,
    MaintenanceRecordUpdate,
    MaintenanceTypeBreakdown,
    VehicleMaintenanceSummaryResponse,
)
from app.services.corporate_fleet_maintenance_service import (
    cancel_maintenance,
    complete_maintenance,
    delete_maintenance_record,
    get_account_maintenance_summary,
    get_maintenance_record,
    get_overdue_maintenance,
    get_vehicle_maintenance_summary,
    list_account_maintenance,
    list_all_platform,
    list_vehicle_maintenance,
    schedule_maintenance,
    update_maintenance_record,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ACCOUNT_ID = 7
VEHICLE_ID = uuid.uuid4()
RECORD_ID = uuid.uuid4()
USER_ID = 10
ADMIN_ID = 1

_SERVICE = "app.services.corporate_fleet_maintenance_service"
_ROUTER = "app.api.v1.corporate_fleet_maintenance"

_NOW = datetime(2026, 4, 17, 9, 0, 0, tzinfo=timezone.utc)
_SCHED_DATE = date(2026, 5, 1)
_COMP_DATE = date(2026, 5, 2)


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


def _make_record(
    record_id: uuid.UUID = RECORD_ID,
    account_id: int = ACCOUNT_ID,
    fleet_vehicle_id: uuid.UUID = VEHICLE_ID,
    maintenance_type: FleetMaintenanceType = FleetMaintenanceType.oil_change,
    status: FleetMaintenanceStatus = FleetMaintenanceStatus.scheduled,
    scheduled_date: date | None = _SCHED_DATE,
    completed_date: date | None = None,
    odometer_at_service: int | None = None,
    next_service_odometer: int | None = None,
    next_service_date: date | None = None,
    cost_usd: float | None = None,
    vendor_name: str | None = None,
    technician_name: str | None = None,
    description: str | None = "Routine oil change",
    notes: str | None = None,
    created_by_id: int | None = ADMIN_ID,
) -> CorporateFleetMaintenanceRecord:
    rec = CorporateFleetMaintenanceRecord()
    rec.id = record_id
    rec.account_id = account_id
    rec.fleet_vehicle_id = fleet_vehicle_id
    rec.maintenance_type = maintenance_type
    rec.status = status
    rec.scheduled_date = scheduled_date
    rec.completed_date = completed_date
    rec.odometer_at_service = odometer_at_service
    rec.next_service_odometer = next_service_odometer
    rec.next_service_date = next_service_date
    rec.cost_usd = cost_usd
    rec.vendor_name = vendor_name
    rec.technician_name = technician_name
    rec.description = description
    rec.notes = notes
    rec.created_by_id = created_by_id
    rec.created_at = _NOW
    rec.updated_at = _NOW
    return rec


def _make_response(rec: CorporateFleetMaintenanceRecord | None = None) -> MaintenanceRecordResponse:
    if rec is None:
        rec = _make_record()
    return MaintenanceRecordResponse(
        id=rec.id,
        account_id=rec.account_id,
        fleet_vehicle_id=rec.fleet_vehicle_id,
        maintenance_type=rec.maintenance_type,
        status=rec.status,
        scheduled_date=rec.scheduled_date,
        completed_date=rec.completed_date,
        odometer_at_service=rec.odometer_at_service,
        next_service_odometer=rec.next_service_odometer,
        next_service_date=rec.next_service_date,
        cost_usd=float(rec.cost_usd) if rec.cost_usd is not None else None,
        vendor_name=rec.vendor_name,
        technician_name=rec.technician_name,
        description=rec.description,
        notes=rec.notes,
        created_by_id=rec.created_by_id,
        created_at=rec.created_at,
        updated_at=rec.updated_at,
    )


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


def _mock_vehicle(is_active: bool = True):
    from app.models.corporate_fleet_vehicle import CorporateFleetVehicle

    v = CorporateFleetVehicle()
    v.id = VEHICLE_ID
    v.account_id = ACCOUNT_ID
    v.name = "Fleet Van 1"
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
# Service layer tests (1–31)
# ===========================================================================


# --- Test 1 ---
@pytest.mark.asyncio
async def test_schedule_maintenance_success():
    db = _mock_db()
    vehicle = _mock_vehicle()
    data = MaintenanceRecordCreate(
        fleet_vehicle_id=VEHICLE_ID,
        maintenance_type=FleetMaintenanceType.oil_change,
        scheduled_date=_SCHED_DATE,
        description="Routine oil change",
    )

    with patch(f"{_SERVICE}._fetch_vehicle", new_callable=AsyncMock) as mock_fv:
        mock_fv.return_value = vehicle
        created = _make_record()
        db.refresh.side_effect = lambda obj: None

        with patch(f"{_SERVICE}.CorporateFleetMaintenanceRecord") as MockModel:
            MockModel.return_value = created
            result = await schedule_maintenance(db, ACCOUNT_ID, VEHICLE_ID, data, created_by_id=ADMIN_ID)

    assert db.add.called
    assert db.commit.called


# --- Test 2 ---
@pytest.mark.asyncio
async def test_schedule_maintenance_404_vehicle_not_found():
    db = _mock_db()
    data = MaintenanceRecordCreate(
        fleet_vehicle_id=VEHICLE_ID,
        maintenance_type=FleetMaintenanceType.tire_rotation,
    )
    with patch(f"{_SERVICE}._fetch_vehicle", new_callable=AsyncMock) as mock_fv:
        mock_fv.side_effect = HTTPException(status_code=404, detail="not found")
        with pytest.raises(HTTPException) as exc:
            await schedule_maintenance(db, ACCOUNT_ID, VEHICLE_ID, data)
    assert exc.value.status_code == 404


# --- Test 3 ---
@pytest.mark.asyncio
async def test_get_maintenance_record_success():
    db = _mock_db()
    rec = _make_record()
    with patch(f"{_SERVICE}._fetch_record", new_callable=AsyncMock) as mock_fr:
        mock_fr.return_value = rec
        result = await get_maintenance_record(db, ACCOUNT_ID, RECORD_ID)
    assert result.id == RECORD_ID
    assert result.maintenance_type == FleetMaintenanceType.oil_change


# --- Test 4 ---
@pytest.mark.asyncio
async def test_get_maintenance_record_404():
    db = _mock_db()
    with patch(f"{_SERVICE}._fetch_record", new_callable=AsyncMock) as mock_fr:
        mock_fr.side_effect = HTTPException(status_code=404, detail="not found")
        with pytest.raises(HTTPException) as exc:
            await get_maintenance_record(db, ACCOUNT_ID, uuid.uuid4())
    assert exc.value.status_code == 404


# --- Test 5 ---
@pytest.mark.asyncio
async def test_update_maintenance_record_success():
    db = _mock_db()
    rec = _make_record()
    with patch(f"{_SERVICE}._fetch_record", new_callable=AsyncMock) as mock_fr:
        mock_fr.return_value = rec
        data = MaintenanceRecordUpdate(
            vendor_name="Jiffy Lube",
            cost_usd=49.99,
        )
        result = await update_maintenance_record(db, ACCOUNT_ID, RECORD_ID, data)
    assert rec.vendor_name == "Jiffy Lube"
    assert db.commit.called


# --- Test 6 ---
@pytest.mark.asyncio
async def test_update_maintenance_record_ignores_none_fields():
    db = _mock_db()
    rec = _make_record()
    original_type = rec.maintenance_type
    with patch(f"{_SERVICE}._fetch_record", new_callable=AsyncMock) as mock_fr:
        mock_fr.return_value = rec
        data = MaintenanceRecordUpdate(notes="Check brakes too")
        await update_maintenance_record(db, ACCOUNT_ID, RECORD_ID, data)
    assert rec.maintenance_type == original_type
    assert rec.notes == "Check brakes too"


# --- Test 7 ---
@pytest.mark.asyncio
async def test_complete_maintenance_success():
    db = _mock_db()
    rec = _make_record(status=FleetMaintenanceStatus.scheduled)
    with patch(f"{_SERVICE}._fetch_record", new_callable=AsyncMock) as mock_fr:
        mock_fr.return_value = rec
        result = await complete_maintenance(
            db, ACCOUNT_ID, RECORD_ID,
            completed_date=_COMP_DATE,
            cost_usd=75.00,
            odometer=35000,
        )
    assert rec.status == FleetMaintenanceStatus.completed
    assert rec.completed_date == _COMP_DATE
    assert rec.odometer_at_service == 35000
    assert db.commit.called


# --- Test 8 ---
@pytest.mark.asyncio
async def test_complete_maintenance_404():
    db = _mock_db()
    with patch(f"{_SERVICE}._fetch_record", new_callable=AsyncMock) as mock_fr:
        mock_fr.side_effect = HTTPException(status_code=404, detail="not found")
        with pytest.raises(HTTPException) as exc:
            await complete_maintenance(db, ACCOUNT_ID, uuid.uuid4())
    assert exc.value.status_code == 404


# --- Test 9 ---
@pytest.mark.asyncio
async def test_cancel_maintenance_success():
    db = _mock_db()
    rec = _make_record(status=FleetMaintenanceStatus.scheduled)
    with patch(f"{_SERVICE}._fetch_record", new_callable=AsyncMock) as mock_fr:
        mock_fr.return_value = rec
        result = await cancel_maintenance(db, ACCOUNT_ID, RECORD_ID)
    assert rec.status == FleetMaintenanceStatus.cancelled
    assert db.commit.called


# --- Test 10 ---
@pytest.mark.asyncio
async def test_cancel_maintenance_409_already_completed():
    db = _mock_db()
    rec = _make_record(status=FleetMaintenanceStatus.completed)
    with patch(f"{_SERVICE}._fetch_record", new_callable=AsyncMock) as mock_fr:
        mock_fr.return_value = rec
        with pytest.raises(HTTPException) as exc:
            await cancel_maintenance(db, ACCOUNT_ID, RECORD_ID)
    assert exc.value.status_code == 409
    assert "completed" in exc.value.detail.lower()


# --- Test 11 ---
@pytest.mark.asyncio
async def test_cancel_maintenance_409_already_cancelled():
    db = _mock_db()
    rec = _make_record(status=FleetMaintenanceStatus.cancelled)
    with patch(f"{_SERVICE}._fetch_record", new_callable=AsyncMock) as mock_fr:
        mock_fr.return_value = rec
        with pytest.raises(HTTPException) as exc:
            await cancel_maintenance(db, ACCOUNT_ID, RECORD_ID)
    assert exc.value.status_code == 409
    assert "cancelled" in exc.value.detail.lower()


# --- Test 12 ---
@pytest.mark.asyncio
async def test_delete_maintenance_record_success():
    db = _mock_db()
    rec = _make_record()
    with patch(f"{_SERVICE}._fetch_record", new_callable=AsyncMock) as mock_fr:
        mock_fr.return_value = rec
        await delete_maintenance_record(db, ACCOUNT_ID, RECORD_ID)
    assert db.delete.called
    assert db.commit.called


# --- Test 13 ---
@pytest.mark.asyncio
async def test_delete_maintenance_record_404():
    db = _mock_db()
    with patch(f"{_SERVICE}._fetch_record", new_callable=AsyncMock) as mock_fr:
        mock_fr.side_effect = HTTPException(status_code=404, detail="not found")
        with pytest.raises(HTTPException) as exc:
            await delete_maintenance_record(db, ACCOUNT_ID, uuid.uuid4())
    assert exc.value.status_code == 404


# --- Test 14 ---
@pytest.mark.asyncio
async def test_list_vehicle_maintenance_returns_all():
    db = _mock_db()
    rows = [
        _make_record(),
        _make_record(record_id=uuid.uuid4(), maintenance_type=FleetMaintenanceType.tire_rotation),
    ]
    with patch(f"{_SERVICE}._fetch_vehicle", new_callable=AsyncMock) as mock_fv:
        mock_fv.return_value = _mock_vehicle()
        db.execute.return_value = _scalars_result(rows)
        results = await list_vehicle_maintenance(db, ACCOUNT_ID, VEHICLE_ID)
    assert len(results) == 2


# --- Test 15 ---
@pytest.mark.asyncio
async def test_list_vehicle_maintenance_status_filter():
    db = _mock_db()
    with patch(f"{_SERVICE}._fetch_vehicle", new_callable=AsyncMock) as mock_fv:
        mock_fv.return_value = _mock_vehicle()
        db.execute.return_value = _scalars_result(
            [_make_record(status=FleetMaintenanceStatus.completed)]
        )
        results = await list_vehicle_maintenance(
            db, ACCOUNT_ID, VEHICLE_ID, status=FleetMaintenanceStatus.completed
        )
    assert len(results) == 1
    assert results[0].status == FleetMaintenanceStatus.completed


# --- Test 16 ---
@pytest.mark.asyncio
async def test_list_vehicle_maintenance_type_filter():
    db = _mock_db()
    with patch(f"{_SERVICE}._fetch_vehicle", new_callable=AsyncMock) as mock_fv:
        mock_fv.return_value = _mock_vehicle()
        db.execute.return_value = _scalars_result(
            [_make_record(maintenance_type=FleetMaintenanceType.brake_inspection)]
        )
        results = await list_vehicle_maintenance(
            db, ACCOUNT_ID, VEHICLE_ID,
            maintenance_type=FleetMaintenanceType.brake_inspection,
        )
    assert len(results) == 1
    assert results[0].maintenance_type == FleetMaintenanceType.brake_inspection


# --- Test 17 ---
@pytest.mark.asyncio
async def test_list_vehicle_maintenance_404_vehicle():
    db = _mock_db()
    with patch(f"{_SERVICE}._fetch_vehicle", new_callable=AsyncMock) as mock_fv:
        mock_fv.side_effect = HTTPException(status_code=404, detail="not found")
        with pytest.raises(HTTPException) as exc:
            await list_vehicle_maintenance(db, ACCOUNT_ID, uuid.uuid4())
    assert exc.value.status_code == 404


# --- Test 18 ---
@pytest.mark.asyncio
async def test_list_account_maintenance_returns_all():
    db = _mock_db()
    rows = [
        _make_record(),
        _make_record(record_id=uuid.uuid4(), maintenance_type=FleetMaintenanceType.tire_rotation),
        _make_record(record_id=uuid.uuid4(), maintenance_type=FleetMaintenanceType.brake_inspection),
    ]
    db.execute.return_value = _scalars_result(rows)
    results = await list_account_maintenance(db, ACCOUNT_ID)
    assert len(results) == 3


# --- Test 19 ---
@pytest.mark.asyncio
async def test_list_account_maintenance_vehicle_filter():
    db = _mock_db()
    db.execute.return_value = _scalars_result([_make_record()])
    results = await list_account_maintenance(db, ACCOUNT_ID, vehicle_id=VEHICLE_ID)
    assert len(results) == 1
    assert results[0].fleet_vehicle_id == VEHICLE_ID


# --- Test 20 ---
@pytest.mark.asyncio
async def test_list_account_maintenance_status_filter():
    db = _mock_db()
    db.execute.return_value = _scalars_result(
        [_make_record(status=FleetMaintenanceStatus.overdue)]
    )
    results = await list_account_maintenance(
        db, ACCOUNT_ID, status=FleetMaintenanceStatus.overdue
    )
    assert len(results) == 1
    assert results[0].status == FleetMaintenanceStatus.overdue


# --- Test 21 ---
@pytest.mark.asyncio
async def test_list_account_maintenance_type_filter():
    db = _mock_db()
    db.execute.return_value = _scalars_result(
        [_make_record(maintenance_type=FleetMaintenanceType.transmission_service)]
    )
    results = await list_account_maintenance(
        db, ACCOUNT_ID, maintenance_type=FleetMaintenanceType.transmission_service
    )
    assert len(results) == 1
    assert results[0].maintenance_type == FleetMaintenanceType.transmission_service


# --- Test 22 ---
@pytest.mark.asyncio
async def test_get_overdue_maintenance_marks_and_returns_overdue():
    db = _mock_db()
    today = date.today()
    past_date = today - timedelta(days=3)

    rec_overdue = _make_record(
        status=FleetMaintenanceStatus.scheduled,
        scheduled_date=past_date,
    )
    rec_future = _make_record(
        record_id=uuid.uuid4(),
        status=FleetMaintenanceStatus.scheduled,
        scheduled_date=today + timedelta(days=10),
    )

    db.execute.return_value = _scalars_result([rec_overdue, rec_future])
    results = await get_overdue_maintenance(db, ACCOUNT_ID)

    assert rec_overdue.status == FleetMaintenanceStatus.overdue
    assert rec_future.status == FleetMaintenanceStatus.scheduled  # not changed
    assert len(results) == 1
    assert db.commit.called


# --- Test 23 ---
@pytest.mark.asyncio
async def test_get_overdue_maintenance_ignores_completed():
    db = _mock_db()
    # The query filters status in (scheduled, in_progress) — completed won't appear
    db.execute.return_value = _scalars_result([])
    results = await get_overdue_maintenance(db, ACCOUNT_ID)
    assert results == []


# --- Test 24 ---
@pytest.mark.asyncio
async def test_get_overdue_maintenance_empty_when_none_overdue():
    db = _mock_db()
    today = date.today()
    rec_future = _make_record(
        status=FleetMaintenanceStatus.scheduled,
        scheduled_date=today + timedelta(days=5),
    )
    db.execute.return_value = _scalars_result([rec_future])
    results = await get_overdue_maintenance(db, ACCOUNT_ID)
    assert results == []
    # commit should NOT be called when no overdue rows
    assert not db.commit.called


# --- Test 25 ---
@pytest.mark.asyncio
async def test_get_vehicle_maintenance_summary_counts_and_cost():
    db = _mock_db()
    rows = [
        _make_record(cost_usd=50.00, status=FleetMaintenanceStatus.completed),
        _make_record(record_id=uuid.uuid4(), cost_usd=100.00, status=FleetMaintenanceStatus.overdue),
        _make_record(record_id=uuid.uuid4(), cost_usd=None, status=FleetMaintenanceStatus.scheduled),
    ]

    with patch(f"{_SERVICE}._fetch_vehicle", new_callable=AsyncMock) as mock_fv:
        mock_fv.return_value = _mock_vehicle()
        db.execute.return_value = _scalars_result(rows)
        summary = await get_vehicle_maintenance_summary(db, ACCOUNT_ID, VEHICLE_ID)

    assert summary.vehicle_id == VEHICLE_ID
    assert summary.total_records == 3
    assert summary.total_cost_usd == pytest.approx(150.00)
    assert summary.overdue_count == 1


# --- Test 26 ---
@pytest.mark.asyncio
async def test_get_vehicle_maintenance_summary_dates():
    db = _mock_db()
    today = date.today()
    comp1 = today - timedelta(days=30)
    comp2 = today - timedelta(days=10)
    future = today + timedelta(days=14)

    rows = [
        _make_record(
            completed_date=comp1,
            status=FleetMaintenanceStatus.completed,
            scheduled_date=None,
        ),
        _make_record(
            record_id=uuid.uuid4(),
            completed_date=comp2,
            status=FleetMaintenanceStatus.completed,
            scheduled_date=None,
        ),
        _make_record(
            record_id=uuid.uuid4(),
            status=FleetMaintenanceStatus.scheduled,
            scheduled_date=future,
            completed_date=None,
        ),
    ]

    with patch(f"{_SERVICE}._fetch_vehicle", new_callable=AsyncMock) as mock_fv:
        mock_fv.return_value = _mock_vehicle()
        db.execute.return_value = _scalars_result(rows)
        summary = await get_vehicle_maintenance_summary(db, ACCOUNT_ID, VEHICLE_ID)

    assert summary.last_service_date == comp2
    assert summary.next_scheduled_date == future


# --- Test 27 ---
@pytest.mark.asyncio
async def test_get_vehicle_maintenance_summary_per_type():
    db = _mock_db()
    rows = [
        _make_record(maintenance_type=FleetMaintenanceType.oil_change, cost_usd=50.00),
        _make_record(record_id=uuid.uuid4(), maintenance_type=FleetMaintenanceType.oil_change, cost_usd=55.00),
        _make_record(record_id=uuid.uuid4(), maintenance_type=FleetMaintenanceType.tire_rotation, cost_usd=30.00),
    ]

    with patch(f"{_SERVICE}._fetch_vehicle", new_callable=AsyncMock) as mock_fv:
        mock_fv.return_value = _mock_vehicle()
        db.execute.return_value = _scalars_result(rows)
        summary = await get_vehicle_maintenance_summary(db, ACCOUNT_ID, VEHICLE_ID)

    per_type_map = {pt.maintenance_type: pt for pt in summary.per_type}
    assert per_type_map[FleetMaintenanceType.oil_change].count == 2
    assert per_type_map[FleetMaintenanceType.oil_change].total_cost_usd == pytest.approx(105.00)
    assert per_type_map[FleetMaintenanceType.tire_rotation].count == 1


# --- Test 28 ---
@pytest.mark.asyncio
async def test_get_account_maintenance_summary_counts_and_cost():
    db = _mock_db()
    vehicle2 = uuid.uuid4()
    rows = [
        _make_record(cost_usd=100.00, status=FleetMaintenanceStatus.overdue),
        _make_record(record_id=uuid.uuid4(), cost_usd=200.00, status=FleetMaintenanceStatus.completed),
        _make_record(record_id=uuid.uuid4(), fleet_vehicle_id=vehicle2, cost_usd=50.00,
                     status=FleetMaintenanceStatus.overdue),
    ]
    db.execute.return_value = _scalars_result(rows)
    summary = await get_account_maintenance_summary(db, ACCOUNT_ID)

    assert summary.account_id == ACCOUNT_ID
    assert summary.total_records == 3
    assert summary.total_cost_usd == pytest.approx(350.00)
    assert summary.overdue_count == 2


# --- Test 29 ---
@pytest.mark.asyncio
async def test_get_account_maintenance_summary_vehicles_with_overdue():
    db = _mock_db()
    vehicle2 = uuid.uuid4()
    rows = [
        _make_record(status=FleetMaintenanceStatus.overdue),
        _make_record(record_id=uuid.uuid4(), fleet_vehicle_id=vehicle2,
                     status=FleetMaintenanceStatus.overdue),
        _make_record(record_id=uuid.uuid4(), status=FleetMaintenanceStatus.completed),
    ]
    db.execute.return_value = _scalars_result(rows)
    summary = await get_account_maintenance_summary(db, ACCOUNT_ID)

    assert len(summary.vehicles_with_overdue) == 2
    assert VEHICLE_ID in summary.vehicles_with_overdue
    assert vehicle2 in summary.vehicles_with_overdue


# --- Test 30 ---
@pytest.mark.asyncio
async def test_list_all_platform_returns_all():
    db = _mock_db()
    rows = [
        _make_record(),
        _make_record(record_id=uuid.uuid4(), account_id=99),
    ]
    db.execute.return_value = _scalars_result(rows)
    results = await list_all_platform(db)
    assert len(results) == 2


# --- Test 31 ---
@pytest.mark.asyncio
async def test_list_all_platform_filters_by_account():
    db = _mock_db()
    db.execute.return_value = _scalars_result([_make_record()])
    results = await list_all_platform(db, account_id=ACCOUNT_ID)
    assert len(results) == 1
    assert results[0].account_id == ACCOUNT_ID


# ===========================================================================
# Schema validation tests (32–37)
# ===========================================================================


# --- Test 32 ---
def test_schema_create_valid():
    schema = MaintenanceRecordCreate(
        fleet_vehicle_id=VEHICLE_ID,
        maintenance_type=FleetMaintenanceType.oil_change,
        scheduled_date=_SCHED_DATE,
        description="Routine oil change",
    )
    assert schema.fleet_vehicle_id == VEHICLE_ID
    assert schema.maintenance_type == FleetMaintenanceType.oil_change
    assert schema.scheduled_date == _SCHED_DATE
    assert schema.cost_usd is None


# --- Test 33 ---
def test_schema_create_missing_required_raises():
    with pytest.raises(ValidationError):
        # Missing fleet_vehicle_id
        MaintenanceRecordCreate(
            maintenance_type=FleetMaintenanceType.oil_change,
        )


# --- Test 34 ---
def test_schema_update_all_optional():
    schema = MaintenanceRecordUpdate()
    assert schema.maintenance_type is None
    assert schema.status is None
    assert schema.scheduled_date is None
    assert schema.completed_date is None
    assert schema.cost_usd is None
    assert schema.vendor_name is None
    assert schema.notes is None


# --- Test 35 ---
def test_schema_response_from_attributes():
    rec = _make_record()
    resp = _make_response(rec)
    assert resp.id == RECORD_ID
    assert resp.account_id == ACCOUNT_ID
    assert resp.maintenance_type == FleetMaintenanceType.oil_change
    assert resp.status == FleetMaintenanceStatus.scheduled
    assert resp.completed_date is None


# --- Test 36 ---
def test_schema_vehicle_summary_valid():
    summary = VehicleMaintenanceSummaryResponse(
        vehicle_id=VEHICLE_ID,
        total_records=5,
        total_cost_usd=325.00,
        last_service_date=date(2026, 3, 1),
        next_scheduled_date=date(2026, 6, 1),
        overdue_count=1,
        per_type=[
            MaintenanceTypeBreakdown(
                maintenance_type=FleetMaintenanceType.oil_change,
                count=3,
                total_cost_usd=150.00,
            )
        ],
    )
    assert summary.vehicle_id == VEHICLE_ID
    assert summary.total_records == 5
    assert summary.overdue_count == 1
    assert summary.per_type[0].maintenance_type == FleetMaintenanceType.oil_change


# --- Test 37 ---
def test_schema_account_summary_valid():
    summary = AccountMaintenanceSummaryResponse(
        account_id=ACCOUNT_ID,
        total_records=12,
        total_cost_usd=875.50,
        overdue_count=3,
        vehicles_with_overdue=[VEHICLE_ID],
    )
    assert summary.account_id == ACCOUNT_ID
    assert summary.total_records == 12
    assert summary.overdue_count == 3
    assert VEHICLE_ID in summary.vehicles_with_overdue


# ===========================================================================
# API layer tests (38–50)
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


# --- Test 38 ---
def test_api_list_vehicle_maintenance_200():
    with (
        _patch_get_account(),
        patch(
            f"{_ROUTER}.list_vehicle_maintenance",
            new_callable=AsyncMock,
            return_value=[_make_response()],
        ),
    ):
        app.dependency_overrides.update(_dep_overrides())
        r = client.get(
            f"/api/v1/corporate/{ACCOUNT_ID}/fleet-vehicles/{VEHICLE_ID}/scheduled-maintenance"
        )
        app.dependency_overrides.clear()
    assert r.status_code == 200


# --- Test 39 ---
def test_api_get_vehicle_maintenance_summary_200():
    summary = VehicleMaintenanceSummaryResponse(
        vehicle_id=VEHICLE_ID,
        total_records=3,
        total_cost_usd=150.00,
        last_service_date=None,
        next_scheduled_date=_SCHED_DATE,
        overdue_count=0,
        per_type=[],
    )
    with (
        _patch_get_account(),
        patch(
            f"{_ROUTER}.get_vehicle_maintenance_summary",
            new_callable=AsyncMock,
            return_value=summary,
        ),
    ):
        app.dependency_overrides.update(_dep_overrides())
        r = client.get(
            f"/api/v1/corporate/{ACCOUNT_ID}/fleet-vehicles/{VEHICLE_ID}/maintenance-summary"
        )
        app.dependency_overrides.clear()
    assert r.status_code == 200
    data = r.json()
    assert data["total_records"] == 3


# --- Test 40 ---
def test_api_get_single_maintenance_record_200():
    with (
        _patch_get_account(),
        patch(
            f"{_ROUTER}.get_maintenance_record",
            new_callable=AsyncMock,
            return_value=_make_response(),
        ),
    ):
        app.dependency_overrides.update(_dep_overrides())
        r = client.get(
            f"/api/v1/corporate/{ACCOUNT_ID}/fleet-vehicles/{VEHICLE_ID}/scheduled-maintenance/{RECORD_ID}"
        )
        app.dependency_overrides.clear()
    assert r.status_code == 200


# --- Test 41 ---
def test_api_schedule_maintenance_201():
    resp = _make_response()
    with (
        _patch_get_account(),
        _patch_require_account_admin(),
        patch(
            f"{_ROUTER}.schedule_maintenance",
            new_callable=AsyncMock,
            return_value=resp,
        ),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        r = client.post(
            f"/api/v1/corporate/{ACCOUNT_ID}/fleet-vehicles/{VEHICLE_ID}/scheduled-maintenance",
            json={
                "fleet_vehicle_id": str(VEHICLE_ID),
                "maintenance_type": "oil_change",
                "scheduled_date": str(_SCHED_DATE),
            },
        )
        app.dependency_overrides.clear()
    assert r.status_code == 201


# --- Test 42 ---
def test_api_list_account_maintenance_200():
    with (
        _patch_get_account(),
        _patch_require_account_admin(),
        patch(
            f"{_ROUTER}.list_account_maintenance",
            new_callable=AsyncMock,
            return_value=[_make_response()],
        ),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        r = client.get(f"/api/v1/corporate/{ACCOUNT_ID}/fleet-maintenance/")
        app.dependency_overrides.clear()
    assert r.status_code == 200


# --- Test 43 ---
def test_api_get_overdue_200():
    with (
        _patch_get_account(),
        _patch_require_account_admin(),
        patch(
            f"{_ROUTER}.get_overdue_maintenance",
            new_callable=AsyncMock,
            return_value=[],
        ),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        r = client.get(f"/api/v1/corporate/{ACCOUNT_ID}/fleet-maintenance/overdue")
        app.dependency_overrides.clear()
    assert r.status_code == 200


# --- Test 44 ---
def test_api_update_maintenance_200():
    with (
        _patch_get_account(),
        _patch_require_account_admin(),
        patch(
            f"{_ROUTER}.update_maintenance_record",
            new_callable=AsyncMock,
            return_value=_make_response(),
        ),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        r = client.put(
            f"/api/v1/corporate/{ACCOUNT_ID}/fleet-maintenance/{RECORD_ID}",
            json={"vendor_name": "AutoZone"},
        )
        app.dependency_overrides.clear()
    assert r.status_code == 200


# --- Test 45 ---
def test_api_complete_maintenance_200():
    completed_rec = _make_record(
        status=FleetMaintenanceStatus.completed,
        completed_date=_COMP_DATE,
    )
    with (
        _patch_get_account(),
        _patch_require_account_admin(),
        patch(
            f"{_ROUTER}.complete_maintenance",
            new_callable=AsyncMock,
            return_value=_make_response(completed_rec),
        ),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        r = client.post(
            f"/api/v1/corporate/{ACCOUNT_ID}/fleet-maintenance/{RECORD_ID}/complete"
        )
        app.dependency_overrides.clear()
    assert r.status_code == 200
    assert r.json()["status"] == "completed"


# --- Test 46 ---
def test_api_cancel_maintenance_200():
    cancelled_rec = _make_record(status=FleetMaintenanceStatus.cancelled)
    with (
        _patch_get_account(),
        _patch_require_account_admin(),
        patch(
            f"{_ROUTER}.cancel_maintenance",
            new_callable=AsyncMock,
            return_value=_make_response(cancelled_rec),
        ),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        r = client.post(
            f"/api/v1/corporate/{ACCOUNT_ID}/fleet-maintenance/{RECORD_ID}/cancel"
        )
        app.dependency_overrides.clear()
    assert r.status_code == 200
    assert r.json()["status"] == "cancelled"


# --- Test 47 ---
def test_api_delete_maintenance_204():
    with (
        _patch_get_account(),
        _patch_require_account_admin(),
        patch(
            f"{_ROUTER}.delete_maintenance_record",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        r = client.delete(
            f"/api/v1/corporate/{ACCOUNT_ID}/fleet-maintenance/{RECORD_ID}"
        )
        app.dependency_overrides.clear()
    assert r.status_code == 204


# --- Test 48 ---
def test_api_get_account_maintenance_summary_200():
    summary = AccountMaintenanceSummaryResponse(
        account_id=ACCOUNT_ID,
        total_records=10,
        total_cost_usd=500.00,
        overdue_count=2,
        vehicles_with_overdue=[VEHICLE_ID],
    )
    with (
        _patch_get_account(),
        _patch_require_account_admin(),
        patch(
            f"{_ROUTER}.get_account_maintenance_summary",
            new_callable=AsyncMock,
            return_value=summary,
        ),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        r = client.get(f"/api/v1/corporate/{ACCOUNT_ID}/fleet-maintenance-summary")
        app.dependency_overrides.clear()
    assert r.status_code == 200
    data = r.json()
    assert data["overdue_count"] == 2


# --- Test 49 ---
def test_api_platform_list_all_200():
    with patch(
        f"{_ROUTER}.list_all_platform",
        new_callable=AsyncMock,
        return_value=[_make_response()],
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        r = client.get("/api/v1/platform/corporate/fleet-maintenance/")
        app.dependency_overrides.clear()
    assert r.status_code == 200


# --- Test 50 ---
def test_api_platform_list_by_account_200():
    with patch(
        f"{_ROUTER}.list_all_platform",
        new_callable=AsyncMock,
        return_value=[_make_response()],
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        r = client.get(f"/api/v1/platform/corporate/fleet-maintenance/{ACCOUNT_ID}")
        app.dependency_overrides.clear()
    assert r.status_code == 200
