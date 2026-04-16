"""Tests for the Corporate Fleet Fuel & Mileage Tracking feature.

Service layer (async, mocked DB):
   1.  log_fuel_fill — success: creates record with correct fields
   2.  log_fuel_fill — 404 when vehicle not in account
   3.  get_fuel_log — success: returns existing log
   4.  get_fuel_log — 404 when not found
   5.  update_fuel_log — success: updates fields
   6.  update_fuel_log — 404 when not found
   7.  delete_fuel_log — success: hard-deletes record
   8.  delete_fuel_log — 404 when not found
   9.  list_vehicle_fuel_logs — returns logs for vehicle
  10.  list_vehicle_fuel_logs — fuel_type filter applied
  11.  list_vehicle_fuel_logs — from_date filter applied
  12.  list_vehicle_fuel_logs — to_date filter applied
  13.  list_vehicle_fuel_logs — 404 when vehicle not in account
  14.  get_vehicle_fuel_summary — empty vehicle returns zero totals
  15.  get_vehicle_fuel_summary — computes total_cost and total_gallons
  16.  get_vehicle_fuel_summary — computes avg_mpg when odometer readings available
  17.  get_vehicle_fuel_summary — avg_mpg is None when no odometer readings
  18.  get_vehicle_fuel_summary — cost_per_mile_usd computed correctly
  19.  get_vehicle_fuel_summary — 404 when vehicle not in account
  20.  list_account_fuel_logs — returns all for account
  21.  list_account_fuel_logs — vehicle_id filter works
  22.  list_account_fuel_logs — fuel_type filter works
  23.  get_fleet_fuel_summary — zero logs returns empty totals
  24.  get_fleet_fuel_summary — aggregates totals across vehicles
  25.  get_fleet_fuel_summary — by_fuel_type breakdown correct
  26.  list_all_platform — returns all logs
  27.  list_all_platform — account_id filter works

Schema validation:
  28.  FuelLogCreate — valid construction
  29.  FuelLogCreate — negative odometer rejected
  30.  FuelLogCreate — negative gallons rejected
  31.  FuelLogUpdate — all optional fields
  32.  FuelLogResponse — from_attributes not needed (manual construction)
  33.  VehicleFuelSummary — valid structure
  34.  FleetFuelSummary — valid structure with by_fuel_type list

API layer (service functions patched):
  35.  POST log fuel fill → 201
  36.  GET list vehicle logs → 200
  37.  GET vehicle fuel summary → 200
  38.  GET get one log → 200
  39.  PUT update log → 200
  40.  DELETE delete log → 204
  41.  GET list account logs → 200
  42.  GET fleet summary → 200
  43.  GET platform list → 200
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
from app.models.corporate_fleet_fuel_log import FleetFuelType
from app.schemas.corporate_fleet_fuel_log import (
    FleetFuelSummary,
    FuelLogCreate,
    FuelLogResponse,
    FuelLogUpdate,
    FuelTypeBreakdown,
    VehicleFuelSummary,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ACCOUNT_ID = 1
VEHICLE_ID = uuid.uuid4()
LOG_ID = uuid.uuid4()
USER_ID = 42
NOW = datetime.now(tz=timezone.utc)
TODAY = date.today()


def _mock_log(
    log_id: uuid.UUID = LOG_ID,
    account_id: int = ACCOUNT_ID,
    vehicle_id: uuid.UUID = VEHICLE_ID,
    fuel_type: FleetFuelType = FleetFuelType.gasoline,
    fill_date: date = TODAY,
    odometer_miles: int | None = 12000,
    gallons_added: float | None = 12.5,
    kwh_added: float | None = None,
    cost_per_unit_usd: float | None = 3.50,
    total_cost_usd: float | None = 43.75,
    station_name: str | None = "Shell Station",
    notes: str | None = None,
    logged_by_id: int | None = USER_ID,
):
    """Build a FuelLogResponse for use in tests."""
    return FuelLogResponse(
        id=log_id,
        fleet_vehicle_id=vehicle_id,
        account_id=account_id,
        fuel_type=fuel_type.value,
        fill_date=fill_date,
        odometer_miles=odometer_miles,
        gallons_added=gallons_added,
        kwh_added=kwh_added,
        cost_per_unit_usd=cost_per_unit_usd,
        total_cost_usd=total_cost_usd,
        station_name=station_name,
        notes=notes,
        logged_by_id=logged_by_id,
        created_at=NOW,
        updated_at=NOW,
    )


def _mock_vehicle_summary() -> VehicleFuelSummary:
    return VehicleFuelSummary(
        fleet_vehicle_id=VEHICLE_ID,
        log_count=3,
        total_cost_usd=131.25,
        total_gallons=37.5,
        total_kwh=0.0,
        min_odometer_miles=10000,
        max_odometer_miles=11500,
        total_miles_tracked=1500,
        avg_mpg=40.0,
        cost_per_mile_usd=0.0875,
        first_fill_date=TODAY,
        last_fill_date=TODAY,
    )


def _mock_fleet_summary() -> FleetFuelSummary:
    return FleetFuelSummary(
        total_logs=5,
        total_cost_usd=218.75,
        total_gallons=62.5,
        total_kwh=0.0,
        by_fuel_type=[
            FuelTypeBreakdown(
                fuel_type="gasoline",
                log_count=5,
                total_cost_usd=218.75,
                total_gallons=62.5,
                total_kwh=0.0,
            )
        ],
        vehicle_count=2,
    )


# ---------------------------------------------------------------------------
# Service layer — log_fuel_fill
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_log_fuel_fill_success():
    """log_fuel_fill creates a new record and returns FuelLogResponse."""
    from app.services import corporate_fleet_fuel_service as svc

    mock_db = AsyncMock()
    mock_vehicle = MagicMock()
    vehicle_result = MagicMock()
    vehicle_result.scalar_one_or_none.return_value = mock_vehicle

    mock_log_row = MagicMock()
    mock_log_row.id = LOG_ID
    mock_log_row.fleet_vehicle_id = VEHICLE_ID
    mock_log_row.account_id = ACCOUNT_ID
    mock_log_row.fuel_type = FleetFuelType.gasoline
    mock_log_row.fill_date = TODAY
    mock_log_row.odometer_miles = 12000
    mock_log_row.gallons_added = 12.5
    mock_log_row.kwh_added = None
    mock_log_row.cost_per_unit_usd = 3.50
    mock_log_row.total_cost_usd = 43.75
    mock_log_row.station_name = "Shell"
    mock_log_row.notes = None
    mock_log_row.logged_by_id = USER_ID
    mock_log_row.created_at = NOW
    mock_log_row.updated_at = NOW

    mock_db.execute.return_value = vehicle_result
    mock_db.commit = AsyncMock()
    mock_db.refresh = AsyncMock()

    data = FuelLogCreate(
        fleet_vehicle_id=VEHICLE_ID,
        fuel_type=FleetFuelType.gasoline,
        fill_date=TODAY,
        odometer_miles=12000,
        gallons_added=12.5,
        cost_per_unit_usd=3.50,
        total_cost_usd=43.75,
        station_name="Shell",
    )

    with patch.object(svc, "CorporateFleetFuelLog") as MockLog:
        instance = MockLog.return_value
        instance.id = LOG_ID
        instance.fleet_vehicle_id = VEHICLE_ID
        instance.account_id = ACCOUNT_ID
        instance.fuel_type = FleetFuelType.gasoline
        instance.fill_date = TODAY
        instance.odometer_miles = 12000
        instance.gallons_added = 12.5
        instance.kwh_added = None
        instance.cost_per_unit_usd = 3.50
        instance.total_cost_usd = 43.75
        instance.station_name = "Shell"
        instance.notes = None
        instance.logged_by_id = USER_ID
        instance.created_at = NOW
        instance.updated_at = NOW

        result = await svc.log_fuel_fill(mock_db, ACCOUNT_ID, data, logged_by_id=USER_ID)

    assert result.fuel_type == "gasoline"
    assert result.fleet_vehicle_id == VEHICLE_ID
    mock_db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_log_fuel_fill_404_vehicle():
    """log_fuel_fill raises 404 when vehicle not in account."""
    from app.services import corporate_fleet_fuel_service as svc

    mock_db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    mock_db.execute.return_value = result

    data = FuelLogCreate(
        fleet_vehicle_id=VEHICLE_ID,
        fuel_type=FleetFuelType.gasoline,
        fill_date=TODAY,
    )

    with pytest.raises(HTTPException) as exc_info:
        await svc.log_fuel_fill(mock_db, ACCOUNT_ID, data)
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Service layer — get_fuel_log
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_fuel_log_success():
    """get_fuel_log returns FuelLogResponse for an existing record."""
    from app.services import corporate_fleet_fuel_service as svc

    mock_db = AsyncMock()
    mock_row = MagicMock()
    mock_row.id = LOG_ID
    mock_row.fleet_vehicle_id = VEHICLE_ID
    mock_row.account_id = ACCOUNT_ID
    mock_row.fuel_type = FleetFuelType.gasoline
    mock_row.fill_date = TODAY
    mock_row.odometer_miles = 12000
    mock_row.gallons_added = 12.5
    mock_row.kwh_added = None
    mock_row.cost_per_unit_usd = 3.50
    mock_row.total_cost_usd = 43.75
    mock_row.station_name = "BP"
    mock_row.notes = None
    mock_row.logged_by_id = USER_ID
    mock_row.created_at = NOW
    mock_row.updated_at = NOW

    result = MagicMock()
    result.scalar_one_or_none.return_value = mock_row
    mock_db.execute.return_value = result

    response = await svc.get_fuel_log(mock_db, ACCOUNT_ID, LOG_ID)
    assert response.id == LOG_ID


@pytest.mark.asyncio
async def test_get_fuel_log_404():
    """get_fuel_log raises 404 when log not found."""
    from app.services import corporate_fleet_fuel_service as svc

    mock_db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    mock_db.execute.return_value = result

    with pytest.raises(HTTPException) as exc_info:
        await svc.get_fuel_log(mock_db, ACCOUNT_ID, LOG_ID)
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Service layer — update_fuel_log
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_fuel_log_success():
    """update_fuel_log updates fields and returns updated response."""
    from app.services import corporate_fleet_fuel_service as svc

    mock_db = AsyncMock()
    mock_row = MagicMock()
    mock_row.id = LOG_ID
    mock_row.fleet_vehicle_id = VEHICLE_ID
    mock_row.account_id = ACCOUNT_ID
    mock_row.fuel_type = FleetFuelType.gasoline
    mock_row.fill_date = TODAY
    mock_row.odometer_miles = 12000
    mock_row.gallons_added = 12.5
    mock_row.kwh_added = None
    mock_row.cost_per_unit_usd = 3.50
    mock_row.total_cost_usd = 43.75
    mock_row.station_name = "Old Station"
    mock_row.notes = None
    mock_row.logged_by_id = USER_ID
    mock_row.created_at = NOW
    mock_row.updated_at = NOW

    result = MagicMock()
    result.scalar_one_or_none.return_value = mock_row
    mock_db.execute.return_value = result
    mock_db.commit = AsyncMock()
    mock_db.refresh = AsyncMock()

    update = FuelLogUpdate(station_name="New Station", total_cost_usd=50.00)
    response = await svc.update_fuel_log(mock_db, ACCOUNT_ID, LOG_ID, update)
    assert mock_row.station_name == "New Station"
    mock_db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_fuel_log_404():
    """update_fuel_log raises 404 when log not found."""
    from app.services import corporate_fleet_fuel_service as svc

    mock_db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    mock_db.execute.return_value = result

    with pytest.raises(HTTPException) as exc_info:
        await svc.update_fuel_log(mock_db, ACCOUNT_ID, LOG_ID, FuelLogUpdate())
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Service layer — delete_fuel_log
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_fuel_log_success():
    """delete_fuel_log removes the record."""
    from app.services import corporate_fleet_fuel_service as svc

    mock_db = AsyncMock()
    mock_row = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = mock_row
    mock_db.execute.return_value = result
    mock_db.commit = AsyncMock()
    mock_db.delete = AsyncMock()

    await svc.delete_fuel_log(mock_db, ACCOUNT_ID, LOG_ID)
    mock_db.delete.assert_awaited_once_with(mock_row)
    mock_db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_fuel_log_404():
    """delete_fuel_log raises 404 when log not found."""
    from app.services import corporate_fleet_fuel_service as svc

    mock_db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    mock_db.execute.return_value = result

    with pytest.raises(HTTPException) as exc_info:
        await svc.delete_fuel_log(mock_db, ACCOUNT_ID, LOG_ID)
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Service layer — list_vehicle_fuel_logs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_vehicle_fuel_logs_returns_logs():
    """list_vehicle_fuel_logs returns logs for the vehicle."""
    from app.services import corporate_fleet_fuel_service as svc

    mock_db = AsyncMock()
    mock_vehicle = MagicMock()
    vehicle_result = MagicMock()
    vehicle_result.scalar_one_or_none.return_value = mock_vehicle

    mock_log = MagicMock()
    mock_log.id = LOG_ID
    mock_log.fleet_vehicle_id = VEHICLE_ID
    mock_log.account_id = ACCOUNT_ID
    mock_log.fuel_type = FleetFuelType.gasoline
    mock_log.fill_date = TODAY
    mock_log.odometer_miles = 12000
    mock_log.gallons_added = 12.5
    mock_log.kwh_added = None
    mock_log.cost_per_unit_usd = 3.50
    mock_log.total_cost_usd = 43.75
    mock_log.station_name = None
    mock_log.notes = None
    mock_log.logged_by_id = None
    mock_log.created_at = NOW
    mock_log.updated_at = NOW

    logs_result = MagicMock()
    logs_result.scalars.return_value.all.return_value = [mock_log]

    mock_db.execute.side_effect = [vehicle_result, logs_result]

    result = await svc.list_vehicle_fuel_logs(mock_db, ACCOUNT_ID, VEHICLE_ID)
    assert len(result) == 1
    assert result[0].id == LOG_ID


@pytest.mark.asyncio
async def test_list_vehicle_fuel_logs_fuel_type_filter():
    """list_vehicle_fuel_logs diesel filter excludes gasoline logs."""
    from app.services import corporate_fleet_fuel_service as svc

    mock_db = AsyncMock()
    mock_vehicle = MagicMock()
    vehicle_result = MagicMock()
    vehicle_result.scalar_one_or_none.return_value = mock_vehicle

    logs_result = MagicMock()
    logs_result.scalars.return_value.all.return_value = []

    mock_db.execute.side_effect = [vehicle_result, logs_result]

    result = await svc.list_vehicle_fuel_logs(
        mock_db, ACCOUNT_ID, VEHICLE_ID, fuel_type=FleetFuelType.diesel
    )
    assert result == []


@pytest.mark.asyncio
async def test_list_vehicle_fuel_logs_from_date_filter():
    """list_vehicle_fuel_logs from_date filter is applied."""
    from app.services import corporate_fleet_fuel_service as svc

    mock_db = AsyncMock()
    vehicle_result = MagicMock()
    vehicle_result.scalar_one_or_none.return_value = MagicMock()
    logs_result = MagicMock()
    logs_result.scalars.return_value.all.return_value = []
    mock_db.execute.side_effect = [vehicle_result, logs_result]

    result = await svc.list_vehicle_fuel_logs(
        mock_db, ACCOUNT_ID, VEHICLE_ID, from_date=date(2026, 1, 1)
    )
    assert result == []


@pytest.mark.asyncio
async def test_list_vehicle_fuel_logs_to_date_filter():
    """list_vehicle_fuel_logs to_date filter is applied."""
    from app.services import corporate_fleet_fuel_service as svc

    mock_db = AsyncMock()
    vehicle_result = MagicMock()
    vehicle_result.scalar_one_or_none.return_value = MagicMock()
    logs_result = MagicMock()
    logs_result.scalars.return_value.all.return_value = []
    mock_db.execute.side_effect = [vehicle_result, logs_result]

    result = await svc.list_vehicle_fuel_logs(
        mock_db, ACCOUNT_ID, VEHICLE_ID, to_date=date(2026, 12, 31)
    )
    assert result == []


@pytest.mark.asyncio
async def test_list_vehicle_fuel_logs_404_vehicle():
    """list_vehicle_fuel_logs raises 404 when vehicle not in account."""
    from app.services import corporate_fleet_fuel_service as svc

    mock_db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    mock_db.execute.return_value = result

    with pytest.raises(HTTPException) as exc_info:
        await svc.list_vehicle_fuel_logs(mock_db, ACCOUNT_ID, VEHICLE_ID)
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Service layer — get_vehicle_fuel_summary
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_vehicle_fuel_summary_empty():
    """get_vehicle_fuel_summary returns zero totals when no logs exist."""
    from app.services import corporate_fleet_fuel_service as svc

    mock_db = AsyncMock()
    vehicle_result = MagicMock()
    vehicle_result.scalar_one_or_none.return_value = MagicMock()
    logs_result = MagicMock()
    logs_result.scalars.return_value.all.return_value = []
    mock_db.execute.side_effect = [vehicle_result, logs_result]

    summary = await svc.get_vehicle_fuel_summary(mock_db, ACCOUNT_ID, VEHICLE_ID)
    assert summary.log_count == 0
    assert summary.total_cost_usd == 0.0
    assert summary.total_gallons == 0.0
    assert summary.avg_mpg is None


@pytest.mark.asyncio
async def test_vehicle_fuel_summary_totals():
    """get_vehicle_fuel_summary sums cost and gallons correctly."""
    from app.services import corporate_fleet_fuel_service as svc

    mock_db = AsyncMock()
    vehicle_result = MagicMock()
    vehicle_result.scalar_one_or_none.return_value = MagicMock()

    def _make_log(total_cost, gallons, kwh=None, odo=None):
        r = MagicMock()
        r.total_cost_usd = total_cost
        r.gallons_added = gallons
        r.kwh_added = kwh
        r.odometer_miles = odo
        r.fill_date = TODAY
        return r

    logs_result = MagicMock()
    logs_result.scalars.return_value.all.return_value = [
        _make_log(43.75, 12.5, odo=10000),
        _make_log(50.00, 14.0, odo=10400),
    ]
    mock_db.execute.side_effect = [vehicle_result, logs_result]

    summary = await svc.get_vehicle_fuel_summary(mock_db, ACCOUNT_ID, VEHICLE_ID)
    assert summary.log_count == 2
    assert abs(summary.total_cost_usd - 93.75) < 0.01
    assert abs(summary.total_gallons - 26.5) < 0.001


@pytest.mark.asyncio
async def test_vehicle_fuel_summary_avg_mpg():
    """get_vehicle_fuel_summary computes avg_mpg from odometer readings."""
    from app.services import corporate_fleet_fuel_service as svc

    mock_db = AsyncMock()
    vehicle_result = MagicMock()
    vehicle_result.scalar_one_or_none.return_value = MagicMock()

    def _make_log(gallons, odo):
        r = MagicMock()
        r.total_cost_usd = 40.0
        r.gallons_added = gallons
        r.kwh_added = None
        r.odometer_miles = odo
        r.fill_date = TODAY
        return r

    logs_result = MagicMock()
    # 400 miles driven on 20 gallons → 20.0 MPG
    logs_result.scalars.return_value.all.return_value = [
        _make_log(10.0, 10000),
        _make_log(10.0, 10400),
    ]
    mock_db.execute.side_effect = [vehicle_result, logs_result]

    summary = await svc.get_vehicle_fuel_summary(mock_db, ACCOUNT_ID, VEHICLE_ID)
    assert summary.total_miles_tracked == 400
    assert abs(summary.avg_mpg - 20.0) < 0.01


@pytest.mark.asyncio
async def test_vehicle_fuel_summary_no_mpg_without_odometer():
    """get_vehicle_fuel_summary avg_mpg is None when no odometer readings."""
    from app.services import corporate_fleet_fuel_service as svc

    mock_db = AsyncMock()
    vehicle_result = MagicMock()
    vehicle_result.scalar_one_or_none.return_value = MagicMock()

    r = MagicMock()
    r.total_cost_usd = 43.75
    r.gallons_added = 12.5
    r.kwh_added = None
    r.odometer_miles = None
    r.fill_date = TODAY

    logs_result = MagicMock()
    logs_result.scalars.return_value.all.return_value = [r]
    mock_db.execute.side_effect = [vehicle_result, logs_result]

    summary = await svc.get_vehicle_fuel_summary(mock_db, ACCOUNT_ID, VEHICLE_ID)
    assert summary.avg_mpg is None
    assert summary.total_miles_tracked is None


@pytest.mark.asyncio
async def test_vehicle_fuel_summary_cost_per_mile():
    """get_vehicle_fuel_summary computes cost_per_mile_usd correctly."""
    from app.services import corporate_fleet_fuel_service as svc

    mock_db = AsyncMock()
    vehicle_result = MagicMock()
    vehicle_result.scalar_one_or_none.return_value = MagicMock()

    def _make_log(cost, gallons, odo):
        r = MagicMock()
        r.total_cost_usd = cost
        r.gallons_added = gallons
        r.kwh_added = None
        r.odometer_miles = odo
        r.fill_date = TODAY
        return r

    logs_result = MagicMock()
    # $100 total, 100 miles → $1.00 per mile
    logs_result.scalars.return_value.all.return_value = [
        _make_log(50.0, 14.0, 10000),
        _make_log(50.0, 14.0, 10100),
    ]
    mock_db.execute.side_effect = [vehicle_result, logs_result]

    summary = await svc.get_vehicle_fuel_summary(mock_db, ACCOUNT_ID, VEHICLE_ID)
    assert summary.cost_per_mile_usd is not None
    assert abs(summary.cost_per_mile_usd - 1.0) < 0.01


@pytest.mark.asyncio
async def test_vehicle_fuel_summary_404_vehicle():
    """get_vehicle_fuel_summary raises 404 when vehicle not in account."""
    from app.services import corporate_fleet_fuel_service as svc

    mock_db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    mock_db.execute.return_value = result

    with pytest.raises(HTTPException) as exc_info:
        await svc.get_vehicle_fuel_summary(mock_db, ACCOUNT_ID, VEHICLE_ID)
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Service layer — list_account_fuel_logs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_account_fuel_logs_all():
    """list_account_fuel_logs returns all logs for the account."""
    from app.services import corporate_fleet_fuel_service as svc

    mock_db = AsyncMock()
    mock_log = MagicMock()
    mock_log.id = LOG_ID
    mock_log.fleet_vehicle_id = VEHICLE_ID
    mock_log.account_id = ACCOUNT_ID
    mock_log.fuel_type = FleetFuelType.gasoline
    mock_log.fill_date = TODAY
    mock_log.odometer_miles = None
    mock_log.gallons_added = 10.0
    mock_log.kwh_added = None
    mock_log.cost_per_unit_usd = None
    mock_log.total_cost_usd = 40.0
    mock_log.station_name = None
    mock_log.notes = None
    mock_log.logged_by_id = None
    mock_log.created_at = NOW
    mock_log.updated_at = NOW

    logs_result = MagicMock()
    logs_result.scalars.return_value.all.return_value = [mock_log]
    mock_db.execute.return_value = logs_result

    result = await svc.list_account_fuel_logs(mock_db, ACCOUNT_ID)
    assert len(result) == 1


@pytest.mark.asyncio
async def test_list_account_fuel_logs_vehicle_filter():
    """list_account_fuel_logs vehicle_id filter is applied."""
    from app.services import corporate_fleet_fuel_service as svc

    mock_db = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = []
    mock_db.execute.return_value = result_mock

    result = await svc.list_account_fuel_logs(
        mock_db, ACCOUNT_ID, fleet_vehicle_id=VEHICLE_ID
    )
    assert result == []


@pytest.mark.asyncio
async def test_list_account_fuel_logs_fuel_type_filter():
    """list_account_fuel_logs fuel_type filter is applied."""
    from app.services import corporate_fleet_fuel_service as svc

    mock_db = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = []
    mock_db.execute.return_value = result_mock

    result = await svc.list_account_fuel_logs(
        mock_db, ACCOUNT_ID, fuel_type=FleetFuelType.electric
    )
    assert result == []


# ---------------------------------------------------------------------------
# Service layer — get_fleet_fuel_summary
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fleet_fuel_summary_empty():
    """get_fleet_fuel_summary returns zero totals when no logs exist."""
    from app.services import corporate_fleet_fuel_service as svc

    mock_db = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = []
    mock_db.execute.return_value = result_mock

    summary = await svc.get_fleet_fuel_summary(mock_db, ACCOUNT_ID)
    assert summary.total_logs == 0
    assert summary.total_cost_usd == 0.0
    assert summary.vehicle_count == 0


@pytest.mark.asyncio
async def test_fleet_fuel_summary_aggregates():
    """get_fleet_fuel_summary aggregates totals across vehicles."""
    from app.services import corporate_fleet_fuel_service as svc

    mock_db = AsyncMock()

    v2 = uuid.uuid4()

    def _make_log(vid, cost, gallons, ft=FleetFuelType.gasoline):
        r = MagicMock()
        r.fleet_vehicle_id = vid
        r.total_cost_usd = cost
        r.gallons_added = gallons
        r.kwh_added = None
        r.fuel_type = ft
        return r

    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = [
        _make_log(VEHICLE_ID, 43.75, 12.5),
        _make_log(v2, 50.00, 14.0),
    ]
    mock_db.execute.return_value = result_mock

    summary = await svc.get_fleet_fuel_summary(mock_db, ACCOUNT_ID)
    assert summary.total_logs == 2
    assert abs(summary.total_cost_usd - 93.75) < 0.01
    assert summary.vehicle_count == 2


@pytest.mark.asyncio
async def test_fleet_fuel_summary_by_fuel_type():
    """get_fleet_fuel_summary by_fuel_type breakdown is correct."""
    from app.services import corporate_fleet_fuel_service as svc

    mock_db = AsyncMock()

    def _make_log(ft, cost, gallons, kwh=None):
        r = MagicMock()
        r.fleet_vehicle_id = VEHICLE_ID
        r.total_cost_usd = cost
        r.gallons_added = gallons
        r.kwh_added = kwh
        r.fuel_type = ft
        return r

    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = [
        _make_log(FleetFuelType.gasoline, 43.75, 12.5),
        _make_log(FleetFuelType.electric, 15.00, None, kwh=50.0),
    ]
    mock_db.execute.return_value = result_mock

    summary = await svc.get_fleet_fuel_summary(mock_db, ACCOUNT_ID)
    by_type = {b.fuel_type: b for b in summary.by_fuel_type}
    assert by_type["gasoline"].log_count == 1
    assert by_type["electric"].total_kwh == 50.0


# ---------------------------------------------------------------------------
# Service layer — list_all_platform
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_all_platform_returns_all():
    """list_all_platform returns logs across all accounts."""
    from app.services import corporate_fleet_fuel_service as svc

    mock_db = AsyncMock()
    mock_log = MagicMock()
    mock_log.id = LOG_ID
    mock_log.fleet_vehicle_id = VEHICLE_ID
    mock_log.account_id = ACCOUNT_ID
    mock_log.fuel_type = FleetFuelType.gasoline
    mock_log.fill_date = TODAY
    mock_log.odometer_miles = None
    mock_log.gallons_added = 10.0
    mock_log.kwh_added = None
    mock_log.cost_per_unit_usd = None
    mock_log.total_cost_usd = 40.0
    mock_log.station_name = None
    mock_log.notes = None
    mock_log.logged_by_id = None
    mock_log.created_at = NOW
    mock_log.updated_at = NOW

    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = [mock_log]
    mock_db.execute.return_value = result_mock

    result = await svc.list_all_platform(mock_db)
    assert len(result) == 1


@pytest.mark.asyncio
async def test_list_all_platform_account_filter():
    """list_all_platform account_id filter is applied."""
    from app.services import corporate_fleet_fuel_service as svc

    mock_db = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = []
    mock_db.execute.return_value = result_mock

    result = await svc.list_all_platform(mock_db, account_id=999)
    assert result == []


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------


def test_fuel_log_create_valid():
    """FuelLogCreate accepts a valid payload."""
    data = FuelLogCreate(
        fleet_vehicle_id=VEHICLE_ID,
        fuel_type=FleetFuelType.gasoline,
        fill_date=TODAY,
        odometer_miles=12000,
        gallons_added=12.5,
        total_cost_usd=43.75,
    )
    assert data.fuel_type == FleetFuelType.gasoline
    assert data.odometer_miles == 12000


def test_fuel_log_create_negative_odometer_rejected():
    """FuelLogCreate rejects negative odometer_miles."""
    with pytest.raises(ValidationError):
        FuelLogCreate(
            fleet_vehicle_id=VEHICLE_ID,
            fuel_type=FleetFuelType.gasoline,
            fill_date=TODAY,
            odometer_miles=-1,
        )


def test_fuel_log_create_negative_gallons_rejected():
    """FuelLogCreate rejects negative gallons_added."""
    with pytest.raises(ValidationError):
        FuelLogCreate(
            fleet_vehicle_id=VEHICLE_ID,
            fuel_type=FleetFuelType.gasoline,
            fill_date=TODAY,
            gallons_added=-5.0,
        )


def test_fuel_log_update_all_optional():
    """FuelLogUpdate can be constructed with no fields."""
    update = FuelLogUpdate()
    assert update.fuel_type is None
    assert update.total_cost_usd is None


def test_fuel_log_response_construction():
    """FuelLogResponse can be constructed directly."""
    resp = _mock_log()
    assert resp.fuel_type == "gasoline"
    assert resp.account_id == ACCOUNT_ID


def test_vehicle_fuel_summary_valid():
    """VehicleFuelSummary can be constructed with all fields."""
    summary = _mock_vehicle_summary()
    assert summary.log_count == 3
    assert summary.avg_mpg == 40.0


def test_fleet_fuel_summary_valid():
    """FleetFuelSummary can be constructed with by_fuel_type list."""
    summary = _mock_fleet_summary()
    assert summary.total_logs == 5
    assert len(summary.by_fuel_type) == 1
    assert summary.by_fuel_type[0].fuel_type == "gasoline"


# ---------------------------------------------------------------------------
# API layer
# ---------------------------------------------------------------------------

_ROUTER = "app.api.v1.corporate_fleet_fuel"
ADMIN_ID = 99

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


def _patch_admin():
    return patch(f"{_ROUTER}._require_account_admin", new_callable=AsyncMock)


def test_api_log_fuel_fill_201():
    """POST /corporate/{account_id}/fleet-fuel/ → 201."""
    with (
        _patch_get_account(),
        patch(f"{_ROUTER}.log_fuel_fill", new_callable=AsyncMock, return_value=_mock_log()),
    ):
        app.dependency_overrides.update(_dep_overrides())
        resp = client.post(
            f"/api/v1/corporate/{ACCOUNT_ID}/fleet-fuel/",
            json={
                "fleet_vehicle_id": str(VEHICLE_ID),
                "fuel_type": "gasoline",
                "fill_date": str(TODAY),
                "odometer_miles": 12000,
                "gallons_added": 12.5,
                "total_cost_usd": 43.75,
            },
        )
        app.dependency_overrides.clear()
    assert resp.status_code == 201


def test_api_list_vehicle_fuel_logs_200():
    """GET /corporate/{account_id}/fleet-vehicles/{vehicle_id}/fuel → 200."""
    with (
        _patch_get_account(),
        patch(f"{_ROUTER}.list_vehicle_fuel_logs", new_callable=AsyncMock, return_value=[_mock_log()]),
    ):
        app.dependency_overrides.update(_dep_overrides())
        resp = client.get(
            f"/api/v1/corporate/{ACCOUNT_ID}/fleet-vehicles/{VEHICLE_ID}/fuel"
        )
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_api_vehicle_fuel_summary_200():
    """GET /corporate/{account_id}/fleet-vehicles/{vehicle_id}/fuel/summary → 200."""
    with (
        _patch_get_account(),
        patch(f"{_ROUTER}.get_vehicle_fuel_summary", new_callable=AsyncMock, return_value=_mock_vehicle_summary()),
    ):
        app.dependency_overrides.update(_dep_overrides())
        resp = client.get(
            f"/api/v1/corporate/{ACCOUNT_ID}/fleet-vehicles/{VEHICLE_ID}/fuel/summary"
        )
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json()["log_count"] == 3


def test_api_get_fuel_log_200():
    """GET /corporate/{account_id}/fleet-fuel/{log_id} → 200."""
    with (
        _patch_get_account(),
        patch(f"{_ROUTER}.get_fuel_log", new_callable=AsyncMock, return_value=_mock_log()),
    ):
        app.dependency_overrides.update(_dep_overrides())
        resp = client.get(f"/api/v1/corporate/{ACCOUNT_ID}/fleet-fuel/{LOG_ID}")
        app.dependency_overrides.clear()
    assert resp.status_code == 200


def test_api_update_fuel_log_200():
    """PUT /corporate/{account_id}/fleet-fuel/{log_id} → 200."""
    with (
        _patch_get_account(),
        _patch_admin(),
        patch(f"{_ROUTER}.update_fuel_log", new_callable=AsyncMock, return_value=_mock_log()),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        resp = client.put(
            f"/api/v1/corporate/{ACCOUNT_ID}/fleet-fuel/{LOG_ID}",
            json={"station_name": "New Station"},
        )
        app.dependency_overrides.clear()
    assert resp.status_code == 200


def test_api_delete_fuel_log_204():
    """DELETE /corporate/{account_id}/fleet-fuel/{log_id} → 204."""
    with (
        _patch_get_account(),
        _patch_admin(),
        patch(f"{_ROUTER}.delete_fuel_log", new_callable=AsyncMock, return_value=None),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        resp = client.delete(f"/api/v1/corporate/{ACCOUNT_ID}/fleet-fuel/{LOG_ID}")
        app.dependency_overrides.clear()
    assert resp.status_code == 204


def test_api_list_account_fuel_logs_200():
    """GET /corporate/{account_id}/fleet-fuel/ → 200."""
    with (
        _patch_get_account(),
        _patch_admin(),
        patch(f"{_ROUTER}.list_account_fuel_logs", new_callable=AsyncMock, return_value=[_mock_log()]),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        resp = client.get(f"/api/v1/corporate/{ACCOUNT_ID}/fleet-fuel/")
        app.dependency_overrides.clear()
    assert resp.status_code == 200


def test_api_fleet_fuel_summary_200():
    """GET /corporate/{account_id}/fleet-fuel/fleet-summary → 200."""
    with (
        _patch_get_account(),
        _patch_admin(),
        patch(f"{_ROUTER}.get_fleet_fuel_summary", new_callable=AsyncMock, return_value=_mock_fleet_summary()),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        resp = client.get(f"/api/v1/corporate/{ACCOUNT_ID}/fleet-fuel/fleet-summary")
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json()["total_logs"] == 5


def test_api_platform_list_200():
    """GET /platform/corporate/fleet-fuel/ → 200."""
    with patch(f"{_ROUTER}.list_all_platform", new_callable=AsyncMock, return_value=[_mock_log()]):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        resp = client.get("/api/v1/platform/corporate/fleet-fuel/")
        app.dependency_overrides.clear()
    assert resp.status_code == 200
