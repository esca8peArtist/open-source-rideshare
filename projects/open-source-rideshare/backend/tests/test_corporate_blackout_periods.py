"""Tests for the Corporate Blackout Periods feature.

Service tests (async, mocked DB):
  1.  create_blackout_period — none recurrence success
  2.  create_blackout_period — annual recurrence success
  3.  create_blackout_period — weekly recurrence with affected_days
  4.  create_blackout_period — end <= start → 400
  5.  get_blackout_period — success
  6.  get_blackout_period — wrong account → 404
  7.  list_blackout_periods — all returned, total correct
  8.  list_blackout_periods — active_only=True filters inactive
  9.  list_blackout_periods — from_dt filter applied
  10. list_blackout_periods — to_dt filter applied
  11. update_blackout_period — name update
  12. update_blackout_period — toggle is_active to False
  13. update_blackout_period — end <= start after update → 400
  14. update_blackout_period — not found → 404
  15. delete_blackout_period — success
  16. delete_blackout_period — not found → 404
  17. check_booking_blackout — none recurrence: dt inside window → match
  18. check_booking_blackout — none recurrence: dt before window → no match
  19. check_booking_blackout — none recurrence: dt after window → no match
  20. check_booking_blackout — annual recurrence: dt in annual window → match
  21. check_booking_blackout — annual recurrence: dt outside annual window → no match
  22. check_booking_blackout — weekly recurrence: correct weekday+time → match
  23. check_booking_blackout — weekly recurrence: wrong weekday → no match
  24. check_booking_blackout — weekly recurrence: correct weekday, wrong time → no match
  25. check_booking_blackout — inactive period ignored
  26. check_booking_blackout — multiple periods: returns all matching
  27. check_booking_blackout — no active periods → empty list
  28. check_booking_blackout — dt at inclusive start boundary → match
  29. check_booking_blackout — dt at inclusive end boundary → match

Schema tests (sync):
  30. BlackoutPeriodCreate — valid none recurrence
  31. BlackoutPeriodCreate — end <= start → ValidationError
  32. BlackoutPeriodCreate — end == start → ValidationError
  33. BlackoutPeriodUpdate — all fields optional (empty update valid)
  34. BlackoutPeriodUpdate — end <= start → ValidationError when both provided
  35. BlackoutCheckResponse — structure

API layer tests (asyncio, service patched):
  36. POST /corporate/accounts/me/blackout-periods — 201
  37. GET  /corporate/accounts/me/blackout-periods — 200 list
  38. GET  /corporate/accounts/me/blackout-periods/check — 200 not blacked out
  39. GET  /corporate/accounts/me/blackout-periods/check — 200 blacked out
  40. GET  /corporate/accounts/me/blackout-periods/{id} — 200
  41. PATCH /corporate/accounts/me/blackout-periods/{id} — 200
  42. DELETE /corporate/accounts/me/blackout-periods/{id} — 204
  43. POST /corporate/accounts/me/blackout-periods/{id}/deactivate — 200
  44. GET  /admin/corporate/accounts/{id}/blackout-periods — 200
  45. GET  /admin/corporate/accounts/{id}/blackout-periods/check — 200
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.models.corporate_blackout_period import (
    BlackoutRecurrence,
    CorporateBlackoutPeriod,
)
from app.schemas.corporate_blackout_period import (
    BlackoutCheckResponse,
    BlackoutPeriodCreate,
    BlackoutPeriodListResponse,
    BlackoutPeriodResponse,
    BlackoutPeriodUpdate,
)
from app.services.corporate_blackout_period import (
    _period_covers,
    check_booking_blackout,
    create_blackout_period,
    delete_blackout_period,
    get_blackout_period,
    list_blackout_periods,
    update_blackout_period,
)


# ---------------------------------------------------------------------------
# Shared constants and helpers
# ---------------------------------------------------------------------------

ACCOUNT_ID = 10
OTHER_ACCOUNT_ID = 20
USER_ID = 1
PERIOD_ID = uuid.uuid4()
PERIOD_ID_2 = uuid.uuid4()

# Fixed window: Dec 24–26 2026 (Christmas)
XMAS_START = datetime(2026, 12, 24, 0, 0, 0, tzinfo=timezone.utc)
XMAS_END = datetime(2026, 12, 26, 23, 59, 59, tzinfo=timezone.utc)
XMAS_MID = datetime(2026, 12, 25, 12, 0, 0, tzinfo=timezone.utc)

# Weekly window: Mon–Fri 09:00–17:00
WEEK_START = datetime(2026, 1, 5, 9, 0, 0, tzinfo=timezone.utc)   # Monday
WEEK_END = datetime(2026, 1, 9, 17, 0, 0, tzinfo=timezone.utc)    # Friday (same week for time ref)
NOW = datetime(2026, 4, 15, 12, 0, 0, tzinfo=timezone.utc)


def _make_period(
    period_id: uuid.UUID = PERIOD_ID,
    account_id: int = ACCOUNT_ID,
    name: str = "Christmas Shutdown",
    start_datetime: datetime = XMAS_START,
    end_datetime: datetime = XMAS_END,
    recurrence: BlackoutRecurrence = BlackoutRecurrence.none,
    affected_days: list[int] | None = None,
    override_allowed: bool = False,
    override_requires_approval: bool = True,
    reason: str | None = "Office closed",
    is_active: bool = True,
    created_by_id: int | None = USER_ID,
) -> MagicMock:
    p = MagicMock(spec=CorporateBlackoutPeriod)
    p.id = period_id
    p.corporate_account_id = account_id
    p.name = name
    p.start_datetime = start_datetime
    p.end_datetime = end_datetime
    p.recurrence = recurrence
    p.affected_days = affected_days
    p.override_allowed = override_allowed
    p.override_requires_approval = override_requires_approval
    p.reason = reason
    p.is_active = is_active
    p.created_by_id = created_by_id
    p.created_at = NOW
    p.updated_at = NOW
    return p


def _scalar_result(value) -> MagicMock:
    res = MagicMock()
    res.scalar_one_or_none.return_value = value
    res.scalar.return_value = value
    return res


def _scalars_result(rows: list) -> MagicMock:
    res = MagicMock()
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = rows
    res.scalars.return_value = scalars_mock
    return res


# ---------------------------------------------------------------------------
# 1. create_blackout_period — none recurrence success
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_create_blackout_period_none_recurrence():
    db = AsyncMock()
    db.add = MagicMock()

    data = BlackoutPeriodCreate(
        name="Christmas Shutdown",
        start_datetime=XMAS_START,
        end_datetime=XMAS_END,
    )
    result = await create_blackout_period(db, ACCOUNT_ID, data, created_by_id=USER_ID)

    db.add.assert_called_once()
    db.commit.assert_awaited_once()
    assert result.corporate_account_id == ACCOUNT_ID
    assert result.name == "Christmas Shutdown"
    assert result.recurrence == BlackoutRecurrence.none
    assert result.is_active is True


# ---------------------------------------------------------------------------
# 2. create_blackout_period — annual recurrence success
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_create_blackout_period_annual_recurrence():
    db = AsyncMock()
    db.add = MagicMock()

    data = BlackoutPeriodCreate(
        name="Annual Christmas",
        start_datetime=XMAS_START,
        end_datetime=XMAS_END,
        recurrence="annual",
    )
    result = await create_blackout_period(db, ACCOUNT_ID, data)

    db.add.assert_called_once()
    assert result.recurrence == BlackoutRecurrence.annual


# ---------------------------------------------------------------------------
# 3. create_blackout_period — weekly recurrence with affected_days
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_create_blackout_period_weekly_recurrence():
    db = AsyncMock()
    db.add = MagicMock()

    data = BlackoutPeriodCreate(
        name="Weekday business hours block",
        start_datetime=WEEK_START,
        end_datetime=WEEK_END,
        recurrence="weekly",
        affected_days=[5, 6],  # Sat, Sun
    )
    result = await create_blackout_period(db, ACCOUNT_ID, data)

    db.add.assert_called_once()
    assert result.recurrence == BlackoutRecurrence.weekly
    assert result.affected_days == [5, 6]


# ---------------------------------------------------------------------------
# 4. create_blackout_period — end <= start → 400
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_create_blackout_period_end_before_start_400():
    db = AsyncMock()

    data = BlackoutPeriodCreate.__new__(BlackoutPeriodCreate)
    object.__setattr__(data, "name", "Bad Period")
    object.__setattr__(data, "start_datetime", XMAS_END)
    object.__setattr__(data, "end_datetime", XMAS_START)
    object.__setattr__(data, "recurrence", "none")
    object.__setattr__(data, "affected_days", None)
    object.__setattr__(data, "override_allowed", False)
    object.__setattr__(data, "override_requires_approval", True)
    object.__setattr__(data, "reason", None)

    with pytest.raises(HTTPException) as exc_info:
        await create_blackout_period(db, ACCOUNT_ID, data)

    assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# 5. get_blackout_period — success
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_blackout_period_success():
    db = AsyncMock()
    period = _make_period()
    db.execute.return_value = _scalar_result(period)

    result = await get_blackout_period(db, ACCOUNT_ID, PERIOD_ID)

    assert result.id == PERIOD_ID
    assert result.corporate_account_id == ACCOUNT_ID


# ---------------------------------------------------------------------------
# 6. get_blackout_period — wrong account → 404
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_blackout_period_wrong_account_404():
    db = AsyncMock()
    db.execute.return_value = _scalar_result(None)

    with pytest.raises(HTTPException) as exc_info:
        await get_blackout_period(db, OTHER_ACCOUNT_ID, PERIOD_ID)

    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# 7. list_blackout_periods — all returned, total correct
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_list_blackout_periods_all():
    db = AsyncMock()
    p1 = _make_period(PERIOD_ID)
    p2 = _make_period(PERIOD_ID_2)

    # count query returns both; paged query returns both
    db.execute.side_effect = [
        _scalars_result([p1, p2]),  # count query
        _scalars_result([p1, p2]),  # paged query
    ]

    items, total = await list_blackout_periods(db, ACCOUNT_ID)

    assert total == 2
    assert len(items) == 2


# ---------------------------------------------------------------------------
# 8. list_blackout_periods — active_only=True filters inactive
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_list_blackout_periods_active_only():
    db = AsyncMock()
    active = _make_period(is_active=True)

    db.execute.side_effect = [
        _scalars_result([active]),  # count
        _scalars_result([active]),  # paged
    ]

    items, total = await list_blackout_periods(db, ACCOUNT_ID, active_only=True)

    assert total == 1
    assert items[0].is_active is True


# ---------------------------------------------------------------------------
# 9. list_blackout_periods — from_dt filter
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_list_blackout_periods_from_dt_filter():
    db = AsyncMock()
    period = _make_period()
    db.execute.side_effect = [
        _scalars_result([period]),
        _scalars_result([period]),
    ]

    items, total = await list_blackout_periods(db, ACCOUNT_ID, from_dt=XMAS_START)

    assert total == 1


# ---------------------------------------------------------------------------
# 10. list_blackout_periods — to_dt filter
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_list_blackout_periods_to_dt_filter():
    db = AsyncMock()
    period = _make_period()
    db.execute.side_effect = [
        _scalars_result([period]),
        _scalars_result([period]),
    ]

    items, total = await list_blackout_periods(db, ACCOUNT_ID, to_dt=XMAS_END)

    assert total == 1


# ---------------------------------------------------------------------------
# 11. update_blackout_period — name update
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_update_blackout_period_name():
    db = AsyncMock()
    period = _make_period()
    db.execute.return_value = _scalar_result(period)

    data = BlackoutPeriodUpdate(name="Holiday Closure Updated")
    result = await update_blackout_period(db, ACCOUNT_ID, PERIOD_ID, data)

    assert result.name == "Holiday Closure Updated"
    db.commit.assert_awaited_once()


# ---------------------------------------------------------------------------
# 12. update_blackout_period — toggle is_active to False
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_update_blackout_period_deactivate():
    db = AsyncMock()
    period = _make_period(is_active=True)
    db.execute.return_value = _scalar_result(period)

    data = BlackoutPeriodUpdate(is_active=False)
    result = await update_blackout_period(db, ACCOUNT_ID, PERIOD_ID, data)

    assert result.is_active is False


# ---------------------------------------------------------------------------
# 13. update_blackout_period — end <= start after update → 400
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_update_blackout_period_end_before_start_400():
    db = AsyncMock()
    period = _make_period()
    db.execute.return_value = _scalar_result(period)

    # Set end before current start
    data = BlackoutPeriodUpdate(end_datetime=datetime(2026, 12, 1, tzinfo=timezone.utc))
    with pytest.raises(HTTPException) as exc_info:
        await update_blackout_period(db, ACCOUNT_ID, PERIOD_ID, data)

    assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# 14. update_blackout_period — not found → 404
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_update_blackout_period_not_found_404():
    db = AsyncMock()
    db.execute.return_value = _scalar_result(None)

    data = BlackoutPeriodUpdate(name="irrelevant")
    with pytest.raises(HTTPException) as exc_info:
        await update_blackout_period(db, ACCOUNT_ID, PERIOD_ID, data)

    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# 15. delete_blackout_period — success
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_delete_blackout_period_success():
    db = AsyncMock()
    period = _make_period()
    db.execute.return_value = _scalar_result(period)
    db.delete = AsyncMock()

    await delete_blackout_period(db, ACCOUNT_ID, PERIOD_ID)

    db.delete.assert_awaited_once_with(period)
    db.commit.assert_awaited_once()


# ---------------------------------------------------------------------------
# 16. delete_blackout_period — not found → 404
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_delete_blackout_period_not_found_404():
    db = AsyncMock()
    db.execute.return_value = _scalar_result(None)

    with pytest.raises(HTTPException) as exc_info:
        await delete_blackout_period(db, ACCOUNT_ID, PERIOD_ID)

    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# 17–28: _period_covers unit tests
# ---------------------------------------------------------------------------

# 17. none recurrence: dt inside window → True
def test_period_covers_none_inside():
    p = _make_period(start_datetime=XMAS_START, end_datetime=XMAS_END,
                     recurrence=BlackoutRecurrence.none)
    assert _period_covers(p, XMAS_MID) is True


# 18. none recurrence: dt before window → False
def test_period_covers_none_before():
    p = _make_period(start_datetime=XMAS_START, end_datetime=XMAS_END,
                     recurrence=BlackoutRecurrence.none)
    dt = datetime(2026, 12, 23, 23, 59, tzinfo=timezone.utc)
    assert _period_covers(p, dt) is False


# 19. none recurrence: dt after window → False
def test_period_covers_none_after():
    p = _make_period(start_datetime=XMAS_START, end_datetime=XMAS_END,
                     recurrence=BlackoutRecurrence.none)
    dt = datetime(2026, 12, 27, 0, 1, tzinfo=timezone.utc)
    assert _period_covers(p, dt) is False


# 20. annual recurrence: dt in annual window (same month/day, different year) → True
def test_period_covers_annual_match():
    # Dec 24–26 defined in 2025, checking 2026
    s = datetime(2025, 12, 24, 0, 0, 0, tzinfo=timezone.utc)
    e = datetime(2025, 12, 26, 23, 59, 59, tzinfo=timezone.utc)
    p = _make_period(start_datetime=s, end_datetime=e,
                     recurrence=BlackoutRecurrence.annual)
    # Christmas 2026
    dt = datetime(2026, 12, 25, 12, 0, tzinfo=timezone.utc)
    assert _period_covers(p, dt) is True


# 21. annual recurrence: dt outside annual window → False
def test_period_covers_annual_no_match():
    s = datetime(2025, 12, 24, 0, 0, 0, tzinfo=timezone.utc)
    e = datetime(2025, 12, 26, 23, 59, 59, tzinfo=timezone.utc)
    p = _make_period(start_datetime=s, end_datetime=e,
                     recurrence=BlackoutRecurrence.annual)
    # July 4
    dt = datetime(2026, 7, 4, 12, 0, tzinfo=timezone.utc)
    assert _period_covers(p, dt) is False


# 22. weekly recurrence: correct weekday + time → True
def test_period_covers_weekly_match():
    # Saturday 10:00–18:00 block
    s = datetime(2026, 1, 3, 10, 0, 0, tzinfo=timezone.utc)  # Saturday
    e = datetime(2026, 1, 3, 18, 0, 0, tzinfo=timezone.utc)
    p = _make_period(start_datetime=s, end_datetime=e,
                     recurrence=BlackoutRecurrence.weekly,
                     affected_days=[5, 6])  # Sat=5, Sun=6
    # Next Saturday at noon
    dt = datetime(2026, 4, 18, 13, 0, tzinfo=timezone.utc)  # Saturday
    assert _period_covers(p, dt) is True


# 23. weekly recurrence: wrong weekday → False
def test_period_covers_weekly_wrong_day():
    s = datetime(2026, 1, 3, 10, 0, 0, tzinfo=timezone.utc)
    e = datetime(2026, 1, 3, 18, 0, 0, tzinfo=timezone.utc)
    p = _make_period(start_datetime=s, end_datetime=e,
                     recurrence=BlackoutRecurrence.weekly,
                     affected_days=[5, 6])  # Sat=5, Sun=6
    # Tuesday
    dt = datetime(2026, 4, 14, 13, 0, tzinfo=timezone.utc)  # Tuesday
    assert _period_covers(p, dt) is False


# 24. weekly recurrence: correct weekday, wrong time → False
def test_period_covers_weekly_wrong_time():
    s = datetime(2026, 1, 3, 10, 0, 0, tzinfo=timezone.utc)
    e = datetime(2026, 1, 3, 18, 0, 0, tzinfo=timezone.utc)
    p = _make_period(start_datetime=s, end_datetime=e,
                     recurrence=BlackoutRecurrence.weekly,
                     affected_days=[5, 6])
    # Saturday but 8am (before 10am)
    dt = datetime(2026, 4, 18, 8, 0, tzinfo=timezone.utc)  # Saturday
    assert _period_covers(p, dt) is False


# 25. check_booking_blackout — inactive period ignored
@pytest.mark.anyio
async def test_check_blackout_inactive_period_ignored():
    db = AsyncMock()
    inactive = _make_period(is_active=False, recurrence=BlackoutRecurrence.none)
    db.execute.return_value = _scalars_result([inactive])

    matching = await check_booking_blackout(db, ACCOUNT_ID, XMAS_MID)

    assert matching == []


# 26. check_booking_blackout — multiple periods: returns all matching
@pytest.mark.anyio
async def test_check_blackout_multiple_matching():
    db = AsyncMock()
    p1 = _make_period(PERIOD_ID, recurrence=BlackoutRecurrence.none)
    p2 = _make_period(PERIOD_ID_2, recurrence=BlackoutRecurrence.none)
    db.execute.return_value = _scalars_result([p1, p2])

    matching = await check_booking_blackout(db, ACCOUNT_ID, XMAS_MID)

    assert len(matching) == 2


# 27. check_booking_blackout — no active periods → empty list
@pytest.mark.anyio
async def test_check_blackout_no_periods():
    db = AsyncMock()
    db.execute.return_value = _scalars_result([])

    matching = await check_booking_blackout(db, ACCOUNT_ID, XMAS_MID)

    assert matching == []


# 28. check_booking_blackout — dt at inclusive start boundary → match
def test_period_covers_at_start_boundary():
    p = _make_period(start_datetime=XMAS_START, end_datetime=XMAS_END,
                     recurrence=BlackoutRecurrence.none)
    assert _period_covers(p, XMAS_START) is True


# 29. check_booking_blackout — dt at inclusive end boundary → match
def test_period_covers_at_end_boundary():
    p = _make_period(start_datetime=XMAS_START, end_datetime=XMAS_END,
                     recurrence=BlackoutRecurrence.none)
    assert _period_covers(p, XMAS_END) is True


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


# 30. BlackoutPeriodCreate — valid none recurrence
def test_schema_create_valid():
    data = BlackoutPeriodCreate(
        name="Test Period",
        start_datetime=XMAS_START,
        end_datetime=XMAS_END,
    )
    assert data.name == "Test Period"
    assert data.recurrence == "none"
    assert data.override_allowed is False
    assert data.override_requires_approval is True


# 31. BlackoutPeriodCreate — end before start → ValidationError
def test_schema_create_end_before_start():
    with pytest.raises(ValidationError):
        BlackoutPeriodCreate(
            name="Bad",
            start_datetime=XMAS_END,
            end_datetime=XMAS_START,
        )


# 32. BlackoutPeriodCreate — end == start → ValidationError
def test_schema_create_end_equals_start():
    with pytest.raises(ValidationError):
        BlackoutPeriodCreate(
            name="Bad",
            start_datetime=XMAS_START,
            end_datetime=XMAS_START,
        )


# 33. BlackoutPeriodUpdate — empty update is valid
def test_schema_update_empty():
    data = BlackoutPeriodUpdate()
    assert data.name is None
    assert data.is_active is None


# 34. BlackoutPeriodUpdate — end <= start → ValidationError when both provided
def test_schema_update_end_before_start():
    with pytest.raises(ValidationError):
        BlackoutPeriodUpdate(
            start_datetime=XMAS_END,
            end_datetime=XMAS_START,
        )


# 35. BlackoutCheckResponse — structure
def test_schema_check_response():
    resp = BlackoutCheckResponse(
        dt=XMAS_MID,
        is_blacked_out=False,
        active_periods=[],
    )
    assert resp.is_blacked_out is False
    assert resp.active_periods == []


# ---------------------------------------------------------------------------
# API layer tests
# ---------------------------------------------------------------------------


API_MODULE = "app.api.v1.corporate_blackout_periods"


def _api_period_mock(period_id: uuid.UUID = PERIOD_ID) -> MagicMock:
    """Return a MagicMock that looks like a CorporateBlackoutPeriod ORM row."""
    p = MagicMock()
    p.id = period_id
    p.corporate_account_id = ACCOUNT_ID
    p.name = "Christmas Shutdown"
    p.start_datetime = XMAS_START
    p.end_datetime = XMAS_END
    p.recurrence = BlackoutRecurrence.none
    p.affected_days = None
    p.override_allowed = False
    p.override_requires_approval = True
    p.reason = "Office closed"
    p.is_active = True
    p.created_by_id = USER_ID
    p.created_at = NOW
    p.updated_at = NOW
    return p


# 36. POST /corporate/accounts/me/blackout-periods — 201
@pytest.mark.anyio
async def test_api_create_blackout_period():
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user, get_db

    mock_user = MagicMock()
    mock_user.id = USER_ID

    async def mock_db():
        yield AsyncMock()

    with patch(f"{API_MODULE}.create_blackout_period", new=AsyncMock(return_value=_api_period_mock())):
        with patch(f"{API_MODULE}._get_member_account_id", new=AsyncMock(return_value=ACCOUNT_ID)):
            app.dependency_overrides[get_current_user] = lambda: mock_user
            app.dependency_overrides[get_db] = mock_db
            try:
                client = TestClient(app)
                resp = client.post(
                    "/api/v1/corporate/accounts/me/blackout-periods",
                    json={
                        "name": "Christmas Shutdown",
                        "start_datetime": XMAS_START.isoformat(),
                        "end_datetime": XMAS_END.isoformat(),
                    },
                )
            finally:
                app.dependency_overrides.pop(get_current_user, None)
                app.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 201
    assert resp.json()["name"] == "Christmas Shutdown"


# 37. GET /corporate/accounts/me/blackout-periods — 200
@pytest.mark.anyio
async def test_api_list_blackout_periods():
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user, get_db

    mock_user = MagicMock()
    mock_user.id = USER_ID

    async def mock_db():
        yield AsyncMock()

    with patch(f"{API_MODULE}.list_blackout_periods", new=AsyncMock(return_value=([_api_period_mock()], 1))):
        with patch(f"{API_MODULE}._get_member_account_id", new=AsyncMock(return_value=ACCOUNT_ID)):
            app.dependency_overrides[get_current_user] = lambda: mock_user
            app.dependency_overrides[get_db] = mock_db
            try:
                client = TestClient(app)
                resp = client.get("/api/v1/corporate/accounts/me/blackout-periods")
            finally:
                app.dependency_overrides.pop(get_current_user, None)
                app.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert len(body["items"]) == 1


# 38. GET /me/blackout-periods/check — 200 not blacked out
@pytest.mark.anyio
async def test_api_check_not_blacked_out():
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user, get_db

    mock_user = MagicMock()
    mock_user.id = USER_ID

    async def mock_db():
        yield AsyncMock()

    with patch(f"{API_MODULE}.check_booking_blackout", new=AsyncMock(return_value=[])):
        with patch(f"{API_MODULE}._get_member_account_id", new=AsyncMock(return_value=ACCOUNT_ID)):
            app.dependency_overrides[get_current_user] = lambda: mock_user
            app.dependency_overrides[get_db] = mock_db
            try:
                client = TestClient(app)
                resp = client.get(
                    "/api/v1/corporate/accounts/me/blackout-periods/check",
                    params={"dt": XMAS_MID.isoformat()},
                )
            finally:
                app.dependency_overrides.pop(get_current_user, None)
                app.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 200
    assert resp.json()["is_blacked_out"] is False


# 39. GET /me/blackout-periods/check — 200 blacked out
@pytest.mark.anyio
async def test_api_check_blacked_out():
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user, get_db

    mock_user = MagicMock()
    mock_user.id = USER_ID

    async def mock_db():
        yield AsyncMock()

    with patch(f"{API_MODULE}.check_booking_blackout", new=AsyncMock(return_value=[_api_period_mock()])):
        with patch(f"{API_MODULE}._get_member_account_id", new=AsyncMock(return_value=ACCOUNT_ID)):
            app.dependency_overrides[get_current_user] = lambda: mock_user
            app.dependency_overrides[get_db] = mock_db
            try:
                client = TestClient(app)
                resp = client.get(
                    "/api/v1/corporate/accounts/me/blackout-periods/check",
                    params={"dt": XMAS_MID.isoformat()},
                )
            finally:
                app.dependency_overrides.pop(get_current_user, None)
                app.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 200
    body = resp.json()
    assert body["is_blacked_out"] is True
    assert len(body["active_periods"]) == 1


# 40. GET /me/blackout-periods/{id} — 200
@pytest.mark.anyio
async def test_api_get_blackout_period():
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user, get_db

    mock_user = MagicMock()
    mock_user.id = USER_ID

    async def mock_db():
        yield AsyncMock()

    with patch(f"{API_MODULE}.get_blackout_period", new=AsyncMock(return_value=_api_period_mock())):
        with patch(f"{API_MODULE}._get_member_account_id", new=AsyncMock(return_value=ACCOUNT_ID)):
            app.dependency_overrides[get_current_user] = lambda: mock_user
            app.dependency_overrides[get_db] = mock_db
            try:
                client = TestClient(app)
                resp = client.get(
                    f"/api/v1/corporate/accounts/me/blackout-periods/{PERIOD_ID}",
                )
            finally:
                app.dependency_overrides.pop(get_current_user, None)
                app.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 200
    assert resp.json()["id"] == str(PERIOD_ID)


# 41. PATCH /me/blackout-periods/{id} — 200
@pytest.mark.anyio
async def test_api_update_blackout_period():
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user, get_db

    mock_user = MagicMock()
    mock_user.id = USER_ID
    updated = _api_period_mock()
    updated.name = "Updated Name"

    async def mock_db():
        yield AsyncMock()

    with patch(f"{API_MODULE}.update_blackout_period", new=AsyncMock(return_value=updated)):
        with patch(f"{API_MODULE}._get_member_account_id", new=AsyncMock(return_value=ACCOUNT_ID)):
            app.dependency_overrides[get_current_user] = lambda: mock_user
            app.dependency_overrides[get_db] = mock_db
            try:
                client = TestClient(app)
                resp = client.patch(
                    f"/api/v1/corporate/accounts/me/blackout-periods/{PERIOD_ID}",
                    json={"name": "Updated Name"},
                )
            finally:
                app.dependency_overrides.pop(get_current_user, None)
                app.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 200
    assert resp.json()["name"] == "Updated Name"


# 42. DELETE /me/blackout-periods/{id} — 204
@pytest.mark.anyio
async def test_api_delete_blackout_period():
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user, get_db

    mock_user = MagicMock()
    mock_user.id = USER_ID

    async def mock_db():
        yield AsyncMock()

    with patch(f"{API_MODULE}.delete_blackout_period", new=AsyncMock(return_value=None)):
        with patch(f"{API_MODULE}._get_member_account_id", new=AsyncMock(return_value=ACCOUNT_ID)):
            app.dependency_overrides[get_current_user] = lambda: mock_user
            app.dependency_overrides[get_db] = mock_db
            try:
                client = TestClient(app)
                resp = client.delete(
                    f"/api/v1/corporate/accounts/me/blackout-periods/{PERIOD_ID}",
                )
            finally:
                app.dependency_overrides.pop(get_current_user, None)
                app.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 204


# 43. POST /me/blackout-periods/{id}/deactivate — 200
@pytest.mark.anyio
async def test_api_deactivate_blackout_period():
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user, get_db

    mock_user = MagicMock()
    mock_user.id = USER_ID
    deactivated = _api_period_mock()
    deactivated.is_active = False

    async def mock_db():
        yield AsyncMock()

    with patch(f"{API_MODULE}.update_blackout_period", new=AsyncMock(return_value=deactivated)):
        with patch(f"{API_MODULE}._get_member_account_id", new=AsyncMock(return_value=ACCOUNT_ID)):
            app.dependency_overrides[get_current_user] = lambda: mock_user
            app.dependency_overrides[get_db] = mock_db
            try:
                client = TestClient(app)
                resp = client.post(
                    f"/api/v1/corporate/accounts/me/blackout-periods/{PERIOD_ID}/deactivate",
                )
            finally:
                app.dependency_overrides.pop(get_current_user, None)
                app.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 200
    assert resp.json()["is_active"] is False


# 44. GET /admin/corporate/accounts/{id}/blackout-periods — 200
@pytest.mark.anyio
async def test_api_admin_list_blackout_periods():
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_db, require_admin

    async def mock_db():
        yield AsyncMock()

    with patch(f"{API_MODULE}.list_blackout_periods", new=AsyncMock(return_value=([_api_period_mock()], 1))):
        app.dependency_overrides[require_admin] = lambda: None
        app.dependency_overrides[get_db] = mock_db
        try:
            client = TestClient(app)
            resp = client.get(
                f"/api/v1/admin/corporate/accounts/{ACCOUNT_ID}/blackout-periods",
            )
        finally:
            app.dependency_overrides.pop(require_admin, None)
            app.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 200
    assert resp.json()["total"] == 1


# 45. GET /admin/.../blackout-periods/check — 200
@pytest.mark.anyio
async def test_api_admin_check_blackout():
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_db, require_admin

    async def mock_db():
        yield AsyncMock()

    with patch(f"{API_MODULE}.check_booking_blackout", new=AsyncMock(return_value=[])):
        app.dependency_overrides[require_admin] = lambda: None
        app.dependency_overrides[get_db] = mock_db
        try:
            client = TestClient(app)
            resp = client.get(
                f"/api/v1/admin/corporate/accounts/{ACCOUNT_ID}/blackout-periods/check",
                params={"dt": NOW.isoformat()},
            )
        finally:
            app.dependency_overrides.pop(require_admin, None)
            app.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 200
    assert resp.json()["is_blacked_out"] is False
