"""Tests for driver shift and hours-tracking system.

Service layer (unit tests with mocked DB):
  1.  start_shift — creates shift when none active
  2.  start_shift — raises 409 when active shift exists
  3.  end_shift — ends active shift, computes total_minutes
  4.  end_shift — raises 404 when no active shift
  5.  get_active_shift — returns None when no active shift
  6.  get_active_shift — returns shift when one is active
  7.  list_driver_shifts — returns paginated results
  8.  get_hours_summary — returns correct structure
  9.  get_fatigue_status — no active shift: has_active_shift=False
  10. get_fatigue_status — active shift under 4h: break_recommended=False
  11. get_fatigue_status — active shift over 4h: break_recommended=True
  12. admin_force_end_shift — ends shift, marks auto_ended
  13. admin_force_end_shift — raises 404 when not found
  14. admin_force_end_shift — raises 409 when not active
  15. admin_list_shifts — returns all shifts when no filter
  16. admin_hours_summary — returns correct structure

API layer (integration-style, skipped without live DB):
  17. POST /drivers/me/shift/start — 201 creates shift
  18. POST /drivers/me/shift/start — 401 unauthenticated
  19. POST /drivers/me/shift/start — 409 when already active
  20. POST /drivers/me/shift/end — 200 ends active shift
  21. POST /drivers/me/shift/end — 404 when no active shift
  22. POST /drivers/me/shift/end — 401 unauthenticated
  23. GET  /drivers/me/shift/current — 200 returns active shift
  24. GET  /drivers/me/shift/current — 404 when no active shift
  25. GET  /drivers/me/shift/current — 401 unauthenticated
  26. GET  /drivers/me/shifts — 200 returns list
  27. GET  /drivers/me/shifts — 401 unauthenticated
  28. GET  /drivers/me/shifts — pagination params respected
  29. GET  /drivers/me/hours/summary — 200 returns summary structure
  30. GET  /drivers/me/hours/summary — 401 unauthenticated
  31. GET  /drivers/me/shift/fatigue — 200 returns fatigue structure
  32. GET  /drivers/me/shift/fatigue — 401 unauthenticated
  33. GET  /admin/driver-shifts — 200 returns all shifts
  34. GET  /admin/driver-shifts — 403 non-admin
  35. GET  /admin/driver-shifts?status=active — filtered
  36. GET  /admin/driver-hours/summary — 200 returns summary
  37. GET  /admin/driver-hours/summary — 403 non-admin
  38. POST /admin/driver-shifts/{id}/end — 200 force-ends shift
  39. POST /admin/driver-shifts/{id}/end — 404 shift not found
  40. POST /admin/driver-shifts/{id}/end — 409 shift not active
  41. POST /admin/driver-shifts/{id}/end — 403 non-admin
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.driver_shift import DriverShift, ShiftStatus
from app.models.user import User, UserRole
from app.services.auth import create_access_token, hash_password
from app.services.driver_shift import (
    admin_force_end_shift,
    admin_hours_summary,
    admin_list_shifts,
    end_shift,
    get_active_shift,
    get_fatigue_status,
    get_hours_summary,
    list_driver_shifts,
    start_shift,
)


# ===========================================================================
# Helpers / factories
# ===========================================================================


def _make_shift(
    *,
    shift_id: int = 1,
    driver_id: int = 42,
    status: ShiftStatus = ShiftStatus.active,
    started_at: datetime | None = None,
    ended_at: datetime | None = None,
    total_minutes: float | None = None,
    rides_completed: int = 0,
) -> MagicMock:
    s = MagicMock(spec=DriverShift)
    s.id = shift_id
    s.driver_id = driver_id
    s.status = status
    s.started_at = started_at or datetime(2026, 4, 15, 8, 0, tzinfo=timezone.utc)
    s.ended_at = ended_at
    s.total_minutes = total_minutes
    s.rides_completed = rides_completed
    s.admin_note = None
    s.ended_by_admin_id = None
    s.created_at = datetime(2026, 4, 15, 8, 0, tzinfo=timezone.utc)
    return s


def _scalar_result(value):
    """Return a mock execute() result with .scalars().first() → value."""
    m = MagicMock()
    m.scalar_one.return_value = value
    inner = MagicMock()
    inner.first.return_value = value
    inner.all.return_value = [value] if value is not None else []
    m.scalars.return_value = inner
    return m


def _scalar_result_list(values: list):
    m = MagicMock()
    m.scalar_one.return_value = len(values)
    inner = MagicMock()
    inner.all.return_value = values
    m.scalars.return_value = inner
    return m


# ===========================================================================
# PART 1 — Service unit tests (mocked DB)
# ===========================================================================


class TestStartShift:
    @pytest.mark.anyio
    async def test_creates_shift_when_none_active(self):
        db = AsyncMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        with patch("app.services.driver_shift._get_active_shift", return_value=None):
            result = await start_shift(db, driver_id=42)

        db.add.assert_called_once()
        db.commit.assert_called_once()
        # The shift object added should be a DriverShift instance
        added_shift = db.add.call_args[0][0]
        assert isinstance(added_shift, DriverShift)
        assert added_shift.driver_id == 42
        assert added_shift.status == ShiftStatus.active

    @pytest.mark.anyio
    async def test_raises_409_when_active_shift_exists(self):
        from fastapi import HTTPException

        existing = _make_shift()
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalar_result(existing))

        with pytest.raises(HTTPException) as exc:
            await start_shift(db, driver_id=42)
        assert exc.value.status_code == 409


class TestEndShift:
    @pytest.mark.anyio
    async def test_ends_active_shift_and_computes_minutes(self):
        # Use a relative start time to avoid clock-skew failures on the Pi
        started = datetime.now(timezone.utc) - timedelta(hours=3)
        shift = _make_shift(started_at=started)
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalar_result(shift))
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        result = await end_shift(db, driver_id=42)

        assert result.status == ShiftStatus.completed
        assert result.ended_at is not None
        assert result.total_minutes is not None
        assert result.total_minutes >= 0

    @pytest.mark.anyio
    async def test_raises_404_when_no_active_shift(self):
        from fastapi import HTTPException

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalar_result(None))

        with pytest.raises(HTTPException) as exc:
            await end_shift(db, driver_id=42)
        assert exc.value.status_code == 404


class TestGetActiveShift:
    @pytest.mark.anyio
    async def test_returns_none_when_no_shift(self):
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalar_result(None))
        result = await get_active_shift(db, driver_id=42)
        assert result is None

    @pytest.mark.anyio
    async def test_returns_shift_when_active(self):
        shift = _make_shift()
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalar_result(shift))
        result = await get_active_shift(db, driver_id=42)
        assert result is shift


class TestListDriverShifts:
    @pytest.mark.anyio
    async def test_returns_paginated_shifts(self):
        shifts = [_make_shift(shift_id=i) for i in range(3)]
        db = AsyncMock()
        # First call returns count, second call returns shifts
        db.execute = AsyncMock(
            side_effect=[
                _scalar_result(3),           # count
                _scalar_result_list(shifts),  # shifts
            ]
        )
        result_shifts, total = await list_driver_shifts(db, driver_id=42, limit=10)
        assert total == 3
        assert len(result_shifts) == 3


class TestGetHoursSummary:
    @pytest.mark.anyio
    async def test_returns_correct_structure(self):
        db = AsyncMock()

        # _get_day_minutes calls: completed minutes (0.0), active shift check (None)
        # _get_week_minutes calls: completed minutes (0.0), active shift check (None)
        # daily shift count, weekly shift count, active shift check
        db.execute = AsyncMock(
            side_effect=[
                _scalar_result(0.0),   # day completed minutes
                _scalar_result(None),  # active shift (day)
                _scalar_result(0.0),   # week completed minutes
                _scalar_result(None),  # active shift (week)
                _scalar_result(0),     # daily shifts count
                _scalar_result(0),     # weekly shifts count
                _scalar_result(None),  # active shift (final)
            ]
        )
        result = await get_hours_summary(db, driver_id=42)
        assert "driver_id" in result
        assert "today" in result
        assert "weekly_hours" in result
        assert "at_weekly_limit" in result
        assert result["driver_id"] == 42


class TestGetFatigueStatus:
    @pytest.mark.anyio
    async def test_no_active_shift_returns_has_active_false(self):
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _scalar_result(None),  # active shift check
                _scalar_result(0.0),   # day completed minutes
                _scalar_result(None),  # active shift (day calc)
                _scalar_result(0.0),   # week completed minutes
                _scalar_result(None),  # active shift (week calc)
            ]
        )
        result = await get_fatigue_status(db, driver_id=42)
        assert result["has_active_shift"] is False
        assert result["break_recommended"] is False
        assert result["shift_minutes_elapsed"] is None

    @pytest.mark.anyio
    async def test_active_shift_under_4h_no_break_recommended(self):
        # Shift started 2 hours ago
        started = datetime.now(timezone.utc) - timedelta(hours=2)
        shift = _make_shift(started_at=started)
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _scalar_result(shift),   # active shift
                _scalar_result(0.0),     # day completed minutes
                _scalar_result(shift),   # active shift (day calc)
                _scalar_result(0.0),     # week completed minutes
                _scalar_result(shift),   # active shift (week calc)
            ]
        )
        result = await get_fatigue_status(db, driver_id=42)
        assert result["has_active_shift"] is True
        assert result["break_recommended"] is False
        assert result["shift_minutes_elapsed"] is not None
        assert result["shift_minutes_elapsed"] > 0

    @pytest.mark.anyio
    async def test_active_shift_over_4h_break_recommended(self):
        # Shift started 5 hours ago
        started = datetime.now(timezone.utc) - timedelta(hours=5)
        shift = _make_shift(started_at=started)
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _scalar_result(shift),   # active shift
                _scalar_result(0.0),     # day completed minutes
                _scalar_result(shift),   # active shift (day calc)
                _scalar_result(0.0),     # week completed minutes
                _scalar_result(shift),   # active shift (week calc)
            ]
        )
        result = await get_fatigue_status(db, driver_id=42)
        assert result["has_active_shift"] is True
        assert result["break_recommended"] is True
        assert result["minutes_until_break_due"] == 0.0


class TestAdminForceEndShift:
    @pytest.mark.anyio
    async def test_ends_shift_marks_auto_ended(self):
        shift = _make_shift()
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalar_result(shift))
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        result = await admin_force_end_shift(db, shift_id=1, admin_id=99, admin_note="Over limit")

        assert result.status == ShiftStatus.auto_ended
        assert result.ended_by_admin_id == 99
        assert result.admin_note == "Over limit"
        assert result.ended_at is not None
        assert result.total_minutes is not None

    @pytest.mark.anyio
    async def test_raises_404_when_shift_not_found(self):
        from fastapi import HTTPException

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalar_result(None))

        with pytest.raises(HTTPException) as exc:
            await admin_force_end_shift(db, shift_id=999, admin_id=99, admin_note=None)
        assert exc.value.status_code == 404

    @pytest.mark.anyio
    async def test_raises_409_when_shift_not_active(self):
        from fastapi import HTTPException

        completed_shift = _make_shift(status=ShiftStatus.completed)
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalar_result(completed_shift))

        with pytest.raises(HTTPException) as exc:
            await admin_force_end_shift(db, shift_id=1, admin_id=99, admin_note=None)
        assert exc.value.status_code == 409


class TestAdminListShifts:
    @pytest.mark.anyio
    async def test_returns_all_shifts_no_filter(self):
        shifts = [_make_shift(shift_id=i) for i in range(5)]
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _scalar_result(5),
                _scalar_result_list(shifts),
            ]
        )
        result_shifts, total = await admin_list_shifts(db)
        assert total == 5
        assert len(result_shifts) == 5


class TestAdminHoursSummary:
    @pytest.mark.anyio
    async def test_returns_correct_structure(self):
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _scalar_result(3),          # active count
                _scalar_result_list([]),    # drivers today
                _scalar_result_list([]),    # drivers this week
                _scalar_result(None),       # avg shift today
            ]
        )
        result = await admin_hours_summary(db)
        assert "total_active_shifts" in result
        assert "drivers_near_daily_limit" in result
        assert "drivers_near_weekly_limit" in result
        assert "drivers_over_daily_limit" in result
        assert "drivers_over_weekly_limit" in result
        assert "average_shift_hours_today" in result
        assert result["total_active_shifts"] == 3


# ===========================================================================
# PART 2 — API integration tests (require live DB; skipped otherwise)
# ===========================================================================

try:
    from tests.conftest import client, db, admin_token, driver_token, driver_user  # type: ignore
    HAS_TEST_DB = True
except Exception:
    HAS_TEST_DB = False


def _driver_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def driver(db):
    """Create a driver user with a driver profile."""
    from app.models.driver import DriverProfile

    user = User(
        email="shiftdriver@example.com",
        hashed_password=hash_password("pw"),
        full_name="Shift Driver",
        role=UserRole.driver,
        is_active=True,
    )
    db.add(user)
    await db.flush()

    profile = DriverProfile(
        user_id=user.id,
        license_number="SD12345",
        license_state="CA",
        is_approved=True,
    )
    db.add(profile)
    await db.commit()
    await db.refresh(user)
    return user


@pytest.fixture
def driver_shift_token(driver):
    return create_access_token({"sub": str(driver.id), "role": "driver"})


@pytest.fixture
async def active_shift(db, driver):
    """Create an active shift for the driver."""
    shift = DriverShift(driver_id=driver.id, status=ShiftStatus.active)
    db.add(shift)
    await db.commit()
    await db.refresh(shift)
    return shift


@pytest.fixture
async def completed_shift(db, driver):
    """Create a completed shift for the driver."""
    now = datetime.now(timezone.utc)
    shift = DriverShift(
        driver_id=driver.id,
        status=ShiftStatus.completed,
        started_at=now - timedelta(hours=3),
        ended_at=now,
        total_minutes=180.0,
    )
    db.add(shift)
    await db.commit()
    await db.refresh(shift)
    return shift


# ---------------------------------------------------------------------------
# POST /drivers/me/shift/start
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_api_start_shift_success(client, driver, driver_shift_token, db):
    resp = await client.post(
        "/api/v1/drivers/me/shift/start",
        headers=_driver_headers(driver_shift_token),
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["status"] == "active"
    assert data["driver_id"] == driver.id
    assert data["ended_at"] is None


@pytest.mark.anyio
async def test_api_start_shift_unauthenticated(client):
    resp = await client.post("/api/v1/drivers/me/shift/start")
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_api_start_shift_conflict(client, driver, driver_shift_token, active_shift, db):
    resp = await client.post(
        "/api/v1/drivers/me/shift/start",
        headers=_driver_headers(driver_shift_token),
    )
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# POST /drivers/me/shift/end
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_api_end_shift_success(client, driver, driver_shift_token, active_shift, db):
    resp = await client.post(
        "/api/v1/drivers/me/shift/end",
        headers=_driver_headers(driver_shift_token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "completed"
    assert data["ended_at"] is not None
    assert data["total_minutes"] is not None


@pytest.mark.anyio
async def test_api_end_shift_not_found(client, driver, driver_shift_token, db):
    resp = await client.post(
        "/api/v1/drivers/me/shift/end",
        headers=_driver_headers(driver_shift_token),
    )
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_api_end_shift_unauthenticated(client):
    resp = await client.post("/api/v1/drivers/me/shift/end")
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# GET /drivers/me/shift/current
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_api_current_shift_returns_active(client, driver, driver_shift_token, active_shift, db):
    resp = await client.get(
        "/api/v1/drivers/me/shift/current",
        headers=_driver_headers(driver_shift_token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "active"
    assert data["id"] == active_shift.id


@pytest.mark.anyio
async def test_api_current_shift_404_when_none(client, driver, driver_shift_token, db):
    resp = await client.get(
        "/api/v1/drivers/me/shift/current",
        headers=_driver_headers(driver_shift_token),
    )
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_api_current_shift_unauthenticated(client):
    resp = await client.get("/api/v1/drivers/me/shift/current")
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# GET /drivers/me/shifts
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_api_list_shifts_success(client, driver, driver_shift_token, completed_shift, db):
    resp = await client.get(
        "/api/v1/drivers/me/shifts",
        headers=_driver_headers(driver_shift_token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "shifts" in data
    assert "total" in data
    assert data["total"] >= 1


@pytest.mark.anyio
async def test_api_list_shifts_unauthenticated(client):
    resp = await client.get("/api/v1/drivers/me/shifts")
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_api_list_shifts_pagination(client, driver, driver_shift_token, completed_shift, db):
    resp = await client.get(
        "/api/v1/drivers/me/shifts?limit=1&offset=0",
        headers=_driver_headers(driver_shift_token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["shifts"]) <= 1


# ---------------------------------------------------------------------------
# GET /drivers/me/hours/summary
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_api_hours_summary_success(client, driver, driver_shift_token, completed_shift, db):
    resp = await client.get(
        "/api/v1/drivers/me/hours/summary",
        headers=_driver_headers(driver_shift_token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["driver_id"] == driver.id
    assert "today" in data
    assert "weekly_hours" in data
    assert "at_weekly_limit" in data
    assert data["today"]["hours_worked"] >= 0


@pytest.mark.anyio
async def test_api_hours_summary_unauthenticated(client):
    resp = await client.get("/api/v1/drivers/me/hours/summary")
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# GET /drivers/me/shift/fatigue
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_api_fatigue_status_no_active_shift(client, driver, driver_shift_token, db):
    resp = await client.get(
        "/api/v1/drivers/me/shift/fatigue",
        headers=_driver_headers(driver_shift_token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["has_active_shift"] is False
    assert data["break_recommended"] is False
    assert "max_hours_per_day" in data
    assert "break_after_hours" in data


@pytest.mark.anyio
async def test_api_fatigue_status_unauthenticated(client):
    resp = await client.get("/api/v1/drivers/me/shift/fatigue")
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# GET /admin/driver-shifts
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_api_admin_list_shifts(client, admin_token, completed_shift, db):
    resp = await client.get(
        "/api/v1/admin/driver-shifts",
        headers=_driver_headers(admin_token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "shifts" in data
    assert "total" in data


@pytest.mark.anyio
async def test_api_admin_list_shifts_forbidden(client, driver_shift_token):
    resp = await client.get(
        "/api/v1/admin/driver-shifts",
        headers=_driver_headers(driver_shift_token),
    )
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_api_admin_list_shifts_status_filter(client, admin_token, active_shift, db):
    resp = await client.get(
        "/api/v1/admin/driver-shifts?status=active",
        headers=_driver_headers(admin_token),
    )
    assert resp.status_code == 200
    data = resp.json()
    for s in data["shifts"]:
        assert s["status"] == "active"


# ---------------------------------------------------------------------------
# GET /admin/driver-hours/summary
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_api_admin_hours_summary(client, admin_token, db):
    resp = await client.get(
        "/api/v1/admin/driver-hours/summary",
        headers=_driver_headers(admin_token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "total_active_shifts" in data
    assert "drivers_near_daily_limit" in data
    assert "average_shift_hours_today" in data


@pytest.mark.anyio
async def test_api_admin_hours_summary_forbidden(client, driver_shift_token):
    resp = await client.get(
        "/api/v1/admin/driver-hours/summary",
        headers=_driver_headers(driver_shift_token),
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# POST /admin/driver-shifts/{id}/end
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_api_admin_force_end_shift(client, admin_token, active_shift, db):
    resp = await client.post(
        f"/api/v1/admin/driver-shifts/{active_shift.id}/end",
        headers=_driver_headers(admin_token),
        json={"admin_note": "Driver exceeded daily limit"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "auto_ended"
    assert data["admin_note"] == "Driver exceeded daily limit"


@pytest.mark.anyio
async def test_api_admin_force_end_shift_not_found(client, admin_token, db):
    resp = await client.post(
        "/api/v1/admin/driver-shifts/999999/end",
        headers=_driver_headers(admin_token),
        json={},
    )
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_api_admin_force_end_shift_already_completed(
    client, admin_token, completed_shift, db
):
    resp = await client.post(
        f"/api/v1/admin/driver-shifts/{completed_shift.id}/end",
        headers=_driver_headers(admin_token),
        json={},
    )
    assert resp.status_code == 409


@pytest.mark.anyio
async def test_api_admin_force_end_shift_forbidden(client, driver_shift_token, active_shift, db):
    resp = await client.post(
        f"/api/v1/admin/driver-shifts/{active_shift.id}/end",
        headers=_driver_headers(driver_shift_token),
        json={},
    )
    assert resp.status_code == 403
