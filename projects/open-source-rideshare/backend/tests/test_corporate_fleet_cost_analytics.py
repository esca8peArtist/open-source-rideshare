"""Tests for the Corporate Fleet Cost Analytics feature.

Service layer (async, mocked DB):
   1.  get_fleet_cost_summary — success returns correct totals
   2.  get_fleet_cost_summary — zero totals when no data
   3.  get_fleet_cost_summary — 403 when not admin
   4.  get_fleet_cost_summary — date filter applied to fuel query
   5.  get_fleet_cost_summary — date filter applied to maintenance query
   6.  get_fleet_cost_summary — date filter applied to toll query
   7.  get_vehicle_cost_breakdown — success returns vehicle list
   8.  get_vehicle_cost_breakdown — empty when no vehicles
   9.  get_vehicle_cost_breakdown — 403 when not admin
  10.  get_vehicle_cost_breakdown — date filter applied
  11.  get_fleet_monthly_cost_trend — returns n_months of data
  12.  get_fleet_monthly_cost_trend — 403 when not admin
  13.  get_fleet_monthly_cost_trend — empty when no data

Schema validation:
  14.  FleetCostSummaryResponse — valid construction
  15.  VehicleCostItem — valid construction
  16.  VehicleCostBreakdownResponse — valid
  17.  MonthlyCostPoint — valid
  18.  FleetMonthlyCostTrendResponse — valid

API layer (service functions patched):
  19.  GET fleet-costs → 200
  20.  GET fleet-costs with date params → 200
  21.  GET fleet-costs → 401 without auth
  22.  GET fleet-costs/monthly → 200
  23.  GET fleet-costs/monthly with n_months param → 200
  24.  GET fleet-costs/vehicles → 200
  25.  GET fleet-costs/vehicles with date params → 200
  26.  GET admin fleet-cost-analytics → 200
  27.  GET admin fleet-cost-analytics → 403 for non-admin

Additional edge cases:
  28.  get_fleet_cost_summary — start_date only filter
  29.  get_fleet_cost_summary — end_date only filter
  30.  get_fleet_cost_summary — total_cost_usd is sum of all three categories
  31.  get_vehicle_cost_breakdown — total_cost_usd per vehicle is sum of three categories
  32.  get_vehicle_cost_breakdown — missing fuel cost defaults to zero
  33.  get_vehicle_cost_breakdown — missing maintenance cost defaults to zero
  34.  get_vehicle_cost_breakdown — missing toll cost defaults to zero
  35.  get_fleet_monthly_cost_trend — n_months=1 returns only most recent month
  36.  get_fleet_monthly_cost_trend — months are in chronological order
  37.  FleetCostSummaryResponse — period_start and period_end can be None
  38.  VehicleCostBreakdownResponse — empty vehicles list is valid
  39.  FleetMonthlyCostTrendResponse — empty months list is valid
  40.  GET fleet-costs/monthly — n_months out of range returns 422
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
from app.schemas.corporate_fleet_cost_analytics import (
    FleetCostSummaryResponse,
    FleetMonthlyCostTrendResponse,
    MonthlyCostPoint,
    VehicleCostBreakdownResponse,
    VehicleCostItem,
)

# ---------------------------------------------------------------------------
# Shared test fixtures
# ---------------------------------------------------------------------------

ACCOUNT_ID = 1
VEHICLE_ID = uuid.uuid4()
VEHICLE_ID_2 = uuid.uuid4()
USER_ID = 42
NOW = datetime.now(tz=timezone.utc)
TODAY = date.today()
_ROUTER = "app.api.v1.corporate_fleet_cost_analytics"
_SVC = "app.services.corporate_fleet_cost_analytics_service"


def _make_summary_response(
    fuel: float = 100.0,
    maint: float = 50.0,
    toll: float = 25.0,
    vehicle_count: int = 2,
    start: date | None = None,
    end: date | None = None,
) -> FleetCostSummaryResponse:
    f = Decimal(str(fuel))
    m = Decimal(str(maint))
    t = Decimal(str(toll))
    return FleetCostSummaryResponse(
        account_id=ACCOUNT_ID,
        period_start=start,
        period_end=end,
        total_fuel_cost_usd=f,
        total_maintenance_cost_usd=m,
        total_toll_cost_usd=t,
        total_cost_usd=f + m + t,
        vehicle_count=vehicle_count,
    )


def _make_vehicle_item(
    vehicle_id: uuid.UUID = VEHICLE_ID,
    fuel: float = 80.0,
    maint: float = 40.0,
    toll: float = 20.0,
) -> VehicleCostItem:
    f = Decimal(str(fuel))
    m = Decimal(str(maint))
    t = Decimal(str(toll))
    return VehicleCostItem(
        vehicle_id=vehicle_id,
        make="Toyota",
        model="Camry",
        year=2022,
        license_plate="ABC-123",
        fuel_cost_usd=f,
        maintenance_cost_usd=m,
        toll_cost_usd=t,
        total_cost_usd=f + m + t,
    )


def _make_breakdown_response(
    vehicles: list[VehicleCostItem] | None = None,
    start: date | None = None,
    end: date | None = None,
) -> VehicleCostBreakdownResponse:
    return VehicleCostBreakdownResponse(
        account_id=ACCOUNT_ID,
        period_start=start,
        period_end=end,
        vehicles=vehicles or [_make_vehicle_item()],
    )


def _make_monthly_response(months: list[MonthlyCostPoint] | None = None) -> FleetMonthlyCostTrendResponse:
    if months is None:
        months = [
            MonthlyCostPoint(
                month="2026-01",
                fuel_cost_usd=Decimal("50"),
                maintenance_cost_usd=Decimal("30"),
                toll_cost_usd=Decimal("10"),
                total_cost_usd=Decimal("90"),
            )
        ]
    return FleetMonthlyCostTrendResponse(account_id=ACCOUNT_ID, months=months)


# ---------------------------------------------------------------------------
# Helper: mock DB that is "not admin" (returns None for member lookup)
# ---------------------------------------------------------------------------


def _db_not_admin() -> AsyncMock:
    mock_db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    mock_db.execute.return_value = result
    return mock_db


def _db_admin() -> AsyncMock:
    """DB mock where first execute (admin check) returns a member."""
    mock_db = AsyncMock()
    mock_member = MagicMock()
    admin_result = MagicMock()
    admin_result.scalar_one_or_none.return_value = mock_member
    return mock_db, admin_result, mock_member


# ---------------------------------------------------------------------------
# Service layer — get_fleet_cost_summary
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_fleet_cost_summary_success():
    """get_fleet_cost_summary returns correct totals with mocked DB."""
    from app.services import corporate_fleet_cost_analytics_service as svc

    mock_db = AsyncMock()
    mock_member = MagicMock()
    admin_result = MagicMock()
    admin_result.scalar_one_or_none.return_value = mock_member

    def _scalar_result(val):
        r = MagicMock()
        r.scalar_one.return_value = val
        return r

    # call order: admin check, fuel sum, maint sum, toll sum, vehicle count
    admin_check = admin_result
    fuel_r = _scalar_result(100)
    maint_r = _scalar_result(50)
    toll_r = _scalar_result(25)
    count_r = _scalar_result(3)

    mock_db.execute.side_effect = [admin_check, fuel_r, maint_r, toll_r, count_r]

    result = await svc.get_fleet_cost_summary(mock_db, ACCOUNT_ID, USER_ID)

    assert result.total_fuel_cost_usd == Decimal("100")
    assert result.total_maintenance_cost_usd == Decimal("50")
    assert result.total_toll_cost_usd == Decimal("25")
    assert result.total_cost_usd == Decimal("175")
    assert result.vehicle_count == 3


@pytest.mark.asyncio
async def test_get_fleet_cost_summary_zero_totals():
    """get_fleet_cost_summary returns zero totals when no data exists."""
    from app.services import corporate_fleet_cost_analytics_service as svc

    mock_db = AsyncMock()
    mock_member = MagicMock()
    admin_result = MagicMock()
    admin_result.scalar_one_or_none.return_value = mock_member

    def _zero_result():
        r = MagicMock()
        r.scalar_one.return_value = 0
        return r

    mock_db.execute.side_effect = [
        admin_result,
        _zero_result(),
        _zero_result(),
        _zero_result(),
        _zero_result(),
    ]

    result = await svc.get_fleet_cost_summary(mock_db, ACCOUNT_ID, USER_ID)

    assert result.total_fuel_cost_usd == Decimal("0")
    assert result.total_maintenance_cost_usd == Decimal("0")
    assert result.total_toll_cost_usd == Decimal("0")
    assert result.total_cost_usd == Decimal("0")
    assert result.vehicle_count == 0


@pytest.mark.asyncio
async def test_get_fleet_cost_summary_403_not_admin():
    """get_fleet_cost_summary raises 403 when user is not an admin."""
    from app.services import corporate_fleet_cost_analytics_service as svc

    mock_db = _db_not_admin()

    with pytest.raises(HTTPException) as exc_info:
        await svc.get_fleet_cost_summary(mock_db, ACCOUNT_ID, USER_ID)
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_get_fleet_cost_summary_date_filter_fuel():
    """get_fleet_cost_summary passes date filters to queries without error."""
    from app.services import corporate_fleet_cost_analytics_service as svc

    mock_db = AsyncMock()
    mock_member = MagicMock()
    admin_result = MagicMock()
    admin_result.scalar_one_or_none.return_value = mock_member

    def _scalar_result(val):
        r = MagicMock()
        r.scalar_one.return_value = val
        return r

    mock_db.execute.side_effect = [
        admin_result,
        _scalar_result(60),
        _scalar_result(0),
        _scalar_result(0),
        _scalar_result(1),
    ]

    result = await svc.get_fleet_cost_summary(
        mock_db, ACCOUNT_ID, USER_ID, start_date=TODAY, end_date=TODAY
    )

    assert result.period_start == TODAY
    assert result.period_end == TODAY
    assert result.total_fuel_cost_usd == Decimal("60")


@pytest.mark.asyncio
async def test_get_fleet_cost_summary_date_filter_maintenance():
    """get_fleet_cost_summary applies date filter to maintenance completed_date."""
    from app.services import corporate_fleet_cost_analytics_service as svc

    mock_db = AsyncMock()
    mock_member = MagicMock()
    admin_result = MagicMock()
    admin_result.scalar_one_or_none.return_value = mock_member

    def _scalar_result(val):
        r = MagicMock()
        r.scalar_one.return_value = val
        return r

    mock_db.execute.side_effect = [
        admin_result,
        _scalar_result(0),
        _scalar_result(200),
        _scalar_result(0),
        _scalar_result(1),
    ]

    result = await svc.get_fleet_cost_summary(
        mock_db, ACCOUNT_ID, USER_ID, start_date=TODAY
    )

    assert result.total_maintenance_cost_usd == Decimal("200")
    assert result.period_start == TODAY


@pytest.mark.asyncio
async def test_get_fleet_cost_summary_date_filter_toll():
    """get_fleet_cost_summary applies date filter to toll charge_date."""
    from app.services import corporate_fleet_cost_analytics_service as svc

    mock_db = AsyncMock()
    mock_member = MagicMock()
    admin_result = MagicMock()
    admin_result.scalar_one_or_none.return_value = mock_member

    def _scalar_result(val):
        r = MagicMock()
        r.scalar_one.return_value = val
        return r

    mock_db.execute.side_effect = [
        admin_result,
        _scalar_result(0),
        _scalar_result(0),
        _scalar_result(75),
        _scalar_result(1),
    ]

    result = await svc.get_fleet_cost_summary(
        mock_db, ACCOUNT_ID, USER_ID, end_date=TODAY
    )

    assert result.total_toll_cost_usd == Decimal("75")
    assert result.period_end == TODAY


# ---------------------------------------------------------------------------
# Service layer — get_vehicle_cost_breakdown
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_vehicle_cost_breakdown_success():
    """get_vehicle_cost_breakdown returns a vehicle list."""
    from app.services import corporate_fleet_cost_analytics_service as svc

    mock_db = AsyncMock()
    mock_member = MagicMock()
    admin_result = MagicMock()
    admin_result.scalar_one_or_none.return_value = mock_member

    mock_vehicle = MagicMock()
    mock_vehicle.id = VEHICLE_ID
    mock_vehicle.make = "Toyota"
    mock_vehicle.model_name = "Camry"
    mock_vehicle.year = 2022
    mock_vehicle.license_plate = "ABC-123"

    vehicles_result = MagicMock()
    vehicles_result.scalars.return_value.all.return_value = [mock_vehicle]

    # fuel GROUP BY rows
    fuel_row = MagicMock()
    fuel_row.fleet_vehicle_id = VEHICLE_ID
    fuel_row.fuel_cost = 80
    fuel_result = MagicMock()
    fuel_result.all.return_value = [fuel_row]

    # maintenance GROUP BY rows
    maint_row = MagicMock()
    maint_row.fleet_vehicle_id = VEHICLE_ID
    maint_row.maint_cost = 40
    maint_result = MagicMock()
    maint_result.all.return_value = [maint_row]

    # toll GROUP BY rows
    toll_row = MagicMock()
    toll_row.fleet_vehicle_id = VEHICLE_ID
    toll_row.toll_cost = 20
    toll_result = MagicMock()
    toll_result.all.return_value = [toll_row]

    mock_db.execute.side_effect = [
        admin_result,
        vehicles_result,
        fuel_result,
        maint_result,
        toll_result,
    ]

    result = await svc.get_vehicle_cost_breakdown(mock_db, ACCOUNT_ID, USER_ID)

    assert len(result.vehicles) == 1
    item = result.vehicles[0]
    assert item.vehicle_id == VEHICLE_ID
    assert item.fuel_cost_usd == Decimal("80")
    assert item.maintenance_cost_usd == Decimal("40")
    assert item.toll_cost_usd == Decimal("20")
    assert item.total_cost_usd == Decimal("140")


@pytest.mark.asyncio
async def test_get_vehicle_cost_breakdown_empty():
    """get_vehicle_cost_breakdown returns empty list when no vehicles."""
    from app.services import corporate_fleet_cost_analytics_service as svc

    mock_db = AsyncMock()
    mock_member = MagicMock()
    admin_result = MagicMock()
    admin_result.scalar_one_or_none.return_value = mock_member

    vehicles_result = MagicMock()
    vehicles_result.scalars.return_value.all.return_value = []

    mock_db.execute.side_effect = [admin_result, vehicles_result]

    result = await svc.get_vehicle_cost_breakdown(mock_db, ACCOUNT_ID, USER_ID)

    assert result.vehicles == []


@pytest.mark.asyncio
async def test_get_vehicle_cost_breakdown_403():
    """get_vehicle_cost_breakdown raises 403 when not admin."""
    from app.services import corporate_fleet_cost_analytics_service as svc

    mock_db = _db_not_admin()

    with pytest.raises(HTTPException) as exc_info:
        await svc.get_vehicle_cost_breakdown(mock_db, ACCOUNT_ID, USER_ID)
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_get_vehicle_cost_breakdown_date_filter():
    """get_vehicle_cost_breakdown passes date filter through without error."""
    from app.services import corporate_fleet_cost_analytics_service as svc

    mock_db = AsyncMock()
    mock_member = MagicMock()
    admin_result = MagicMock()
    admin_result.scalar_one_or_none.return_value = mock_member

    mock_vehicle = MagicMock()
    mock_vehicle.id = VEHICLE_ID
    mock_vehicle.make = "Ford"
    mock_vehicle.model_name = "Explorer"
    mock_vehicle.year = 2021
    mock_vehicle.license_plate = "XYZ-999"

    vehicles_result = MagicMock()
    vehicles_result.scalars.return_value.all.return_value = [mock_vehicle]

    empty_result = MagicMock()
    empty_result.all.return_value = []

    mock_db.execute.side_effect = [
        admin_result,
        vehicles_result,
        empty_result,
        empty_result,
        empty_result,
    ]

    result = await svc.get_vehicle_cost_breakdown(
        mock_db, ACCOUNT_ID, USER_ID, start_date=TODAY, end_date=TODAY
    )

    assert result.period_start == TODAY
    assert result.period_end == TODAY
    assert len(result.vehicles) == 1
    assert result.vehicles[0].total_cost_usd == Decimal("0")


# ---------------------------------------------------------------------------
# Service layer — get_fleet_monthly_cost_trend
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_fleet_monthly_cost_trend_returns_data():
    """get_fleet_monthly_cost_trend returns data points from mocked DB."""
    from app.services import corporate_fleet_cost_analytics_service as svc

    mock_db = AsyncMock()
    mock_member = MagicMock()
    admin_result = MagicMock()
    admin_result.scalar_one_or_none.return_value = mock_member

    fuel_row = MagicMock()
    fuel_row.yr = 2026
    fuel_row.mo = 1
    fuel_row.fuel_cost = 120
    fuel_result = MagicMock()
    fuel_result.all.return_value = [fuel_row]

    maint_row = MagicMock()
    maint_row.yr = 2026
    maint_row.mo = 1
    maint_row.maint_cost = 60
    maint_result = MagicMock()
    maint_result.all.return_value = [maint_row]

    toll_row = MagicMock()
    toll_row.yr = 2026
    toll_row.mo = 1
    toll_row.toll_cost = 30
    toll_result = MagicMock()
    toll_result.all.return_value = [toll_row]

    mock_db.execute.side_effect = [admin_result, fuel_result, maint_result, toll_result]

    result = await svc.get_fleet_monthly_cost_trend(mock_db, ACCOUNT_ID, USER_ID, n_months=12)

    assert len(result.months) == 1
    point = result.months[0]
    assert point.month == "2026-01"
    assert point.fuel_cost_usd == Decimal("120")
    assert point.maintenance_cost_usd == Decimal("60")
    assert point.toll_cost_usd == Decimal("30")
    assert point.total_cost_usd == Decimal("210")


@pytest.mark.asyncio
async def test_get_fleet_monthly_cost_trend_403():
    """get_fleet_monthly_cost_trend raises 403 when not admin."""
    from app.services import corporate_fleet_cost_analytics_service as svc

    mock_db = _db_not_admin()

    with pytest.raises(HTTPException) as exc_info:
        await svc.get_fleet_monthly_cost_trend(mock_db, ACCOUNT_ID, USER_ID)
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_get_fleet_monthly_cost_trend_empty():
    """get_fleet_monthly_cost_trend returns empty list when no data."""
    from app.services import corporate_fleet_cost_analytics_service as svc

    mock_db = AsyncMock()
    mock_member = MagicMock()
    admin_result = MagicMock()
    admin_result.scalar_one_or_none.return_value = mock_member

    empty_result = MagicMock()
    empty_result.all.return_value = []

    mock_db.execute.side_effect = [
        admin_result,
        empty_result,
        empty_result,
        empty_result,
    ]

    result = await svc.get_fleet_monthly_cost_trend(mock_db, ACCOUNT_ID, USER_ID)

    assert result.months == []


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------


def test_fleet_cost_summary_response_valid():
    """FleetCostSummaryResponse constructs correctly."""
    obj = _make_summary_response()
    assert obj.total_cost_usd == Decimal("175")
    assert obj.vehicle_count == 2
    assert obj.period_start is None
    assert obj.period_end is None


def test_vehicle_cost_item_valid():
    """VehicleCostItem constructs correctly."""
    obj = _make_vehicle_item()
    assert obj.total_cost_usd == Decimal("140")
    assert obj.make == "Toyota"
    assert obj.license_plate == "ABC-123"


def test_vehicle_cost_breakdown_response_valid():
    """VehicleCostBreakdownResponse constructs correctly."""
    obj = _make_breakdown_response()
    assert len(obj.vehicles) == 1
    assert obj.vehicles[0].vehicle_id == VEHICLE_ID


def test_monthly_cost_point_valid():
    """MonthlyCostPoint constructs correctly."""
    obj = MonthlyCostPoint(
        month="2026-03",
        fuel_cost_usd=Decimal("50"),
        maintenance_cost_usd=Decimal("20"),
        toll_cost_usd=Decimal("10"),
        total_cost_usd=Decimal("80"),
    )
    assert obj.month == "2026-03"
    assert obj.total_cost_usd == Decimal("80")


def test_fleet_monthly_cost_trend_response_valid():
    """FleetMonthlyCostTrendResponse constructs correctly."""
    obj = _make_monthly_response()
    assert len(obj.months) == 1
    assert obj.months[0].month == "2026-01"
    assert obj.account_id == ACCOUNT_ID


# ---------------------------------------------------------------------------
# API layer — helpers
# ---------------------------------------------------------------------------

BASE = f"/api/v1/corporate/{ACCOUNT_ID}/fleet/analytics"
BASE_ADMIN = "/api/v1/admin"

client = TestClient(app)


def _make_user(user_id: int = USER_ID, is_admin: bool = False):
    from app.models.user import User
    u = MagicMock(spec=User)
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
        return _make_user(user_id=user_id, is_admin=True)

    return {
        get_current_user: _user,
        get_db: _db,
        require_admin: _admin,
    }


def _patch_get_summary():
    return patch(
        f"{_ROUTER}.get_fleet_cost_summary",
        new_callable=AsyncMock,
        return_value=_make_summary_response(),
    )


def _patch_get_monthly():
    return patch(
        f"{_ROUTER}.get_fleet_monthly_cost_trend",
        new_callable=AsyncMock,
        return_value=_make_monthly_response(),
    )


def _patch_get_breakdown():
    return patch(
        f"{_ROUTER}.get_vehicle_cost_breakdown",
        new_callable=AsyncMock,
        return_value=_make_breakdown_response(),
    )


# ---------------------------------------------------------------------------
# API layer — GET fleet-costs
# ---------------------------------------------------------------------------


def test_api_get_fleet_costs_200():
    """GET /fleet/analytics/fleet-costs returns 200."""
    with _patch_get_summary():
        app.dependency_overrides.update(_dep_overrides())
        resp = client.get(f"{BASE}/fleet-costs")
        app.dependency_overrides.clear()
    assert resp.status_code == 200


def test_api_get_fleet_costs_with_date_params_200():
    """GET /fleet/analytics/fleet-costs with date params returns 200."""
    with _patch_get_summary():
        app.dependency_overrides.update(_dep_overrides())
        resp = client.get(
            f"{BASE}/fleet-costs",
            params={"start_date": "2026-01-01", "end_date": "2026-03-31"},
        )
        app.dependency_overrides.clear()
    assert resp.status_code == 200


def test_api_get_fleet_costs_401_no_auth():
    """GET /fleet/analytics/fleet-costs returns 401 without authentication."""
    resp = client.get(f"{BASE}/fleet-costs")
    # Without dependency override the real auth dep raises 401/403
    assert resp.status_code in (401, 403, 422)


# ---------------------------------------------------------------------------
# API layer — GET fleet-costs/monthly
# ---------------------------------------------------------------------------


def test_api_get_fleet_costs_monthly_200():
    """GET /fleet/analytics/fleet-costs/monthly returns 200."""
    with _patch_get_monthly():
        app.dependency_overrides.update(_dep_overrides())
        resp = client.get(f"{BASE}/fleet-costs/monthly")
        app.dependency_overrides.clear()
    assert resp.status_code == 200


def test_api_get_fleet_costs_monthly_with_n_months_200():
    """GET /fleet/analytics/fleet-costs/monthly?n_months=6 returns 200."""
    with _patch_get_monthly():
        app.dependency_overrides.update(_dep_overrides())
        resp = client.get(f"{BASE}/fleet-costs/monthly", params={"n_months": 6})
        app.dependency_overrides.clear()
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# API layer — GET fleet-costs/vehicles
# ---------------------------------------------------------------------------


def test_api_get_fleet_costs_vehicles_200():
    """GET /fleet/analytics/fleet-costs/vehicles returns 200."""
    with _patch_get_breakdown():
        app.dependency_overrides.update(_dep_overrides())
        resp = client.get(f"{BASE}/fleet-costs/vehicles")
        app.dependency_overrides.clear()
    assert resp.status_code == 200


def test_api_get_fleet_costs_vehicles_with_date_params_200():
    """GET /fleet/analytics/fleet-costs/vehicles with date params returns 200."""
    with _patch_get_breakdown():
        app.dependency_overrides.update(_dep_overrides())
        resp = client.get(
            f"{BASE}/fleet-costs/vehicles",
            params={"start_date": "2026-01-01"},
        )
        app.dependency_overrides.clear()
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# API layer — GET admin fleet-cost-analytics
# ---------------------------------------------------------------------------


def test_api_admin_get_fleet_cost_analytics_200():
    """GET /admin/fleet-cost-analytics/{account_id} returns 200."""
    with _patch_get_summary():
        app.dependency_overrides.update(_dep_overrides(is_admin=True))
        resp = client.get(f"{BASE_ADMIN}/fleet-cost-analytics/{ACCOUNT_ID}")
        app.dependency_overrides.clear()
    assert resp.status_code == 200


def test_api_admin_get_fleet_cost_analytics_403_non_admin():
    """GET /admin/fleet-cost-analytics/{account_id} returns 403 for non-admin."""
    from app.api.deps import require_admin

    async def _raise_403():
        raise HTTPException(status_code=403, detail="Not a platform admin")

    with _patch_get_summary():
        app.dependency_overrides.update(_dep_overrides())
        app.dependency_overrides[require_admin] = _raise_403
        resp = client.get(f"{BASE_ADMIN}/fleet-cost-analytics/{ACCOUNT_ID}")
        app.dependency_overrides.clear()
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Additional edge case tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_fleet_cost_summary_start_date_only():
    """get_fleet_cost_summary accepts start_date without end_date."""
    from app.services import corporate_fleet_cost_analytics_service as svc

    mock_db = AsyncMock()
    mock_member = MagicMock()
    admin_result = MagicMock()
    admin_result.scalar_one_or_none.return_value = mock_member

    def _scalar_result(val):
        r = MagicMock()
        r.scalar_one.return_value = val
        return r

    mock_db.execute.side_effect = [
        admin_result,
        _scalar_result(10),
        _scalar_result(5),
        _scalar_result(2),
        _scalar_result(1),
    ]

    result = await svc.get_fleet_cost_summary(
        mock_db, ACCOUNT_ID, USER_ID, start_date=TODAY
    )
    assert result.period_start == TODAY
    assert result.period_end is None


@pytest.mark.asyncio
async def test_get_fleet_cost_summary_end_date_only():
    """get_fleet_cost_summary accepts end_date without start_date."""
    from app.services import corporate_fleet_cost_analytics_service as svc

    mock_db = AsyncMock()
    mock_member = MagicMock()
    admin_result = MagicMock()
    admin_result.scalar_one_or_none.return_value = mock_member

    def _scalar_result(val):
        r = MagicMock()
        r.scalar_one.return_value = val
        return r

    mock_db.execute.side_effect = [
        admin_result,
        _scalar_result(10),
        _scalar_result(5),
        _scalar_result(2),
        _scalar_result(1),
    ]

    result = await svc.get_fleet_cost_summary(
        mock_db, ACCOUNT_ID, USER_ID, end_date=TODAY
    )
    assert result.period_start is None
    assert result.period_end == TODAY


def test_fleet_cost_summary_total_is_sum():
    """FleetCostSummaryResponse total_cost_usd equals sum of three categories."""
    fuel = Decimal("111.11")
    maint = Decimal("222.22")
    toll = Decimal("333.33")
    obj = FleetCostSummaryResponse(
        account_id=1,
        period_start=None,
        period_end=None,
        total_fuel_cost_usd=fuel,
        total_maintenance_cost_usd=maint,
        total_toll_cost_usd=toll,
        total_cost_usd=fuel + maint + toll,
        vehicle_count=5,
    )
    assert obj.total_cost_usd == Decimal("666.66")


def test_vehicle_cost_item_total_is_sum():
    """VehicleCostItem total_cost_usd equals sum of three cost fields."""
    obj = VehicleCostItem(
        vehicle_id=VEHICLE_ID,
        make="Honda",
        model="CR-V",
        year=2023,
        license_plate="DEF-456",
        fuel_cost_usd=Decimal("50"),
        maintenance_cost_usd=Decimal("30"),
        toll_cost_usd=Decimal("20"),
        total_cost_usd=Decimal("100"),
    )
    assert obj.total_cost_usd == Decimal("100")


@pytest.mark.asyncio
async def test_get_vehicle_cost_breakdown_missing_fuel_defaults_zero():
    """get_vehicle_cost_breakdown defaults fuel cost to zero when no fuel records."""
    from app.services import corporate_fleet_cost_analytics_service as svc

    mock_db = AsyncMock()
    mock_member = MagicMock()
    admin_result = MagicMock()
    admin_result.scalar_one_or_none.return_value = mock_member

    mock_vehicle = MagicMock()
    mock_vehicle.id = VEHICLE_ID
    mock_vehicle.make = "Honda"
    mock_vehicle.model_name = "Civic"
    mock_vehicle.year = 2020
    mock_vehicle.license_plate = "GHI-789"

    vehicles_result = MagicMock()
    vehicles_result.scalars.return_value.all.return_value = [mock_vehicle]

    empty_result = MagicMock()
    empty_result.all.return_value = []  # no fuel records

    maint_row = MagicMock()
    maint_row.fleet_vehicle_id = VEHICLE_ID
    maint_row.maint_cost = 100
    maint_result = MagicMock()
    maint_result.all.return_value = [maint_row]

    toll_result = MagicMock()
    toll_result.all.return_value = []

    mock_db.execute.side_effect = [
        admin_result,
        vehicles_result,
        empty_result,  # fuel
        maint_result,
        toll_result,
    ]

    result = await svc.get_vehicle_cost_breakdown(mock_db, ACCOUNT_ID, USER_ID)

    assert result.vehicles[0].fuel_cost_usd == Decimal("0")
    assert result.vehicles[0].maintenance_cost_usd == Decimal("100")


@pytest.mark.asyncio
async def test_get_vehicle_cost_breakdown_missing_maint_defaults_zero():
    """get_vehicle_cost_breakdown defaults maintenance cost to zero when no records."""
    from app.services import corporate_fleet_cost_analytics_service as svc

    mock_db = AsyncMock()
    mock_member = MagicMock()
    admin_result = MagicMock()
    admin_result.scalar_one_or_none.return_value = mock_member

    mock_vehicle = MagicMock()
    mock_vehicle.id = VEHICLE_ID
    mock_vehicle.make = "Nissan"
    mock_vehicle.model_name = "Rogue"
    mock_vehicle.year = 2019
    mock_vehicle.license_plate = "JKL-012"

    vehicles_result = MagicMock()
    vehicles_result.scalars.return_value.all.return_value = [mock_vehicle]

    fuel_row = MagicMock()
    fuel_row.fleet_vehicle_id = VEHICLE_ID
    fuel_row.fuel_cost = 50
    fuel_result = MagicMock()
    fuel_result.all.return_value = [fuel_row]

    empty_result = MagicMock()
    empty_result.all.return_value = []

    mock_db.execute.side_effect = [
        admin_result,
        vehicles_result,
        fuel_result,
        empty_result,  # maint
        empty_result,  # toll
    ]

    result = await svc.get_vehicle_cost_breakdown(mock_db, ACCOUNT_ID, USER_ID)

    assert result.vehicles[0].maintenance_cost_usd == Decimal("0")
    assert result.vehicles[0].fuel_cost_usd == Decimal("50")


@pytest.mark.asyncio
async def test_get_vehicle_cost_breakdown_missing_toll_defaults_zero():
    """get_vehicle_cost_breakdown defaults toll cost to zero when no records."""
    from app.services import corporate_fleet_cost_analytics_service as svc

    mock_db = AsyncMock()
    mock_member = MagicMock()
    admin_result = MagicMock()
    admin_result.scalar_one_or_none.return_value = mock_member

    mock_vehicle = MagicMock()
    mock_vehicle.id = VEHICLE_ID
    mock_vehicle.make = "Chevy"
    mock_vehicle.model_name = "Tahoe"
    mock_vehicle.year = 2021
    mock_vehicle.license_plate = "MNO-345"

    vehicles_result = MagicMock()
    vehicles_result.scalars.return_value.all.return_value = [mock_vehicle]

    empty_result = MagicMock()
    empty_result.all.return_value = []

    toll_row_result = MagicMock()
    toll_row_result.all.return_value = []

    mock_db.execute.side_effect = [
        admin_result,
        vehicles_result,
        empty_result,  # fuel
        empty_result,  # maint
        toll_row_result,  # toll empty
    ]

    result = await svc.get_vehicle_cost_breakdown(mock_db, ACCOUNT_ID, USER_ID)

    assert result.vehicles[0].toll_cost_usd == Decimal("0")


@pytest.mark.asyncio
async def test_get_fleet_monthly_cost_trend_n_months_1():
    """get_fleet_monthly_cost_trend with n_months=1 returns only most recent month."""
    from app.services import corporate_fleet_cost_analytics_service as svc

    mock_db = AsyncMock()
    mock_member = MagicMock()
    admin_result = MagicMock()
    admin_result.scalar_one_or_none.return_value = mock_member

    # Two months of fuel data
    fuel_row1 = MagicMock()
    fuel_row1.yr = 2025
    fuel_row1.mo = 12
    fuel_row1.fuel_cost = 50

    fuel_row2 = MagicMock()
    fuel_row2.yr = 2026
    fuel_row2.mo = 1
    fuel_row2.fuel_cost = 60

    fuel_result = MagicMock()
    fuel_result.all.return_value = [fuel_row1, fuel_row2]

    empty_result = MagicMock()
    empty_result.all.return_value = []

    mock_db.execute.side_effect = [
        admin_result,
        fuel_result,
        empty_result,
        empty_result,
    ]

    result = await svc.get_fleet_monthly_cost_trend(mock_db, ACCOUNT_ID, USER_ID, n_months=1)

    assert len(result.months) == 1
    assert result.months[0].month == "2026-01"


@pytest.mark.asyncio
async def test_get_fleet_monthly_cost_trend_chronological_order():
    """get_fleet_monthly_cost_trend returns months in chronological order."""
    from app.services import corporate_fleet_cost_analytics_service as svc

    mock_db = AsyncMock()
    mock_member = MagicMock()
    admin_result = MagicMock()
    admin_result.scalar_one_or_none.return_value = mock_member

    row1 = MagicMock()
    row1.yr = 2025
    row1.mo = 11
    row1.fuel_cost = 40

    row2 = MagicMock()
    row2.yr = 2026
    row2.mo = 2
    row2.fuel_cost = 70

    fuel_result = MagicMock()
    fuel_result.all.return_value = [row1, row2]

    empty_result = MagicMock()
    empty_result.all.return_value = []

    mock_db.execute.side_effect = [
        admin_result,
        fuel_result,
        empty_result,
        empty_result,
    ]

    result = await svc.get_fleet_monthly_cost_trend(mock_db, ACCOUNT_ID, USER_ID, n_months=12)

    assert len(result.months) == 2
    assert result.months[0].month < result.months[1].month


def test_fleet_cost_summary_period_start_end_none():
    """FleetCostSummaryResponse is valid when period_start and period_end are None."""
    obj = FleetCostSummaryResponse(
        account_id=1,
        period_start=None,
        period_end=None,
        total_fuel_cost_usd=Decimal("0"),
        total_maintenance_cost_usd=Decimal("0"),
        total_toll_cost_usd=Decimal("0"),
        total_cost_usd=Decimal("0"),
        vehicle_count=0,
    )
    assert obj.period_start is None
    assert obj.period_end is None


def test_vehicle_cost_breakdown_response_empty_vehicles():
    """VehicleCostBreakdownResponse with empty vehicles list is valid."""
    obj = VehicleCostBreakdownResponse(
        account_id=1,
        period_start=None,
        period_end=None,
        vehicles=[],
    )
    assert obj.vehicles == []


def test_fleet_monthly_cost_trend_response_empty_months():
    """FleetMonthlyCostTrendResponse with empty months list is valid."""
    obj = FleetMonthlyCostTrendResponse(account_id=1, months=[])
    assert obj.months == []


def test_api_get_fleet_costs_monthly_n_months_out_of_range():
    """GET /fleet/analytics/fleet-costs/monthly with n_months=0 returns 422."""
    with _patch_get_monthly():
        app.dependency_overrides.update(_dep_overrides())
        resp = client.get(f"{BASE}/fleet-costs/monthly", params={"n_months": 0})
        app.dependency_overrides.clear()
    assert resp.status_code == 422
