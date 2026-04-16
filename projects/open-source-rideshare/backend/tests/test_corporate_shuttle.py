"""Tests for Corporate Shuttle Routes & Seat Booking.

Service layer (async, mocked DB):
   1.  create_route — success: creates route
   2.  create_route — 409 on duplicate active name in account
   3.  create_route — same name in different account is allowed
   4.  get_route — success: returns route
   5.  get_route — 404 when not found
   6.  get_route — 404 when account_id mismatch
   7.  list_routes — returns all routes for account
   8.  list_routes — filters by is_active=True
   9.  list_routes — filters by is_active=False
  10.  update_route — success: updates name
  11.  update_route — 404 when not found
  12.  update_route — 409 on name collision
  13.  update_route — same name (no change) does not 409
  14.  deactivate_route — success: sets is_active=False, cascades schedules
  15.  deactivate_route — 404 when not found
  16.  deactivate_route — 409 when already inactive
  17.  add_schedule — success: creates schedule
  18.  add_schedule — 404 when route not found
  19.  add_schedule — 409 when route is inactive
  20.  get_schedule — success: returns schedule
  21.  get_schedule — 404 when not found
  22.  list_schedules — returns all schedules for account
  23.  list_schedules — filters by route_id
  24.  list_schedules — filters by is_active
  25.  book_seat — success: creates confirmed booking
  26.  book_seat — 404 when schedule not found
  27.  book_seat — 409 when schedule inactive
  28.  book_seat — 409 when already booked (duplicate)
  29.  book_seat — 409 when capacity exceeded
  30.  cancel_booking — success: sets status=cancelled
  31.  cancel_booking — 404 when not found
  32.  cancel_booking — 409 when already completed
  33.  cancel_booking — 409 when already no_show
  34.  get_schedule_roster — returns non-cancelled bookings
  35.  get_schedule_roster — returns empty list when none
  36.  get_route_summary — returns correct counts
  37.  get_route_summary — 404 when route not found
  38.  list_member_bookings — returns member bookings
  39.  list_member_bookings — returns empty list when none
  40.  list_all_platform — returns all routes without filter
  41.  list_all_platform — filters by account_id

Schema validation:
  42.  RouteCreate — requires name, origin_name, origin_address, dest_name, dest_address
  43.  RouteCreate — rejects empty name
  44.  RouteCreate — defaults default_capacity to 20
  45.  RouteUpdate — all fields optional
  46.  ScheduleCreate — requires schedule_name, days_of_week, departure_time, seat_capacity
  47.  ScheduleCreate — departure_time must match HH:MM pattern
  48.  BookingCreate — requires booking_date
  49.  BookingCancelRequest — reason is optional
  50.  RouteResponse — from_attributes construction
  51.  ScheduleResponse — from_attributes construction
  52.  BookingResponse — from_attributes construction

API layer (service functions patched):
  53.  GET  /shuttle/routes — 200 member can list active routes
  54.  POST /shuttle/routes — 201 admin can create route
  55.  POST /shuttle/routes — 403 non-admin cannot create
  56.  POST /shuttle/routes — 409 on duplicate name
  57.  GET  /shuttle/routes/{id} — 200 member can get route
  58.  GET  /shuttle/routes/{id} — 404 when not found
  59.  PUT  /shuttle/routes/{id} — 200 admin can update route
  60.  PUT  /shuttle/routes/{id} — 403 non-admin blocked
  61.  POST /shuttle/routes/{id}/deactivate — 200 admin can deactivate
  62.  POST /shuttle/routes/{id}/deactivate — 409 already inactive
  63.  GET  /shuttle/routes/{id}/summary — 200 admin can get summary
  64.  POST /shuttle/routes/{id}/schedules — 201 admin can add schedule
  65.  POST /shuttle/routes/{id}/schedules — 403 non-admin blocked
  66.  POST /shuttle/routes/{id}/schedules — 404 route not found
  67.  GET  /shuttle/schedules/{id} — 200 member can get schedule
  68.  GET  /shuttle/schedules/{id} — 404 when not found
  69.  POST /shuttle/schedules/{id}/book — 201 member can book seat
  70.  POST /shuttle/schedules/{id}/book — 409 capacity exceeded
  71.  POST /shuttle/schedules/{id}/book — 409 already booked
  72.  GET  /shuttle/schedules/{id}/roster — 200 admin can get roster
  73.  GET  /shuttle/schedules/{id}/roster — 403 non-admin blocked
  74.  GET  /shuttle/my-bookings — 200 member can list own bookings
  75.  POST /shuttle/bookings/{id}/cancel — 200 member can cancel booking
  76.  POST /shuttle/bookings/{id}/cancel — 409 completed booking
  77.  GET  /platform/corporate/shuttle/all — 200 platform-admin list all
  78.  GET  /platform/corporate/shuttle/all — 200 with account_id filter
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
    CorporateShuttleRoute,
    CorporateShuttleSchedule,
    ShuttleBookingStatus,
)
from app.schemas.corporate_shuttle import (
    BookingCancelRequest,
    BookingCreate,
    BookingResponse,
    RouteSummaryResponse,
    RouteCreate,
    RouteResponse,
    RouteUpdate,
    ScheduleCreate,
    ScheduleResponse,
)
from app.services.corporate_shuttle_service import (
    add_schedule,
    book_seat,
    cancel_booking,
    create_route,
    deactivate_route,
    get_route,
    get_route_summary,
    get_schedule,
    get_schedule_roster,
    list_all_platform,
    list_member_bookings,
    list_routes,
    list_schedules,
    update_route,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ACCOUNT_ID = 11
ROUTE_ID = uuid.uuid4()
SCHEDULE_ID = uuid.uuid4()
BOOKING_ID = uuid.uuid4()
USER_ID = 30
ADMIN_ID = 2
MEMBER_ID = 45

_SERVICE = "app.services.corporate_shuttle_service"
_ROUTER = "app.api.v1.corporate_shuttle"

_NOW = datetime(2026, 4, 16, 9, 0, 0, tzinfo=timezone.utc)
_TODAY = date(2026, 4, 16)


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


def _make_route(
    route_id: uuid.UUID = ROUTE_ID,
    account_id: int = ACCOUNT_ID,
    name: str = "Downtown HQ → North Campus",
    is_active: bool = True,
    created_by_id: int | None = ADMIN_ID,
) -> CorporateShuttleRoute:
    r = CorporateShuttleRoute()
    r.id = route_id
    r.account_id = account_id
    r.name = name
    r.description = "Main employee shuttle route"
    r.origin_name = "Downtown HQ"
    r.origin_address = "1 Main St, Springfield, IL"
    r.origin_lat = None
    r.origin_lng = None
    r.destination_name = "North Campus"
    r.destination_address = "500 North Ave, Springfield, IL"
    r.destination_lat = None
    r.destination_lng = None
    r.route_stops = None
    r.default_capacity = 30
    r.notes = None
    r.is_active = is_active
    r.created_by_id = created_by_id
    r.created_at = _NOW
    r.updated_at = _NOW
    return r


def _make_schedule(
    schedule_id: uuid.UUID = SCHEDULE_ID,
    account_id: int = ACCOUNT_ID,
    route_id: uuid.UUID = ROUTE_ID,
    schedule_name: str = "Morning Run",
    is_active: bool = True,
    seat_capacity: int = 20,
    days_of_week: list | None = None,
) -> CorporateShuttleSchedule:
    s = CorporateShuttleSchedule()
    s.id = schedule_id
    s.route_id = route_id
    s.account_id = account_id
    s.schedule_name = schedule_name
    s.days_of_week = days_of_week if days_of_week is not None else [0, 1, 2, 3, 4]
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
    account_id: int = ACCOUNT_ID,
    schedule_id: uuid.UUID = SCHEDULE_ID,
    member_id: int = MEMBER_ID,
    booking_date: date = _TODAY,
    booking_status: ShuttleBookingStatus = ShuttleBookingStatus.confirmed,
    cancelled_at: datetime | None = None,
    cancelled_by_id: int | None = None,
    cancellation_reason: str | None = None,
) -> CorporateShuttleBooking:
    b = CorporateShuttleBooking()
    b.id = booking_id
    b.schedule_id = schedule_id
    b.account_id = account_id
    b.member_id = member_id
    b.booking_date = booking_date
    b.status = booking_status
    b.notes = None
    b.cancelled_at = cancelled_at
    b.cancelled_by_id = cancelled_by_id
    b.cancellation_reason = cancellation_reason
    b.created_at = _NOW
    b.updated_at = _NOW
    return b


# ---------------------------------------------------------------------------
# DB mock helpers
# ---------------------------------------------------------------------------


def _scalar_result(value):
    r = MagicMock()
    r.scalar_one_or_none.return_value = value
    return r


def _scalar_one_result(value):
    r = MagicMock()
    r.scalar_one.return_value = value
    return r


def _scalars_result(rows: list):
    r = MagicMock()
    r.scalars.return_value.all.return_value = rows
    return r


def _all_result(rows: list):
    r = MagicMock()
    r.all.return_value = rows
    return r


def _make_db(*side_effects):
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=list(side_effects))
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    db.add = MagicMock()
    return db


# ===========================================================================
# SERVICE LAYER TESTS
# ===========================================================================


# ---------------------------------------------------------------------------
# create_route
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_route_success():
    """create_route creates a route when name is unique."""
    route = _make_route()
    db = _make_db(_scalar_result(None))  # no duplicate

    async def _refresh(obj):
        obj.id = ROUTE_ID
        obj.account_id = ACCOUNT_ID
        obj.name = "Downtown HQ → North Campus"
        obj.description = "Main employee shuttle route"
        obj.origin_name = "Downtown HQ"
        obj.origin_address = "1 Main St, Springfield, IL"
        obj.origin_lat = None
        obj.origin_lng = None
        obj.destination_name = "North Campus"
        obj.destination_address = "500 North Ave, Springfield, IL"
        obj.destination_lat = None
        obj.destination_lng = None
        obj.route_stops = None
        obj.default_capacity = 30
        obj.notes = None
        obj.is_active = True
        obj.created_by_id = ADMIN_ID
        obj.created_at = _NOW
        obj.updated_at = _NOW

    db.refresh = _refresh
    data = RouteCreate(
        name="Downtown HQ → North Campus",
        origin_name="Downtown HQ",
        origin_address="1 Main St, Springfield, IL",
        destination_name="North Campus",
        destination_address="500 North Ave, Springfield, IL",
        default_capacity=30,
    )
    result = await create_route(db, ACCOUNT_ID, data, created_by_id=ADMIN_ID)
    assert result.name == "Downtown HQ → North Campus"
    assert result.is_active is True
    assert result.default_capacity == 30


@pytest.mark.asyncio
async def test_create_route_409_duplicate_name():
    """create_route raises 409 when an active route with the same name exists."""
    db = _make_db(_scalar_result(_make_route()))  # duplicate found
    data = RouteCreate(
        name="Downtown HQ → North Campus",
        origin_name="Downtown HQ",
        origin_address="1 Main St",
        destination_name="North Campus",
        destination_address="500 North Ave",
    )
    with pytest.raises(HTTPException) as exc:
        await create_route(db, ACCOUNT_ID, data)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_create_route_different_account_allowed():
    """create_route allows same name in a different account."""
    db = _make_db(_scalar_result(None))  # no collision for account 99

    async def _refresh(obj):
        obj.id = uuid.uuid4()
        obj.account_id = 99
        obj.name = "Downtown HQ → North Campus"
        obj.description = None
        obj.origin_name = "Downtown HQ"
        obj.origin_address = "1 Main St"
        obj.origin_lat = None
        obj.origin_lng = None
        obj.destination_name = "North Campus"
        obj.destination_address = "500 North Ave"
        obj.destination_lat = None
        obj.destination_lng = None
        obj.route_stops = None
        obj.default_capacity = 20
        obj.notes = None
        obj.is_active = True
        obj.created_by_id = None
        obj.created_at = _NOW
        obj.updated_at = _NOW

    db.refresh = _refresh
    data = RouteCreate(
        name="Downtown HQ → North Campus",
        origin_name="Downtown HQ",
        origin_address="1 Main St",
        destination_name="North Campus",
        destination_address="500 North Ave",
    )
    result = await create_route(db, 99, data)
    assert result.account_id == 99


# ---------------------------------------------------------------------------
# get_route
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_route_success():
    route = _make_route()
    db = _make_db(_scalar_result(route))
    result = await get_route(db, ROUTE_ID, ACCOUNT_ID)
    assert result.id == ROUTE_ID


@pytest.mark.asyncio
async def test_get_route_404_not_found():
    db = _make_db(_scalar_result(None))
    with pytest.raises(HTTPException) as exc:
        await get_route(db, ROUTE_ID, ACCOUNT_ID)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_get_route_404_wrong_account():
    db = _make_db(_scalar_result(None))
    with pytest.raises(HTTPException) as exc:
        await get_route(db, ROUTE_ID, 999)
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# list_routes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_routes_returns_all():
    routes = [_make_route(), _make_route(route_id=uuid.uuid4(), name="South Route")]
    db = _make_db(_scalars_result(routes))
    result = await list_routes(db, ACCOUNT_ID)
    assert len(result) == 2


@pytest.mark.asyncio
async def test_list_routes_filters_active():
    active = _make_route()
    db = _make_db(_scalars_result([active]))
    result = await list_routes(db, ACCOUNT_ID, is_active=True)
    assert all(r.is_active for r in result)


@pytest.mark.asyncio
async def test_list_routes_filters_inactive():
    inactive = _make_route(is_active=False)
    db = _make_db(_scalars_result([inactive]))
    result = await list_routes(db, ACCOUNT_ID, is_active=False)
    assert all(not r.is_active for r in result)


# ---------------------------------------------------------------------------
# update_route
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_route_success():
    route = _make_route()
    db = _make_db(
        _scalar_result(route),  # _fetch_route
        _scalar_result(None),   # collision check
    )

    async def _refresh(obj):
        pass

    db.refresh = _refresh
    data = RouteUpdate(name="Updated Route", notes="Updated notes")
    result = await update_route(db, ROUTE_ID, ACCOUNT_ID, data)
    assert result.name == "Updated Route"
    assert result.notes == "Updated notes"


@pytest.mark.asyncio
async def test_update_route_404():
    db = _make_db(_scalar_result(None))
    data = RouteUpdate(name="X")
    with pytest.raises(HTTPException) as exc:
        await update_route(db, ROUTE_ID, ACCOUNT_ID, data)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_update_route_409_name_collision():
    route = _make_route()
    other = _make_route(route_id=uuid.uuid4(), name="Other Route")
    db = _make_db(
        _scalar_result(route),  # _fetch_route
        _scalar_result(other),  # collision found
    )
    data = RouteUpdate(name="Other Route")
    with pytest.raises(HTTPException) as exc:
        await update_route(db, ROUTE_ID, ACCOUNT_ID, data)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_update_route_same_name_no_409():
    """Updating with the same name should not raise 409."""
    route = _make_route(name="Downtown HQ → North Campus")
    db = _make_db(_scalar_result(route))  # only _fetch_route; no collision check needed

    async def _refresh(obj):
        pass

    db.refresh = _refresh
    data = RouteUpdate(notes="Changed notes only")
    result = await update_route(db, ROUTE_ID, ACCOUNT_ID, data)
    assert result.notes == "Changed notes only"


# ---------------------------------------------------------------------------
# deactivate_route
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deactivate_route_success():
    """deactivate_route sets is_active=False and cascades to active schedules."""
    route = _make_route(is_active=True)
    schedule = _make_schedule(is_active=True)
    db = _make_db(
        _scalar_result(route),       # _fetch_route
        _scalars_result([schedule]), # active schedules to cascade
    )

    async def _refresh(obj):
        pass

    db.refresh = _refresh
    result = await deactivate_route(db, ROUTE_ID, ACCOUNT_ID)
    assert result.is_active is False
    assert schedule.is_active is False  # cascaded


@pytest.mark.asyncio
async def test_deactivate_route_404():
    db = _make_db(_scalar_result(None))
    with pytest.raises(HTTPException) as exc:
        await deactivate_route(db, ROUTE_ID, ACCOUNT_ID)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_deactivate_route_409_already_inactive():
    route = _make_route(is_active=False)
    db = _make_db(_scalar_result(route))
    with pytest.raises(HTTPException) as exc:
        await deactivate_route(db, ROUTE_ID, ACCOUNT_ID)
    assert exc.value.status_code == 409


# ---------------------------------------------------------------------------
# add_schedule
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_schedule_success():
    route = _make_route(is_active=True)
    db = _make_db(_scalar_result(route))  # _fetch_route

    async def _refresh(obj):
        obj.id = SCHEDULE_ID
        obj.route_id = ROUTE_ID
        obj.account_id = ACCOUNT_ID
        obj.schedule_name = "Morning Run"
        obj.days_of_week = [0, 1, 2, 3, 4]
        obj.departure_time = "08:00"
        obj.estimated_duration_minutes = 25
        obj.seat_capacity = 20
        obj.notes = None
        obj.is_active = True
        obj.created_by_id = ADMIN_ID
        obj.created_at = _NOW
        obj.updated_at = _NOW

    db.refresh = _refresh
    data = ScheduleCreate(
        schedule_name="Morning Run",
        days_of_week=[0, 1, 2, 3, 4],
        departure_time="08:00",
        seat_capacity=20,
    )
    result = await add_schedule(db, ROUTE_ID, ACCOUNT_ID, data, created_by_id=ADMIN_ID)
    assert result.schedule_name == "Morning Run"
    assert result.is_active is True


@pytest.mark.asyncio
async def test_add_schedule_404_route_not_found():
    db = _make_db(_scalar_result(None))
    data = ScheduleCreate(
        schedule_name="Morning Run",
        days_of_week=[0, 1, 2, 3, 4],
        departure_time="08:00",
        seat_capacity=20,
    )
    with pytest.raises(HTTPException) as exc:
        await add_schedule(db, ROUTE_ID, ACCOUNT_ID, data)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_add_schedule_409_route_inactive():
    route = _make_route(is_active=False)
    db = _make_db(_scalar_result(route))
    data = ScheduleCreate(
        schedule_name="Morning Run",
        days_of_week=[0, 1, 2, 3, 4],
        departure_time="08:00",
        seat_capacity=20,
    )
    with pytest.raises(HTTPException) as exc:
        await add_schedule(db, ROUTE_ID, ACCOUNT_ID, data)
    assert exc.value.status_code == 409


# ---------------------------------------------------------------------------
# get_schedule
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_schedule_success():
    schedule = _make_schedule()
    db = _make_db(_scalar_result(schedule))
    result = await get_schedule(db, SCHEDULE_ID, ACCOUNT_ID)
    assert result.id == SCHEDULE_ID


@pytest.mark.asyncio
async def test_get_schedule_404():
    db = _make_db(_scalar_result(None))
    with pytest.raises(HTTPException) as exc:
        await get_schedule(db, SCHEDULE_ID, ACCOUNT_ID)
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# list_schedules
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_schedules_returns_all():
    schedules = [_make_schedule(), _make_schedule(schedule_id=uuid.uuid4(), schedule_name="Evening Run")]
    db = _make_db(_scalars_result(schedules))
    result = await list_schedules(db, ACCOUNT_ID)
    assert len(result) == 2


@pytest.mark.asyncio
async def test_list_schedules_filters_by_route():
    schedule = _make_schedule()
    db = _make_db(_scalars_result([schedule]))
    result = await list_schedules(db, ACCOUNT_ID, route_id=ROUTE_ID)
    assert result[0].route_id == ROUTE_ID


@pytest.mark.asyncio
async def test_list_schedules_filters_by_is_active():
    active = _make_schedule(is_active=True)
    db = _make_db(_scalars_result([active]))
    result = await list_schedules(db, ACCOUNT_ID, is_active=True)
    assert all(r.is_active for r in result)


# ---------------------------------------------------------------------------
# book_seat
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_book_seat_success():
    schedule = _make_schedule(is_active=True, seat_capacity=10)
    db = _make_db(
        _scalar_result(schedule),  # _fetch_schedule
        _scalar_result(None),       # duplicate check → no duplicate
        _scalar_one_result(3),      # capacity check → 3 booked < 10
    )

    async def _refresh(obj):
        obj.id = BOOKING_ID
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

    db.refresh = _refresh
    result = await book_seat(db, SCHEDULE_ID, ACCOUNT_ID, MEMBER_ID, _TODAY)
    assert result.status == ShuttleBookingStatus.confirmed
    assert result.member_id == MEMBER_ID


@pytest.mark.asyncio
async def test_book_seat_404_schedule_not_found():
    db = _make_db(_scalar_result(None))
    with pytest.raises(HTTPException) as exc:
        await book_seat(db, SCHEDULE_ID, ACCOUNT_ID, MEMBER_ID, _TODAY)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_book_seat_409_schedule_inactive():
    schedule = _make_schedule(is_active=False)
    db = _make_db(_scalar_result(schedule))
    with pytest.raises(HTTPException) as exc:
        await book_seat(db, SCHEDULE_ID, ACCOUNT_ID, MEMBER_ID, _TODAY)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_book_seat_409_already_booked():
    schedule = _make_schedule(is_active=True, seat_capacity=10)
    existing = _make_booking()
    db = _make_db(
        _scalar_result(schedule),   # _fetch_schedule
        _scalar_result(existing),   # duplicate found
    )
    with pytest.raises(HTTPException) as exc:
        await book_seat(db, SCHEDULE_ID, ACCOUNT_ID, MEMBER_ID, _TODAY)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_book_seat_409_capacity_exceeded():
    schedule = _make_schedule(is_active=True, seat_capacity=5)
    db = _make_db(
        _scalar_result(schedule),  # _fetch_schedule
        _scalar_result(None),       # no duplicate
        _scalar_one_result(5),      # already 5 booked == capacity
    )
    with pytest.raises(HTTPException) as exc:
        await book_seat(db, SCHEDULE_ID, ACCOUNT_ID, MEMBER_ID, _TODAY)
    assert exc.value.status_code == 409


# ---------------------------------------------------------------------------
# cancel_booking
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cancel_booking_success():
    booking = _make_booking(booking_status=ShuttleBookingStatus.confirmed)
    db = _make_db(_scalar_result(booking))

    async def _refresh(obj):
        pass

    db.refresh = _refresh
    result = await cancel_booking(db, BOOKING_ID, ACCOUNT_ID, ADMIN_ID, reason="Changed plans")
    assert result.status == ShuttleBookingStatus.cancelled
    assert result.cancelled_by_id == ADMIN_ID
    assert result.cancellation_reason == "Changed plans"


@pytest.mark.asyncio
async def test_cancel_booking_404():
    db = _make_db(_scalar_result(None))
    with pytest.raises(HTTPException) as exc:
        await cancel_booking(db, BOOKING_ID, ACCOUNT_ID, ADMIN_ID)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_cancel_booking_409_completed():
    booking = _make_booking(booking_status=ShuttleBookingStatus.completed)
    db = _make_db(_scalar_result(booking))
    with pytest.raises(HTTPException) as exc:
        await cancel_booking(db, BOOKING_ID, ACCOUNT_ID, ADMIN_ID)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_cancel_booking_409_no_show():
    booking = _make_booking(booking_status=ShuttleBookingStatus.no_show)
    db = _make_db(_scalar_result(booking))
    with pytest.raises(HTTPException) as exc:
        await cancel_booking(db, BOOKING_ID, ACCOUNT_ID, ADMIN_ID)
    assert exc.value.status_code == 409


# ---------------------------------------------------------------------------
# get_schedule_roster
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_schedule_roster_returns_non_cancelled():
    booking = _make_booking(booking_status=ShuttleBookingStatus.confirmed)
    db = _make_db(_scalars_result([booking]))
    result = await get_schedule_roster(db, SCHEDULE_ID, ACCOUNT_ID, _TODAY)
    assert len(result) == 1
    assert result[0].status == ShuttleBookingStatus.confirmed


@pytest.mark.asyncio
async def test_get_schedule_roster_empty():
    db = _make_db(_scalars_result([]))
    result = await get_schedule_roster(db, SCHEDULE_ID, ACCOUNT_ID, _TODAY)
    assert result == []


# ---------------------------------------------------------------------------
# get_route_summary
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_route_summary_returns_correct_counts():
    route = _make_route()
    # Active schedule with days [0,1,2,3,4] — Mon–Fri
    # 2026-04-16 is a Thursday (weekday=3 → in [0,1,2,3,4])
    schedule = _make_schedule(days_of_week=[0, 1, 2, 3, 4])
    db = AsyncMock()
    sched_id_row = MagicMock()
    sched_id_row.__getitem__ = lambda self, i: SCHEDULE_ID

    execute_results = [
        _scalar_result(route),          # _fetch_route
        _scalar_one_result(3),           # total_schedules
        _scalar_one_result(2),           # active_schedules
        _all_result([(SCHEDULE_ID,)]),   # sched_ids
        _scalar_one_result(10),          # total_bookings_this_month
        _scalars_result([schedule]),     # active scheds for upcoming dates
    ]
    db.execute = AsyncMock(side_effect=execute_results)
    db.flush = AsyncMock()
    db.refresh = AsyncMock()

    result = await get_route_summary(db, ROUTE_ID, ACCOUNT_ID)
    assert result.total_schedules == 3
    assert result.active_schedules == 2
    assert result.total_bookings_this_month == 10
    # 2026-04-16 is Thursday (weekday=3), which is in [0,1,2,3,4]
    assert _TODAY in result.upcoming_run_dates


@pytest.mark.asyncio
async def test_get_route_summary_404():
    db = _make_db(_scalar_result(None))
    with pytest.raises(HTTPException) as exc:
        await get_route_summary(db, ROUTE_ID, ACCOUNT_ID)
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# list_member_bookings
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_member_bookings_returns_bookings():
    booking = _make_booking()
    db = _make_db(_scalars_result([booking]))
    result = await list_member_bookings(db, ACCOUNT_ID, MEMBER_ID)
    assert len(result) == 1
    assert result[0].member_id == MEMBER_ID


@pytest.mark.asyncio
async def test_list_member_bookings_empty():
    db = _make_db(_scalars_result([]))
    result = await list_member_bookings(db, ACCOUNT_ID, MEMBER_ID)
    assert result == []


# ---------------------------------------------------------------------------
# list_all_platform
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_all_platform_no_filter():
    routes = [
        _make_route(),
        _make_route(route_id=uuid.uuid4(), account_id=99, name="Remote Route"),
    ]
    db = _make_db(_scalars_result(routes))
    result = await list_all_platform(db)
    assert len(result) == 2


@pytest.mark.asyncio
async def test_list_all_platform_filters_by_account():
    route = _make_route()
    db = _make_db(_scalars_result([route]))
    result = await list_all_platform(db, account_id=ACCOUNT_ID)
    assert len(result) == 1
    assert result[0].account_id == ACCOUNT_ID


# ===========================================================================
# SCHEMA VALIDATION TESTS
# ===========================================================================


def test_route_create_requires_required_fields():
    with pytest.raises(ValidationError):
        RouteCreate(
            origin_name="A",
            origin_address="B",
            destination_name="C",
            destination_address="D",
        )  # missing name


def test_route_create_rejects_empty_name():
    with pytest.raises(ValidationError):
        RouteCreate(
            name="",
            origin_name="A",
            origin_address="B",
            destination_name="C",
            destination_address="D",
        )


def test_route_create_defaults_capacity():
    rc = RouteCreate(
        name="Test",
        origin_name="A",
        origin_address="B",
        destination_name="C",
        destination_address="D",
    )
    assert rc.default_capacity == 20


def test_route_update_all_optional():
    ru = RouteUpdate()
    assert ru.name is None
    assert ru.origin_name is None
    assert ru.default_capacity is None


def test_schedule_create_requires_fields():
    with pytest.raises(ValidationError):
        ScheduleCreate(
            days_of_week=[0, 1],
            departure_time="08:00",
            seat_capacity=20,
        )  # missing schedule_name


def test_schedule_create_departure_time_pattern():
    with pytest.raises(ValidationError):
        ScheduleCreate(
            schedule_name="Morning",
            days_of_week=[0],
            departure_time="8:00",  # invalid — must be HH:MM
            seat_capacity=20,
        )


def test_schedule_create_valid():
    sc = ScheduleCreate(
        schedule_name="Morning Run",
        days_of_week=[0, 1, 2, 3, 4],
        departure_time="08:00",
        seat_capacity=20,
    )
    assert sc.seat_capacity == 20


def test_booking_create_requires_booking_date():
    with pytest.raises(ValidationError):
        BookingCreate()


def test_booking_cancel_request_reason_optional():
    bcr = BookingCancelRequest()
    assert bcr.reason is None


def test_route_response_from_attributes():
    route = _make_route()
    resp = RouteResponse.model_validate(route)
    assert resp.id == ROUTE_ID
    assert resp.account_id == ACCOUNT_ID
    assert resp.name == "Downtown HQ → North Campus"
    assert resp.is_active is True


def test_schedule_response_from_attributes():
    schedule = _make_schedule()
    resp = ScheduleResponse.model_validate(schedule)
    assert resp.id == SCHEDULE_ID
    assert resp.schedule_name == "Morning Run"
    assert resp.seat_capacity == 20


def test_booking_response_from_attributes():
    booking = _make_booking()
    resp = BookingResponse.model_validate(booking)
    assert resp.id == BOOKING_ID
    assert resp.member_id == MEMBER_ID
    assert resp.status == ShuttleBookingStatus.confirmed


# ===========================================================================
# API LAYER TESTS
# ===========================================================================

_BASE = f"/api/v1/corporate/{ACCOUNT_ID}/shuttle"

_client = TestClient(app)


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


def _route_payload():
    return RouteResponse(
        id=ROUTE_ID,
        account_id=ACCOUNT_ID,
        name="Downtown HQ → North Campus",
        description=None,
        origin_name="Downtown HQ",
        origin_address="1 Main St",
        origin_lat=None,
        origin_lng=None,
        destination_name="North Campus",
        destination_address="500 North Ave",
        destination_lat=None,
        destination_lng=None,
        route_stops=None,
        default_capacity=30,
        notes=None,
        is_active=True,
        created_by_id=ADMIN_ID,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _schedule_payload():
    return ScheduleResponse(
        id=SCHEDULE_ID,
        route_id=ROUTE_ID,
        account_id=ACCOUNT_ID,
        schedule_name="Morning Run",
        days_of_week=[0, 1, 2, 3, 4],
        departure_time="08:00",
        estimated_duration_minutes=25,
        seat_capacity=20,
        notes=None,
        is_active=True,
        created_by_id=ADMIN_ID,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _booking_payload(bstatus: ShuttleBookingStatus = ShuttleBookingStatus.confirmed):
    return BookingResponse(
        id=BOOKING_ID,
        schedule_id=SCHEDULE_ID,
        account_id=ACCOUNT_ID,
        member_id=MEMBER_ID,
        booking_date=_TODAY,
        status=bstatus,
        notes=None,
        cancelled_at=None,
        cancelled_by_id=None,
        cancellation_reason=None,
        created_at=_NOW,
        updated_at=_NOW,
    )


# ---- Member: list active routes ----


def test_api_list_active_routes_200():
    with (
        _patch_get_account(),
        patch(f"{_ROUTER}.list_routes", new_callable=AsyncMock, return_value=[_route_payload()]),
    ):
        app.dependency_overrides.update(_dep_overrides())
        resp = _client.get(f"{_BASE}/routes")
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert len(resp.json()) == 1
    assert resp.json()[0]["name"] == "Downtown HQ → North Campus"


# ---- Admin: create route ----


def test_api_create_route_201():
    with (
        _patch_get_account(),
        _patch_require_account_admin(),
        patch(f"{_ROUTER}.create_route", new_callable=AsyncMock, return_value=_route_payload()),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        resp = _client.post(
            f"{_BASE}/routes",
            json={
                "name": "Downtown HQ → North Campus",
                "origin_name": "Downtown HQ",
                "origin_address": "1 Main St",
                "destination_name": "North Campus",
                "destination_address": "500 North Ave",
            },
        )
        app.dependency_overrides.clear()
    assert resp.status_code == 201
    assert resp.json()["name"] == "Downtown HQ → North Campus"


def test_api_create_route_403_non_admin():
    with (
        _patch_get_account(),
        _patch_require_account_admin(raises=True),
    ):
        app.dependency_overrides.update(_dep_overrides())
        resp = _client.post(
            f"{_BASE}/routes",
            json={
                "name": "Route",
                "origin_name": "A",
                "origin_address": "B",
                "destination_name": "C",
                "destination_address": "D",
            },
        )
        app.dependency_overrides.clear()
    assert resp.status_code == 403


def test_api_create_route_409_duplicate():
    with (
        _patch_get_account(),
        _patch_require_account_admin(),
        patch(
            f"{_ROUTER}.create_route",
            new_callable=AsyncMock,
            side_effect=HTTPException(status_code=409, detail="Duplicate name"),
        ),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        resp = _client.post(
            f"{_BASE}/routes",
            json={
                "name": "Duplicate",
                "origin_name": "A",
                "origin_address": "B",
                "destination_name": "C",
                "destination_address": "D",
            },
        )
        app.dependency_overrides.clear()
    assert resp.status_code == 409


# ---- Member: get route ----


def test_api_get_route_200():
    with (
        _patch_get_account(),
        patch(f"{_ROUTER}.get_route", new_callable=AsyncMock, return_value=_route_payload()),
    ):
        app.dependency_overrides.update(_dep_overrides())
        resp = _client.get(f"{_BASE}/routes/{ROUTE_ID}")
        app.dependency_overrides.clear()
    assert resp.status_code == 200


def test_api_get_route_404():
    with (
        _patch_get_account(),
        patch(
            f"{_ROUTER}.get_route",
            new_callable=AsyncMock,
            side_effect=HTTPException(status_code=404, detail="Not found"),
        ),
    ):
        app.dependency_overrides.update(_dep_overrides())
        resp = _client.get(f"{_BASE}/routes/{ROUTE_ID}")
        app.dependency_overrides.clear()
    assert resp.status_code == 404


# ---- Admin: update route ----


def test_api_update_route_200():
    with (
        _patch_get_account(),
        _patch_require_account_admin(),
        patch(f"{_ROUTER}.update_route", new_callable=AsyncMock, return_value=_route_payload()),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        resp = _client.put(f"{_BASE}/routes/{ROUTE_ID}", json={"notes": "Updated"})
        app.dependency_overrides.clear()
    assert resp.status_code == 200


def test_api_update_route_403():
    with (
        _patch_get_account(),
        _patch_require_account_admin(raises=True),
    ):
        app.dependency_overrides.update(_dep_overrides())
        resp = _client.put(f"{_BASE}/routes/{ROUTE_ID}", json={"notes": "Updated"})
        app.dependency_overrides.clear()
    assert resp.status_code == 403


# ---- Admin: deactivate route ----


def test_api_deactivate_route_200():
    inactive_payload = _route_payload().model_copy(update={"is_active": False})
    with (
        _patch_get_account(),
        _patch_require_account_admin(),
        patch(f"{_ROUTER}.deactivate_route", new_callable=AsyncMock, return_value=inactive_payload),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        resp = _client.post(f"{_BASE}/routes/{ROUTE_ID}/deactivate")
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False


def test_api_deactivate_route_409():
    with (
        _patch_get_account(),
        _patch_require_account_admin(),
        patch(
            f"{_ROUTER}.deactivate_route",
            new_callable=AsyncMock,
            side_effect=HTTPException(status_code=409, detail="Already inactive"),
        ),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        resp = _client.post(f"{_BASE}/routes/{ROUTE_ID}/deactivate")
        app.dependency_overrides.clear()
    assert resp.status_code == 409


# ---- Admin: route summary ----


def test_api_get_route_summary_200():
    summary = RouteSummaryResponse(
        route=_route_payload(),
        total_schedules=3,
        active_schedules=2,
        total_bookings_this_month=10,
        upcoming_run_dates=[_TODAY],
    )
    with (
        _patch_get_account(),
        _patch_require_account_admin(),
        patch(f"{_ROUTER}.get_route_summary", new_callable=AsyncMock, return_value=summary),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        resp = _client.get(f"{_BASE}/routes/{ROUTE_ID}/summary")
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json()["total_schedules"] == 3


# ---- Admin: add schedule ----


def test_api_add_schedule_201():
    with (
        _patch_get_account(),
        _patch_require_account_admin(),
        patch(f"{_ROUTER}.add_schedule", new_callable=AsyncMock, return_value=_schedule_payload()),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        resp = _client.post(
            f"{_BASE}/routes/{ROUTE_ID}/schedules",
            json={
                "schedule_name": "Morning Run",
                "days_of_week": [0, 1, 2, 3, 4],
                "departure_time": "08:00",
                "seat_capacity": 20,
            },
        )
        app.dependency_overrides.clear()
    assert resp.status_code == 201
    assert resp.json()["schedule_name"] == "Morning Run"


def test_api_add_schedule_403_non_admin():
    with (
        _patch_get_account(),
        _patch_require_account_admin(raises=True),
    ):
        app.dependency_overrides.update(_dep_overrides())
        resp = _client.post(
            f"{_BASE}/routes/{ROUTE_ID}/schedules",
            json={
                "schedule_name": "Morning Run",
                "days_of_week": [0],
                "departure_time": "08:00",
                "seat_capacity": 20,
            },
        )
        app.dependency_overrides.clear()
    assert resp.status_code == 403


def test_api_add_schedule_404_route_not_found():
    with (
        _patch_get_account(),
        _patch_require_account_admin(),
        patch(
            f"{_ROUTER}.add_schedule",
            new_callable=AsyncMock,
            side_effect=HTTPException(status_code=404, detail="Route not found"),
        ),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        resp = _client.post(
            f"{_BASE}/routes/{ROUTE_ID}/schedules",
            json={
                "schedule_name": "Morning Run",
                "days_of_week": [0],
                "departure_time": "08:00",
                "seat_capacity": 20,
            },
        )
        app.dependency_overrides.clear()
    assert resp.status_code == 404


# ---- Member: get schedule ----


def test_api_get_schedule_200():
    with (
        _patch_get_account(),
        patch(f"{_ROUTER}.get_schedule", new_callable=AsyncMock, return_value=_schedule_payload()),
    ):
        app.dependency_overrides.update(_dep_overrides())
        resp = _client.get(f"{_BASE}/schedules/{SCHEDULE_ID}")
        app.dependency_overrides.clear()
    assert resp.status_code == 200


def test_api_get_schedule_404():
    with (
        _patch_get_account(),
        patch(
            f"{_ROUTER}.get_schedule",
            new_callable=AsyncMock,
            side_effect=HTTPException(status_code=404, detail="Not found"),
        ),
    ):
        app.dependency_overrides.update(_dep_overrides())
        resp = _client.get(f"{_BASE}/schedules/{SCHEDULE_ID}")
        app.dependency_overrides.clear()
    assert resp.status_code == 404


# ---- Member: book seat ----


def test_api_book_seat_201():
    with (
        _patch_get_account(),
        patch(f"{_ROUTER}.book_seat", new_callable=AsyncMock, return_value=_booking_payload()),
    ):
        app.dependency_overrides.update(_dep_overrides())
        resp = _client.post(
            f"{_BASE}/schedules/{SCHEDULE_ID}/book",
            json={"booking_date": str(_TODAY)},
        )
        app.dependency_overrides.clear()
    assert resp.status_code == 201
    assert resp.json()["status"] == "confirmed"


def test_api_book_seat_409_capacity():
    with (
        _patch_get_account(),
        patch(
            f"{_ROUTER}.book_seat",
            new_callable=AsyncMock,
            side_effect=HTTPException(status_code=409, detail="No seats available"),
        ),
    ):
        app.dependency_overrides.update(_dep_overrides())
        resp = _client.post(
            f"{_BASE}/schedules/{SCHEDULE_ID}/book",
            json={"booking_date": str(_TODAY)},
        )
        app.dependency_overrides.clear()
    assert resp.status_code == 409


def test_api_book_seat_409_already_booked():
    with (
        _patch_get_account(),
        patch(
            f"{_ROUTER}.book_seat",
            new_callable=AsyncMock,
            side_effect=HTTPException(status_code=409, detail="Already booked"),
        ),
    ):
        app.dependency_overrides.update(_dep_overrides())
        resp = _client.post(
            f"{_BASE}/schedules/{SCHEDULE_ID}/book",
            json={"booking_date": str(_TODAY)},
        )
        app.dependency_overrides.clear()
    assert resp.status_code == 409


# ---- Admin: roster ----


def test_api_get_roster_200():
    with (
        _patch_get_account(),
        _patch_require_account_admin(),
        patch(
            f"{_ROUTER}.get_schedule_roster",
            new_callable=AsyncMock,
            return_value=[_booking_payload()],
        ),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        resp = _client.get(
            f"{_BASE}/schedules/{SCHEDULE_ID}/roster",
            params={"booking_date": str(_TODAY)},
        )
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_api_get_roster_403_non_admin():
    with (
        _patch_get_account(),
        _patch_require_account_admin(raises=True),
    ):
        app.dependency_overrides.update(_dep_overrides())
        resp = _client.get(
            f"{_BASE}/schedules/{SCHEDULE_ID}/roster",
            params={"booking_date": str(_TODAY)},
        )
        app.dependency_overrides.clear()
    assert resp.status_code == 403


# ---- Member: my bookings ----


def test_api_my_bookings_200():
    with (
        _patch_get_account(),
        patch(
            f"{_ROUTER}.list_member_bookings",
            new_callable=AsyncMock,
            return_value=[_booking_payload()],
        ),
    ):
        app.dependency_overrides.update(_dep_overrides())
        resp = _client.get(f"{_BASE}/my-bookings")
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json()[0]["member_id"] == MEMBER_ID


# ---- Member: cancel booking ----


def test_api_cancel_booking_200():
    cancelled = _booking_payload(bstatus=ShuttleBookingStatus.cancelled)
    with (
        _patch_get_account(),
        patch(f"{_ROUTER}.cancel_booking", new_callable=AsyncMock, return_value=cancelled),
    ):
        app.dependency_overrides.update(_dep_overrides())
        resp = _client.post(f"{_BASE}/bookings/{BOOKING_ID}/cancel", json={})
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"


def test_api_cancel_booking_409_completed():
    with (
        _patch_get_account(),
        patch(
            f"{_ROUTER}.cancel_booking",
            new_callable=AsyncMock,
            side_effect=HTTPException(status_code=409, detail="Cannot cancel completed"),
        ),
    ):
        app.dependency_overrides.update(_dep_overrides())
        resp = _client.post(f"{_BASE}/bookings/{BOOKING_ID}/cancel", json={})
        app.dependency_overrides.clear()
    assert resp.status_code == 409


# ---- Platform-admin ----


def test_api_platform_list_all_200():
    with (
        patch(
            f"{_ROUTER}.list_all_platform",
            new_callable=AsyncMock,
            return_value=[_route_payload()],
        ),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        resp = _client.get("/api/v1/platform/corporate/shuttle/all")
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_api_platform_list_all_with_account_filter():
    with (
        patch(
            f"{_ROUTER}.list_all_platform",
            new_callable=AsyncMock,
            return_value=[_route_payload()],
        ),
    ):
        app.dependency_overrides.update(_dep_overrides(user_id=ADMIN_ID, is_admin=True))
        resp = _client.get(f"/api/v1/platform/corporate/shuttle/all?account_id={ACCOUNT_ID}")
        app.dependency_overrides.clear()
    assert resp.status_code == 200
