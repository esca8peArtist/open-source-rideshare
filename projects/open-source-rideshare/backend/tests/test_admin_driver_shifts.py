"""Unit tests for admin driver shift history endpoints.

GET /admin/drivers/shifts/active
GET /admin/drivers/{driver_id}/shift-history

Coverage
--------
Schemas
  - DriverShiftEntry: all fields populated
  - DriverShiftEntry: nullable fields default to None
  - DriverShiftHistoryResponse: serializes correctly
  - ActiveShiftEntry: all fields populated
  - ActiveShiftsResponse: serializes correctly

Active shifts (admin_list_active_shifts)
  - No active shifts -> total=0, items=[]
  - Single active shift -> correct field mapping
  - Multiple active shifts -> newest-first order
  - Pagination: skip/limit respected
  - Driver with no matching profile -> driver_profile_id=0, driver_name=None

Shift history (admin_get_driver_shift_history)
  - Empty history (driver exists, no shifts) -> total=0, items=[]
  - Single completed shift -> correct field mapping
  - Multiple shifts -> newest-first order
  - Status filter: completed only
  - Status filter: auto_ended only
  - Invalid status filter -> 422
  - 404 when driver profile not found
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.schemas.admin import (
    ActiveShiftEntry,
    ActiveShiftsResponse,
    DriverShiftEntry,
    DriverShiftHistoryResponse,
)

NOW = datetime(2026, 4, 18, 12, 0, 0, tzinfo=timezone.utc)
EARLIER = datetime(2026, 4, 17, 10, 0, 0, tzinfo=timezone.utc)
EARLIEST = datetime(2026, 4, 16, 8, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_shift(
    shift_id=1,
    driver_user_id=10,
    shift_status="active",
    started_at=NOW,
    ended_at=None,
    total_minutes=None,
    rides_completed=3,
):
    from app.models.driver_shift import ShiftStatus

    s = MagicMock()
    s.id = shift_id
    s.driver_id = driver_user_id
    s.status = ShiftStatus(shift_status)
    s.started_at = started_at
    s.ended_at = ended_at
    s.total_minutes = total_minutes
    s.rides_completed = rides_completed
    return s


def _make_profile(profile_id=1, user_id=10, name="Test Driver"):
    p = MagicMock()
    p.id = profile_id
    p.user_id = user_id
    u = MagicMock()
    u.name = name
    p.user = u
    return p


def _make_admin():
    from app.models.user import User, UserRole
    a = MagicMock(spec=User)
    a.id = 99
    a.role = UserRole.ADMIN
    return a


def _scalar_result(value):
    r = MagicMock()
    r.scalar.return_value = value
    return r


def _scalars_result(items):
    scalars = MagicMock()
    scalars.all.return_value = items
    r = MagicMock()
    r.scalars.return_value = scalars
    return r


def _unique_scalars_result(items):
    unique = MagicMock()
    unique.all.return_value = items
    scalars = MagicMock()
    scalars.unique.return_value = unique
    r = MagicMock()
    r.scalars.return_value = scalars
    return r


def _none_result():
    r = MagicMock()
    r.scalar_one_or_none.return_value = None
    return r


def _one_result(value):
    r = MagicMock()
    r.scalar_one_or_none.return_value = value
    return r


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


class TestDriverShiftEntrySchema:
    def test_all_fields_populated(self):
        entry = DriverShiftEntry(
            id=1,
            status="completed",
            started_at=EARLIER,
            ended_at=NOW,
            total_minutes=120.5,
            rides_completed=5,
        )
        assert entry.id == 1
        assert entry.status == "completed"
        assert entry.total_minutes == 120.5
        assert entry.rides_completed == 5

    def test_nullable_fields_default_to_none(self):
        entry = DriverShiftEntry(
            id=2,
            status="active",
            started_at=NOW,
            ended_at=None,
            total_minutes=None,
            rides_completed=0,
        )
        assert entry.ended_at is None
        assert entry.total_minutes is None


class TestDriverShiftHistoryResponseSchema:
    def test_serializes_correctly(self):
        entry = DriverShiftEntry(
            id=1, status="completed", started_at=NOW, ended_at=NOW,
            total_minutes=60.0, rides_completed=2,
        )
        resp = DriverShiftHistoryResponse(driver_id=5, total=1, items=[entry])
        assert resp.driver_id == 5
        assert resp.total == 1
        assert len(resp.items) == 1


class TestActiveShiftEntrySchema:
    def test_all_fields_populated(self):
        entry = ActiveShiftEntry(
            shift_id=1,
            driver_profile_id=3,
            user_id=10,
            driver_name="Alice Driver",
            started_at=NOW,
            rides_completed=4,
        )
        assert entry.shift_id == 1
        assert entry.driver_profile_id == 3
        assert entry.driver_name == "Alice Driver"

    def test_driver_name_nullable(self):
        entry = ActiveShiftEntry(
            shift_id=2, driver_profile_id=0, user_id=99,
            driver_name=None, started_at=NOW, rides_completed=0,
        )
        assert entry.driver_name is None


class TestActiveShiftsResponseSchema:
    def test_serializes_correctly(self):
        entry = ActiveShiftEntry(
            shift_id=1, driver_profile_id=3, user_id=10,
            driver_name="Bob", started_at=NOW, rides_completed=2,
        )
        resp = ActiveShiftsResponse(total=1, items=[entry])
        assert resp.total == 1
        assert len(resp.items) == 1


# ---------------------------------------------------------------------------
# admin_list_active_shifts tests
# ---------------------------------------------------------------------------


class TestAdminListActiveShifts:
    @pytest.mark.asyncio
    async def test_no_active_shifts(self):
        from app.api.v1.admin import admin_list_active_shifts

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            _scalar_result(0),      # count query
            _scalars_result([]),    # shifts query
        ])

        result = await admin_list_active_shifts(
            skip=0, limit=50, _admin=_make_admin(), db=db
        )
        assert result.total == 0
        assert result.items == []

    @pytest.mark.asyncio
    async def test_single_active_shift_correct_mapping(self):
        from app.api.v1.admin import admin_list_active_shifts

        shift = _make_shift(shift_id=1, driver_user_id=10, rides_completed=3)
        profile = _make_profile(profile_id=5, user_id=10, name="Alice")

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            _scalar_result(1),
            _scalars_result([shift]),
            _unique_scalars_result([profile]),
        ])

        result = await admin_list_active_shifts(
            skip=0, limit=50, _admin=_make_admin(), db=db
        )
        assert result.total == 1
        item = result.items[0]
        assert item.shift_id == 1
        assert item.driver_profile_id == 5
        assert item.user_id == 10
        assert item.driver_name == "Alice"
        assert item.rides_completed == 3
        assert item.started_at == NOW

    @pytest.mark.asyncio
    async def test_multiple_shifts_newest_first(self):
        from app.api.v1.admin import admin_list_active_shifts

        shift1 = _make_shift(shift_id=1, driver_user_id=10, started_at=NOW)
        shift2 = _make_shift(shift_id=2, driver_user_id=11, started_at=EARLIER)
        p1 = _make_profile(profile_id=5, user_id=10, name="Alice")
        p2 = _make_profile(profile_id=6, user_id=11, name="Bob")

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            _scalar_result(2),
            _scalars_result([shift1, shift2]),
            _unique_scalars_result([p1, p2]),
        ])

        result = await admin_list_active_shifts(
            skip=0, limit=50, _admin=_make_admin(), db=db
        )
        assert result.total == 2
        assert result.items[0].shift_id == 1
        assert result.items[1].shift_id == 2

    @pytest.mark.asyncio
    async def test_missing_profile_uses_fallback(self):
        """Driver shift with no matching DriverProfile -> profile_id=0, name=None."""
        from app.api.v1.admin import admin_list_active_shifts

        shift = _make_shift(shift_id=1, driver_user_id=99)

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            _scalar_result(1),
            _scalars_result([shift]),
            _unique_scalars_result([]),  # no matching profile
        ])

        result = await admin_list_active_shifts(
            skip=0, limit=50, _admin=_make_admin(), db=db
        )
        assert result.total == 1
        item = result.items[0]
        assert item.driver_profile_id == 0
        assert item.driver_name is None

    @pytest.mark.asyncio
    async def test_pagination_respected(self):
        from app.api.v1.admin import admin_list_active_shifts

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            _scalar_result(10),
            _scalars_result([]),
        ])

        result = await admin_list_active_shifts(
            skip=5, limit=3, _admin=_make_admin(), db=db
        )
        assert result.total == 10
        assert result.items == []


# ---------------------------------------------------------------------------
# admin_get_driver_shift_history tests
# ---------------------------------------------------------------------------


class TestAdminGetDriverShiftHistory:
    @pytest.mark.asyncio
    async def test_404_when_driver_not_found(self):
        from fastapi import HTTPException
        from app.api.v1.admin import admin_get_driver_shift_history

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_none_result())

        with pytest.raises(HTTPException) as exc_info:
            await admin_get_driver_shift_history(
                driver_id=999, skip=0, limit=50, status_filter=None,
                _admin=_make_admin(), db=db,
            )
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_empty_history(self):
        from app.api.v1.admin import admin_get_driver_shift_history

        profile = _make_profile(profile_id=1, user_id=10)
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            _one_result(profile),
            _scalar_result(0),
            _scalars_result([]),
        ])

        result = await admin_get_driver_shift_history(
            driver_id=1, skip=0, limit=50, status_filter=None,
            _admin=_make_admin(), db=db,
        )
        assert result.driver_id == 1
        assert result.total == 0
        assert result.items == []

    @pytest.mark.asyncio
    async def test_single_completed_shift_field_mapping(self):
        from app.api.v1.admin import admin_get_driver_shift_history

        profile = _make_profile(profile_id=1, user_id=10)
        shift = _make_shift(
            shift_id=7, driver_user_id=10, shift_status="completed",
            started_at=EARLIER, ended_at=NOW, total_minutes=90.0, rides_completed=4,
        )
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            _one_result(profile),
            _scalar_result(1),
            _scalars_result([shift]),
        ])

        result = await admin_get_driver_shift_history(
            driver_id=1, skip=0, limit=50, status_filter=None,
            _admin=_make_admin(), db=db,
        )
        assert result.total == 1
        item = result.items[0]
        assert item.id == 7
        assert item.status == "completed"
        assert item.started_at == EARLIER
        assert item.ended_at == NOW
        assert item.total_minutes == 90.0
        assert item.rides_completed == 4

    @pytest.mark.asyncio
    async def test_multiple_shifts_newest_first(self):
        from app.api.v1.admin import admin_get_driver_shift_history

        profile = _make_profile(profile_id=1, user_id=10)
        shift1 = _make_shift(shift_id=3, driver_user_id=10, started_at=NOW)
        shift2 = _make_shift(shift_id=2, driver_user_id=10, started_at=EARLIER)
        shift3 = _make_shift(shift_id=1, driver_user_id=10, started_at=EARLIEST)
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            _one_result(profile),
            _scalar_result(3),
            _scalars_result([shift1, shift2, shift3]),
        ])

        result = await admin_get_driver_shift_history(
            driver_id=1, skip=0, limit=50, status_filter=None,
            _admin=_make_admin(), db=db,
        )
        assert result.total == 3
        assert result.items[0].id == 3
        assert result.items[1].id == 2
        assert result.items[2].id == 1

    @pytest.mark.asyncio
    async def test_status_filter_completed(self):
        from app.api.v1.admin import admin_get_driver_shift_history

        profile = _make_profile(profile_id=1, user_id=10)
        shift = _make_shift(shift_id=5, shift_status="completed")
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            _one_result(profile),
            _scalar_result(1),
            _scalars_result([shift]),
        ])

        result = await admin_get_driver_shift_history(
            driver_id=1, skip=0, limit=50, status_filter="completed",
            _admin=_make_admin(), db=db,
        )
        assert result.total == 1
        assert result.items[0].status == "completed"

    @pytest.mark.asyncio
    async def test_status_filter_auto_ended(self):
        from app.api.v1.admin import admin_get_driver_shift_history

        profile = _make_profile(profile_id=1, user_id=10)
        shift = _make_shift(shift_id=6, shift_status="auto_ended")
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            _one_result(profile),
            _scalar_result(1),
            _scalars_result([shift]),
        ])

        result = await admin_get_driver_shift_history(
            driver_id=1, skip=0, limit=50, status_filter="auto_ended",
            _admin=_make_admin(), db=db,
        )
        assert result.total == 1
        assert result.items[0].status == "auto_ended"

    @pytest.mark.asyncio
    async def test_invalid_status_filter_raises_422(self):
        from fastapi import HTTPException
        from app.api.v1.admin import admin_get_driver_shift_history

        profile = _make_profile(profile_id=1, user_id=10)
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_one_result(profile))

        with pytest.raises(HTTPException) as exc_info:
            await admin_get_driver_shift_history(
                driver_id=1, skip=0, limit=50, status_filter="invalid_status",
                _admin=_make_admin(), db=db,
            )
        assert exc_info.value.status_code == 422
