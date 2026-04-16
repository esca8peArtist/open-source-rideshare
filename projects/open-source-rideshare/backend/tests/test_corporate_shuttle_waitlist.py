"""Tests for Corporate Shuttle Waitlist.

Service layer (async, mocked DB):
   1.  join_waitlist — success: creates entry with queue_position=1
   2.  join_waitlist — success: second joiner gets queue_position=2
   3.  join_waitlist — 404 when schedule not found
   4.  join_waitlist — 409 when schedule is inactive
   5.  join_waitlist — 409 when member already has an active booking
   6.  join_waitlist — 409 when member already on waitlist
   7.  leave_waitlist — success: sets status=cancelled
   8.  leave_waitlist — 404 when entry not found
   9.  leave_waitlist — 404 when account_id mismatch
  10.  leave_waitlist — 409 when entry is promoted
  11.  leave_waitlist — 409 when entry is expired
  12.  leave_waitlist — 409 when already cancelled
  13.  get_waitlist_entry — success: returns entry
  14.  get_waitlist_entry — 404 when not found
  15.  get_waitlist_entry — 404 when account_id mismatch
  16.  get_schedule_waitlist — returns waiting entries ordered by position
  17.  get_schedule_waitlist — returns empty list when none
  18.  get_schedule_waitlist — filters by status
  19.  get_member_waitlists — returns member entries newest first
  20.  get_member_waitlists — returns empty list when none
  21.  get_member_waitlists — filters by status
  22.  promote_from_waitlist — success: creates booking and marks entry promoted
  23.  promote_from_waitlist — returns None when schedule not found
  24.  promote_from_waitlist — returns None when schedule inactive
  25.  promote_from_waitlist — returns None when still at capacity
  26.  promote_from_waitlist — returns None when no waiters
  27.  get_waitlist_summary — returns correct counts
  28.  get_waitlist_summary — returns zeros when no entries
  29.  list_all_platform — returns all entries without filter
  30.  list_all_platform — filters by account_id
  31.  list_all_platform — filters by status

Schema validation:
  32.  WaitlistJoinRequest — requires booking_date
  33.  WaitlistJoinRequest — notes is optional
  34.  WaitlistJoinRequest — notes max_length 1000
  35.  WaitlistLeaveRequest — reason is optional
  36.  WaitlistLeaveRequest — reason max_length 500
  37.  WaitlistResponse — from_attributes construction
  38.  WaitlistSummaryResponse — structure validation
  39.  WaitlistStatus — waiting/promoted/expired/cancelled values

API layer (service functions patched):
  40.  POST /shuttle/schedules/{id}/waitlist — 201 member can join
  41.  POST /shuttle/schedules/{id}/waitlist — 404 schedule not found
  42.  POST /shuttle/schedules/{id}/waitlist — 409 schedule inactive
  43.  POST /shuttle/schedules/{id}/waitlist — 409 already booked
  44.  POST /shuttle/schedules/{id}/waitlist — 409 already waiting
  45.  GET  /shuttle/my-waitlists — 200 member can list own entries
  46.  GET  /shuttle/my-waitlists — 200 with status filter
  47.  GET  /shuttle/waitlist/{id} — 200 member can get entry
  48.  GET  /shuttle/waitlist/{id} — 404 not found
  49.  POST /shuttle/waitlist/{id}/leave — 200 member can leave
  50.  POST /shuttle/waitlist/{id}/leave — 404 not found
  51.  POST /shuttle/waitlist/{id}/leave — 409 not waiting
  52.  GET  /shuttle/schedules/{id}/waitlist — 200 admin can list
  53.  GET  /shuttle/schedules/{id}/waitlist — 403 non-admin blocked
  54.  GET  /shuttle/schedules/{id}/waitlist — 200 with status filter
  55.  GET  /shuttle/schedules/{id}/waitlist/summary — 200 admin can get summary
  56.  GET  /shuttle/schedules/{id}/waitlist/summary — 403 non-admin blocked
  57.  GET  /platform/corporate/shuttle/waitlist/all — 200 platform-admin list all
  58.  GET  /platform/corporate/shuttle/waitlist/all — 200 with account_id filter
  59.  GET  /platform/corporate/shuttle/waitlist/all — 200 with status filter
  60.  GET  /platform/corporate/shuttle/waitlist/all — 403 non-admin blocked

Integration: cancel_booking triggers promote_from_waitlist
  61.  cancel_booking endpoint — promote_from_waitlist called after cancel
  62.  cancel_booking endpoint — promote_from_waitlist not called when 404
  63.  cancel_booking endpoint — promote succeeds (full flow schema)
  64.  cancel_booking endpoint — promote returns None silently (no seat)
  65.  promote_from_waitlist — member_id None entry is skipped
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
from app.models.corporate_shuttle import (
    CorporateShuttleBooking,
    CorporateShuttleSchedule,
    ShuttleBookingStatus,
)
from app.models.corporate_shuttle_waitlist import (
    CorporateShuttleWaitlist,
    WaitlistStatus,
)
from app.schemas.corporate_shuttle_waitlist import (
    WaitlistJoinRequest,
    WaitlistLeaveRequest,
    WaitlistResponse,
    WaitlistSummaryResponse,
)
from app.services.corporate_shuttle_waitlist_service import (
    get_member_waitlists,
    get_schedule_waitlist,
    get_waitlist_entry,
    get_waitlist_summary,
    join_waitlist,
    leave_waitlist,
    list_all_platform,
    promote_from_waitlist,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ACCOUNT_ID = 15
SCHEDULE_ID = uuid.uuid4()
ENTRY_ID = uuid.uuid4()
BOOKING_ID = uuid.uuid4()
USER_ID = 40
ADMIN_ID = 3
MEMBER_ID = 55
OTHER_MEMBER_ID = 56

_SERVICE = "app.services.corporate_shuttle_waitlist_service"
_SHUTTLE_SERVICE = "app.services.corporate_shuttle_service"
_ROUTER = "app.api.v1.corporate_shuttle_waitlist"

_NOW = datetime(2026, 4, 16, 10, 0, 0, tzinfo=timezone.utc)
_TODAY = date(2026, 4, 16)


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


def _make_schedule(
    schedule_id: uuid.UUID = SCHEDULE_ID,
    account_id: int = ACCOUNT_ID,
    is_active: bool = True,
    seat_capacity: int = 20,
) -> CorporateShuttleSchedule:
    s = CorporateShuttleSchedule()
    s.id = schedule_id
    s.route_id = uuid.uuid4()
    s.account_id = account_id
    s.schedule_name = "Morning Run"
    s.days_of_week = [0, 1, 2, 3, 4]
    s.departure_time = "08:00"
    s.estimated_duration_minutes = 25
    s.seat_capacity = seat_capacity
    s.notes = None
    s.is_active = is_active
    s.created_by_id = ADMIN_ID
    s.created_at = _NOW
    s.updated_at = _NOW
    return s


def _make_booking(
    booking_id: uuid.UUID = BOOKING_ID,
    member_id: int = MEMBER_ID,
    booking_status: ShuttleBookingStatus = ShuttleBookingStatus.confirmed,
) -> CorporateShuttleBooking:
    b = CorporateShuttleBooking()
    b.id = booking_id
    b.schedule_id = SCHEDULE_ID
    b.account_id = ACCOUNT_ID
    b.member_id = member_id
    b.booking_date = _TODAY
    b.status = booking_status
    b.notes = None
    b.cancelled_at = None
    b.cancelled_by_id = None
    b.cancellation_reason = None
    b.created_at = _NOW
    b.updated_at = _NOW
    return b


def _make_entry(
    entry_id: uuid.UUID = ENTRY_ID,
    account_id: int = ACCOUNT_ID,
    schedule_id: uuid.UUID = SCHEDULE_ID,
    member_id: int = MEMBER_ID,
    booking_date: date = _TODAY,
    entry_status: WaitlistStatus = WaitlistStatus.waiting,
    queue_position: int = 1,
    promoted_at: datetime | None = None,
    promoted_booking_id: uuid.UUID | None = None,
    cancelled_at: datetime | None = None,
    cancellation_reason: str | None = None,
) -> CorporateShuttleWaitlist:
    e = CorporateShuttleWaitlist()
    e.id = entry_id
    e.schedule_id = schedule_id
    e.account_id = account_id
    e.member_id = member_id
    e.booking_date = booking_date
    e.status = entry_status
    e.queue_position = queue_position
    e.notes = None
    e.promoted_at = promoted_at
    e.promoted_booking_id = promoted_booking_id
    e.cancelled_at = cancelled_at
    e.cancellation_reason = cancellation_reason
    e.created_at = _NOW
    e.updated_at = _NOW
    return e


def _make_waitlist_response(
    entry_id: uuid.UUID = ENTRY_ID,
    entry_status: WaitlistStatus = WaitlistStatus.waiting,
    queue_position: int = 1,
    promoted_booking_id: uuid.UUID | None = None,
) -> WaitlistResponse:
    return WaitlistResponse(
        id=entry_id,
        schedule_id=SCHEDULE_ID,
        account_id=ACCOUNT_ID,
        member_id=MEMBER_ID,
        booking_date=_TODAY,
        status=entry_status,
        queue_position=queue_position,
        notes=None,
        promoted_at=None,
        promoted_booking_id=promoted_booking_id,
        cancelled_at=None,
        cancellation_reason=None,
        created_at=_NOW,
        updated_at=_NOW,
    )


# ---------------------------------------------------------------------------
# Shared async DB mock helper
# ---------------------------------------------------------------------------


def _mock_db() -> AsyncMock:
    db = AsyncMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    db.add = MagicMock()
    return db


# ---------------------------------------------------------------------------
# Service tests: join_waitlist
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_join_waitlist_success_first():
    """join_waitlist — success: creates entry with queue_position=1."""
    db = _mock_db()
    schedule = _make_schedule(seat_capacity=1)

    exec_results = [
        MagicMock(scalar_one_or_none=MagicMock(return_value=schedule)),  # fetch schedule
        MagicMock(scalar_one_or_none=MagicMock(return_value=None)),      # no existing booking
        MagicMock(scalar_one_or_none=MagicMock(return_value=None)),      # no existing waitlist
        MagicMock(scalar_one_or_none=MagicMock(return_value=None)),      # max position → None
    ]
    db.execute = AsyncMock(side_effect=exec_results)

    entry = _make_entry()
    db.refresh = AsyncMock(side_effect=lambda obj: setattr(obj, "id", entry.id) or
                           setattr(obj, "queue_position", 1) or
                           setattr(obj, "status", WaitlistStatus.waiting) or
                           setattr(obj, "schedule_id", SCHEDULE_ID) or
                           setattr(obj, "account_id", ACCOUNT_ID) or
                           setattr(obj, "member_id", MEMBER_ID) or
                           setattr(obj, "booking_date", _TODAY) or
                           setattr(obj, "notes", None) or
                           setattr(obj, "promoted_at", None) or
                           setattr(obj, "promoted_booking_id", None) or
                           setattr(obj, "cancelled_at", None) or
                           setattr(obj, "cancellation_reason", None) or
                           setattr(obj, "created_at", _NOW) or
                           setattr(obj, "updated_at", _NOW))

    result = await join_waitlist(db, SCHEDULE_ID, ACCOUNT_ID, MEMBER_ID, _TODAY)
    assert result.queue_position == 1
    assert result.status == WaitlistStatus.waiting
    db.add.assert_called_once()


@pytest.mark.asyncio
async def test_join_waitlist_second_position():
    """join_waitlist — success: second joiner gets queue_position=2."""
    db = _mock_db()
    schedule = _make_schedule(seat_capacity=1)

    exec_results = [
        MagicMock(scalar_one_or_none=MagicMock(return_value=schedule)),
        MagicMock(scalar_one_or_none=MagicMock(return_value=None)),
        MagicMock(scalar_one_or_none=MagicMock(return_value=None)),
        MagicMock(scalar_one_or_none=MagicMock(return_value=1)),  # max position = 1
    ]
    db.execute = AsyncMock(side_effect=exec_results)

    entry = _make_entry(queue_position=2)
    db.refresh = AsyncMock(side_effect=lambda obj: setattr(obj, "id", entry.id) or
                           setattr(obj, "queue_position", 2) or
                           setattr(obj, "status", WaitlistStatus.waiting) or
                           setattr(obj, "schedule_id", SCHEDULE_ID) or
                           setattr(obj, "account_id", ACCOUNT_ID) or
                           setattr(obj, "member_id", OTHER_MEMBER_ID) or
                           setattr(obj, "booking_date", _TODAY) or
                           setattr(obj, "notes", None) or
                           setattr(obj, "promoted_at", None) or
                           setattr(obj, "promoted_booking_id", None) or
                           setattr(obj, "cancelled_at", None) or
                           setattr(obj, "cancellation_reason", None) or
                           setattr(obj, "created_at", _NOW) or
                           setattr(obj, "updated_at", _NOW))

    result = await join_waitlist(db, SCHEDULE_ID, ACCOUNT_ID, OTHER_MEMBER_ID, _TODAY)
    assert result.queue_position == 2


@pytest.mark.asyncio
async def test_join_waitlist_404_schedule_not_found():
    """join_waitlist — 404 when schedule not found."""
    db = _mock_db()
    db.execute = AsyncMock(return_value=MagicMock(
        scalar_one_or_none=MagicMock(return_value=None)
    ))
    with pytest.raises(HTTPException) as exc:
        await join_waitlist(db, SCHEDULE_ID, ACCOUNT_ID, MEMBER_ID, _TODAY)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_join_waitlist_409_schedule_inactive():
    """join_waitlist — 409 when schedule is inactive."""
    db = _mock_db()
    schedule = _make_schedule(is_active=False)
    db.execute = AsyncMock(return_value=MagicMock(
        scalar_one_or_none=MagicMock(return_value=schedule)
    ))
    with pytest.raises(HTTPException) as exc:
        await join_waitlist(db, SCHEDULE_ID, ACCOUNT_ID, MEMBER_ID, _TODAY)
    assert exc.value.status_code == 409
    assert "inactive" in exc.value.detail.lower()


@pytest.mark.asyncio
async def test_join_waitlist_409_already_booked():
    """join_waitlist — 409 when member already has an active booking."""
    db = _mock_db()
    schedule = _make_schedule()
    booking = _make_booking()

    exec_results = [
        MagicMock(scalar_one_or_none=MagicMock(return_value=schedule)),
        MagicMock(scalar_one_or_none=MagicMock(return_value=booking)),
    ]
    db.execute = AsyncMock(side_effect=exec_results)

    with pytest.raises(HTTPException) as exc:
        await join_waitlist(db, SCHEDULE_ID, ACCOUNT_ID, MEMBER_ID, _TODAY)
    assert exc.value.status_code == 409
    assert "booking" in exc.value.detail.lower()


@pytest.mark.asyncio
async def test_join_waitlist_409_already_waiting():
    """join_waitlist — 409 when member already on waitlist."""
    db = _mock_db()
    schedule = _make_schedule()
    existing = _make_entry()

    exec_results = [
        MagicMock(scalar_one_or_none=MagicMock(return_value=schedule)),
        MagicMock(scalar_one_or_none=MagicMock(return_value=None)),   # no active booking
        MagicMock(scalar_one_or_none=MagicMock(return_value=existing)),  # already waiting
    ]
    db.execute = AsyncMock(side_effect=exec_results)

    with pytest.raises(HTTPException) as exc:
        await join_waitlist(db, SCHEDULE_ID, ACCOUNT_ID, MEMBER_ID, _TODAY)
    assert exc.value.status_code == 409
    assert "waitlist" in exc.value.detail.lower()


# ---------------------------------------------------------------------------
# Service tests: leave_waitlist
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_leave_waitlist_success():
    """leave_waitlist — success: sets status=cancelled."""
    db = _mock_db()
    entry = _make_entry()

    db.execute = AsyncMock(return_value=MagicMock(
        scalar_one_or_none=MagicMock(return_value=entry)
    ))
    db.refresh = AsyncMock(side_effect=lambda obj: setattr(obj, "status", WaitlistStatus.cancelled) or
                           setattr(obj, "cancelled_at", _NOW) or
                           setattr(obj, "cancellation_reason", "No longer needed") or
                           setattr(obj, "id", ENTRY_ID) or
                           setattr(obj, "schedule_id", SCHEDULE_ID) or
                           setattr(obj, "account_id", ACCOUNT_ID) or
                           setattr(obj, "member_id", MEMBER_ID) or
                           setattr(obj, "booking_date", _TODAY) or
                           setattr(obj, "queue_position", 1) or
                           setattr(obj, "notes", None) or
                           setattr(obj, "promoted_at", None) or
                           setattr(obj, "promoted_booking_id", None) or
                           setattr(obj, "created_at", _NOW) or
                           setattr(obj, "updated_at", _NOW))

    result = await leave_waitlist(db, ENTRY_ID, ACCOUNT_ID, reason="No longer needed")
    assert entry.status == WaitlistStatus.cancelled
    assert entry.cancelled_at is not None


@pytest.mark.asyncio
async def test_leave_waitlist_404_not_found():
    """leave_waitlist — 404 when entry not found."""
    db = _mock_db()
    db.execute = AsyncMock(return_value=MagicMock(
        scalar_one_or_none=MagicMock(return_value=None)
    ))
    with pytest.raises(HTTPException) as exc:
        await leave_waitlist(db, ENTRY_ID, ACCOUNT_ID)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_leave_waitlist_404_account_mismatch():
    """leave_waitlist — 404 when account_id mismatch."""
    db = _mock_db()
    db.execute = AsyncMock(return_value=MagicMock(
        scalar_one_or_none=MagicMock(return_value=None)
    ))
    with pytest.raises(HTTPException) as exc:
        await leave_waitlist(db, ENTRY_ID, account_id=999)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_leave_waitlist_409_promoted():
    """leave_waitlist — 409 when entry is promoted."""
    db = _mock_db()
    entry = _make_entry(entry_status=WaitlistStatus.promoted)
    db.execute = AsyncMock(return_value=MagicMock(
        scalar_one_or_none=MagicMock(return_value=entry)
    ))
    with pytest.raises(HTTPException) as exc:
        await leave_waitlist(db, ENTRY_ID, ACCOUNT_ID)
    assert exc.value.status_code == 409
    assert "promoted" in exc.value.detail.lower()


@pytest.mark.asyncio
async def test_leave_waitlist_409_expired():
    """leave_waitlist — 409 when entry is expired."""
    db = _mock_db()
    entry = _make_entry(entry_status=WaitlistStatus.expired)
    db.execute = AsyncMock(return_value=MagicMock(
        scalar_one_or_none=MagicMock(return_value=entry)
    ))
    with pytest.raises(HTTPException) as exc:
        await leave_waitlist(db, ENTRY_ID, ACCOUNT_ID)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_leave_waitlist_409_already_cancelled():
    """leave_waitlist — 409 when already cancelled."""
    db = _mock_db()
    entry = _make_entry(entry_status=WaitlistStatus.cancelled)
    db.execute = AsyncMock(return_value=MagicMock(
        scalar_one_or_none=MagicMock(return_value=entry)
    ))
    with pytest.raises(HTTPException) as exc:
        await leave_waitlist(db, ENTRY_ID, ACCOUNT_ID)
    assert exc.value.status_code == 409


# ---------------------------------------------------------------------------
# Service tests: get_waitlist_entry
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_waitlist_entry_success():
    """get_waitlist_entry — success: returns entry."""
    db = _mock_db()
    entry = _make_entry()
    db.execute = AsyncMock(return_value=MagicMock(
        scalar_one_or_none=MagicMock(return_value=entry)
    ))
    result = await get_waitlist_entry(db, ENTRY_ID, ACCOUNT_ID)
    assert result.id == ENTRY_ID
    assert result.status == WaitlistStatus.waiting


@pytest.mark.asyncio
async def test_get_waitlist_entry_404():
    """get_waitlist_entry — 404 when not found."""
    db = _mock_db()
    db.execute = AsyncMock(return_value=MagicMock(
        scalar_one_or_none=MagicMock(return_value=None)
    ))
    with pytest.raises(HTTPException) as exc:
        await get_waitlist_entry(db, ENTRY_ID, ACCOUNT_ID)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_get_waitlist_entry_404_account_mismatch():
    """get_waitlist_entry — 404 when account_id mismatch."""
    db = _mock_db()
    db.execute = AsyncMock(return_value=MagicMock(
        scalar_one_or_none=MagicMock(return_value=None)
    ))
    with pytest.raises(HTTPException) as exc:
        await get_waitlist_entry(db, ENTRY_ID, account_id=999)
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# Service tests: get_schedule_waitlist
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_schedule_waitlist_returns_entries():
    """get_schedule_waitlist — returns waiting entries ordered by position."""
    db = _mock_db()
    e1 = _make_entry(entry_id=uuid.uuid4(), queue_position=1)
    e2 = _make_entry(entry_id=uuid.uuid4(), member_id=OTHER_MEMBER_ID, queue_position=2)
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [e1, e2]
    db.execute = AsyncMock(return_value=mock_result)

    result = await get_schedule_waitlist(db, SCHEDULE_ID, ACCOUNT_ID, _TODAY)
    assert len(result) == 2
    assert result[0].queue_position == 1
    assert result[1].queue_position == 2


@pytest.mark.asyncio
async def test_get_schedule_waitlist_empty():
    """get_schedule_waitlist — returns empty list when none."""
    db = _mock_db()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    db.execute = AsyncMock(return_value=mock_result)

    result = await get_schedule_waitlist(db, SCHEDULE_ID, ACCOUNT_ID, _TODAY)
    assert result == []


@pytest.mark.asyncio
async def test_get_schedule_waitlist_status_filter():
    """get_schedule_waitlist — filters by status."""
    db = _mock_db()
    promoted = _make_entry(entry_status=WaitlistStatus.promoted)
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [promoted]
    db.execute = AsyncMock(return_value=mock_result)

    result = await get_schedule_waitlist(
        db, SCHEDULE_ID, ACCOUNT_ID, _TODAY, status_filter=WaitlistStatus.promoted
    )
    assert len(result) == 1
    assert result[0].status == WaitlistStatus.promoted


# ---------------------------------------------------------------------------
# Service tests: get_member_waitlists
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_member_waitlists_returns_entries():
    """get_member_waitlists — returns member entries newest first."""
    db = _mock_db()
    e = _make_entry()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [e]
    db.execute = AsyncMock(return_value=mock_result)

    result = await get_member_waitlists(db, ACCOUNT_ID, MEMBER_ID)
    assert len(result) == 1
    assert result[0].member_id == MEMBER_ID


@pytest.mark.asyncio
async def test_get_member_waitlists_empty():
    """get_member_waitlists — returns empty list when none."""
    db = _mock_db()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    db.execute = AsyncMock(return_value=mock_result)

    result = await get_member_waitlists(db, ACCOUNT_ID, MEMBER_ID)
    assert result == []


@pytest.mark.asyncio
async def test_get_member_waitlists_status_filter():
    """get_member_waitlists — filters by status."""
    db = _mock_db()
    e = _make_entry(entry_status=WaitlistStatus.promoted)
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [e]
    db.execute = AsyncMock(return_value=mock_result)

    result = await get_member_waitlists(
        db, ACCOUNT_ID, MEMBER_ID, status_filter=WaitlistStatus.promoted
    )
    assert result[0].status == WaitlistStatus.promoted


# ---------------------------------------------------------------------------
# Service tests: promote_from_waitlist
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_promote_from_waitlist_success():
    """promote_from_waitlist — success: creates booking and marks promoted."""
    db = _mock_db()
    schedule = _make_schedule(seat_capacity=5)
    waiter = _make_entry(member_id=MEMBER_ID, queue_position=1)
    booking = _make_booking()

    exec_results = [
        MagicMock(scalar_one_or_none=MagicMock(return_value=schedule)),  # fetch schedule
        MagicMock(scalar_one=MagicMock(return_value=4)),                  # current count < capacity
        MagicMock(scalar_one_or_none=MagicMock(return_value=waiter)),     # first waiter
    ]
    db.execute = AsyncMock(side_effect=exec_results)

    call_count = 0

    async def _refresh(obj):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # booking refresh
            obj.id = booking.id
            obj.schedule_id = SCHEDULE_ID
            obj.account_id = ACCOUNT_ID
            obj.member_id = MEMBER_ID
            obj.booking_date = _TODAY
            obj.status = ShuttleBookingStatus.confirmed
            obj.notes = None
            obj.cancelled_at = None
            obj.cancelled_by_id = None
            obj.cancellation_reason = None
            obj.created_at = _NOW
            obj.updated_at = _NOW
        else:
            # waitlist entry refresh
            obj.id = waiter.id
            obj.schedule_id = SCHEDULE_ID
            obj.account_id = ACCOUNT_ID
            obj.member_id = MEMBER_ID
            obj.booking_date = _TODAY
            obj.status = WaitlistStatus.promoted
            obj.queue_position = 1
            obj.notes = None
            obj.promoted_at = _NOW
            obj.promoted_booking_id = booking.id
            obj.cancelled_at = None
            obj.cancellation_reason = None
            obj.created_at = _NOW
            obj.updated_at = _NOW

    db.refresh = AsyncMock(side_effect=_refresh)

    result = await promote_from_waitlist(db, SCHEDULE_ID, ACCOUNT_ID, _TODAY)
    assert result is not None
    assert result.status == WaitlistStatus.promoted
    assert result.promoted_booking_id == booking.id
    db.add.assert_called_once()


@pytest.mark.asyncio
async def test_promote_from_waitlist_no_schedule():
    """promote_from_waitlist — returns None when schedule not found."""
    db = _mock_db()
    db.execute = AsyncMock(return_value=MagicMock(
        scalar_one_or_none=MagicMock(return_value=None)
    ))
    result = await promote_from_waitlist(db, SCHEDULE_ID, ACCOUNT_ID, _TODAY)
    assert result is None


@pytest.mark.asyncio
async def test_promote_from_waitlist_inactive_schedule():
    """promote_from_waitlist — returns None when schedule inactive."""
    db = _mock_db()
    schedule = _make_schedule(is_active=False)
    db.execute = AsyncMock(return_value=MagicMock(
        scalar_one_or_none=MagicMock(return_value=schedule)
    ))
    result = await promote_from_waitlist(db, SCHEDULE_ID, ACCOUNT_ID, _TODAY)
    assert result is None


@pytest.mark.asyncio
async def test_promote_from_waitlist_still_at_capacity():
    """promote_from_waitlist — returns None when still at capacity."""
    db = _mock_db()
    schedule = _make_schedule(seat_capacity=5)

    exec_results = [
        MagicMock(scalar_one_or_none=MagicMock(return_value=schedule)),
        MagicMock(scalar_one=MagicMock(return_value=5)),  # count == capacity
    ]
    db.execute = AsyncMock(side_effect=exec_results)

    result = await promote_from_waitlist(db, SCHEDULE_ID, ACCOUNT_ID, _TODAY)
    assert result is None


@pytest.mark.asyncio
async def test_promote_from_waitlist_no_waiters():
    """promote_from_waitlist — returns None when no waiters."""
    db = _mock_db()
    schedule = _make_schedule(seat_capacity=5)

    exec_results = [
        MagicMock(scalar_one_or_none=MagicMock(return_value=schedule)),
        MagicMock(scalar_one=MagicMock(return_value=4)),
        MagicMock(scalar_one_or_none=MagicMock(return_value=None)),  # no waiter
    ]
    db.execute = AsyncMock(side_effect=exec_results)

    result = await promote_from_waitlist(db, SCHEDULE_ID, ACCOUNT_ID, _TODAY)
    assert result is None


@pytest.mark.asyncio
async def test_promote_from_waitlist_skips_null_member():
    """promote_from_waitlist — member_id None entry is skipped (returns None)."""
    db = _mock_db()
    schedule = _make_schedule(seat_capacity=5)
    waiter = _make_entry(member_id=None)

    exec_results = [
        MagicMock(scalar_one_or_none=MagicMock(return_value=schedule)),
        MagicMock(scalar_one=MagicMock(return_value=4)),
        MagicMock(scalar_one_or_none=MagicMock(return_value=waiter)),
    ]
    db.execute = AsyncMock(side_effect=exec_results)

    result = await promote_from_waitlist(db, SCHEDULE_ID, ACCOUNT_ID, _TODAY)
    assert result is None


# ---------------------------------------------------------------------------
# Service tests: get_waitlist_summary
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_waitlist_summary_correct_counts():
    """get_waitlist_summary — returns correct counts."""
    db = _mock_db()

    Row = MagicMock
    row_waiting = Row()
    row_waiting.status = WaitlistStatus.waiting
    row_waiting.cnt = 3

    row_promoted = Row()
    row_promoted.status = WaitlistStatus.promoted
    row_promoted.cnt = 1

    mock_result = MagicMock()
    mock_result.all.return_value = [row_waiting, row_promoted]
    db.execute = AsyncMock(return_value=mock_result)

    result = await get_waitlist_summary(db, SCHEDULE_ID, ACCOUNT_ID, _TODAY)
    assert result.waiting_count == 3
    assert result.promoted_count == 1
    assert result.total_entries == 4
    assert result.schedule_id == SCHEDULE_ID
    assert result.booking_date == _TODAY


@pytest.mark.asyncio
async def test_get_waitlist_summary_zeros_when_empty():
    """get_waitlist_summary — returns zeros when no entries."""
    db = _mock_db()
    mock_result = MagicMock()
    mock_result.all.return_value = []
    db.execute = AsyncMock(return_value=mock_result)

    result = await get_waitlist_summary(db, SCHEDULE_ID, ACCOUNT_ID, _TODAY)
    assert result.waiting_count == 0
    assert result.promoted_count == 0
    assert result.total_entries == 0


# ---------------------------------------------------------------------------
# Service tests: list_all_platform
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_all_platform_no_filter():
    """list_all_platform — returns all entries without filter."""
    db = _mock_db()
    e = _make_entry()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [e]
    db.execute = AsyncMock(return_value=mock_result)

    result = await list_all_platform(db)
    assert len(result) == 1


@pytest.mark.asyncio
async def test_list_all_platform_account_filter():
    """list_all_platform — filters by account_id."""
    db = _mock_db()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    db.execute = AsyncMock(return_value=mock_result)

    result = await list_all_platform(db, account_id=999)
    assert result == []


@pytest.mark.asyncio
async def test_list_all_platform_status_filter():
    """list_all_platform — filters by status."""
    db = _mock_db()
    e = _make_entry(entry_status=WaitlistStatus.promoted)
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [e]
    db.execute = AsyncMock(return_value=mock_result)

    result = await list_all_platform(db, status_filter=WaitlistStatus.promoted)
    assert result[0].status == WaitlistStatus.promoted


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------


def test_waitlist_join_request_requires_booking_date():
    """WaitlistJoinRequest — requires booking_date."""
    with pytest.raises(ValidationError):
        WaitlistJoinRequest()


def test_waitlist_join_request_notes_optional():
    """WaitlistJoinRequest — notes is optional."""
    req = WaitlistJoinRequest(booking_date=_TODAY)
    assert req.notes is None


def test_waitlist_join_request_notes_max_length():
    """WaitlistJoinRequest — notes max_length 1000."""
    with pytest.raises(ValidationError):
        WaitlistJoinRequest(booking_date=_TODAY, notes="x" * 1001)


def test_waitlist_leave_request_reason_optional():
    """WaitlistLeaveRequest — reason is optional."""
    req = WaitlistLeaveRequest()
    assert req.reason is None


def test_waitlist_leave_request_reason_max_length():
    """WaitlistLeaveRequest — reason max_length 500."""
    with pytest.raises(ValidationError):
        WaitlistLeaveRequest(reason="x" * 501)


def test_waitlist_response_from_attributes():
    """WaitlistResponse — from_attributes construction."""
    entry = _make_entry()
    resp = WaitlistResponse.model_validate(entry)
    assert resp.id == entry.id
    assert resp.status == WaitlistStatus.waiting
    assert resp.queue_position == 1


def test_waitlist_summary_response_structure():
    """WaitlistSummaryResponse — structure validation."""
    s = WaitlistSummaryResponse(
        schedule_id=SCHEDULE_ID,
        booking_date=_TODAY,
        waiting_count=2,
        promoted_count=1,
        total_entries=3,
    )
    assert s.total_entries == 3


def test_waitlist_status_values():
    """WaitlistStatus — waiting/promoted/expired/cancelled values."""
    assert WaitlistStatus.waiting == "waiting"
    assert WaitlistStatus.promoted == "promoted"
    assert WaitlistStatus.expired == "expired"
    assert WaitlistStatus.cancelled == "cancelled"


# ---------------------------------------------------------------------------
# API tests — shared fixtures
# ---------------------------------------------------------------------------

client = TestClient(app)


def _make_user(user_id: int = USER_ID, is_admin: bool = False):
    from app.models.user import User as UserModel
    u = MagicMock(spec=UserModel)
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
        return _make_user(user_id=ADMIN_ID, is_admin=True)

    return {
        get_current_user: _user,
        get_db: _db,
        require_admin: _admin,
    }


def _patch_get_account():
    return patch(f"{_ROUTER}.get_account", new_callable=AsyncMock)


def _patch_require_account_admin(raises: bool = False):
    if raises:
        return patch(
            f"{_ROUTER}._require_account_admin",
            new_callable=AsyncMock,
            side_effect=HTTPException(status_code=403, detail="forbidden"),
        )
    return patch(f"{_ROUTER}._require_account_admin", new_callable=AsyncMock)


# ---------------------------------------------------------------------------
# API tests: join waitlist
# ---------------------------------------------------------------------------

_BASE = f"/api/v1/corporate/{ACCOUNT_ID}/shuttle"


def test_api_join_waitlist_201():
    """POST /shuttle/schedules/{id}/waitlist — 201 member can join."""
    resp_data = _make_waitlist_response()
    with (
        _patch_get_account(),
        patch(f"{_ROUTER}.join_waitlist", new_callable=AsyncMock, return_value=resp_data),
    ):
        app.dependency_overrides.update(_dep_overrides())
        resp = client.post(
            f"{_BASE}/schedules/{SCHEDULE_ID}/waitlist",
            json={"booking_date": str(_TODAY)},
        )
        app.dependency_overrides.clear()
    assert resp.status_code == 201
    assert resp.json()["status"] == "waiting"


def test_api_join_waitlist_404_schedule():
    """POST /shuttle/schedules/{id}/waitlist — 404 schedule not found."""
    with (
        _patch_get_account(),
        patch(
            f"{_ROUTER}.join_waitlist",
            new_callable=AsyncMock,
            side_effect=HTTPException(status_code=404, detail="Shuttle schedule not found."),
        ),
    ):
        app.dependency_overrides.update(_dep_overrides())
        resp = client.post(
            f"{_BASE}/schedules/{SCHEDULE_ID}/waitlist",
            json={"booking_date": str(_TODAY)},
        )
        app.dependency_overrides.clear()
    assert resp.status_code == 404


def test_api_join_waitlist_409_inactive():
    """POST /shuttle/schedules/{id}/waitlist — 409 schedule inactive."""
    with (
        _patch_get_account(),
        patch(
            f"{_ROUTER}.join_waitlist",
            new_callable=AsyncMock,
            side_effect=HTTPException(status_code=409, detail="inactive schedule"),
        ),
    ):
        app.dependency_overrides.update(_dep_overrides())
        resp = client.post(
            f"{_BASE}/schedules/{SCHEDULE_ID}/waitlist",
            json={"booking_date": str(_TODAY)},
        )
        app.dependency_overrides.clear()
    assert resp.status_code == 409


def test_api_join_waitlist_409_already_booked():
    """POST /shuttle/schedules/{id}/waitlist — 409 already booked."""
    with (
        _patch_get_account(),
        patch(
            f"{_ROUTER}.join_waitlist",
            new_callable=AsyncMock,
            side_effect=HTTPException(status_code=409, detail="already has an active booking"),
        ),
    ):
        app.dependency_overrides.update(_dep_overrides())
        resp = client.post(
            f"{_BASE}/schedules/{SCHEDULE_ID}/waitlist",
            json={"booking_date": str(_TODAY)},
        )
        app.dependency_overrides.clear()
    assert resp.status_code == 409


def test_api_join_waitlist_409_already_waiting():
    """POST /shuttle/schedules/{id}/waitlist — 409 already waiting."""
    with (
        _patch_get_account(),
        patch(
            f"{_ROUTER}.join_waitlist",
            new_callable=AsyncMock,
            side_effect=HTTPException(status_code=409, detail="already on the waitlist"),
        ),
    ):
        app.dependency_overrides.update(_dep_overrides())
        resp = client.post(
            f"{_BASE}/schedules/{SCHEDULE_ID}/waitlist",
            json={"booking_date": str(_TODAY)},
        )
        app.dependency_overrides.clear()
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# API tests: my-waitlists
# ---------------------------------------------------------------------------


def test_api_list_my_waitlists_200():
    """GET /shuttle/my-waitlists — 200 member can list own entries."""
    resp_data = [_make_waitlist_response()]
    with (
        _patch_get_account(),
        patch(f"{_ROUTER}.get_member_waitlists", new_callable=AsyncMock, return_value=resp_data),
    ):
        app.dependency_overrides.update(_dep_overrides())
        resp = client.get(f"{_BASE}/my-waitlists")
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_api_list_my_waitlists_with_status_filter():
    """GET /shuttle/my-waitlists — 200 with status filter."""
    resp_data = [_make_waitlist_response(entry_status=WaitlistStatus.promoted)]
    with (
        _patch_get_account(),
        patch(f"{_ROUTER}.get_member_waitlists", new_callable=AsyncMock, return_value=resp_data),
    ):
        app.dependency_overrides.update(_dep_overrides())
        resp = client.get(f"{_BASE}/my-waitlists?status=promoted")
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json()[0]["status"] == "promoted"


# ---------------------------------------------------------------------------
# API tests: get entry
# ---------------------------------------------------------------------------


def test_api_get_entry_200():
    """GET /shuttle/waitlist/{id} — 200 member can get entry."""
    resp_data = _make_waitlist_response()
    with (
        _patch_get_account(),
        patch(f"{_ROUTER}.get_waitlist_entry", new_callable=AsyncMock, return_value=resp_data),
    ):
        app.dependency_overrides.update(_dep_overrides())
        resp = client.get(f"{_BASE}/waitlist/{ENTRY_ID}")
        app.dependency_overrides.clear()
    assert resp.status_code == 200


def test_api_get_entry_404():
    """GET /shuttle/waitlist/{id} — 404 not found."""
    with (
        _patch_get_account(),
        patch(
            f"{_ROUTER}.get_waitlist_entry",
            new_callable=AsyncMock,
            side_effect=HTTPException(status_code=404, detail="Waitlist entry not found."),
        ),
    ):
        app.dependency_overrides.update(_dep_overrides())
        resp = client.get(f"{_BASE}/waitlist/{ENTRY_ID}")
        app.dependency_overrides.clear()
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# API tests: leave waitlist
# ---------------------------------------------------------------------------


def test_api_leave_waitlist_200():
    """POST /shuttle/waitlist/{id}/leave — 200 member can leave."""
    resp_data = _make_waitlist_response(entry_status=WaitlistStatus.cancelled)
    with (
        _patch_get_account(),
        patch(f"{_ROUTER}.leave_waitlist", new_callable=AsyncMock, return_value=resp_data),
    ):
        app.dependency_overrides.update(_dep_overrides())
        resp = client.post(f"{_BASE}/waitlist/{ENTRY_ID}/leave", json={})
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"


def test_api_leave_waitlist_404():
    """POST /shuttle/waitlist/{id}/leave — 404 not found."""
    with (
        _patch_get_account(),
        patch(
            f"{_ROUTER}.leave_waitlist",
            new_callable=AsyncMock,
            side_effect=HTTPException(status_code=404, detail="Waitlist entry not found."),
        ),
    ):
        app.dependency_overrides.update(_dep_overrides())
        resp = client.post(f"{_BASE}/waitlist/{ENTRY_ID}/leave", json={})
        app.dependency_overrides.clear()
    assert resp.status_code == 404


def test_api_leave_waitlist_409_not_waiting():
    """POST /shuttle/waitlist/{id}/leave — 409 not waiting."""
    with (
        _patch_get_account(),
        patch(
            f"{_ROUTER}.leave_waitlist",
            new_callable=AsyncMock,
            side_effect=HTTPException(status_code=409, detail="not in 'waiting' status"),
        ),
    ):
        app.dependency_overrides.update(_dep_overrides())
        resp = client.post(f"{_BASE}/waitlist/{ENTRY_ID}/leave", json={})
        app.dependency_overrides.clear()
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# API tests: schedule waitlist (admin)
# ---------------------------------------------------------------------------


def test_api_get_schedule_waitlist_200():
    """GET /shuttle/schedules/{id}/waitlist — 200 admin can list."""
    resp_data = [_make_waitlist_response()]
    with (
        _patch_get_account(),
        _patch_require_account_admin(),
        patch(f"{_ROUTER}.get_schedule_waitlist", new_callable=AsyncMock, return_value=resp_data),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        resp = client.get(
            f"{_BASE}/schedules/{SCHEDULE_ID}/waitlist?booking_date={_TODAY}"
        )
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_api_get_schedule_waitlist_403_non_admin():
    """GET /shuttle/schedules/{id}/waitlist — 403 non-admin blocked."""
    with (
        _patch_get_account(),
        _patch_require_account_admin(raises=True),
    ):
        app.dependency_overrides.update(_dep_overrides())
        resp = client.get(
            f"{_BASE}/schedules/{SCHEDULE_ID}/waitlist?booking_date={_TODAY}"
        )
        app.dependency_overrides.clear()
    assert resp.status_code == 403


def test_api_get_schedule_waitlist_with_status_filter():
    """GET /shuttle/schedules/{id}/waitlist — 200 with status filter."""
    resp_data = [_make_waitlist_response(entry_status=WaitlistStatus.waiting)]
    with (
        _patch_get_account(),
        _patch_require_account_admin(),
        patch(f"{_ROUTER}.get_schedule_waitlist", new_callable=AsyncMock, return_value=resp_data),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        resp = client.get(
            f"{_BASE}/schedules/{SCHEDULE_ID}/waitlist?booking_date={_TODAY}&status=waiting"
        )
        app.dependency_overrides.clear()
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# API tests: waitlist summary (admin)
# ---------------------------------------------------------------------------


def test_api_get_waitlist_summary_200():
    """GET /shuttle/schedules/{id}/waitlist/summary — 200 admin can get summary."""
    summary = WaitlistSummaryResponse(
        schedule_id=SCHEDULE_ID,
        booking_date=_TODAY,
        waiting_count=2,
        promoted_count=1,
        total_entries=3,
    )
    with (
        _patch_get_account(),
        _patch_require_account_admin(),
        patch(f"{_ROUTER}.get_waitlist_summary", new_callable=AsyncMock, return_value=summary),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        resp = client.get(
            f"{_BASE}/schedules/{SCHEDULE_ID}/waitlist/summary?booking_date={_TODAY}"
        )
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    data = resp.json()
    assert data["waiting_count"] == 2
    assert data["promoted_count"] == 1
    assert data["total_entries"] == 3


def test_api_get_waitlist_summary_403_non_admin():
    """GET /shuttle/schedules/{id}/waitlist/summary — 403 non-admin blocked."""
    with (
        _patch_get_account(),
        _patch_require_account_admin(raises=True),
    ):
        app.dependency_overrides.update(_dep_overrides())
        resp = client.get(
            f"{_BASE}/schedules/{SCHEDULE_ID}/waitlist/summary?booking_date={_TODAY}"
        )
        app.dependency_overrides.clear()
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# API tests: platform-admin
# ---------------------------------------------------------------------------


def test_api_platform_list_all_200():
    """GET /platform/corporate/shuttle/waitlist/all — 200 platform-admin list all."""
    resp_data = [_make_waitlist_response()]
    with patch(f"{_ROUTER}.list_all_platform", new_callable=AsyncMock, return_value=resp_data):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        resp = client.get("/api/v1/platform/corporate/shuttle/waitlist/all")
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_api_platform_list_all_account_filter():
    """GET /platform/corporate/shuttle/waitlist/all — 200 with account_id filter."""
    with patch(f"{_ROUTER}.list_all_platform", new_callable=AsyncMock, return_value=[]):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        resp = client.get(
            f"/api/v1/platform/corporate/shuttle/waitlist/all?account_id={ACCOUNT_ID}"
        )
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json() == []


def test_api_platform_list_all_status_filter():
    """GET /platform/corporate/shuttle/waitlist/all — 200 with status filter."""
    resp_data = [_make_waitlist_response()]
    with patch(f"{_ROUTER}.list_all_platform", new_callable=AsyncMock, return_value=resp_data):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        resp = client.get("/api/v1/platform/corporate/shuttle/waitlist/all?status=waiting")
        app.dependency_overrides.clear()
    assert resp.status_code == 200


def test_api_platform_list_all_403_non_admin():
    """GET /platform/corporate/shuttle/waitlist/all — 403 non-admin blocked."""
    from app.api.deps import require_admin

    async def _raise():
        raise HTTPException(status_code=403, detail="Forbidden")

    app.dependency_overrides[require_admin] = _raise
    resp = client.get("/api/v1/platform/corporate/shuttle/waitlist/all")
    app.dependency_overrides.clear()
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Integration: cancel_booking → promote_from_waitlist
# ---------------------------------------------------------------------------

_SHUTTLE_ROUTER = "app.api.v1.corporate_shuttle"


def test_cancel_booking_calls_promote_waitlist():
    """cancel_booking endpoint — promote_from_waitlist called after cancel."""
    from app.schemas.corporate_shuttle import BookingResponse as BResp
    cancelled_booking_resp = BResp(
        id=BOOKING_ID,
        schedule_id=SCHEDULE_ID,
        account_id=ACCOUNT_ID,
        member_id=MEMBER_ID,
        booking_date=_TODAY,
        status=ShuttleBookingStatus.cancelled,
        notes=None,
        cancelled_at=_NOW,
        cancelled_by_id=USER_ID,
        cancellation_reason=None,
        created_at=_NOW,
        updated_at=_NOW,
    )

    with (
        patch(f"{_SHUTTLE_ROUTER}.get_account", new_callable=AsyncMock),
        patch(
            f"{_SHUTTLE_ROUTER}.cancel_booking",
            new_callable=AsyncMock,
            return_value=cancelled_booking_resp,
        ),
        patch(
            f"{_SHUTTLE_ROUTER}.promote_from_waitlist",
            new_callable=AsyncMock,
            return_value=None,
        ) as mock_promote,
    ):
        app.dependency_overrides.update(_dep_overrides())
        resp = client.post(
            f"/api/v1/corporate/{ACCOUNT_ID}/shuttle/bookings/{BOOKING_ID}/cancel",
            json={},
        )
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    mock_promote.assert_called_once()


def test_cancel_booking_promote_not_called_on_404():
    """cancel_booking endpoint — promote_from_waitlist not called when 404."""
    with (
        patch(f"{_SHUTTLE_ROUTER}.get_account", new_callable=AsyncMock),
        patch(
            f"{_SHUTTLE_ROUTER}.cancel_booking",
            new_callable=AsyncMock,
            side_effect=HTTPException(status_code=404, detail="not found"),
        ),
        patch(
            f"{_SHUTTLE_ROUTER}.promote_from_waitlist",
            new_callable=AsyncMock,
            return_value=None,
        ) as mock_promote,
    ):
        app.dependency_overrides.update(_dep_overrides())
        resp = client.post(
            f"/api/v1/corporate/{ACCOUNT_ID}/shuttle/bookings/{BOOKING_ID}/cancel",
            json={},
        )
        app.dependency_overrides.clear()
    assert resp.status_code == 404
    mock_promote.assert_not_called()


def test_cancel_booking_promote_success_full_flow():
    """cancel_booking endpoint — promote succeeds (full flow schema)."""
    from app.schemas.corporate_shuttle import BookingResponse as BResp
    booking_resp = BResp(
        id=BOOKING_ID,
        schedule_id=SCHEDULE_ID,
        account_id=ACCOUNT_ID,
        member_id=MEMBER_ID,
        booking_date=_TODAY,
        status=ShuttleBookingStatus.cancelled,
        notes=None,
        cancelled_at=_NOW,
        cancelled_by_id=USER_ID,
        cancellation_reason=None,
        created_at=_NOW,
        updated_at=_NOW,
    )
    promoted_entry = _make_waitlist_response(
        entry_status=WaitlistStatus.promoted,
        promoted_booking_id=uuid.uuid4(),
    )

    with (
        patch(f"{_SHUTTLE_ROUTER}.get_account", new_callable=AsyncMock),
        patch(
            f"{_SHUTTLE_ROUTER}.cancel_booking",
            new_callable=AsyncMock,
            return_value=booking_resp,
        ),
        patch(
            f"{_SHUTTLE_ROUTER}.promote_from_waitlist",
            new_callable=AsyncMock,
            return_value=promoted_entry,
        ),
    ):
        app.dependency_overrides.update(_dep_overrides())
        resp = client.post(
            f"/api/v1/corporate/{ACCOUNT_ID}/shuttle/bookings/{BOOKING_ID}/cancel",
            json={},
        )
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"


def test_cancel_booking_promote_returns_none():
    """cancel_booking endpoint — promote returns None silently (no seat)."""
    from app.schemas.corporate_shuttle import BookingResponse as BResp
    booking_resp = BResp(
        id=BOOKING_ID,
        schedule_id=SCHEDULE_ID,
        account_id=ACCOUNT_ID,
        member_id=MEMBER_ID,
        booking_date=_TODAY,
        status=ShuttleBookingStatus.cancelled,
        notes=None,
        cancelled_at=_NOW,
        cancelled_by_id=USER_ID,
        cancellation_reason=None,
        created_at=_NOW,
        updated_at=_NOW,
    )

    with (
        patch(f"{_SHUTTLE_ROUTER}.get_account", new_callable=AsyncMock),
        patch(
            f"{_SHUTTLE_ROUTER}.cancel_booking",
            new_callable=AsyncMock,
            return_value=booking_resp,
        ),
        patch(
            f"{_SHUTTLE_ROUTER}.promote_from_waitlist",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        app.dependency_overrides.update(_dep_overrides())
        resp = client.post(
            f"/api/v1/corporate/{ACCOUNT_ID}/shuttle/bookings/{BOOKING_ID}/cancel",
            json={},
        )
        app.dependency_overrides.clear()
    assert resp.status_code == 200
