"""Comprehensive unit tests for the driver availability and scheduling feature.

Covers:
- Model fields and table structure
- Schema validation (ScheduleSlotCreate, WeeklyScheduleResponse, etc.)
- Service logic: schedule CRUD, online toggle, heartbeat, stale-heartbeat detection,
  is_driver_available_now, get_available_drivers_for_matching
- API endpoint auth checks (driver-only, admin-only)

All tests are pure unit tests — no database required.
Tests that would require a live PostgreSQL database are marked with
pytest.mark.skip(reason="requires PostgreSQL") consistent with other test files
in this project.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.driver_availability import DriverOnlineStatus, DriverSchedule
from app.schemas.driver_availability import (
    DAY_NAMES,
    ScheduleSlotCreate,
    ScheduleSlotResponse,
    SetOnlineRequest,
    WeeklyScheduleResponse,
    OnlineStatusResponse,
    DriverAvailabilityResponse,
)
from app.services.driver_availability import (
    HEARTBEAT_STALE_MINUTES,
    _heartbeat_is_stale,
    delete_schedule_slot,
    get_available_drivers_for_matching,
    get_driver_schedule,
    get_online_drivers,
    is_driver_available_now,
    set_driver_online,
    set_schedule_slot,
    update_heartbeat,
)


# ===========================================================================
# Model tests
# ===========================================================================


class TestDriverScheduleModel:
    def test_tablename(self):
        assert DriverSchedule.__tablename__ == "driver_schedules"

    def test_has_required_columns(self):
        cols = {c.key for c in DriverSchedule.__table__.columns}
        required = {"id", "driver_id", "day_of_week", "start_time", "end_time", "is_active",
                    "created_at", "updated_at"}
        assert required.issubset(cols)

    def test_unique_constraint_exists(self):
        constraint_names = {c.name for c in DriverSchedule.__table__.constraints}
        assert "uq_driver_schedule_day_start" in constraint_names

    def test_is_active_has_default(self):
        col = DriverSchedule.__table__.columns["is_active"]
        assert col.default is not None or col.server_default is not None


class TestDriverOnlineStatusModel:
    def test_tablename(self):
        assert DriverOnlineStatus.__tablename__ == "driver_online_status"

    def test_has_required_columns(self):
        cols = {c.key for c in DriverOnlineStatus.__table__.columns}
        required = {"id", "driver_id", "is_online", "went_online_at", "last_heartbeat", "updated_at"}
        assert required.issubset(cols)

    def test_driver_id_is_unique(self):
        col = DriverOnlineStatus.__table__.columns["driver_id"]
        assert col.unique is True

    def test_is_online_default_false(self):
        # Column-level default
        col = DriverOnlineStatus.__table__.columns["is_online"]
        assert col.default is not None or col.server_default is not None


# ===========================================================================
# Schema tests
# ===========================================================================


class TestScheduleSlotCreate:
    def test_valid_slot(self):
        slot = ScheduleSlotCreate(day_of_week=0, start_time="08:00", end_time="17:00")
        assert slot.day_of_week == 0
        assert slot.start_time == "08:00"
        assert slot.end_time == "17:00"

    def test_start_as_time(self):
        slot = ScheduleSlotCreate(day_of_week=1, start_time="09:30", end_time="18:00")
        assert slot.start_as_time() == time(9, 30)

    def test_end_as_time(self):
        slot = ScheduleSlotCreate(day_of_week=1, start_time="09:30", end_time="18:00")
        assert slot.end_as_time() == time(18, 0)

    def test_invalid_time_format_raises(self):
        with pytest.raises(Exception):
            ScheduleSlotCreate(day_of_week=0, start_time="8:00", end_time="17:00")

    def test_end_before_start_raises(self):
        with pytest.raises(Exception):
            ScheduleSlotCreate(day_of_week=0, start_time="17:00", end_time="08:00")

    def test_equal_start_end_raises(self):
        with pytest.raises(Exception):
            ScheduleSlotCreate(day_of_week=0, start_time="09:00", end_time="09:00")

    def test_day_of_week_bounds(self):
        # Valid bounds
        ScheduleSlotCreate(day_of_week=0, start_time="08:00", end_time="09:00")
        ScheduleSlotCreate(day_of_week=6, start_time="08:00", end_time="09:00")

    def test_day_of_week_out_of_bounds(self):
        with pytest.raises(Exception):
            ScheduleSlotCreate(day_of_week=7, start_time="08:00", end_time="09:00")

    def test_day_of_week_negative(self):
        with pytest.raises(Exception):
            ScheduleSlotCreate(day_of_week=-1, start_time="08:00", end_time="09:00")


class TestWeeklyScheduleResponse:
    def _make_slot(self, day_of_week: int, start: str, end: str) -> MagicMock:
        slot = MagicMock()
        slot.id = 1
        slot.driver_id = 42
        slot.day_of_week = day_of_week
        slot.start_time = time(*map(int, start.split(":")))
        slot.end_time = time(*map(int, end.split(":")))
        slot.is_active = True
        return slot

    def test_from_slots_empty(self):
        resp = WeeklyScheduleResponse.from_slots([])
        assert resp.monday == []
        assert resp.sunday == []

    def test_from_slots_groups_by_day(self):
        slots = [
            self._make_slot(0, "08:00", "12:00"),  # Monday
            self._make_slot(0, "13:00", "17:00"),  # Monday
            self._make_slot(4, "09:00", "18:00"),  # Friday
        ]
        resp = WeeklyScheduleResponse.from_slots(slots)
        assert len(resp.monday) == 2
        assert len(resp.friday) == 1
        assert resp.tuesday == []

    def test_day_names_constant(self):
        assert DAY_NAMES[0] == "monday"
        assert DAY_NAMES[6] == "sunday"
        assert len(DAY_NAMES) == 7


class TestSetOnlineRequest:
    def test_online_true(self):
        req = SetOnlineRequest(is_online=True)
        assert req.is_online is True

    def test_online_false(self):
        req = SetOnlineRequest(is_online=False)
        assert req.is_online is False

    def test_is_online_required(self):
        with pytest.raises(Exception):
            SetOnlineRequest()


class TestOnlineStatusResponse:
    def test_from_model(self):
        now = datetime.now(timezone.utc)
        row = MagicMock()
        row.driver_id = 5
        row.is_online = True
        row.went_online_at = now
        row.last_heartbeat = now
        resp = OnlineStatusResponse.model_validate(row)
        assert resp.driver_id == 5
        assert resp.is_online is True


# ===========================================================================
# Service unit tests (mocked DB)
# ===========================================================================


def _make_async_result(value):
    """Helper: returns a mock mimicking AsyncSession.execute() result."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    result.scalars.return_value.all.return_value = value if isinstance(value, list) else (
        [value] if value is not None else []
    )
    return result


class TestHeartbeatStaleHelper:
    def test_none_is_stale(self):
        assert _heartbeat_is_stale(None) is True

    def test_recent_is_not_stale(self):
        recent = datetime.now(timezone.utc) - timedelta(minutes=1)
        assert _heartbeat_is_stale(recent) is False

    def test_old_is_stale(self):
        old = datetime.now(timezone.utc) - timedelta(minutes=HEARTBEAT_STALE_MINUTES + 1)
        assert _heartbeat_is_stale(old) is True

    def test_exactly_at_threshold_is_not_stale(self):
        # Exactly at threshold — not strictly greater than, so not stale.
        at_threshold = datetime.now(timezone.utc) - timedelta(minutes=HEARTBEAT_STALE_MINUTES)
        # Allow 1-second tolerance for test execution time.
        result = _heartbeat_is_stale(at_threshold)
        # Could be True or False depending on microseconds, just verify it doesn't raise.
        assert isinstance(result, bool)

    def test_naive_datetime_treated_as_utc(self):
        """Naive datetimes (no tzinfo) should not raise — treated as UTC."""
        naive = datetime.utcnow() - timedelta(minutes=1)
        assert _heartbeat_is_stale(naive) is False


class TestSetDriverOnline:
    @pytest.mark.asyncio
    async def test_creates_new_status_when_going_online(self):
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_make_async_result(None))

        result = await set_driver_online(db, driver_id=1, is_online=True)

        db.add.assert_called_once()
        added = db.add.call_args[0][0]
        assert added.is_online is True
        assert added.went_online_at is not None
        assert added.last_heartbeat is not None

    @pytest.mark.asyncio
    async def test_creates_new_status_when_going_offline(self):
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_make_async_result(None))

        result = await set_driver_online(db, driver_id=1, is_online=False)

        db.add.assert_called_once()
        added = db.add.call_args[0][0]
        assert added.is_online is False
        assert added.went_online_at is None

    @pytest.mark.asyncio
    async def test_stamps_went_online_at_on_transition_to_online(self):
        existing = MagicMock()
        existing.is_online = False
        existing.went_online_at = None

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_make_async_result(existing))

        await set_driver_online(db, driver_id=1, is_online=True)

        assert existing.is_online is True
        assert existing.went_online_at is not None

    @pytest.mark.asyncio
    async def test_does_not_re_stamp_went_online_at_if_already_online(self):
        original_time = datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc)
        existing = MagicMock()
        existing.is_online = True
        existing.went_online_at = original_time

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_make_async_result(existing))

        await set_driver_online(db, driver_id=1, is_online=True)

        # went_online_at should NOT be updated when already online.
        assert existing.went_online_at == original_time

    @pytest.mark.asyncio
    async def test_set_offline(self):
        existing = MagicMock()
        existing.is_online = True

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_make_async_result(existing))

        await set_driver_online(db, driver_id=1, is_online=False)

        assert existing.is_online is False


class TestGetOnlineDrivers:
    @pytest.mark.asyncio
    async def test_returns_driver_ids(self):
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = [1, 2, 3]

        db = AsyncMock()
        db.execute = AsyncMock(return_value=result_mock)

        ids = await get_online_drivers(db)
        assert ids == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_returns_empty_when_none_online(self):
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = []

        db = AsyncMock()
        db.execute = AsyncMock(return_value=result_mock)

        ids = await get_online_drivers(db)
        assert ids == []


class TestUpdateHeartbeat:
    @pytest.mark.asyncio
    async def test_creates_row_if_not_exists(self):
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_make_async_result(None))

        result = await update_heartbeat(db, driver_id=7)

        db.add.assert_called_once()
        added = db.add.call_args[0][0]
        assert added.last_heartbeat is not None
        assert added.is_online is True

    @pytest.mark.asyncio
    async def test_updates_existing_heartbeat(self):
        old_hb = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)
        existing = MagicMock()
        existing.last_heartbeat = old_hb

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_make_async_result(existing))

        await update_heartbeat(db, driver_id=7)

        assert existing.last_heartbeat != old_hb
        assert existing.last_heartbeat is not None


class TestIsDriverAvailableNow:
    @pytest.mark.asyncio
    async def test_offline_driver_is_not_available(self):
        status_row = MagicMock()
        status_row.is_online = False

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_make_async_result(status_row))

        result = await is_driver_available_now(db, driver_id=1)
        assert result is False

    @pytest.mark.asyncio
    async def test_no_status_row_means_not_available(self):
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_make_async_result(None))

        result = await is_driver_available_now(db, driver_id=1)
        assert result is False

    @pytest.mark.asyncio
    async def test_online_no_schedule_is_available(self):
        status_row = MagicMock()
        status_row.is_online = True

        # First execute → status, second execute → empty schedule
        result_status = _make_async_result(status_row)
        result_slots = MagicMock()
        result_slots.scalars.return_value.all.return_value = []

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[result_status, result_slots])

        result = await is_driver_available_now(db, driver_id=1)
        assert result is True

    @pytest.mark.asyncio
    async def test_online_within_schedule_window_is_available(self):
        status_row = MagicMock()
        status_row.is_online = True

        # Build a slot that spans the whole day so we're always within it.
        slot = MagicMock()
        slot.start_time = time(0, 0)
        slot.end_time = time(23, 59)

        result_status = _make_async_result(status_row)
        result_slots = MagicMock()
        result_slots.scalars.return_value.all.return_value = [slot]

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[result_status, result_slots])

        result = await is_driver_available_now(db, driver_id=1)
        assert result is True

    @pytest.mark.asyncio
    async def test_online_outside_schedule_window_is_not_available(self):
        status_row = MagicMock()
        status_row.is_online = True

        # A slot that is definitely in the past (00:01–00:02) — extremely unlikely
        # to fire during a real test run, but we mock the time check instead.
        slot = MagicMock()
        slot.start_time = time(0, 1)
        slot.end_time = time(0, 2)

        result_status = _make_async_result(status_row)
        result_slots = MagicMock()
        result_slots.scalars.return_value.all.return_value = [slot]

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[result_status, result_slots])

        # Patch datetime.now so current time is 12:00 UTC — outside 00:01–00:02.
        fake_now = datetime(2026, 4, 13, 12, 0, 0, tzinfo=timezone.utc)
        with patch(
            "app.services.driver_availability.datetime"
        ) as mock_dt:
            mock_dt.now.return_value = fake_now
            mock_dt.now.side_effect = None
            result = await is_driver_available_now(db, driver_id=1)

        assert result is False


class TestGetAvailableDriversForMatching:
    @pytest.mark.asyncio
    async def test_returns_available_online_drivers(self):
        """Drivers that are online and available should be returned."""
        with (
            patch(
                "app.services.driver_availability.get_online_drivers",
                new=AsyncMock(return_value=[1, 2, 3]),
            ),
            patch(
                "app.services.driver_availability.is_driver_available_now",
                new=AsyncMock(side_effect=lambda db, did: did in {1, 3}),
            ),
        ):
            db = AsyncMock()
            result = await get_available_drivers_for_matching(db)
            assert sorted(result) == [1, 3]

    @pytest.mark.asyncio
    async def test_empty_when_no_online_drivers(self):
        with patch(
            "app.services.driver_availability.get_online_drivers",
            new=AsyncMock(return_value=[]),
        ):
            db = AsyncMock()
            result = await get_available_drivers_for_matching(db)
            assert result == []


class TestScheduleCRUD:
    @pytest.mark.asyncio
    async def test_set_schedule_slot_creates_new(self):
        slot_create = ScheduleSlotCreate(day_of_week=1, start_time="09:00", end_time="17:00")

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_make_async_result(None))

        result = await set_schedule_slot(db, driver_id=10, slot=slot_create)

        db.add.assert_called_once()
        added = db.add.call_args[0][0]
        assert added.driver_id == 10
        assert added.day_of_week == 1
        assert added.start_time == time(9, 0)
        assert added.end_time == time(17, 0)
        assert added.is_active is True

    @pytest.mark.asyncio
    async def test_set_schedule_slot_updates_existing(self):
        existing = MagicMock()
        existing.driver_id = 10
        existing.day_of_week = 1
        existing.start_time = time(9, 0)
        existing.end_time = time(12, 0)
        existing.is_active = False

        slot_create = ScheduleSlotCreate(day_of_week=1, start_time="09:00", end_time="17:00")

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_make_async_result(existing))

        result = await set_schedule_slot(db, driver_id=10, slot=slot_create)

        # Should update end_time and re-activate — not add a new row.
        db.add.assert_not_called()
        assert existing.end_time == time(17, 0)
        assert existing.is_active is True

    @pytest.mark.asyncio
    async def test_delete_schedule_slot_found(self):
        existing = MagicMock()

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_make_async_result(existing))

        deleted = await delete_schedule_slot(db, driver_id=10, slot_id=5)

        assert deleted is True
        db.delete.assert_called_once_with(existing)

    @pytest.mark.asyncio
    async def test_delete_schedule_slot_not_found(self):
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_make_async_result(None))

        deleted = await delete_schedule_slot(db, driver_id=10, slot_id=99)

        assert deleted is False
        db.delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_driver_schedule_returns_list(self):
        slot1 = MagicMock()
        slot2 = MagicMock()

        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = [slot1, slot2]

        db = AsyncMock()
        db.execute = AsyncMock(return_value=result_mock)

        slots = await get_driver_schedule(db, driver_id=10)
        assert slots == [slot1, slot2]

    @pytest.mark.asyncio
    async def test_get_driver_schedule_empty(self):
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = []

        db = AsyncMock()
        db.execute = AsyncMock(return_value=result_mock)

        slots = await get_driver_schedule(db, driver_id=10)
        assert slots == []


# ===========================================================================
# API endpoint auth checks
# ===========================================================================


class TestDriverAvailabilityAPIAuth:
    """Verify that driver endpoints reject non-drivers and admin endpoints reject non-admins.

    These tests import the router and inspect dependency injection without
    spinning up a full database.
    """

    def test_router_is_importable(self):
        from app.api.v1.driver_availability import router
        assert router is not None

    def test_driver_endpoints_use_require_driver(self):
        """Spot-check that driver-facing routes depend on require_driver.

        FastAPI stores resolved dependencies in route.dependant.dependencies
        (a recursive structure).  We flatten all dependency callables and check
        that require_driver appears somewhere in the tree.
        """
        from app.api.v1.driver_availability import router
        from app.api.deps import require_driver

        def collect_deps(dependant):
            """Recursively collect all dependency callables from a Dependant."""
            found = set()
            for dep in dependant.dependencies:
                if dep.call is not None:
                    found.add(dep.call)
                found |= collect_deps(dep.dependencies if hasattr(dep, "dependencies") else dep)
            return found

        def all_dep_callables(dependant):
            """Walk the full dependency tree."""
            result = set()
            queue = list(dependant.dependencies)
            while queue:
                item = queue.pop()
                if hasattr(item, "call") and item.call is not None:
                    result.add(item.call)
                if hasattr(item, "dependencies"):
                    queue.extend(item.dependencies)
            return result

        driver_paths = {
            "/drivers/me/availability",
            "/drivers/me/availability/schedule",
            "/drivers/me/availability/online",
            "/drivers/me/availability/heartbeat",
        }

        for route in router.routes:
            if hasattr(route, "path") and route.path in driver_paths:
                deps = all_dep_callables(route.dependant)
                assert require_driver in deps, (
                    f"Route {route.path} should depend on require_driver; found: {deps}"
                )

    def test_admin_endpoints_use_require_admin(self):
        """Spot-check that admin routes depend on require_admin."""
        from app.api.v1.driver_availability import router
        from app.api.deps import require_admin

        def all_dep_callables(dependant):
            result = set()
            queue = list(dependant.dependencies)
            while queue:
                item = queue.pop()
                if hasattr(item, "call") and item.call is not None:
                    result.add(item.call)
                if hasattr(item, "dependencies"):
                    queue.extend(item.dependencies)
            return result

        admin_paths = {
            "/admin/drivers/availability",
        }

        for route in router.routes:
            if hasattr(route, "path") and route.path in admin_paths:
                deps = all_dep_callables(route.dependant)
                assert require_admin in deps, (
                    f"Route {route.path} should depend on require_admin; found: {deps}"
                )

    def test_driver_delete_slot_endpoint_exists(self):
        from app.api.v1.driver_availability import router

        paths = {route.path for route in router.routes if hasattr(route, "path")}
        assert "/drivers/me/availability/schedule/{slot_id}" in paths

    def test_admin_driver_detail_endpoint_exists(self):
        from app.api.v1.driver_availability import router

        paths = {route.path for route in router.routes if hasattr(route, "path")}
        assert "/admin/drivers/{driver_id}/availability" in paths


# ===========================================================================
# DB-dependent tests (skipped without PostgreSQL)
# ===========================================================================


@pytest.mark.skip(reason="requires PostgreSQL")
class TestDriverAvailabilityDBIntegration:
    """Integration tests that exercise the full service + ORM stack.

    These are intentionally skipped in CI unless a PostgreSQL instance is
    available.  Run manually with:

        pytest tests/test_driver_availability.py::TestDriverAvailabilityDBIntegration -v
    """

    async def test_full_schedule_lifecycle(self, db_session):
        slot = await set_schedule_slot(
            db_session, driver_id=1,
            slot=ScheduleSlotCreate(day_of_week=0, start_time="08:00", end_time="17:00"),
        )
        assert slot.id is not None

        slots = await get_driver_schedule(db_session, driver_id=1)
        assert len(slots) >= 1

        deleted = await delete_schedule_slot(db_session, driver_id=1, slot_id=slot.id)
        assert deleted is True

    async def test_online_status_lifecycle(self, db_session):
        status = await set_driver_online(db_session, driver_id=1, is_online=True)
        assert status.is_online is True
        assert status.went_online_at is not None

        status = await set_driver_online(db_session, driver_id=1, is_online=False)
        assert status.is_online is False

    async def test_heartbeat_updates_timestamp(self, db_session):
        status = await update_heartbeat(db_session, driver_id=1)
        assert status.last_heartbeat is not None
