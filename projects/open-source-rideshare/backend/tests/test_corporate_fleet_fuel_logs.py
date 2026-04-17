"""Tests for the Corporate Fleet Fuel Log feature.

Service layer (async, mocked DB):
   1.  create_fuel_log — success (member)
   2.  create_fuel_log — 403 when not a member
   3.  create_fuel_log — 404 when vehicle not found
   4.  update_fuel_log — success by owner
   5.  update_fuel_log — success by admin (not owner)
   6.  update_fuel_log — 403 when different member (not admin, not owner)
   7.  update_fuel_log — 404 when log not found
   8.  delete_fuel_log — success by owner
   9.  delete_fuel_log — success by admin
  10.  delete_fuel_log — 403 when different member
  11.  delete_fuel_log — 404 when log not found
  12.  list_fuel_logs_for_vehicle — success returns list
  13.  list_fuel_logs_for_vehicle — 403 when not a member
  14.  list_fuel_logs_for_vehicle — 404 when vehicle not found
  15.  list_fuel_logs_for_vehicle — pagination (skip/limit)
  16.  list_fuel_logs_for_account — admin success
  17.  list_fuel_logs_for_account — 403 when not admin
  18.  list_fuel_logs_for_account — pagination
  19.  get_vehicle_fuel_summary — success with data
  20.  get_vehicle_fuel_summary — vehicle with no logs returns zeroes
  21.  get_vehicle_fuel_summary — 403 when not a member
  22.  get_vehicle_fuel_summary — 404 when vehicle not found

Schema validation:
  23.  FuelLogCreate — valid construction
  24.  FuelLogCreate — fuel_type enum validation
  25.  FuelLogUpdate — partial update (all None)
  26.  FuelLogResponse — valid construction from_attributes
  27.  VehicleFuelSummaryAnalytics — valid construction
  28.  VehicleFuelSummaryAnalytics — optional fields can be None

API layer (service functions patched):
  29.  POST vehicles/{vehicle_id}/fuel-logs → 201
  30.  POST vehicles/{vehicle_id}/fuel-logs → 401 without auth
  31.  GET  vehicles/{vehicle_id}/fuel-logs → 200
  32.  GET  vehicles/{vehicle_id}/fuel-logs/summary → 200
  33.  PUT  fuel-logs/{log_id} → 200
  34.  DELETE fuel-logs/{log_id} → 204
  35.  GET  accounts/{account_id}/fuel-logs → 200 (admin)
  36.  GET  accounts/{account_id}/fuel-logs → 403 when not admin (service raises)
  37.  GET  vehicles/{vehicle_id}/fuel-logs pagination params → 200

Additional edge cases:
  38.  create_fuel_log — EV log (kwh_added set, gallons_added None)
  39.  get_vehicle_fuel_summary — avg_cost_per_gallon is None when no gallon logs
  40.  get_vehicle_fuel_summary — avg_cost_per_kwh is None when no EV logs
  41.  update_fuel_log — owner with logged_by_id None falls through to admin check
  42.  FuelLogCreate — negative odometer raises validation error
  43.  list_fuel_logs_for_account — returns empty list when no logs
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.corporate_fleet_fuel_log import (
    FuelLogCreate,
    FuelLogResponse,
    FuelLogUpdate,
    VehicleFuelSummaryAnalytics,
)
from app.models.corporate_fleet_fuel_log import FleetFuelType

# ---------------------------------------------------------------------------
# Shared test fixtures
# ---------------------------------------------------------------------------

ACCOUNT_ID = 10
VEHICLE_ID = uuid.uuid4()
LOG_ID = uuid.uuid4()
USER_ID = 99
ADMIN_USER_ID = 77
OTHER_USER_ID = 55
NOW = datetime.now(tz=timezone.utc)
TODAY = date.today()

_SVC = "app.services.corporate_fleet_fuel_log_service"
_ROUTER = "app.api.v1.corporate_fleet_fuel_logs"


def _make_log_response(
    log_id: uuid.UUID = LOG_ID,
    vehicle_id: uuid.UUID = VEHICLE_ID,
    account_id: int = ACCOUNT_ID,
    fuel_type: str = "gasoline",
    logged_by_id: int | None = USER_ID,
) -> FuelLogResponse:
    return FuelLogResponse(
        id=log_id,
        fleet_vehicle_id=vehicle_id,
        account_id=account_id,
        fuel_type=fuel_type,
        fill_date=TODAY,
        odometer_miles=50000,
        gallons_added=12.5,
        kwh_added=None,
        cost_per_unit_usd=3.50,
        total_cost_usd=43.75,
        station_name="Shell Station",
        notes=None,
        logged_by_id=logged_by_id,
        created_at=NOW,
        updated_at=NOW,
    )


def _make_summary_response(
    vehicle_id: uuid.UUID = VEHICLE_ID,
) -> VehicleFuelSummaryAnalytics:
    return VehicleFuelSummaryAnalytics(
        fleet_vehicle_id=vehicle_id,
        total_fill_ups=5,
        total_gallons=Decimal("62.5"),
        total_kwh=Decimal("0"),
        total_cost_usd=Decimal("218.75"),
        avg_cost_per_gallon_usd=Decimal("3.50"),
        avg_cost_per_kwh_usd=None,
        last_fill_date=TODAY,
    )


def _mock_member(role="member"):
    m = MagicMock()
    m.role = role
    m.is_active = True
    return m


def _db_member_found() -> AsyncMock:
    """DB mock where member lookup returns a member."""
    mock_db = AsyncMock()
    member_result = MagicMock()
    member_result.scalar_one_or_none.return_value = _mock_member()
    return mock_db, member_result


def _db_not_member() -> AsyncMock:
    mock_db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    mock_db.execute.return_value = result
    return mock_db


def _db_not_admin() -> AsyncMock:
    mock_db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    mock_db.execute.return_value = result
    return mock_db


# ---------------------------------------------------------------------------
# Service layer — create_fuel_log
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_fuel_log_success():
    """create_fuel_log creates a log when actor is a member."""
    from app.services import corporate_fleet_fuel_log_service as svc

    mock_db = AsyncMock()

    member = _mock_member()
    member_result = MagicMock()
    member_result.scalar_one_or_none.return_value = member

    vehicle = MagicMock()
    vehicle_result = MagicMock()
    vehicle_result.scalar_one_or_none.return_value = vehicle

    mock_db.execute.side_effect = [member_result, vehicle_result]
    mock_db.commit = AsyncMock()
    mock_db.refresh = AsyncMock()

    data = FuelLogCreate(
        fleet_vehicle_id=VEHICLE_ID,
        fuel_type=FleetFuelType.gasoline,
        fill_date=TODAY,
        gallons_added=10.0,
        total_cost_usd=35.0,
    )

    with patch.object(svc, "CorporateFleetFuelLog") as mock_model:
        mock_log = MagicMock()
        mock_log.id = LOG_ID
        mock_log.fleet_vehicle_id = VEHICLE_ID
        mock_log.account_id = ACCOUNT_ID
        mock_log.fuel_type = "gasoline"
        mock_log.fill_date = TODAY
        mock_log.odometer_miles = None
        mock_log.gallons_added = 10.0
        mock_log.kwh_added = None
        mock_log.cost_per_unit_usd = None
        mock_log.total_cost_usd = 35.0
        mock_log.station_name = None
        mock_log.notes = None
        mock_log.logged_by_id = USER_ID
        mock_log.created_at = NOW
        mock_log.updated_at = NOW
        mock_model.return_value = mock_log

        with patch.object(svc, "_to_response", return_value=_make_log_response()):
            result = await svc.create_fuel_log(mock_db, ACCOUNT_ID, VEHICLE_ID, data, USER_ID)

    assert result.account_id == ACCOUNT_ID
    assert result.fleet_vehicle_id == VEHICLE_ID
    mock_db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_create_fuel_log_403_not_member():
    """create_fuel_log raises 403 when actor is not a member."""
    from app.services import corporate_fleet_fuel_log_service as svc

    mock_db = _db_not_member()

    data = FuelLogCreate(
        fleet_vehicle_id=VEHICLE_ID,
        fuel_type=FleetFuelType.gasoline,
        fill_date=TODAY,
    )

    with pytest.raises(HTTPException) as exc_info:
        await svc.create_fuel_log(mock_db, ACCOUNT_ID, VEHICLE_ID, data, USER_ID)
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_create_fuel_log_404_vehicle_not_found():
    """create_fuel_log raises 404 when vehicle not found in this account."""
    from app.services import corporate_fleet_fuel_log_service as svc

    mock_db = AsyncMock()

    member = _mock_member()
    member_result = MagicMock()
    member_result.scalar_one_or_none.return_value = member

    vehicle_result = MagicMock()
    vehicle_result.scalar_one_or_none.return_value = None

    mock_db.execute.side_effect = [member_result, vehicle_result]

    data = FuelLogCreate(
        fleet_vehicle_id=VEHICLE_ID,
        fuel_type=FleetFuelType.gasoline,
        fill_date=TODAY,
    )

    with pytest.raises(HTTPException) as exc_info:
        await svc.create_fuel_log(mock_db, ACCOUNT_ID, VEHICLE_ID, data, USER_ID)
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Service layer — update_fuel_log
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_fuel_log_success_by_owner():
    """update_fuel_log succeeds when actor is the log owner."""
    from app.services import corporate_fleet_fuel_log_service as svc

    mock_db = AsyncMock()

    mock_log = MagicMock()
    mock_log.logged_by_id = USER_ID
    mock_log.account_id = ACCOUNT_ID
    log_result = MagicMock()
    log_result.scalar_one_or_none.return_value = mock_log

    mock_db.execute.side_effect = [log_result]
    mock_db.commit = AsyncMock()
    mock_db.refresh = AsyncMock()

    data = FuelLogUpdate(notes="Updated note")

    with patch.object(svc, "_to_response", return_value=_make_log_response()):
        result = await svc.update_fuel_log(mock_db, LOG_ID, data, USER_ID)

    assert result is not None
    mock_db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_update_fuel_log_success_by_admin():
    """update_fuel_log succeeds when actor is an account admin (not owner)."""
    from app.services import corporate_fleet_fuel_log_service as svc

    mock_db = AsyncMock()

    mock_log = MagicMock()
    mock_log.logged_by_id = OTHER_USER_ID  # Different user created the log
    mock_log.account_id = ACCOUNT_ID
    log_result = MagicMock()
    log_result.scalar_one_or_none.return_value = mock_log

    # Admin check passes
    admin_member = MagicMock()
    admin_result = MagicMock()
    admin_result.scalar_one_or_none.return_value = admin_member

    mock_db.execute.side_effect = [log_result, admin_result]
    mock_db.commit = AsyncMock()
    mock_db.refresh = AsyncMock()

    data = FuelLogUpdate(total_cost_usd=50.0)

    with patch.object(svc, "_to_response", return_value=_make_log_response()):
        result = await svc.update_fuel_log(mock_db, LOG_ID, data, ADMIN_USER_ID)

    assert result is not None
    mock_db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_update_fuel_log_403_different_member_not_admin():
    """update_fuel_log raises 403 when actor is a member but not owner or admin."""
    from app.services import corporate_fleet_fuel_log_service as svc

    mock_db = AsyncMock()

    mock_log = MagicMock()
    mock_log.logged_by_id = OTHER_USER_ID
    mock_log.account_id = ACCOUNT_ID
    log_result = MagicMock()
    log_result.scalar_one_or_none.return_value = mock_log

    # Admin check fails (not an admin)
    admin_result = MagicMock()
    admin_result.scalar_one_or_none.return_value = None

    mock_db.execute.side_effect = [log_result, admin_result]

    data = FuelLogUpdate(notes="hack attempt")

    with pytest.raises(HTTPException) as exc_info:
        await svc.update_fuel_log(mock_db, LOG_ID, data, USER_ID)
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_update_fuel_log_404_not_found():
    """update_fuel_log raises 404 when the log does not exist."""
    from app.services import corporate_fleet_fuel_log_service as svc

    mock_db = AsyncMock()
    log_result = MagicMock()
    log_result.scalar_one_or_none.return_value = None
    mock_db.execute.return_value = log_result

    data = FuelLogUpdate(notes="irrelevant")

    with pytest.raises(HTTPException) as exc_info:
        await svc.update_fuel_log(mock_db, LOG_ID, data, USER_ID)
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Service layer — delete_fuel_log
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_fuel_log_success_by_owner():
    """delete_fuel_log succeeds when actor is the log owner."""
    from app.services import corporate_fleet_fuel_log_service as svc

    mock_db = AsyncMock()

    mock_log = MagicMock()
    mock_log.logged_by_id = USER_ID
    mock_log.account_id = ACCOUNT_ID
    log_result = MagicMock()
    log_result.scalar_one_or_none.return_value = mock_log

    mock_db.execute.side_effect = [log_result]
    mock_db.delete = AsyncMock()
    mock_db.commit = AsyncMock()

    await svc.delete_fuel_log(mock_db, LOG_ID, USER_ID)

    mock_db.delete.assert_called_once_with(mock_log)
    mock_db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_delete_fuel_log_success_by_admin():
    """delete_fuel_log succeeds when actor is an account admin."""
    from app.services import corporate_fleet_fuel_log_service as svc

    mock_db = AsyncMock()

    mock_log = MagicMock()
    mock_log.logged_by_id = OTHER_USER_ID
    mock_log.account_id = ACCOUNT_ID
    log_result = MagicMock()
    log_result.scalar_one_or_none.return_value = mock_log

    admin_member = MagicMock()
    admin_result = MagicMock()
    admin_result.scalar_one_or_none.return_value = admin_member

    mock_db.execute.side_effect = [log_result, admin_result]
    mock_db.delete = AsyncMock()
    mock_db.commit = AsyncMock()

    await svc.delete_fuel_log(mock_db, LOG_ID, ADMIN_USER_ID)

    mock_db.delete.assert_called_once_with(mock_log)
    mock_db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_delete_fuel_log_403_different_member():
    """delete_fuel_log raises 403 when actor is not owner and not admin."""
    from app.services import corporate_fleet_fuel_log_service as svc

    mock_db = AsyncMock()

    mock_log = MagicMock()
    mock_log.logged_by_id = OTHER_USER_ID
    mock_log.account_id = ACCOUNT_ID
    log_result = MagicMock()
    log_result.scalar_one_or_none.return_value = mock_log

    admin_result = MagicMock()
    admin_result.scalar_one_or_none.return_value = None

    mock_db.execute.side_effect = [log_result, admin_result]

    with pytest.raises(HTTPException) as exc_info:
        await svc.delete_fuel_log(mock_db, LOG_ID, USER_ID)
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_delete_fuel_log_404_not_found():
    """delete_fuel_log raises 404 when the log does not exist."""
    from app.services import corporate_fleet_fuel_log_service as svc

    mock_db = AsyncMock()
    log_result = MagicMock()
    log_result.scalar_one_or_none.return_value = None
    mock_db.execute.return_value = log_result

    with pytest.raises(HTTPException) as exc_info:
        await svc.delete_fuel_log(mock_db, LOG_ID, USER_ID)
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Service layer — list_fuel_logs_for_vehicle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_fuel_logs_for_vehicle_success():
    """list_fuel_logs_for_vehicle returns list of logs."""
    from app.services import corporate_fleet_fuel_log_service as svc

    mock_db = AsyncMock()

    member_result = MagicMock()
    member_result.scalar_one_or_none.return_value = _mock_member()

    vehicle = MagicMock()
    vehicle_result = MagicMock()
    vehicle_result.scalar_one_or_none.return_value = vehicle

    mock_log = MagicMock()
    logs_result = MagicMock()
    logs_result.scalars.return_value.all.return_value = [mock_log]

    mock_db.execute.side_effect = [member_result, vehicle_result, logs_result]

    with patch.object(svc, "_to_response", return_value=_make_log_response()):
        result = await svc.list_fuel_logs_for_vehicle(
            mock_db, ACCOUNT_ID, VEHICLE_ID, USER_ID
        )

    assert len(result) == 1


@pytest.mark.asyncio
async def test_list_fuel_logs_for_vehicle_403_not_member():
    """list_fuel_logs_for_vehicle raises 403 when not a member."""
    from app.services import corporate_fleet_fuel_log_service as svc

    mock_db = _db_not_member()

    with pytest.raises(HTTPException) as exc_info:
        await svc.list_fuel_logs_for_vehicle(mock_db, ACCOUNT_ID, VEHICLE_ID, USER_ID)
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_list_fuel_logs_for_vehicle_404_vehicle_not_found():
    """list_fuel_logs_for_vehicle raises 404 when vehicle not found."""
    from app.services import corporate_fleet_fuel_log_service as svc

    mock_db = AsyncMock()

    member_result = MagicMock()
    member_result.scalar_one_or_none.return_value = _mock_member()

    vehicle_result = MagicMock()
    vehicle_result.scalar_one_or_none.return_value = None

    mock_db.execute.side_effect = [member_result, vehicle_result]

    with pytest.raises(HTTPException) as exc_info:
        await svc.list_fuel_logs_for_vehicle(mock_db, ACCOUNT_ID, VEHICLE_ID, USER_ID)
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_list_fuel_logs_for_vehicle_pagination():
    """list_fuel_logs_for_vehicle passes skip/limit without error."""
    from app.services import corporate_fleet_fuel_log_service as svc

    mock_db = AsyncMock()

    member_result = MagicMock()
    member_result.scalar_one_or_none.return_value = _mock_member()

    vehicle = MagicMock()
    vehicle_result = MagicMock()
    vehicle_result.scalar_one_or_none.return_value = vehicle

    logs_result = MagicMock()
    logs_result.scalars.return_value.all.return_value = []

    mock_db.execute.side_effect = [member_result, vehicle_result, logs_result]

    result = await svc.list_fuel_logs_for_vehicle(
        mock_db, ACCOUNT_ID, VEHICLE_ID, USER_ID, skip=10, limit=5
    )
    assert result == []


# ---------------------------------------------------------------------------
# Service layer — list_fuel_logs_for_account
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_fuel_logs_for_account_admin_success():
    """list_fuel_logs_for_account returns logs when actor is an admin."""
    from app.services import corporate_fleet_fuel_log_service as svc

    mock_db = AsyncMock()

    admin_member = MagicMock()
    admin_result = MagicMock()
    admin_result.scalar_one_or_none.return_value = admin_member

    mock_log = MagicMock()
    logs_result = MagicMock()
    logs_result.scalars.return_value.all.return_value = [mock_log, mock_log]

    mock_db.execute.side_effect = [admin_result, logs_result]

    with patch.object(svc, "_to_response", return_value=_make_log_response()):
        result = await svc.list_fuel_logs_for_account(mock_db, ACCOUNT_ID, ADMIN_USER_ID)

    assert len(result) == 2


@pytest.mark.asyncio
async def test_list_fuel_logs_for_account_403_not_admin():
    """list_fuel_logs_for_account raises 403 when actor is not an admin."""
    from app.services import corporate_fleet_fuel_log_service as svc

    mock_db = _db_not_admin()

    with pytest.raises(HTTPException) as exc_info:
        await svc.list_fuel_logs_for_account(mock_db, ACCOUNT_ID, USER_ID)
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_list_fuel_logs_for_account_pagination():
    """list_fuel_logs_for_account respects skip/limit parameters."""
    from app.services import corporate_fleet_fuel_log_service as svc

    mock_db = AsyncMock()

    admin_member = MagicMock()
    admin_result = MagicMock()
    admin_result.scalar_one_or_none.return_value = admin_member

    logs_result = MagicMock()
    logs_result.scalars.return_value.all.return_value = []

    mock_db.execute.side_effect = [admin_result, logs_result]

    result = await svc.list_fuel_logs_for_account(
        mock_db, ACCOUNT_ID, ADMIN_USER_ID, skip=5, limit=10
    )
    assert result == []


# ---------------------------------------------------------------------------
# Service layer — get_vehicle_fuel_summary
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_vehicle_fuel_summary_success():
    """get_vehicle_fuel_summary returns correct analytics with data."""
    from app.services import corporate_fleet_fuel_log_service as svc

    mock_db = AsyncMock()

    member_result = MagicMock()
    member_result.scalar_one_or_none.return_value = _mock_member()

    vehicle = MagicMock()
    vehicle_result = MagicMock()
    vehicle_result.scalar_one_or_none.return_value = vehicle

    # Aggregation result: count, total_cost, last_fill
    agg_row = MagicMock()
    agg_row.total_fill_ups = 5
    agg_row.total_cost_usd = 218.75
    agg_row.last_fill_date = TODAY
    agg_result = MagicMock()
    agg_result.one.return_value = agg_row

    # Gallons sum
    gallons_result = MagicMock()
    gallons_result.scalar_one.return_value = 62.5

    # kWh sum
    kwh_result = MagicMock()
    kwh_result.scalar_one.return_value = 0

    # Avg cost per gallon
    avg_gallon_result = MagicMock()
    avg_gallon_result.scalar_one.return_value = 3.50

    # Avg cost per kWh
    avg_kwh_result = MagicMock()
    avg_kwh_result.scalar_one.return_value = None

    mock_db.execute.side_effect = [
        member_result,
        vehicle_result,
        agg_result,
        gallons_result,
        kwh_result,
        avg_gallon_result,
        avg_kwh_result,
    ]

    result = await svc.get_vehicle_fuel_summary(mock_db, ACCOUNT_ID, VEHICLE_ID, USER_ID)

    assert result.total_fill_ups == 5
    assert result.total_cost_usd == Decimal("218.75")
    assert result.total_gallons == Decimal("62.5")
    assert result.total_kwh == Decimal("0")
    assert result.avg_cost_per_gallon_usd == Decimal("3.5")
    assert result.avg_cost_per_kwh_usd is None
    assert result.last_fill_date == TODAY


@pytest.mark.asyncio
async def test_get_vehicle_fuel_summary_no_logs_returns_zeroes():
    """get_vehicle_fuel_summary returns zeroes when no logs exist."""
    from app.services import corporate_fleet_fuel_log_service as svc

    mock_db = AsyncMock()

    member_result = MagicMock()
    member_result.scalar_one_or_none.return_value = _mock_member()

    vehicle = MagicMock()
    vehicle_result = MagicMock()
    vehicle_result.scalar_one_or_none.return_value = vehicle

    agg_row = MagicMock()
    agg_row.total_fill_ups = 0
    agg_row.total_cost_usd = 0
    agg_row.last_fill_date = None
    agg_result = MagicMock()
    agg_result.one.return_value = agg_row

    zero_result = MagicMock()
    zero_result.scalar_one.return_value = 0

    none_result = MagicMock()
    none_result.scalar_one.return_value = None

    mock_db.execute.side_effect = [
        member_result,
        vehicle_result,
        agg_result,
        zero_result,
        zero_result,
        none_result,
        none_result,
    ]

    result = await svc.get_vehicle_fuel_summary(mock_db, ACCOUNT_ID, VEHICLE_ID, USER_ID)

    assert result.total_fill_ups == 0
    assert result.total_cost_usd == Decimal("0")
    assert result.total_gallons == Decimal("0")
    assert result.total_kwh == Decimal("0")
    assert result.avg_cost_per_gallon_usd is None
    assert result.avg_cost_per_kwh_usd is None
    assert result.last_fill_date is None


@pytest.mark.asyncio
async def test_get_vehicle_fuel_summary_403_not_member():
    """get_vehicle_fuel_summary raises 403 when not a member."""
    from app.services import corporate_fleet_fuel_log_service as svc

    mock_db = _db_not_member()

    with pytest.raises(HTTPException) as exc_info:
        await svc.get_vehicle_fuel_summary(mock_db, ACCOUNT_ID, VEHICLE_ID, USER_ID)
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_get_vehicle_fuel_summary_404_vehicle_not_found():
    """get_vehicle_fuel_summary raises 404 when vehicle not found."""
    from app.services import corporate_fleet_fuel_log_service as svc

    mock_db = AsyncMock()

    member_result = MagicMock()
    member_result.scalar_one_or_none.return_value = _mock_member()

    vehicle_result = MagicMock()
    vehicle_result.scalar_one_or_none.return_value = None

    mock_db.execute.side_effect = [member_result, vehicle_result]

    with pytest.raises(HTTPException) as exc_info:
        await svc.get_vehicle_fuel_summary(mock_db, ACCOUNT_ID, VEHICLE_ID, USER_ID)
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------


def test_fuel_log_create_valid():
    """FuelLogCreate constructs correctly with required fields."""
    obj = FuelLogCreate(
        fleet_vehicle_id=VEHICLE_ID,
        fuel_type=FleetFuelType.gasoline,
        fill_date=TODAY,
        gallons_added=10.5,
        total_cost_usd=36.75,
    )
    assert obj.fuel_type == FleetFuelType.gasoline
    assert obj.gallons_added == 10.5
    assert obj.kwh_added is None


def test_fuel_log_create_fuel_type_validation():
    """FuelLogCreate accepts all FleetFuelType values."""
    for ft in FleetFuelType:
        obj = FuelLogCreate(
            fleet_vehicle_id=VEHICLE_ID,
            fuel_type=ft,
            fill_date=TODAY,
        )
        assert obj.fuel_type == ft


def test_fuel_log_update_all_none():
    """FuelLogUpdate is valid when all fields are None."""
    obj = FuelLogUpdate()
    assert obj.fuel_type is None
    assert obj.fill_date is None
    assert obj.gallons_added is None


def test_fuel_log_response_valid():
    """FuelLogResponse constructs correctly."""
    obj = _make_log_response()
    assert obj.id == LOG_ID
    assert obj.fuel_type == "gasoline"
    assert obj.total_cost_usd == 43.75


def test_vehicle_fuel_summary_analytics_valid():
    """VehicleFuelSummaryAnalytics constructs correctly."""
    obj = _make_summary_response()
    assert obj.total_fill_ups == 5
    assert obj.total_cost_usd == Decimal("218.75")
    assert obj.avg_cost_per_kwh_usd is None


def test_vehicle_fuel_summary_analytics_optional_fields_none():
    """VehicleFuelSummaryAnalytics is valid when optional fields are None."""
    obj = VehicleFuelSummaryAnalytics(
        fleet_vehicle_id=VEHICLE_ID,
        total_fill_ups=0,
        total_gallons=Decimal("0"),
        total_kwh=Decimal("0"),
        total_cost_usd=Decimal("0"),
        avg_cost_per_gallon_usd=None,
        avg_cost_per_kwh_usd=None,
        last_fill_date=None,
    )
    assert obj.avg_cost_per_gallon_usd is None
    assert obj.last_fill_date is None


# ---------------------------------------------------------------------------
# API layer helpers
# ---------------------------------------------------------------------------

BASE = "/api/v1/corporate/fleet"
client = TestClient(app)


def _make_user(user_id: int = USER_ID, is_admin: bool = False):
    from app.models.user import User
    u = MagicMock(spec=User)
    u.id = user_id
    u.is_admin = is_admin
    return u


def _dep_overrides(user_id: int = USER_ID, is_admin: bool = False):
    from app.api.deps import get_current_user, get_db

    async def _user():
        return _make_user(user_id=user_id, is_admin=is_admin)

    async def _db():
        return AsyncMock()

    return {
        get_current_user: _user,
        get_db: _db,
    }


# ---------------------------------------------------------------------------
# API layer — POST create fuel log
# ---------------------------------------------------------------------------


def test_api_post_fuel_log_201():
    """POST /vehicles/{vehicle_id}/fuel-logs returns 201."""
    with patch(f"{_ROUTER}.create_fuel_log", new_callable=AsyncMock) as mock_svc:
        mock_svc.return_value = _make_log_response()
        app.dependency_overrides.update(_dep_overrides())
        resp = client.post(
            f"{BASE}/vehicles/{VEHICLE_ID}/fuel-logs",
            params={"account_id": ACCOUNT_ID},
            json={
                "fleet_vehicle_id": str(VEHICLE_ID),
                "fuel_type": "gasoline",
                "fill_date": str(TODAY),
                "gallons_added": 10.5,
                "total_cost_usd": 36.75,
            },
        )
        app.dependency_overrides.clear()
    assert resp.status_code == 201


def test_api_post_fuel_log_401_no_auth():
    """POST /vehicles/{vehicle_id}/fuel-logs returns 401/403 without auth."""
    resp = client.post(
        f"{BASE}/vehicles/{VEHICLE_ID}/fuel-logs",
        params={"account_id": ACCOUNT_ID},
        json={
            "fleet_vehicle_id": str(VEHICLE_ID),
            "fuel_type": "gasoline",
            "fill_date": str(TODAY),
        },
    )
    assert resp.status_code in (401, 403, 422)


# ---------------------------------------------------------------------------
# API layer — GET list logs for vehicle
# ---------------------------------------------------------------------------


def test_api_get_fuel_logs_for_vehicle_200():
    """GET /vehicles/{vehicle_id}/fuel-logs returns 200."""
    with patch(f"{_ROUTER}.list_fuel_logs_for_vehicle", new_callable=AsyncMock) as mock_svc:
        mock_svc.return_value = [_make_log_response()]
        app.dependency_overrides.update(_dep_overrides())
        resp = client.get(
            f"{BASE}/vehicles/{VEHICLE_ID}/fuel-logs",
            params={"account_id": ACCOUNT_ID},
        )
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 1


# ---------------------------------------------------------------------------
# API layer — GET fuel summary for vehicle
# ---------------------------------------------------------------------------


def test_api_get_fuel_summary_200():
    """GET /vehicles/{vehicle_id}/fuel-logs/summary returns 200."""
    with patch(f"{_ROUTER}.get_vehicle_fuel_summary", new_callable=AsyncMock) as mock_svc:
        mock_svc.return_value = _make_summary_response()
        app.dependency_overrides.update(_dep_overrides())
        resp = client.get(
            f"{BASE}/vehicles/{VEHICLE_ID}/fuel-logs/summary",
            params={"account_id": ACCOUNT_ID},
        )
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_fill_ups"] == 5


# ---------------------------------------------------------------------------
# API layer — PUT update fuel log
# ---------------------------------------------------------------------------


def test_api_put_fuel_log_200():
    """PUT /fuel-logs/{log_id} returns 200."""
    with patch(f"{_ROUTER}.update_fuel_log", new_callable=AsyncMock) as mock_svc:
        mock_svc.return_value = _make_log_response()
        app.dependency_overrides.update(_dep_overrides())
        resp = client.put(
            f"{BASE}/fuel-logs/{LOG_ID}",
            json={"notes": "Updated note"},
        )
        app.dependency_overrides.clear()
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# API layer — DELETE fuel log
# ---------------------------------------------------------------------------


def test_api_delete_fuel_log_204():
    """DELETE /fuel-logs/{log_id} returns 204."""
    with patch(f"{_ROUTER}.delete_fuel_log", new_callable=AsyncMock) as mock_svc:
        mock_svc.return_value = None
        app.dependency_overrides.update(_dep_overrides())
        resp = client.delete(f"{BASE}/fuel-logs/{LOG_ID}")
        app.dependency_overrides.clear()
    assert resp.status_code == 204


# ---------------------------------------------------------------------------
# API layer — GET fleet-wide account fuel logs
# ---------------------------------------------------------------------------


def test_api_get_fuel_logs_for_account_admin_200():
    """GET /accounts/{account_id}/fuel-logs returns 200 for admin."""
    with patch(f"{_ROUTER}.list_fuel_logs_for_account", new_callable=AsyncMock) as mock_svc:
        mock_svc.return_value = [_make_log_response(), _make_log_response()]
        app.dependency_overrides.update(_dep_overrides(is_admin=True))
        resp = client.get(f"{BASE}/accounts/{ACCOUNT_ID}/fuel-logs")
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert len(resp.json()) == 2


def test_api_get_fuel_logs_for_account_403_not_admin():
    """GET /accounts/{account_id}/fuel-logs returns 403 when service raises."""
    with patch(f"{_ROUTER}.list_fuel_logs_for_account", new_callable=AsyncMock) as mock_svc:
        mock_svc.side_effect = HTTPException(status_code=403, detail="Not an admin")
        app.dependency_overrides.update(_dep_overrides())
        resp = client.get(f"{BASE}/accounts/{ACCOUNT_ID}/fuel-logs")
        app.dependency_overrides.clear()
    assert resp.status_code == 403


def test_api_get_fuel_logs_for_vehicle_pagination_200():
    """GET /vehicles/{vehicle_id}/fuel-logs with skip/limit returns 200."""
    with patch(f"{_ROUTER}.list_fuel_logs_for_vehicle", new_callable=AsyncMock) as mock_svc:
        mock_svc.return_value = []
        app.dependency_overrides.update(_dep_overrides())
        resp = client.get(
            f"{BASE}/vehicles/{VEHICLE_ID}/fuel-logs",
            params={"account_id": ACCOUNT_ID, "skip": 10, "limit": 5},
        )
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json() == []


# ---------------------------------------------------------------------------
# Additional edge cases
# ---------------------------------------------------------------------------


def test_fuel_log_create_ev_log():
    """FuelLogCreate supports EV-only log with kwh_added."""
    obj = FuelLogCreate(
        fleet_vehicle_id=VEHICLE_ID,
        fuel_type=FleetFuelType.electric,
        fill_date=TODAY,
        kwh_added=40.0,
        total_cost_usd=12.00,
    )
    assert obj.kwh_added == 40.0
    assert obj.gallons_added is None
    assert obj.fuel_type == FleetFuelType.electric


@pytest.mark.asyncio
async def test_get_vehicle_fuel_summary_no_gallon_logs():
    """get_vehicle_fuel_summary avg_cost_per_gallon is None when no gallon-type logs."""
    from app.services import corporate_fleet_fuel_log_service as svc

    mock_db = AsyncMock()

    member_result = MagicMock()
    member_result.scalar_one_or_none.return_value = _mock_member()

    vehicle = MagicMock()
    vehicle_result = MagicMock()
    vehicle_result.scalar_one_or_none.return_value = vehicle

    agg_row = MagicMock()
    agg_row.total_fill_ups = 2
    agg_row.total_cost_usd = 50.0
    agg_row.last_fill_date = TODAY
    agg_result = MagicMock()
    agg_result.one.return_value = agg_row

    zero_result = MagicMock()
    zero_result.scalar_one.return_value = 0

    kwh_result = MagicMock()
    kwh_result.scalar_one.return_value = 80.0

    none_result = MagicMock()
    none_result.scalar_one.return_value = None

    avg_kwh_result = MagicMock()
    avg_kwh_result.scalar_one.return_value = 0.625

    mock_db.execute.side_effect = [
        member_result,
        vehicle_result,
        agg_result,
        zero_result,  # gallons = 0
        kwh_result,   # kwh = 80.0
        none_result,  # avg_gallon = None
        avg_kwh_result,  # avg_kwh = 0.625
    ]

    result = await svc.get_vehicle_fuel_summary(mock_db, ACCOUNT_ID, VEHICLE_ID, USER_ID)

    assert result.avg_cost_per_gallon_usd is None
    assert result.avg_cost_per_kwh_usd == Decimal("0.625")


@pytest.mark.asyncio
async def test_get_vehicle_fuel_summary_no_ev_logs():
    """get_vehicle_fuel_summary avg_cost_per_kwh is None when no EV logs."""
    from app.services import corporate_fleet_fuel_log_service as svc

    mock_db = AsyncMock()

    member_result = MagicMock()
    member_result.scalar_one_or_none.return_value = _mock_member()

    vehicle = MagicMock()
    vehicle_result = MagicMock()
    vehicle_result.scalar_one_or_none.return_value = vehicle

    agg_row = MagicMock()
    agg_row.total_fill_ups = 3
    agg_row.total_cost_usd = 105.0
    agg_row.last_fill_date = TODAY
    agg_result = MagicMock()
    agg_result.one.return_value = agg_row

    gallons_result = MagicMock()
    gallons_result.scalar_one.return_value = 30.0

    zero_kwh = MagicMock()
    zero_kwh.scalar_one.return_value = 0

    avg_gallon = MagicMock()
    avg_gallon.scalar_one.return_value = 3.50

    none_kwh = MagicMock()
    none_kwh.scalar_one.return_value = None

    mock_db.execute.side_effect = [
        member_result,
        vehicle_result,
        agg_result,
        gallons_result,
        zero_kwh,
        avg_gallon,
        none_kwh,
    ]

    result = await svc.get_vehicle_fuel_summary(mock_db, ACCOUNT_ID, VEHICLE_ID, USER_ID)

    assert result.avg_cost_per_kwh_usd is None
    assert result.avg_cost_per_gallon_usd == Decimal("3.5")


@pytest.mark.asyncio
async def test_update_fuel_log_owner_is_none_falls_to_admin_check():
    """update_fuel_log falls through to admin check when logged_by_id is None."""
    from app.services import corporate_fleet_fuel_log_service as svc

    mock_db = AsyncMock()

    mock_log = MagicMock()
    mock_log.logged_by_id = None  # No owner recorded
    mock_log.account_id = ACCOUNT_ID
    log_result = MagicMock()
    log_result.scalar_one_or_none.return_value = mock_log

    # Admin check also fails → 403
    admin_result = MagicMock()
    admin_result.scalar_one_or_none.return_value = None

    mock_db.execute.side_effect = [log_result, admin_result]

    data = FuelLogUpdate(notes="test")

    with pytest.raises(HTTPException) as exc_info:
        await svc.update_fuel_log(mock_db, LOG_ID, data, USER_ID)
    assert exc_info.value.status_code == 403


def test_fuel_log_create_negative_odometer_raises():
    """FuelLogCreate rejects negative odometer_miles."""
    import pydantic
    with pytest.raises(pydantic.ValidationError):
        FuelLogCreate(
            fleet_vehicle_id=VEHICLE_ID,
            fuel_type=FleetFuelType.gasoline,
            fill_date=TODAY,
            odometer_miles=-100,
        )


@pytest.mark.asyncio
async def test_list_fuel_logs_for_account_empty():
    """list_fuel_logs_for_account returns empty list when no logs exist."""
    from app.services import corporate_fleet_fuel_log_service as svc

    mock_db = AsyncMock()

    admin_member = MagicMock()
    admin_result = MagicMock()
    admin_result.scalar_one_or_none.return_value = admin_member

    logs_result = MagicMock()
    logs_result.scalars.return_value.all.return_value = []

    mock_db.execute.side_effect = [admin_result, logs_result]

    result = await svc.list_fuel_logs_for_account(mock_db, ACCOUNT_ID, ADMIN_USER_ID)
    assert result == []
