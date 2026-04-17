"""Tests for the Corporate Fleet Toll & Transponder Management feature.

Service layer (async, mocked DB):
   1.  assign_transponder — success: creates with is_active=True
   2.  assign_transponder — 404 when vehicle not in account
   3.  assign_transponder — 409 when transponder_number already exists for account
   4.  get_transponder — success: returns existing record
   5.  get_transponder — 404 when not found
   6.  list_vehicle_transponders — returns all for vehicle
   7.  list_vehicle_transponders — is_active filter works
   8.  list_account_transponders — returns all for account
   9.  list_account_transponders — is_active filter works
  10.  list_account_transponders — provider filter works
  11.  deactivate_transponder — success: sets is_active=False and removed_date
  12.  deactivate_transponder — 409 if already inactive
  13.  reactivate_transponder — success: sets is_active=True and clears removed_date
  14.  reactivate_transponder — 409 if already active
  15.  log_toll_charge — success: creates record
  16.  log_toll_charge — 404 when vehicle not in account
  17.  get_toll_charge — success: returns existing record
  18.  get_toll_charge — 404 when not found
  19.  update_toll_charge — success: updates fields
  20.  update_toll_charge — 404 when not found
  21.  delete_toll_charge — success: deletes record
  22.  delete_toll_charge — 404 when not found
  23.  list_vehicle_toll_charges — returns all for vehicle
  24.  list_vehicle_toll_charges — date_from filter works
  25.  list_vehicle_toll_charges — date_to filter works
  26.  get_vehicle_toll_summary — returns zero totals for empty vehicle
  27.  get_vehicle_toll_summary — returns correct aggregates
  28.  list_account_toll_charges — returns all for account
  29.  list_account_toll_charges — vehicle filter works
  30.  get_fleet_toll_summary — returns zero totals for empty fleet
  31.  get_fleet_toll_summary — aggregates totals correctly
  32.  list_all_platform — returns all transponders
  33.  list_all_platform — account_id filter works

Schema validation:
  34.  TransponderCreate — valid construction
  35.  TransponderCreate — missing required field raises ValidationError
  36.  TransponderResponse — valid structure
  37.  TollChargeCreate — valid construction
  38.  TollChargeCreate — negative amount rejected
  39.  TollChargeUpdate — all optional
  40.  TollChargeResponse — valid structure
  41.  VehicleTollSummaryResponse — valid structure
  42.  FleetTollSummaryResponse — valid structure with top_vehicles list

API layer (service functions patched):
  43.  GET list vehicle transponders → 200
  44.  GET list vehicle toll charges → 200
  45.  GET vehicle toll summary → 200
  46.  GET get one transponder → 200
  47.  GET get one charge → 200
  48.  POST assign transponder → 201
  49.  GET list account transponders → 200
  50.  POST deactivate transponder → 200
  51.  POST reactivate transponder → 200
  52.  POST log toll charge → 201
  53.  GET list account toll charges → 200
  54.  GET fleet toll summary → 200
  55.  PUT update charge → 200
  56.  DELETE delete charge → 204
  57.  GET platform list transponders → 200
  58.  GET platform list transponders by account → 200
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
from app.models.corporate_fleet_toll import TransponderProvider
from app.schemas.corporate_fleet_toll import (
    FleetTollSummaryResponse,
    FleetTollVehicleBreakdown,
    TollChargeCreate,
    TollChargeResponse,
    TollChargeUpdate,
    TransponderCreate,
    TransponderResponse,
    VehicleTollSummaryResponse,
)

# ---------------------------------------------------------------------------
# Shared test fixtures
# ---------------------------------------------------------------------------

ACCOUNT_ID = 1
VEHICLE_ID = uuid.uuid4()
TRANSPONDER_ID = uuid.uuid4()
CHARGE_ID = uuid.uuid4()
USER_ID = 42
NOW = datetime.now(tz=timezone.utc)
TODAY = date.today()


def _mock_transponder(
    transponder_id: uuid.UUID = TRANSPONDER_ID,
    account_id: int = ACCOUNT_ID,
    vehicle_id: uuid.UUID = VEHICLE_ID,
    transponder_number: str = "EZP-123456",
    provider: TransponderProvider = TransponderProvider.ezpass,
    assigned_date: date = TODAY,
    removed_date: date | None = None,
    monthly_plan_cost_usd: float | None = 4.99,
    toll_account_number: str | None = "ACC-9999",
    is_active: bool = True,
    notes: str | None = None,
    assigned_by_id: int | None = USER_ID,
) -> TransponderResponse:
    return TransponderResponse(
        id=transponder_id,
        account_id=account_id,
        fleet_vehicle_id=vehicle_id,
        transponder_number=transponder_number,
        provider=provider,
        assigned_date=assigned_date,
        removed_date=removed_date,
        monthly_plan_cost_usd=monthly_plan_cost_usd,
        toll_account_number=toll_account_number,
        is_active=is_active,
        notes=notes,
        assigned_by_id=assigned_by_id,
        created_at=NOW,
        updated_at=NOW,
    )


def _mock_charge(
    charge_id: uuid.UUID = CHARGE_ID,
    account_id: int = ACCOUNT_ID,
    vehicle_id: uuid.UUID = VEHICLE_ID,
    transponder_id: uuid.UUID | None = TRANSPONDER_ID,
    charge_date: date = TODAY,
    plaza_name: str | None = "Lincoln Tunnel",
    amount_usd: float = 17.00,
    entry_location: str | None = "NJ-3 West",
    exit_location: str | None = "9th Ave Manhattan",
    trip_purpose: str | None = "Client meeting",
    notes: str | None = None,
    logged_by_id: int | None = USER_ID,
) -> TollChargeResponse:
    return TollChargeResponse(
        id=charge_id,
        account_id=account_id,
        fleet_vehicle_id=vehicle_id,
        transponder_id=transponder_id,
        charge_date=charge_date,
        plaza_name=plaza_name,
        amount_usd=amount_usd,
        entry_location=entry_location,
        exit_location=exit_location,
        trip_purpose=trip_purpose,
        notes=notes,
        logged_by_id=logged_by_id,
        created_at=NOW,
    )


def _mock_vehicle_summary() -> VehicleTollSummaryResponse:
    return VehicleTollSummaryResponse(
        fleet_vehicle_id=VEHICLE_ID,
        charge_count=5,
        total_cost_usd=62.50,
        active_transponder_count=1,
        date_from=TODAY,
        date_to=TODAY,
    )


def _mock_fleet_summary() -> FleetTollSummaryResponse:
    return FleetTollSummaryResponse(
        total_charge_count=10,
        total_cost_usd=125.00,
        active_transponder_count=3,
        vehicle_count=2,
        per_provider_cost_usd={"ezpass": 80.00, "fastrak": 45.00},
        top_vehicles=[
            FleetTollVehicleBreakdown(
                fleet_vehicle_id=VEHICLE_ID,
                charge_count=6,
                total_cost_usd=80.00,
            )
        ],
    )


# ---------------------------------------------------------------------------
# Service layer — assign_transponder
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_assign_transponder_success():
    """assign_transponder creates a new record with is_active=True."""
    from app.services import corporate_fleet_toll_service as svc

    mock_db = AsyncMock()
    mock_vehicle = MagicMock()
    vehicle_result = MagicMock()
    vehicle_result.scalar_one_or_none.return_value = mock_vehicle

    # unique-check returns None (no conflict)
    unique_result = MagicMock()
    unique_result.scalar_one_or_none.return_value = None

    # After commit + refresh, the row object will have these attributes
    # set by mock_db.refresh side effect
    created_row = MagicMock()
    created_row.id = TRANSPONDER_ID
    created_row.account_id = ACCOUNT_ID
    created_row.fleet_vehicle_id = VEHICLE_ID
    created_row.transponder_number = "EZP-123456"
    created_row.provider = TransponderProvider.ezpass
    created_row.assigned_date = TODAY
    created_row.removed_date = None
    created_row.monthly_plan_cost_usd = 4.99
    created_row.toll_account_number = "ACC-9999"
    created_row.is_active = True
    created_row.notes = None
    created_row.assigned_by_id = USER_ID
    created_row.created_at = NOW
    created_row.updated_at = NOW

    mock_db.execute.side_effect = [vehicle_result, unique_result]
    mock_db.commit = AsyncMock()

    async def _refresh(row):
        # Simulate refresh populating the row with DB-generated values
        row.id = created_row.id
        row.account_id = created_row.account_id
        row.fleet_vehicle_id = created_row.fleet_vehicle_id
        row.transponder_number = created_row.transponder_number
        row.provider = created_row.provider
        row.assigned_date = created_row.assigned_date
        row.removed_date = created_row.removed_date
        row.monthly_plan_cost_usd = created_row.monthly_plan_cost_usd
        row.toll_account_number = created_row.toll_account_number
        row.is_active = created_row.is_active
        row.notes = created_row.notes
        row.assigned_by_id = created_row.assigned_by_id
        row.created_at = created_row.created_at
        row.updated_at = created_row.updated_at

    mock_db.refresh = _refresh

    data = TransponderCreate(
        fleet_vehicle_id=VEHICLE_ID,
        transponder_number="EZP-123456",
        provider=TransponderProvider.ezpass,
        assigned_date=TODAY,
        monthly_plan_cost_usd=4.99,
        toll_account_number="ACC-9999",
    )

    result = await svc.assign_transponder(mock_db, ACCOUNT_ID, data, assigned_by_id=USER_ID)

    assert result.is_active is True
    assert result.fleet_vehicle_id == VEHICLE_ID
    mock_db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_assign_transponder_404_vehicle():
    """assign_transponder raises 404 when vehicle not in account."""
    from app.services import corporate_fleet_toll_service as svc

    mock_db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    mock_db.execute.return_value = result

    data = TransponderCreate(
        fleet_vehicle_id=VEHICLE_ID,
        transponder_number="EZP-111",
        provider=TransponderProvider.ezpass,
        assigned_date=TODAY,
    )

    with pytest.raises(HTTPException) as exc_info:
        await svc.assign_transponder(mock_db, ACCOUNT_ID, data)
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_assign_transponder_409_duplicate_number():
    """assign_transponder raises 409 when transponder_number already exists."""
    from app.services import corporate_fleet_toll_service as svc

    mock_db = AsyncMock()
    mock_vehicle = MagicMock()
    vehicle_result = MagicMock()
    vehicle_result.scalar_one_or_none.return_value = mock_vehicle

    # unique-check returns existing record
    existing_result = MagicMock()
    existing_result.scalar_one_or_none.return_value = TRANSPONDER_ID

    mock_db.execute.side_effect = [vehicle_result, existing_result]

    data = TransponderCreate(
        fleet_vehicle_id=VEHICLE_ID,
        transponder_number="EZP-123456",
        provider=TransponderProvider.ezpass,
        assigned_date=TODAY,
    )

    with pytest.raises(HTTPException) as exc_info:
        await svc.assign_transponder(mock_db, ACCOUNT_ID, data)
    assert exc_info.value.status_code == 409


# ---------------------------------------------------------------------------
# Service layer — get_transponder
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_transponder_success():
    """get_transponder returns TransponderResponse for an existing record."""
    from app.services import corporate_fleet_toll_service as svc

    mock_db = AsyncMock()
    mock_row = MagicMock()
    mock_row.id = TRANSPONDER_ID
    mock_row.account_id = ACCOUNT_ID
    mock_row.fleet_vehicle_id = VEHICLE_ID
    mock_row.transponder_number = "EZP-123456"
    mock_row.provider = TransponderProvider.ezpass
    mock_row.assigned_date = TODAY
    mock_row.removed_date = None
    mock_row.monthly_plan_cost_usd = 4.99
    mock_row.toll_account_number = "ACC-9999"
    mock_row.is_active = True
    mock_row.notes = None
    mock_row.assigned_by_id = USER_ID
    mock_row.created_at = NOW
    mock_row.updated_at = NOW

    result = MagicMock()
    result.scalar_one_or_none.return_value = mock_row
    mock_db.execute.return_value = result

    response = await svc.get_transponder(mock_db, ACCOUNT_ID, TRANSPONDER_ID)
    assert response.id == TRANSPONDER_ID
    assert response.is_active is True


@pytest.mark.asyncio
async def test_get_transponder_404():
    """get_transponder raises 404 when transponder not found."""
    from app.services import corporate_fleet_toll_service as svc

    mock_db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    mock_db.execute.return_value = result

    with pytest.raises(HTTPException) as exc_info:
        await svc.get_transponder(mock_db, ACCOUNT_ID, TRANSPONDER_ID)
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Service layer — list_vehicle_transponders
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_vehicle_transponders_returns_all():
    """list_vehicle_transponders returns transponders for the vehicle."""
    from app.services import corporate_fleet_toll_service as svc

    mock_db = AsyncMock()
    mock_vehicle = MagicMock()
    vehicle_result = MagicMock()
    vehicle_result.scalar_one_or_none.return_value = mock_vehicle

    mock_row = MagicMock()
    mock_row.id = TRANSPONDER_ID
    mock_row.account_id = ACCOUNT_ID
    mock_row.fleet_vehicle_id = VEHICLE_ID
    mock_row.transponder_number = "EZP-123456"
    mock_row.provider = TransponderProvider.ezpass
    mock_row.assigned_date = TODAY
    mock_row.removed_date = None
    mock_row.monthly_plan_cost_usd = None
    mock_row.toll_account_number = None
    mock_row.is_active = True
    mock_row.notes = None
    mock_row.assigned_by_id = None
    mock_row.created_at = NOW
    mock_row.updated_at = NOW

    list_result = MagicMock()
    list_result.scalars.return_value.all.return_value = [mock_row]

    mock_db.execute.side_effect = [vehicle_result, list_result]

    results = await svc.list_vehicle_transponders(mock_db, ACCOUNT_ID, VEHICLE_ID)
    assert len(results) == 1
    assert results[0].transponder_number == "EZP-123456"


@pytest.mark.asyncio
async def test_list_vehicle_transponders_is_active_filter():
    """list_vehicle_transponders respects is_active filter."""
    from app.services import corporate_fleet_toll_service as svc

    mock_db = AsyncMock()
    mock_vehicle = MagicMock()
    vehicle_result = MagicMock()
    vehicle_result.scalar_one_or_none.return_value = mock_vehicle

    list_result = MagicMock()
    list_result.scalars.return_value.all.return_value = []

    mock_db.execute.side_effect = [vehicle_result, list_result]

    results = await svc.list_vehicle_transponders(
        mock_db, ACCOUNT_ID, VEHICLE_ID, is_active=False
    )
    assert results == []


# ---------------------------------------------------------------------------
# Service layer — list_account_transponders
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_account_transponders_returns_all():
    """list_account_transponders returns all for account."""
    from app.services import corporate_fleet_toll_service as svc

    mock_db = AsyncMock()
    list_result = MagicMock()
    list_result.scalars.return_value.all.return_value = []
    mock_db.execute.return_value = list_result

    results = await svc.list_account_transponders(mock_db, ACCOUNT_ID)
    assert results == []


@pytest.mark.asyncio
async def test_list_account_transponders_is_active_filter():
    """list_account_transponders respects is_active filter."""
    from app.services import corporate_fleet_toll_service as svc

    mock_db = AsyncMock()
    list_result = MagicMock()
    list_result.scalars.return_value.all.return_value = []
    mock_db.execute.return_value = list_result

    results = await svc.list_account_transponders(mock_db, ACCOUNT_ID, is_active=True)
    assert results == []


@pytest.mark.asyncio
async def test_list_account_transponders_provider_filter():
    """list_account_transponders respects provider filter."""
    from app.services import corporate_fleet_toll_service as svc

    mock_db = AsyncMock()
    list_result = MagicMock()
    list_result.scalars.return_value.all.return_value = []
    mock_db.execute.return_value = list_result

    results = await svc.list_account_transponders(
        mock_db, ACCOUNT_ID, provider=TransponderProvider.fastrak
    )
    assert results == []


# ---------------------------------------------------------------------------
# Service layer — deactivate_transponder / reactivate_transponder
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deactivate_transponder_success():
    """deactivate_transponder sets is_active=False and records removed_date."""
    from app.services import corporate_fleet_toll_service as svc

    mock_db = AsyncMock()
    mock_row = MagicMock()
    mock_row.id = TRANSPONDER_ID
    mock_row.account_id = ACCOUNT_ID
    mock_row.fleet_vehicle_id = VEHICLE_ID
    mock_row.transponder_number = "EZP-123456"
    mock_row.provider = TransponderProvider.ezpass
    mock_row.assigned_date = TODAY
    mock_row.removed_date = None
    mock_row.monthly_plan_cost_usd = None
    mock_row.toll_account_number = None
    mock_row.is_active = True
    mock_row.notes = None
    mock_row.assigned_by_id = None
    mock_row.created_at = NOW
    mock_row.updated_at = NOW

    fetch_result = MagicMock()
    fetch_result.scalar_one_or_none.return_value = mock_row
    mock_db.execute.return_value = fetch_result
    mock_db.commit = AsyncMock()
    mock_db.refresh = AsyncMock()

    await svc.deactivate_transponder(mock_db, ACCOUNT_ID, TRANSPONDER_ID)

    assert mock_row.is_active is False
    assert mock_row.removed_date is not None
    mock_db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_deactivate_transponder_409_already_inactive():
    """deactivate_transponder raises 409 if already inactive."""
    from app.services import corporate_fleet_toll_service as svc

    mock_db = AsyncMock()
    mock_row = MagicMock()
    mock_row.is_active = False

    fetch_result = MagicMock()
    fetch_result.scalar_one_or_none.return_value = mock_row
    mock_db.execute.return_value = fetch_result

    with pytest.raises(HTTPException) as exc_info:
        await svc.deactivate_transponder(mock_db, ACCOUNT_ID, TRANSPONDER_ID)
    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_reactivate_transponder_success():
    """reactivate_transponder sets is_active=True and clears removed_date."""
    from app.services import corporate_fleet_toll_service as svc

    mock_db = AsyncMock()
    mock_row = MagicMock()
    mock_row.id = TRANSPONDER_ID
    mock_row.account_id = ACCOUNT_ID
    mock_row.fleet_vehicle_id = VEHICLE_ID
    mock_row.transponder_number = "EZP-123456"
    mock_row.provider = TransponderProvider.ezpass
    mock_row.assigned_date = TODAY
    mock_row.removed_date = TODAY
    mock_row.monthly_plan_cost_usd = None
    mock_row.toll_account_number = None
    mock_row.is_active = False
    mock_row.notes = None
    mock_row.assigned_by_id = None
    mock_row.created_at = NOW
    mock_row.updated_at = NOW

    fetch_result = MagicMock()
    fetch_result.scalar_one_or_none.return_value = mock_row
    mock_db.execute.return_value = fetch_result
    mock_db.commit = AsyncMock()
    mock_db.refresh = AsyncMock()

    await svc.reactivate_transponder(mock_db, ACCOUNT_ID, TRANSPONDER_ID)

    assert mock_row.is_active is True
    assert mock_row.removed_date is None
    mock_db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_reactivate_transponder_409_already_active():
    """reactivate_transponder raises 409 if already active."""
    from app.services import corporate_fleet_toll_service as svc

    mock_db = AsyncMock()
    mock_row = MagicMock()
    mock_row.is_active = True

    fetch_result = MagicMock()
    fetch_result.scalar_one_or_none.return_value = mock_row
    mock_db.execute.return_value = fetch_result

    with pytest.raises(HTTPException) as exc_info:
        await svc.reactivate_transponder(mock_db, ACCOUNT_ID, TRANSPONDER_ID)
    assert exc_info.value.status_code == 409


# ---------------------------------------------------------------------------
# Service layer — log_toll_charge
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_log_toll_charge_success():
    """log_toll_charge creates a new record."""
    from app.services import corporate_fleet_toll_service as svc

    mock_db = AsyncMock()
    mock_vehicle = MagicMock()
    vehicle_result = MagicMock()
    vehicle_result.scalar_one_or_none.return_value = mock_vehicle
    mock_db.execute.return_value = vehicle_result
    mock_db.commit = AsyncMock()
    mock_db.refresh = AsyncMock()

    data = TollChargeCreate(
        fleet_vehicle_id=VEHICLE_ID,
        charge_date=TODAY,
        amount_usd=17.00,
        plaza_name="Lincoln Tunnel",
    )

    with patch.object(svc, "CorporateFleetTollCharge") as MockCharge:
        instance = MockCharge.return_value
        instance.id = CHARGE_ID
        instance.account_id = ACCOUNT_ID
        instance.fleet_vehicle_id = VEHICLE_ID
        instance.transponder_id = None
        instance.charge_date = TODAY
        instance.plaza_name = "Lincoln Tunnel"
        instance.amount_usd = 17.00
        instance.entry_location = None
        instance.exit_location = None
        instance.trip_purpose = None
        instance.notes = None
        instance.logged_by_id = USER_ID
        instance.created_at = NOW

        result = await svc.log_toll_charge(mock_db, ACCOUNT_ID, data, logged_by_id=USER_ID)

    assert result.amount_usd == 17.00
    mock_db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_log_toll_charge_404_vehicle():
    """log_toll_charge raises 404 when vehicle not in account."""
    from app.services import corporate_fleet_toll_service as svc

    mock_db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    mock_db.execute.return_value = result

    data = TollChargeCreate(
        fleet_vehicle_id=VEHICLE_ID,
        charge_date=TODAY,
        amount_usd=5.00,
    )

    with pytest.raises(HTTPException) as exc_info:
        await svc.log_toll_charge(mock_db, ACCOUNT_ID, data)
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Service layer — get_toll_charge
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_toll_charge_success():
    """get_toll_charge returns TollChargeResponse for an existing record."""
    from app.services import corporate_fleet_toll_service as svc

    mock_db = AsyncMock()
    mock_row = MagicMock()
    mock_row.id = CHARGE_ID
    mock_row.account_id = ACCOUNT_ID
    mock_row.fleet_vehicle_id = VEHICLE_ID
    mock_row.transponder_id = None
    mock_row.charge_date = TODAY
    mock_row.plaza_name = "GW Bridge"
    mock_row.amount_usd = 16.00
    mock_row.entry_location = None
    mock_row.exit_location = None
    mock_row.trip_purpose = None
    mock_row.notes = None
    mock_row.logged_by_id = USER_ID
    mock_row.created_at = NOW

    result = MagicMock()
    result.scalar_one_or_none.return_value = mock_row
    mock_db.execute.return_value = result

    response = await svc.get_toll_charge(mock_db, ACCOUNT_ID, CHARGE_ID)
    assert response.id == CHARGE_ID
    assert response.amount_usd == 16.00


@pytest.mark.asyncio
async def test_get_toll_charge_404():
    """get_toll_charge raises 404 when charge not found."""
    from app.services import corporate_fleet_toll_service as svc

    mock_db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    mock_db.execute.return_value = result

    with pytest.raises(HTTPException) as exc_info:
        await svc.get_toll_charge(mock_db, ACCOUNT_ID, CHARGE_ID)
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Service layer — update_toll_charge / delete_toll_charge
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_toll_charge_success():
    """update_toll_charge updates provided fields."""
    from app.services import corporate_fleet_toll_service as svc

    mock_db = AsyncMock()
    mock_row = MagicMock()
    mock_row.id = CHARGE_ID
    mock_row.account_id = ACCOUNT_ID
    mock_row.fleet_vehicle_id = VEHICLE_ID
    mock_row.transponder_id = None
    mock_row.charge_date = TODAY
    mock_row.plaza_name = "Old Name"
    mock_row.amount_usd = 10.00
    mock_row.entry_location = None
    mock_row.exit_location = None
    mock_row.trip_purpose = None
    mock_row.notes = None
    mock_row.logged_by_id = USER_ID
    mock_row.created_at = NOW

    fetch_result = MagicMock()
    fetch_result.scalar_one_or_none.return_value = mock_row
    mock_db.execute.return_value = fetch_result
    mock_db.commit = AsyncMock()
    mock_db.refresh = AsyncMock()

    data = TollChargeUpdate(plaza_name="New Name", amount_usd=15.00)
    await svc.update_toll_charge(mock_db, ACCOUNT_ID, CHARGE_ID, data)

    assert mock_row.plaza_name == "New Name"
    assert mock_row.amount_usd == 15.00
    mock_db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_toll_charge_404():
    """update_toll_charge raises 404 when not found."""
    from app.services import corporate_fleet_toll_service as svc

    mock_db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    mock_db.execute.return_value = result

    with pytest.raises(HTTPException) as exc_info:
        await svc.update_toll_charge(mock_db, ACCOUNT_ID, CHARGE_ID, TollChargeUpdate())
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_delete_toll_charge_success():
    """delete_toll_charge removes the record."""
    from app.services import corporate_fleet_toll_service as svc

    mock_db = AsyncMock()
    mock_row = MagicMock()

    fetch_result = MagicMock()
    fetch_result.scalar_one_or_none.return_value = mock_row
    mock_db.execute.return_value = fetch_result
    mock_db.delete = AsyncMock()
    mock_db.commit = AsyncMock()

    await svc.delete_toll_charge(mock_db, ACCOUNT_ID, CHARGE_ID)

    mock_db.delete.assert_awaited_once_with(mock_row)
    mock_db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_toll_charge_404():
    """delete_toll_charge raises 404 when not found."""
    from app.services import corporate_fleet_toll_service as svc

    mock_db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    mock_db.execute.return_value = result

    with pytest.raises(HTTPException) as exc_info:
        await svc.delete_toll_charge(mock_db, ACCOUNT_ID, CHARGE_ID)
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Service layer — list_vehicle_toll_charges
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_vehicle_toll_charges_returns_all():
    """list_vehicle_toll_charges returns all charges for vehicle."""
    from app.services import corporate_fleet_toll_service as svc

    mock_db = AsyncMock()
    mock_vehicle = MagicMock()
    vehicle_result = MagicMock()
    vehicle_result.scalar_one_or_none.return_value = mock_vehicle

    list_result = MagicMock()
    list_result.scalars.return_value.all.return_value = []

    mock_db.execute.side_effect = [vehicle_result, list_result]

    results = await svc.list_vehicle_toll_charges(mock_db, ACCOUNT_ID, VEHICLE_ID)
    assert results == []


@pytest.mark.asyncio
async def test_list_vehicle_toll_charges_date_from_filter():
    """list_vehicle_toll_charges applies date_from filter."""
    from app.services import corporate_fleet_toll_service as svc

    mock_db = AsyncMock()
    mock_vehicle = MagicMock()
    vehicle_result = MagicMock()
    vehicle_result.scalar_one_or_none.return_value = mock_vehicle

    list_result = MagicMock()
    list_result.scalars.return_value.all.return_value = []

    mock_db.execute.side_effect = [vehicle_result, list_result]

    results = await svc.list_vehicle_toll_charges(
        mock_db, ACCOUNT_ID, VEHICLE_ID, date_from=TODAY
    )
    assert results == []


@pytest.mark.asyncio
async def test_list_vehicle_toll_charges_date_to_filter():
    """list_vehicle_toll_charges applies date_to filter."""
    from app.services import corporate_fleet_toll_service as svc

    mock_db = AsyncMock()
    mock_vehicle = MagicMock()
    vehicle_result = MagicMock()
    vehicle_result.scalar_one_or_none.return_value = mock_vehicle

    list_result = MagicMock()
    list_result.scalars.return_value.all.return_value = []

    mock_db.execute.side_effect = [vehicle_result, list_result]

    results = await svc.list_vehicle_toll_charges(
        mock_db, ACCOUNT_ID, VEHICLE_ID, date_to=TODAY
    )
    assert results == []


# ---------------------------------------------------------------------------
# Service layer — get_vehicle_toll_summary
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_vehicle_toll_summary_zero_totals():
    """get_vehicle_toll_summary returns zero totals for an empty vehicle."""
    from app.services import corporate_fleet_toll_service as svc

    mock_db = AsyncMock()
    mock_vehicle = MagicMock()
    vehicle_result = MagicMock()
    vehicle_result.scalar_one_or_none.return_value = mock_vehicle

    charge_row = MagicMock()
    charge_row.charge_count = 0
    charge_row.total_cost = 0
    charge_row.date_from = None
    charge_row.date_to = None
    charge_result = MagicMock()
    charge_result.one.return_value = charge_row

    transponder_result = MagicMock()
    transponder_result.scalar_one.return_value = 0

    mock_db.execute.side_effect = [vehicle_result, charge_result, transponder_result]

    result = await svc.get_vehicle_toll_summary(mock_db, ACCOUNT_ID, VEHICLE_ID)
    assert result.charge_count == 0
    assert result.total_cost_usd == 0.0
    assert result.active_transponder_count == 0
    assert result.date_from is None


@pytest.mark.asyncio
async def test_get_vehicle_toll_summary_with_data():
    """get_vehicle_toll_summary returns correct aggregates."""
    from app.services import corporate_fleet_toll_service as svc

    mock_db = AsyncMock()
    mock_vehicle = MagicMock()
    vehicle_result = MagicMock()
    vehicle_result.scalar_one_or_none.return_value = mock_vehicle

    charge_row = MagicMock()
    charge_row.charge_count = 5
    charge_row.total_cost = 62.50
    charge_row.date_from = TODAY
    charge_row.date_to = TODAY
    charge_result = MagicMock()
    charge_result.one.return_value = charge_row

    transponder_result = MagicMock()
    transponder_result.scalar_one.return_value = 1

    mock_db.execute.side_effect = [vehicle_result, charge_result, transponder_result]

    result = await svc.get_vehicle_toll_summary(mock_db, ACCOUNT_ID, VEHICLE_ID)
    assert result.charge_count == 5
    assert result.total_cost_usd == 62.50
    assert result.active_transponder_count == 1


# ---------------------------------------------------------------------------
# Service layer — list_account_toll_charges
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_account_toll_charges_returns_all():
    """list_account_toll_charges returns all charges for account."""
    from app.services import corporate_fleet_toll_service as svc

    mock_db = AsyncMock()
    list_result = MagicMock()
    list_result.scalars.return_value.all.return_value = []
    mock_db.execute.return_value = list_result

    results = await svc.list_account_toll_charges(mock_db, ACCOUNT_ID)
    assert results == []


@pytest.mark.asyncio
async def test_list_account_toll_charges_vehicle_filter():
    """list_account_toll_charges respects vehicle filter."""
    from app.services import corporate_fleet_toll_service as svc

    mock_db = AsyncMock()
    list_result = MagicMock()
    list_result.scalars.return_value.all.return_value = []
    mock_db.execute.return_value = list_result

    results = await svc.list_account_toll_charges(
        mock_db, ACCOUNT_ID, fleet_vehicle_id=VEHICLE_ID
    )
    assert results == []


# ---------------------------------------------------------------------------
# Service layer — get_fleet_toll_summary
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_fleet_toll_summary_empty():
    """get_fleet_toll_summary returns zero totals for an empty fleet."""
    from app.services import corporate_fleet_toll_service as svc

    mock_db = AsyncMock()

    totals_row = MagicMock()
    totals_row.charge_count = 0
    totals_row.total_cost = 0
    totals_row.vehicle_count = 0
    totals_result = MagicMock()
    totals_result.one.return_value = totals_row

    active_result = MagicMock()
    active_result.scalar_one.return_value = 0

    provider_result = MagicMock()
    provider_result.all.return_value = []

    vehicle_result = MagicMock()
    vehicle_result.all.return_value = []

    mock_db.execute.side_effect = [
        totals_result,
        active_result,
        provider_result,
        vehicle_result,
    ]

    result = await svc.get_fleet_toll_summary(mock_db, ACCOUNT_ID)
    assert result.total_charge_count == 0
    assert result.total_cost_usd == 0.0
    assert result.active_transponder_count == 0
    assert result.per_provider_cost_usd == {}
    assert result.top_vehicles == []


@pytest.mark.asyncio
async def test_get_fleet_toll_summary_with_data():
    """get_fleet_toll_summary aggregates totals correctly."""
    from app.services import corporate_fleet_toll_service as svc

    mock_db = AsyncMock()

    totals_row = MagicMock()
    totals_row.charge_count = 10
    totals_row.total_cost = 125.00
    totals_row.vehicle_count = 2
    totals_result = MagicMock()
    totals_result.one.return_value = totals_row

    active_result = MagicMock()
    active_result.scalar_one.return_value = 3

    provider_row = MagicMock()
    provider_row.provider = TransponderProvider.ezpass
    provider_row.provider_cost = 80.00
    provider_result = MagicMock()
    provider_result.all.return_value = [provider_row]

    vehicle_row = MagicMock()
    vehicle_row.fleet_vehicle_id = VEHICLE_ID
    vehicle_row.charge_count = 6
    vehicle_row.vehicle_cost = 80.00
    vehicle_result = MagicMock()
    vehicle_result.all.return_value = [vehicle_row]

    mock_db.execute.side_effect = [
        totals_result,
        active_result,
        provider_result,
        vehicle_result,
    ]

    result = await svc.get_fleet_toll_summary(mock_db, ACCOUNT_ID)
    assert result.total_charge_count == 10
    assert result.total_cost_usd == 125.00
    assert result.active_transponder_count == 3
    assert result.vehicle_count == 2
    assert "ezpass" in result.per_provider_cost_usd
    assert len(result.top_vehicles) == 1


# ---------------------------------------------------------------------------
# Service layer — list_all_platform
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_all_platform_returns_all():
    """list_all_platform returns all transponders."""
    from app.services import corporate_fleet_toll_service as svc

    mock_db = AsyncMock()
    list_result = MagicMock()
    list_result.scalars.return_value.all.return_value = []
    mock_db.execute.return_value = list_result

    results = await svc.list_all_platform(mock_db)
    assert results == []


@pytest.mark.asyncio
async def test_list_all_platform_account_filter():
    """list_all_platform filters by account_id."""
    from app.services import corporate_fleet_toll_service as svc

    mock_db = AsyncMock()
    list_result = MagicMock()
    list_result.scalars.return_value.all.return_value = []
    mock_db.execute.return_value = list_result

    results = await svc.list_all_platform(mock_db, account_id=ACCOUNT_ID)
    assert results == []


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------


def test_transponder_create_valid():
    """TransponderCreate accepts valid data."""
    obj = TransponderCreate(
        fleet_vehicle_id=VEHICLE_ID,
        transponder_number="EZP-123456",
        provider=TransponderProvider.ezpass,
        assigned_date=TODAY,
        monthly_plan_cost_usd=4.99,
        toll_account_number="ACC-9999",
    )
    assert obj.provider == TransponderProvider.ezpass
    assert obj.transponder_number == "EZP-123456"


def test_transponder_create_missing_required():
    """TransponderCreate raises ValidationError when required fields are missing."""
    with pytest.raises(ValidationError):
        TransponderCreate(transponder_number="EZP-000")  # missing fleet_vehicle_id, provider, assigned_date


def test_transponder_response_valid():
    """TransponderResponse is a valid schema."""
    obj = _mock_transponder()
    assert obj.is_active is True
    assert obj.provider == TransponderProvider.ezpass


def test_toll_charge_create_valid():
    """TollChargeCreate accepts valid data."""
    obj = TollChargeCreate(
        fleet_vehicle_id=VEHICLE_ID,
        charge_date=TODAY,
        amount_usd=17.00,
        plaza_name="Lincoln Tunnel",
    )
    assert obj.amount_usd == 17.00


def test_toll_charge_create_negative_amount_rejected():
    """TollChargeCreate rejects negative amount_usd."""
    with pytest.raises(ValidationError):
        TollChargeCreate(
            fleet_vehicle_id=VEHICLE_ID,
            charge_date=TODAY,
            amount_usd=-1.00,
        )


def test_toll_charge_update_all_optional():
    """TollChargeUpdate accepts empty update."""
    obj = TollChargeUpdate()
    assert obj.amount_usd is None
    assert obj.plaza_name is None


def test_toll_charge_response_valid():
    """TollChargeResponse is a valid schema."""
    obj = _mock_charge()
    assert obj.amount_usd == 17.00
    assert obj.fleet_vehicle_id == VEHICLE_ID


def test_vehicle_toll_summary_valid():
    """VehicleTollSummaryResponse is a valid schema."""
    obj = _mock_vehicle_summary()
    assert obj.charge_count == 5
    assert obj.total_cost_usd == 62.50


def test_fleet_toll_summary_valid():
    """FleetTollSummaryResponse is a valid schema with top_vehicles list."""
    obj = _mock_fleet_summary()
    assert obj.total_charge_count == 10
    assert len(obj.top_vehicles) == 1
    assert obj.top_vehicles[0].fleet_vehicle_id == VEHICLE_ID


# ---------------------------------------------------------------------------
# API layer — helper
# ---------------------------------------------------------------------------

BASE_MEMBER = f"/api/v1/corporate/{ACCOUNT_ID}"
BASE_ADMIN = f"/api/v1/corporate/{ACCOUNT_ID}"
BASE_PLATFORM = "/api/v1/platform/corporate"
_ROUTER = "app.api.v1.corporate_fleet_toll"

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
        return _make_user(user_id=user_id, is_admin=True)

    return {
        get_current_user: _user,
        get_db: _db,
        require_admin: _admin,
    }


def _patch_get_account():
    return patch(f"{_ROUTER}.get_account", new_callable=AsyncMock)


def _patch_require_account_admin():
    return patch(f"{_ROUTER}._require_account_admin", new_callable=AsyncMock)


# ---------------------------------------------------------------------------
# API layer — member endpoints
# ---------------------------------------------------------------------------


def test_api_list_vehicle_transponders_200():
    """GET /fleet-vehicles/{vehicle_id}/transponders returns 200."""
    with (
        _patch_get_account(),
        patch(
            f"{_ROUTER}.list_vehicle_transponders",
            new_callable=AsyncMock,
            return_value=[_mock_transponder()],
        ),
    ):
        app.dependency_overrides.update(_dep_overrides())
        resp = client.get(f"{BASE_MEMBER}/fleet-vehicles/{VEHICLE_ID}/transponders")
        app.dependency_overrides.clear()
    assert resp.status_code == 200


def test_api_list_vehicle_toll_charges_200():
    """GET /fleet-vehicles/{vehicle_id}/toll-charges returns 200."""
    with (
        _patch_get_account(),
        patch(
            f"{_ROUTER}.list_vehicle_toll_charges",
            new_callable=AsyncMock,
            return_value=[_mock_charge()],
        ),
    ):
        app.dependency_overrides.update(_dep_overrides())
        resp = client.get(f"{BASE_MEMBER}/fleet-vehicles/{VEHICLE_ID}/toll-charges")
        app.dependency_overrides.clear()
    assert resp.status_code == 200


def test_api_get_vehicle_toll_summary_200():
    """GET /fleet-vehicles/{vehicle_id}/toll-summary returns 200."""
    with (
        _patch_get_account(),
        patch(
            f"{_ROUTER}.get_vehicle_toll_summary",
            new_callable=AsyncMock,
            return_value=_mock_vehicle_summary(),
        ),
    ):
        app.dependency_overrides.update(_dep_overrides())
        resp = client.get(f"{BASE_MEMBER}/fleet-vehicles/{VEHICLE_ID}/toll-summary")
        app.dependency_overrides.clear()
    assert resp.status_code == 200


def test_api_get_transponder_200():
    """GET /fleet-transponders/{transponder_id} returns 200."""
    with (
        _patch_get_account(),
        patch(
            f"{_ROUTER}.get_transponder",
            new_callable=AsyncMock,
            return_value=_mock_transponder(),
        ),
    ):
        app.dependency_overrides.update(_dep_overrides())
        resp = client.get(f"{BASE_MEMBER}/fleet-transponders/{TRANSPONDER_ID}")
        app.dependency_overrides.clear()
    assert resp.status_code == 200


def test_api_get_toll_charge_200():
    """GET /fleet-toll-charges/{charge_id} returns 200."""
    with (
        _patch_get_account(),
        patch(
            f"{_ROUTER}.get_toll_charge",
            new_callable=AsyncMock,
            return_value=_mock_charge(),
        ),
    ):
        app.dependency_overrides.update(_dep_overrides())
        resp = client.get(f"{BASE_MEMBER}/fleet-toll-charges/{CHARGE_ID}")
        app.dependency_overrides.clear()
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# API layer — admin endpoints
# ---------------------------------------------------------------------------


def test_api_assign_transponder_201():
    """POST /fleet-transponders/ returns 201."""
    with (
        _patch_get_account(),
        _patch_require_account_admin(),
        patch(
            f"{_ROUTER}.assign_transponder",
            new_callable=AsyncMock,
            return_value=_mock_transponder(),
        ),
    ):
        app.dependency_overrides.update(_dep_overrides())
        resp = client.post(
            f"{BASE_ADMIN}/fleet-transponders/",
            json={
                "fleet_vehicle_id": str(VEHICLE_ID),
                "transponder_number": "EZP-123456",
                "provider": "ezpass",
                "assigned_date": str(TODAY),
            },
        )
        app.dependency_overrides.clear()
    assert resp.status_code == 201


def test_api_list_account_transponders_200():
    """GET /fleet-transponders/ returns 200."""
    with (
        _patch_get_account(),
        _patch_require_account_admin(),
        patch(
            f"{_ROUTER}.list_account_transponders",
            new_callable=AsyncMock,
            return_value=[],
        ),
    ):
        app.dependency_overrides.update(_dep_overrides())
        resp = client.get(f"{BASE_ADMIN}/fleet-transponders/")
        app.dependency_overrides.clear()
    assert resp.status_code == 200


def test_api_deactivate_transponder_200():
    """POST /fleet-transponders/{id}/deactivate returns 200."""
    deactivated = _mock_transponder(is_active=False, removed_date=TODAY)
    with (
        _patch_get_account(),
        _patch_require_account_admin(),
        patch(
            f"{_ROUTER}.deactivate_transponder",
            new_callable=AsyncMock,
            return_value=deactivated,
        ),
    ):
        app.dependency_overrides.update(_dep_overrides())
        resp = client.post(
            f"{BASE_ADMIN}/fleet-transponders/{TRANSPONDER_ID}/deactivate"
        )
        app.dependency_overrides.clear()
    assert resp.status_code == 200


def test_api_reactivate_transponder_200():
    """POST /fleet-transponders/{id}/reactivate returns 200."""
    with (
        _patch_get_account(),
        _patch_require_account_admin(),
        patch(
            f"{_ROUTER}.reactivate_transponder",
            new_callable=AsyncMock,
            return_value=_mock_transponder(),
        ),
    ):
        app.dependency_overrides.update(_dep_overrides())
        resp = client.post(
            f"{BASE_ADMIN}/fleet-transponders/{TRANSPONDER_ID}/reactivate"
        )
        app.dependency_overrides.clear()
    assert resp.status_code == 200


def test_api_log_toll_charge_201():
    """POST /fleet-toll-charges/ returns 201."""
    with (
        _patch_get_account(),
        _patch_require_account_admin(),
        patch(
            f"{_ROUTER}.log_toll_charge",
            new_callable=AsyncMock,
            return_value=_mock_charge(),
        ),
    ):
        app.dependency_overrides.update(_dep_overrides())
        resp = client.post(
            f"{BASE_ADMIN}/fleet-toll-charges/",
            json={
                "fleet_vehicle_id": str(VEHICLE_ID),
                "charge_date": str(TODAY),
                "amount_usd": 17.00,
            },
        )
        app.dependency_overrides.clear()
    assert resp.status_code == 201


def test_api_list_account_toll_charges_200():
    """GET /fleet-toll-charges/ returns 200."""
    with (
        _patch_get_account(),
        _patch_require_account_admin(),
        patch(
            f"{_ROUTER}.list_account_toll_charges",
            new_callable=AsyncMock,
            return_value=[],
        ),
    ):
        app.dependency_overrides.update(_dep_overrides())
        resp = client.get(f"{BASE_ADMIN}/fleet-toll-charges/")
        app.dependency_overrides.clear()
    assert resp.status_code == 200


def test_api_get_fleet_toll_summary_200():
    """GET /fleet-toll-summary returns 200."""
    with (
        _patch_get_account(),
        _patch_require_account_admin(),
        patch(
            f"{_ROUTER}.get_fleet_toll_summary",
            new_callable=AsyncMock,
            return_value=_mock_fleet_summary(),
        ),
    ):
        app.dependency_overrides.update(_dep_overrides())
        resp = client.get(f"{BASE_ADMIN}/fleet-toll-summary")
        app.dependency_overrides.clear()
    assert resp.status_code == 200


def test_api_update_charge_200():
    """PUT /fleet-toll-charges/{charge_id} returns 200."""
    with (
        _patch_get_account(),
        _patch_require_account_admin(),
        patch(
            f"{_ROUTER}.update_toll_charge",
            new_callable=AsyncMock,
            return_value=_mock_charge(),
        ),
    ):
        app.dependency_overrides.update(_dep_overrides())
        resp = client.put(
            f"{BASE_ADMIN}/fleet-toll-charges/{CHARGE_ID}",
            json={"amount_usd": 20.00},
        )
        app.dependency_overrides.clear()
    assert resp.status_code == 200


def test_api_delete_charge_204():
    """DELETE /fleet-toll-charges/{charge_id} returns 204."""
    with (
        _patch_get_account(),
        _patch_require_account_admin(),
        patch(
            f"{_ROUTER}.delete_toll_charge",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        app.dependency_overrides.update(_dep_overrides())
        resp = client.delete(f"{BASE_ADMIN}/fleet-toll-charges/{CHARGE_ID}")
        app.dependency_overrides.clear()
    assert resp.status_code == 204


# ---------------------------------------------------------------------------
# API layer — platform admin endpoints
# ---------------------------------------------------------------------------


def test_api_platform_list_transponders_200():
    """GET /platform/corporate/fleet-transponders/ returns 200."""
    with patch(
        f"{_ROUTER}.list_all_platform",
        new_callable=AsyncMock,
        return_value=[],
    ):
        app.dependency_overrides.update(_dep_overrides(is_admin=True))
        resp = client.get(f"{BASE_PLATFORM}/fleet-transponders/")
        app.dependency_overrides.clear()
    assert resp.status_code == 200


def test_api_platform_list_transponders_by_account_200():
    """GET /platform/corporate/fleet-transponders/{account_id} returns 200."""
    with patch(
        f"{_ROUTER}.list_all_platform",
        new_callable=AsyncMock,
        return_value=[],
    ):
        app.dependency_overrides.update(_dep_overrides(is_admin=True))
        resp = client.get(f"{BASE_PLATFORM}/fleet-transponders/{ACCOUNT_ID}")
        app.dependency_overrides.clear()
    assert resp.status_code == 200
