"""Unit tests for driver shift management endpoints.

Tests cover:
  - POST /driver/me/shifts/start — creates a new shift
  - POST /driver/me/shifts/start — 409 when active shift already exists
  - POST /driver/me/shifts/end   — ends active shift and computes total_minutes
  - POST /driver/me/shifts/end   — 404 when no active shift
  - GET  /driver/me/shifts/active — returns active shift
  - GET  /driver/me/shifts/active — 404 when none
  - GET  /driver/me/shifts        — paginated list, newest first
  - GET  /driver/me/shifts        — empty list when no shifts
  - All authenticated endpoints return 401 without credentials
  - Schema serialises correctly
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.driver_shift import ShiftStatus
from app.schemas.driver_shift import DriverShiftListResponse, DriverShiftResponse

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 4, 18, 12, 0, 0, tzinfo=timezone.utc)
DRIVER_ID = 5


def _fake_shift(
    id: int = 1,
    driver_id: int = DRIVER_ID,
    status: ShiftStatus = ShiftStatus.active,
    started_at: datetime = _NOW,
    ended_at: datetime | None = None,
    total_minutes: float | None = None,
    rides_completed: int = 0,
) -> MagicMock:
    s = MagicMock()
    s.id = id
    s.driver_id = driver_id
    s.status = status
    s.started_at = started_at
    s.ended_at = ended_at
    s.total_minutes = total_minutes
    s.rides_completed = rides_completed
    return s


def _driver_user(id: int = DRIVER_ID) -> MagicMock:
    u = MagicMock()
    u.id = id
    u.role = "driver"
    return u


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


class TestDriverShiftSchema:
    def test_response_serialises_active_shift(self):
        resp = DriverShiftResponse(
            id=1,
            driver_id=DRIVER_ID,
            status=ShiftStatus.active,
            started_at=_NOW,
            ended_at=None,
            total_minutes=None,
            rides_completed=0,
        )
        data = resp.model_dump()
        assert data["status"] == ShiftStatus.active
        assert data["ended_at"] is None
        assert data["rides_completed"] == 0

    def test_response_serialises_completed_shift(self):
        from datetime import timedelta

        ended = _NOW + timedelta(hours=4)
        resp = DriverShiftResponse(
            id=2,
            driver_id=DRIVER_ID,
            status=ShiftStatus.completed,
            started_at=_NOW,
            ended_at=ended,
            total_minutes=240.0,
            rides_completed=8,
        )
        data = resp.model_dump()
        assert data["total_minutes"] == 240.0
        assert data["rides_completed"] == 8

    def test_list_response_serialises(self):
        resp = DriverShiftListResponse(
            items=[
                DriverShiftResponse(
                    id=1,
                    driver_id=DRIVER_ID,
                    status=ShiftStatus.active,
                    started_at=_NOW,
                    ended_at=None,
                    total_minutes=None,
                    rides_completed=0,
                )
            ],
            total=1,
            page=1,
            page_size=20,
        )
        assert len(resp.items) == 1
        assert resp.total == 1


# ---------------------------------------------------------------------------
# POST /driver/me/shifts/start
# ---------------------------------------------------------------------------


class TestStartShift:
    @pytest.mark.asyncio
    async def test_creates_shift_when_none_active(self):
        from app.api.v1.driver_shifts import start_shift

        db = AsyncMock()
        result_no_active = MagicMock()
        result_no_active.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=result_no_active)
        db.add = MagicMock()
        db.commit = AsyncMock()

        added_shift: list = []

        def capture_add(obj):
            # Populate required fields so model_validate succeeds after refresh
            obj.id = 1
            obj.ended_at = None
            obj.total_minutes = None
            obj.rides_completed = 0
            added_shift.append(obj)

        db.add = MagicMock(side_effect=capture_add)
        db.refresh = AsyncMock()

        await start_shift(driver=_driver_user(), db=db)

        assert len(added_shift) == 1
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_409_when_active_shift_exists(self):
        from fastapi import HTTPException

        from app.api.v1.driver_shifts import start_shift

        db = AsyncMock()
        result_active = MagicMock()
        result_active.scalar_one_or_none.return_value = _fake_shift()
        db.execute = AsyncMock(return_value=result_active)

        with pytest.raises(HTTPException) as exc:
            await start_shift(driver=_driver_user(), db=db)
        assert exc.value.status_code == 409

    def test_requires_auth(self):
        client = TestClient(app)
        resp = client.post("/api/v1/driver/me/shifts/start")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# POST /driver/me/shifts/end
# ---------------------------------------------------------------------------


class TestEndShift:
    @pytest.mark.asyncio
    async def test_ends_active_shift(self):
        from app.api.v1.driver_shifts import end_shift

        shift = _fake_shift()
        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = shift
        db.execute = AsyncMock(return_value=result)
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        await end_shift(driver=_driver_user(), db=db)

        assert shift.status == ShiftStatus.completed
        assert shift.ended_at is not None
        assert shift.total_minutes is not None
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_404_when_no_active_shift(self):
        from fastapi import HTTPException

        from app.api.v1.driver_shifts import end_shift

        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=result)

        with pytest.raises(HTTPException) as exc:
            await end_shift(driver=_driver_user(), db=db)
        assert exc.value.status_code == 404

    def test_requires_auth(self):
        client = TestClient(app)
        resp = client.post("/api/v1/driver/me/shifts/end")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /driver/me/shifts/active
# ---------------------------------------------------------------------------


class TestGetActiveShift:
    @pytest.mark.asyncio
    async def test_returns_active_shift(self):
        from app.api.v1.driver_shifts import get_active_shift

        shift = _fake_shift()
        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = shift
        db.execute = AsyncMock(return_value=result)

        resp = await get_active_shift(driver=_driver_user(), db=db)
        assert resp.id == shift.id
        assert resp.status == ShiftStatus.active

    @pytest.mark.asyncio
    async def test_returns_404_when_no_active_shift(self):
        from fastapi import HTTPException

        from app.api.v1.driver_shifts import get_active_shift

        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=result)

        with pytest.raises(HTTPException) as exc:
            await get_active_shift(driver=_driver_user(), db=db)
        assert exc.value.status_code == 404

    def test_requires_auth(self):
        client = TestClient(app)
        resp = client.get("/api/v1/driver/me/shifts/active")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /driver/me/shifts
# ---------------------------------------------------------------------------


class TestListShifts:
    @pytest.mark.asyncio
    async def test_returns_paginated_shifts(self):
        from app.api.v1.driver_shifts import list_shifts

        shifts = [_fake_shift(id=i) for i in range(1, 4)]

        db = AsyncMock()

        count_result = MagicMock()
        count_result.scalar_one.return_value = 3

        list_result = MagicMock()
        list_result.scalars.return_value.all.return_value = shifts

        db.execute = AsyncMock(side_effect=[count_result, list_result])

        resp = await list_shifts(page=1, page_size=20, driver=_driver_user(), db=db)

        assert resp.total == 3
        assert len(resp.items) == 3
        assert resp.page == 1
        assert resp.page_size == 20

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_shifts(self):
        from app.api.v1.driver_shifts import list_shifts

        db = AsyncMock()

        count_result = MagicMock()
        count_result.scalar_one.return_value = 0

        list_result = MagicMock()
        list_result.scalars.return_value.all.return_value = []

        db.execute = AsyncMock(side_effect=[count_result, list_result])

        resp = await list_shifts(page=1, page_size=20, driver=_driver_user(), db=db)

        assert resp.total == 0
        assert resp.items == []

    def test_requires_auth(self):
        client = TestClient(app)
        resp = client.get("/api/v1/driver/me/shifts")
        assert resp.status_code == 401

    def test_default_pagination_params(self):
        """Verify page and page_size params exist with expected defaults."""
        from app.api.v1.driver_shifts import list_shifts
        import inspect

        sig = inspect.signature(list_shifts)
        # FastAPI wraps defaults in Query(...); check the .default attribute
        assert sig.parameters["page"].default.default == 1
        assert sig.parameters["page_size"].default.default == 20
