"""Unit tests for vehicle maintenance tracking feature.

Tests cover:
- MaintenanceLogCreate schema validation
- MaintenanceLogResponse serialisation
- UpcomingMaintenanceItem and UpcomingMaintenanceResponse
- FleetMaintenanceSummary
- Service: log_maintenance, get_vehicle_maintenance_history,
           get_driver_maintenance_history, get_upcoming_maintenance,
           get_fleet_maintenance_summary
- Router: POST /drivers/me/vehicles/{id}/maintenance,
          GET  /drivers/me/vehicles/{id}/maintenance,
          GET  /drivers/me/maintenance/upcoming,
          GET  /admin/maintenance/fleet
"""

from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.vehicle_maintenance import MaintenanceType, VehicleMaintenanceLog
from app.schemas.vehicle_maintenance import (
    FleetMaintenanceSummary,
    MaintenanceHistoryResponse,
    MaintenanceLogCreate,
    MaintenanceLogResponse,
    UpcomingMaintenanceItem,
    UpcomingMaintenanceResponse,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_log(
    id: int = 1,
    vehicle_id: int = 10,
    driver_profile_id: int = 5,
    maintenance_type: MaintenanceType = MaintenanceType.OIL_CHANGE,
    date_serviced: date | None = None,
    next_service_date: date | None = None,
    next_service_mileage: int | None = None,
    cost_usd: float | None = None,
) -> VehicleMaintenanceLog:
    log = MagicMock(spec=VehicleMaintenanceLog)
    log.id = id
    log.vehicle_id = vehicle_id
    log.driver_profile_id = driver_profile_id
    log.maintenance_type = maintenance_type
    log.description = None
    log.service_provider = "Jiffy Lube"
    log.notes = None
    log.date_serviced = date_serviced or date(2026, 3, 1)
    log.mileage_at_service = 45000
    log.cost_usd = cost_usd
    log.next_service_date = next_service_date
    log.next_service_mileage = next_service_mileage
    log.created_at = datetime.now(timezone.utc)
    return log


# ---------------------------------------------------------------------------
# Schema tests: MaintenanceLogCreate
# ---------------------------------------------------------------------------


class TestMaintenanceLogCreate:
    def test_minimal_valid(self):
        req = MaintenanceLogCreate(
            maintenance_type=MaintenanceType.OIL_CHANGE,
            date_serviced=date(2026, 3, 1),
        )
        assert req.maintenance_type == MaintenanceType.OIL_CHANGE
        assert req.description is None
        assert req.cost_usd is None

    def test_full_fields(self):
        req = MaintenanceLogCreate(
            maintenance_type=MaintenanceType.BRAKE_REPLACEMENT,
            description="Replaced rear pads and rotors",
            service_provider="Midas",
            notes="Front pads at 60%",
            date_serviced=date(2026, 3, 15),
            mileage_at_service=52000,
            cost_usd=380.0,
            next_service_date=date(2028, 3, 15),
            next_service_mileage=82000,
        )
        assert req.maintenance_type == MaintenanceType.BRAKE_REPLACEMENT
        assert req.mileage_at_service == 52000
        assert req.cost_usd == 380.0
        assert req.next_service_date == date(2028, 3, 15)

    def test_rejects_negative_mileage(self):
        with pytest.raises(Exception):
            MaintenanceLogCreate(
                maintenance_type=MaintenanceType.TIRE_ROTATION,
                date_serviced=date(2026, 3, 1),
                mileage_at_service=-1,
            )

    def test_rejects_negative_cost(self):
        with pytest.raises(Exception):
            MaintenanceLogCreate(
                maintenance_type=MaintenanceType.OIL_CHANGE,
                date_serviced=date(2026, 3, 1),
                cost_usd=-5.0,
            )

    def test_all_maintenance_types_valid(self):
        for mt in MaintenanceType:
            req = MaintenanceLogCreate(
                maintenance_type=mt,
                date_serviced=date(2026, 1, 1),
            )
            assert req.maintenance_type == mt


# ---------------------------------------------------------------------------
# Schema tests: MaintenanceLogResponse
# ---------------------------------------------------------------------------


class TestMaintenanceLogResponse:
    def test_from_mock_model(self):
        log = _make_log(cost_usd=55.0, next_service_date=date(2026, 9, 1))
        resp = MaintenanceLogResponse(
            id=log.id,
            vehicle_id=log.vehicle_id,
            driver_profile_id=log.driver_profile_id,
            maintenance_type=log.maintenance_type,
            description=log.description,
            service_provider=log.service_provider,
            notes=log.notes,
            date_serviced=log.date_serviced,
            mileage_at_service=log.mileage_at_service,
            cost_usd=log.cost_usd,
            next_service_date=log.next_service_date,
            next_service_mileage=log.next_service_mileage,
            created_at=log.created_at,
        )
        assert resp.id == 1
        assert resp.maintenance_type == MaintenanceType.OIL_CHANGE
        assert resp.cost_usd == 55.0
        assert resp.next_service_date == date(2026, 9, 1)

    def test_optional_fields_none(self):
        resp = MaintenanceLogResponse(
            id=2,
            vehicle_id=10,
            driver_profile_id=5,
            maintenance_type=MaintenanceType.WIPER_BLADES,
            description=None,
            service_provider=None,
            notes=None,
            date_serviced=date(2026, 1, 10),
            mileage_at_service=None,
            cost_usd=None,
            next_service_date=None,
            next_service_mileage=None,
            created_at=datetime.now(timezone.utc),
        )
        assert resp.service_provider is None
        assert resp.cost_usd is None


# ---------------------------------------------------------------------------
# Schema tests: UpcomingMaintenanceItem
# ---------------------------------------------------------------------------


class TestUpcomingMaintenanceItem:
    def test_overdue_item(self):
        item = UpcomingMaintenanceItem(
            log_id=1,
            vehicle_id=10,
            maintenance_type=MaintenanceType.OIL_CHANGE,
            next_service_date=date(2026, 3, 1),
            next_service_mileage=None,
            days_until_due=-14,
            is_overdue=True,
        )
        assert item.is_overdue is True
        assert item.days_until_due == -14

    def test_upcoming_item(self):
        item = UpcomingMaintenanceItem(
            log_id=2,
            vehicle_id=10,
            maintenance_type=MaintenanceType.TIRE_ROTATION,
            next_service_date=date(2026, 5, 1),
            next_service_mileage=50000,
            days_until_due=16,
            is_overdue=False,
        )
        assert item.is_overdue is False
        assert item.days_until_due == 16

    def test_no_date_set(self):
        item = UpcomingMaintenanceItem(
            log_id=3,
            vehicle_id=10,
            maintenance_type=MaintenanceType.OTHER,
            next_service_date=None,
            next_service_mileage=60000,
            days_until_due=None,
            is_overdue=False,
        )
        assert item.days_until_due is None


# ---------------------------------------------------------------------------
# Schema tests: UpcomingMaintenanceResponse
# ---------------------------------------------------------------------------


class TestUpcomingMaintenanceResponse:
    def test_empty(self):
        resp = UpcomingMaintenanceResponse(items=[], total=0)
        assert resp.total == 0

    def test_with_items(self):
        items = [
            UpcomingMaintenanceItem(
                log_id=1,
                vehicle_id=10,
                maintenance_type=MaintenanceType.OIL_CHANGE,
                next_service_date=date(2026, 4, 1),
                next_service_mileage=None,
                days_until_due=-14,
                is_overdue=True,
            ),
            UpcomingMaintenanceItem(
                log_id=2,
                vehicle_id=10,
                maintenance_type=MaintenanceType.AIR_FILTER,
                next_service_date=date(2026, 5, 10),
                next_service_mileage=None,
                days_until_due=25,
                is_overdue=False,
            ),
        ]
        resp = UpcomingMaintenanceResponse(items=items, total=2)
        assert resp.total == 2
        assert resp.items[0].is_overdue is True
        assert resp.items[1].is_overdue is False


# ---------------------------------------------------------------------------
# Schema tests: FleetMaintenanceSummary
# ---------------------------------------------------------------------------


class TestFleetMaintenanceSummary:
    def test_zero_state(self):
        summary = FleetMaintenanceSummary(
            total_logs=0,
            overdue_count=0,
            due_within_30_days=0,
            vehicles_with_overdue=0,
            recent_logs=[],
        )
        assert summary.total_logs == 0
        assert summary.overdue_count == 0

    def test_with_counts(self):
        summary = FleetMaintenanceSummary(
            total_logs=150,
            overdue_count=3,
            due_within_30_days=7,
            vehicles_with_overdue=2,
            recent_logs=[],
        )
        assert summary.overdue_count == 3
        assert summary.due_within_30_days == 7


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------


class TestVehicleMaintenanceModel:
    def test_tablename(self):
        assert VehicleMaintenanceLog.__tablename__ == "vehicle_maintenance_logs"

    def test_required_columns(self):
        col_names = {c.name for c in VehicleMaintenanceLog.__table__.columns}
        assert "id" in col_names
        assert "vehicle_id" in col_names
        assert "driver_profile_id" in col_names
        assert "maintenance_type" in col_names
        assert "date_serviced" in col_names
        assert "created_at" in col_names

    def test_optional_columns(self):
        col_names = {c.name for c in VehicleMaintenanceLog.__table__.columns}
        assert "cost_usd" in col_names
        assert "next_service_date" in col_names
        assert "next_service_mileage" in col_names
        assert "mileage_at_service" in col_names
        assert "service_provider" in col_names
        assert "description" in col_names
        assert "notes" in col_names

    def test_maintenance_type_enum_values(self):
        assert MaintenanceType.OIL_CHANGE == "oil_change"
        assert MaintenanceType.BRAKE_REPLACEMENT == "brake_replacement"
        assert MaintenanceType.ANNUAL_INSPECTION == "annual_inspection"
        assert MaintenanceType.OTHER == "other"


# ---------------------------------------------------------------------------
# Service: log_maintenance
# ---------------------------------------------------------------------------


class TestLogMaintenance:
    @pytest.mark.asyncio
    async def test_creates_entry(self):
        from app.services.vehicle_maintenance import log_maintenance

        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()

        entry = await log_maintenance(
            db=db,
            vehicle_id=10,
            driver_profile_id=5,
            maintenance_type=MaintenanceType.OIL_CHANGE,
            date_serviced=date(2026, 3, 1),
            cost_usd=49.99,
            next_service_date=date(2026, 9, 1),
        )
        db.add.assert_called_once()
        db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_cost_usd_converted_to_float(self):
        from app.services.vehicle_maintenance import log_maintenance

        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()

        await log_maintenance(
            db=db,
            vehicle_id=10,
            driver_profile_id=5,
            maintenance_type=MaintenanceType.TIRE_ROTATION,
            date_serviced=date(2026, 3, 1),
            cost_usd=29,  # integer — should be cast to float
        )
        added = db.add.call_args[0][0]
        assert isinstance(added.cost_usd, float)

    @pytest.mark.asyncio
    async def test_optional_fields_none(self):
        from app.services.vehicle_maintenance import log_maintenance

        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()

        await log_maintenance(
            db=db,
            vehicle_id=10,
            driver_profile_id=5,
            maintenance_type=MaintenanceType.OTHER,
            date_serviced=date(2026, 3, 1),
        )
        added = db.add.call_args[0][0]
        assert added.cost_usd is None
        assert added.next_service_date is None
        assert added.next_service_mileage is None


# ---------------------------------------------------------------------------
# Service: get_vehicle_maintenance_history
# ---------------------------------------------------------------------------


class TestGetVehicleMaintenanceHistory:
    @pytest.mark.asyncio
    async def test_empty_history(self):
        from app.services.vehicle_maintenance import get_vehicle_maintenance_history

        db = AsyncMock()
        count_result = MagicMock()
        count_result.scalar_one.return_value = 0
        rows_result = MagicMock()
        rows_result.scalars.return_value.all.return_value = []

        db.execute = AsyncMock(side_effect=[count_result, rows_result])
        logs, total = await get_vehicle_maintenance_history(db, vehicle_id=10)
        assert total == 0
        assert logs == []

    @pytest.mark.asyncio
    async def test_returns_logs(self):
        from app.services.vehicle_maintenance import get_vehicle_maintenance_history

        db = AsyncMock()
        count_result = MagicMock()
        count_result.scalar_one.return_value = 2
        log1 = _make_log(id=1)
        log2 = _make_log(id=2, maintenance_type=MaintenanceType.TIRE_ROTATION)
        rows_result = MagicMock()
        rows_result.scalars.return_value.all.return_value = [log1, log2]

        db.execute = AsyncMock(side_effect=[count_result, rows_result])
        logs, total = await get_vehicle_maintenance_history(db, vehicle_id=10)
        assert total == 2
        assert len(logs) == 2


# ---------------------------------------------------------------------------
# Service: get_driver_maintenance_history
# ---------------------------------------------------------------------------


class TestGetDriverMaintenanceHistory:
    @pytest.mark.asyncio
    async def test_returns_across_vehicles(self):
        from app.services.vehicle_maintenance import get_driver_maintenance_history

        db = AsyncMock()
        count_result = MagicMock()
        count_result.scalar_one.return_value = 3
        log1 = _make_log(id=1, vehicle_id=10)
        log2 = _make_log(id=2, vehicle_id=11)
        log3 = _make_log(id=3, vehicle_id=11, maintenance_type=MaintenanceType.AIR_FILTER)
        rows_result = MagicMock()
        rows_result.scalars.return_value.all.return_value = [log1, log2, log3]

        db.execute = AsyncMock(side_effect=[count_result, rows_result])
        logs, total = await get_driver_maintenance_history(db, driver_profile_id=5)
        assert total == 3
        assert len(logs) == 3

    @pytest.mark.asyncio
    async def test_empty(self):
        from app.services.vehicle_maintenance import get_driver_maintenance_history

        db = AsyncMock()
        count_result = MagicMock()
        count_result.scalar_one.return_value = 0
        rows_result = MagicMock()
        rows_result.scalars.return_value.all.return_value = []

        db.execute = AsyncMock(side_effect=[count_result, rows_result])
        logs, total = await get_driver_maintenance_history(db, driver_profile_id=5)
        assert total == 0
        assert logs == []


# ---------------------------------------------------------------------------
# Service: get_upcoming_maintenance
# ---------------------------------------------------------------------------


class TestGetUpcomingMaintenance:
    @pytest.mark.asyncio
    async def test_no_upcoming(self):
        from app.services.vehicle_maintenance import get_upcoming_maintenance

        db = AsyncMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(return_value=result)

        items = await get_upcoming_maintenance(db, driver_profile_id=5)
        assert items == []

    @pytest.mark.asyncio
    async def test_overdue_item(self):
        from app.services.vehicle_maintenance import get_upcoming_maintenance

        today = date.today()
        overdue_date = today - timedelta(days=10)

        db = AsyncMock()
        log = _make_log(next_service_date=overdue_date)
        result = MagicMock()
        result.scalars.return_value.all.return_value = [log]
        db.execute = AsyncMock(return_value=result)

        items = await get_upcoming_maintenance(db, driver_profile_id=5, days_ahead=30)
        assert len(items) == 1
        assert items[0]["is_overdue"] is True
        assert items[0]["days_until_due"] == -10

    @pytest.mark.asyncio
    async def test_upcoming_item(self):
        from app.services.vehicle_maintenance import get_upcoming_maintenance

        today = date.today()
        upcoming_date = today + timedelta(days=15)

        db = AsyncMock()
        log = _make_log(next_service_date=upcoming_date)
        result = MagicMock()
        result.scalars.return_value.all.return_value = [log]
        db.execute = AsyncMock(return_value=result)

        items = await get_upcoming_maintenance(db, driver_profile_id=5)
        assert len(items) == 1
        assert items[0]["is_overdue"] is False
        assert items[0]["days_until_due"] == 15

    @pytest.mark.asyncio
    async def test_due_today(self):
        from app.services.vehicle_maintenance import get_upcoming_maintenance

        today = date.today()
        db = AsyncMock()
        log = _make_log(next_service_date=today)
        result = MagicMock()
        result.scalars.return_value.all.return_value = [log]
        db.execute = AsyncMock(return_value=result)

        items = await get_upcoming_maintenance(db, driver_profile_id=5)
        assert items[0]["days_until_due"] == 0
        assert items[0]["is_overdue"] is False

    @pytest.mark.asyncio
    async def test_returns_correct_structure(self):
        from app.services.vehicle_maintenance import get_upcoming_maintenance

        today = date.today()
        log = _make_log(
            vehicle_id=10,
            maintenance_type=MaintenanceType.OIL_CHANGE,
            next_service_date=today - timedelta(days=5),
            next_service_mileage=50000,
        )
        db = AsyncMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = [log]
        db.execute = AsyncMock(return_value=result)

        items = await get_upcoming_maintenance(db, driver_profile_id=5)
        assert "log_id" in items[0]
        assert "vehicle_id" in items[0]
        assert "maintenance_type" in items[0]
        assert "next_service_date" in items[0]
        assert "next_service_mileage" in items[0]
        assert "days_until_due" in items[0]
        assert "is_overdue" in items[0]


# ---------------------------------------------------------------------------
# Service: get_fleet_maintenance_summary
# ---------------------------------------------------------------------------


class TestGetFleetMaintenanceSummary:
    @pytest.mark.asyncio
    async def test_all_zeros(self):
        from app.services.vehicle_maintenance import get_fleet_maintenance_summary

        db = AsyncMock()

        def make_scalar(value):
            r = MagicMock()
            r.scalar_one.return_value = value
            return r

        recent_result = MagicMock()
        recent_result.scalars.return_value.all.return_value = []

        db.execute = AsyncMock(side_effect=[
            make_scalar(0),  # total_logs
            make_scalar(0),  # overdue_count
            make_scalar(0),  # due_within_30
            make_scalar(0),  # vehicles_with_overdue
            recent_result,   # recent_logs
        ])

        summary = await get_fleet_maintenance_summary(db)
        assert summary["total_logs"] == 0
        assert summary["overdue_count"] == 0
        assert summary["due_within_30_days"] == 0
        assert summary["vehicles_with_overdue"] == 0
        assert summary["recent_logs"] == []

    @pytest.mark.asyncio
    async def test_with_data(self):
        from app.services.vehicle_maintenance import get_fleet_maintenance_summary

        db = AsyncMock()

        def make_scalar(value):
            r = MagicMock()
            r.scalar_one.return_value = value
            return r

        log1 = _make_log(id=1)
        log2 = _make_log(id=2, maintenance_type=MaintenanceType.TIRE_ROTATION)
        recent_result = MagicMock()
        recent_result.scalars.return_value.all.return_value = [log1, log2]

        db.execute = AsyncMock(side_effect=[
            make_scalar(50),  # total_logs
            make_scalar(3),   # overdue_count
            make_scalar(7),   # due_within_30
            make_scalar(2),   # vehicles_with_overdue
            recent_result,    # recent_logs
        ])

        summary = await get_fleet_maintenance_summary(db)
        assert summary["total_logs"] == 50
        assert summary["overdue_count"] == 3
        assert summary["due_within_30_days"] == 7
        assert summary["vehicles_with_overdue"] == 2
        assert len(summary["recent_logs"]) == 2


# ---------------------------------------------------------------------------
# Router: endpoint structure validation
# ---------------------------------------------------------------------------


class TestRouterStructure:
    def test_router_has_expected_routes(self):
        from app.api.v1.vehicle_maintenance import router

        paths = {route.path for route in router.routes}
        assert "/drivers/me/vehicles/{vehicle_id}/maintenance" in paths
        assert "/drivers/me/maintenance/upcoming" in paths
        assert "/admin/maintenance/fleet" in paths

    def test_router_tag(self):
        from app.api.v1.vehicle_maintenance import router

        assert "vehicle-maintenance" in router.tags

    def test_create_endpoint_is_post(self):
        from app.api.v1.vehicle_maintenance import router

        post_routes = [
            r for r in router.routes
            if hasattr(r, "methods") and "POST" in r.methods
            and r.path == "/drivers/me/vehicles/{vehicle_id}/maintenance"
        ]
        assert len(post_routes) == 1

    def test_history_endpoint_is_get(self):
        from app.api.v1.vehicle_maintenance import router

        get_routes = [
            r for r in router.routes
            if hasattr(r, "methods") and "GET" in r.methods
            and r.path == "/drivers/me/vehicles/{vehicle_id}/maintenance"
        ]
        assert len(get_routes) == 1

    def test_upcoming_endpoint_is_get(self):
        from app.api.v1.vehicle_maintenance import router

        get_routes = [
            r for r in router.routes
            if hasattr(r, "methods") and "GET" in r.methods
            and r.path == "/drivers/me/maintenance/upcoming"
        ]
        assert len(get_routes) == 1

    def test_fleet_endpoint_is_get(self):
        from app.api.v1.vehicle_maintenance import router

        get_routes = [
            r for r in router.routes
            if hasattr(r, "methods") and "GET" in r.methods
            and r.path == "/admin/maintenance/fleet"
        ]
        assert len(get_routes) == 1


# ---------------------------------------------------------------------------
# Router: function signature validation (service wiring)
# ---------------------------------------------------------------------------


class TestServiceFunctionSignatures:
    def test_log_maintenance_signature(self):
        import inspect
        from app.services.vehicle_maintenance import log_maintenance

        sig = inspect.signature(log_maintenance)
        params = list(sig.parameters.keys())
        assert "db" in params
        assert "vehicle_id" in params
        assert "driver_profile_id" in params
        assert "maintenance_type" in params
        assert "date_serviced" in params

    def test_get_upcoming_signature(self):
        import inspect
        from app.services.vehicle_maintenance import get_upcoming_maintenance

        sig = inspect.signature(get_upcoming_maintenance)
        params = list(sig.parameters.keys())
        assert "db" in params
        assert "driver_profile_id" in params
        assert "days_ahead" in params

    def test_get_fleet_summary_signature(self):
        import inspect
        from app.services.vehicle_maintenance import get_fleet_maintenance_summary

        sig = inspect.signature(get_fleet_maintenance_summary)
        params = list(sig.parameters.keys())
        assert "db" in params
        assert "days_ahead" in params
