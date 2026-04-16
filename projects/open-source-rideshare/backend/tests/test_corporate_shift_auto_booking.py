"""Tests for the Corporate Shift Auto-Booking feature.

Helper utility:
   1. _upcoming_dates_for_shift — empty days_of_week returns nothing
   2. _upcoming_dates_for_shift — all days returns every date in range
   3. _upcoming_dates_for_shift — specific days returns only matching dates
   4. _build_address — assembles non-None parts
   5. _build_address — returns empty string when all parts None

Service layer (async, mocked DB):
   6.  generate_shift_auto_bookings — creates to_work bookings for upcoming dates
   7.  generate_shift_auto_bookings — include_return_rides creates from_work too
   8.  generate_shift_auto_bookings — skips duplicate on IntegrityError
   9.  generate_shift_auto_bookings — no assignments → created=0 skipped=0
  10.  generate_shift_auto_bookings — scans correct account only
  11.  get_shift_auto_booking — returns record when found
  12.  get_shift_auto_booking — raises 404 when not found
  13.  list_shift_auto_bookings — returns all records for account
  14.  list_shift_auto_bookings — filters by shift_id
  15.  list_shift_auto_bookings — filters by member_id
  16.  list_shift_auto_bookings — filters by status
  17.  list_shift_auto_bookings — filters by direction
  18.  list_member_auto_bookings — delegates to list_shift_auto_bookings
  19.  cancel_shift_auto_booking — raises 404 when not found
  20.  cancel_shift_auto_booking — raises 409 when status is booked
  21.  cancel_shift_auto_booking — raises 409 when status is cancelled
  22.  cancel_shift_auto_booking — sets status to cancelled on pending record
  23.  process_shift_auto_booking — raises 404 when not found
  24.  process_shift_auto_booking — raises 409 when not pending
  25.  process_shift_auto_booking — marks failed when shift missing
  26.  process_shift_auto_booking — marks failed when member missing
  27.  process_shift_auto_booking — creates ride and marks booked (to_work)
  28.  process_shift_auto_booking — creates ride with reversed addresses (from_work)
  29.  get_shift_auto_booking_summary — raises 404 when shift not found
  30.  get_shift_auto_booking_summary — returns correct counts
  31.  list_all_platform — returns all records without filter
  32.  list_all_platform — filters by account_id
  33.  list_all_platform — filters by status

Schema validation:
  34.  GenerateAutoBookingsRequest — defaults to days_ahead=7 include_return_rides=True
  35.  GenerateAutoBookingsRequest — days_ahead ≥ 1 and ≤ 30
  36.  GenerateAutoBookingsResponse — construction
  37.  AutoBookingResponse — from_attributes construction
  38.  AutoBookingListResponse — construction
  39.  ShiftAutoBookingSummaryResponse — construction

API layer (service functions patched):
  40.  GET my — 200 member can list own bookings
  41.  GET my — 404 when no corporate account
  42.  POST generate — 200 admin can generate
  43.  POST generate — 403 non-admin cannot generate
  44.  POST generate — 404 when no corporate account
  45.  GET {booking_id} — 200 member can get record
  46.  GET {booking_id} — 404 when record not found
  47.  POST {booking_id}/cancel — 200 member can cancel
  48.  POST {booking_id}/cancel — 409 when not pending
  49.  POST {booking_id}/process — 200 admin can process
  50.  POST {booking_id}/process — 403 non-admin cannot process
  51.  POST {booking_id}/process — 409 when not pending
  52.  GET account list — 200 admin can list with no filters
  53.  GET account list — 200 filters by shift_id
  54.  GET account list — 200 filters by status
  55.  GET account list — 403 non-admin cannot list
  56.  GET shift auto-bookings — 200 admin can list shift-scoped
  57.  GET shift auto-bookings — 403 non-admin cannot list
  58.  GET shift summary — 200 admin can get summary
  59.  GET shift summary — 403 non-admin cannot get summary
  60.  GET shift summary — 404 when shift not found
  61.  GET platform all — 200 platform-admin can list
  62.  GET platform account — 200 platform-admin can list for account
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import app
from app.models.corporate_shift_auto_booking import (
    CorporateShiftAutoBooking,
    ShiftAutoBookingDirection,
    ShiftAutoBookingStatus,
)
from app.schemas.corporate_shift_auto_booking import (
    AutoBookingListResponse,
    AutoBookingResponse,
    GenerateAutoBookingsRequest,
    GenerateAutoBookingsResponse,
    ShiftAutoBookingSummaryResponse,
)
from app.services.corporate_shift_auto_booking import (
    _build_address,
    _upcoming_dates_for_shift,
    cancel_shift_auto_booking,
    generate_shift_auto_bookings,
    get_shift_auto_booking,
    get_shift_auto_booking_summary,
    list_all_platform,
    list_member_auto_bookings,
    list_shift_auto_bookings,
    process_shift_auto_booking,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ACCOUNT_ID = 10
MEMBER_ID = 3
ADMIN_ID = 2
USER_ID = 1
SHIFT_ID = 55
ASSIGNMENT_ID = 88
BOOKING_ID = uuid.uuid4()

_SERVICE = "app.services.corporate_shift_auto_booking"
_ROUTER = "app.api.v1.corporate_shift_auto_booking"

_NOW = datetime(2026, 4, 16, 9, 0, 0, tzinfo=timezone.utc)
_TODAY = date(2026, 4, 16)  # Wednesday, weekday 2


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_booking(
    booking_id: uuid.UUID = BOOKING_ID,
    shift_id: int = SHIFT_ID,
    assignment_id: int = ASSIGNMENT_ID,
    member_id: int = MEMBER_ID,
    account_id: int = ACCOUNT_ID,
    shift_date: date = _TODAY,
    direction: ShiftAutoBookingDirection = ShiftAutoBookingDirection.to_work,
    scheduled_for: datetime = _NOW,
    booking_status: ShiftAutoBookingStatus = ShiftAutoBookingStatus.pending,
    ride_id: int | None = None,
    failure_reason: str | None = None,
    booked_at: datetime | None = None,
    cancelled_at: datetime | None = None,
) -> CorporateShiftAutoBooking:
    b = CorporateShiftAutoBooking()
    b.id = booking_id
    b.shift_id = shift_id
    b.assignment_id = assignment_id
    b.member_id = member_id
    b.account_id = account_id
    b.shift_date = shift_date
    b.ride_direction = direction
    b.scheduled_for = scheduled_for
    b.status = booking_status
    b.ride_id = ride_id
    b.failure_reason = failure_reason
    b.booked_at = booked_at
    b.cancelled_at = cancelled_at
    b.created_at = _NOW
    return b


def _booking_response(booking: CorporateShiftAutoBooking) -> AutoBookingResponse:
    return AutoBookingResponse(
        id=booking.id,
        shift_id=booking.shift_id,
        assignment_id=booking.assignment_id,
        member_id=booking.member_id,
        account_id=booking.account_id,
        shift_date=booking.shift_date,
        ride_direction=booking.ride_direction,
        scheduled_for=booking.scheduled_for,
        status=booking.status,
        ride_id=booking.ride_id,
        failure_reason=booking.failure_reason,
        booked_at=booking.booked_at,
        cancelled_at=booking.cancelled_at,
        created_at=booking.created_at,
    )


def _list_response(items: list) -> AutoBookingListResponse:
    return AutoBookingListResponse(total=len(items), items=items)


# ---------------------------------------------------------------------------
# Helper utility tests  (1–5)
# ---------------------------------------------------------------------------


class TestUpcomingDatesForShift:
    """Tests for _upcoming_dates_for_shift."""

    def test_empty_days_returns_nothing(self):
        """1. Empty days_of_week → no dates returned."""
        result = _upcoming_dates_for_shift([], _TODAY, 7)
        assert result == []

    def test_all_days_returns_every_date(self):
        """2. All weekdays → every date in range returned."""
        result = _upcoming_dates_for_shift([0, 1, 2, 3, 4, 5, 6], _TODAY, 5)
        assert len(result) == 5
        assert result[0] == _TODAY

    def test_specific_days_filters_correctly(self):
        """3. days_of_week=[0] → only Mondays returned."""
        # _TODAY is 2026-04-16 (Wednesday=2), next Monday is 2026-04-20
        result = _upcoming_dates_for_shift([0], _TODAY, 7)
        assert all(d.weekday() == 0 for d in result)
        assert len(result) == 1
        assert result[0] == date(2026, 4, 20)


class TestBuildAddress:
    """Tests for _build_address."""

    def test_assembles_non_none_parts(self):
        """4. Non-None parts are joined with ', '."""
        result = _build_address("123 Main St", None, "Springfield", "IL", "62701", None)
        assert result == "123 Main St, Springfield, IL, 62701"

    def test_all_none_returns_empty(self):
        """5. All None → empty string."""
        result = _build_address(None, None, None, None, None, None)
        assert result == ""


# ---------------------------------------------------------------------------
# Service layer tests  (6–33)
# ---------------------------------------------------------------------------


class TestGenerateShiftAutoBookings:
    """Tests for generate_shift_auto_bookings."""

    @pytest.mark.asyncio
    async def test_creates_to_work_bookings(self):
        """6. Creates to_work bookings for upcoming shift dates."""
        from app.models.corporate_shift import CorporateShift, CorporateShiftAssignment

        shift = CorporateShift()
        shift.id = SHIFT_ID
        shift.account_id = ACCOUNT_ID
        shift.days_of_week = [2]  # Wednesday = _TODAY
        shift.shift_start_time = time(6, 0)
        shift.shift_end_time = time(14, 0)

        assignment = CorporateShiftAssignment()
        assignment.id = ASSIGNMENT_ID
        assignment.shift_id = SHIFT_ID
        assignment.member_id = MEMBER_ID
        assignment.auto_request_rides = True
        assignment.is_active = True

        db = AsyncMock()
        execute_result = MagicMock()
        execute_result.all.return_value = [(shift, assignment)]
        db.execute = AsyncMock(return_value=execute_result)
        db.flush = AsyncMock()
        db.commit = AsyncMock()

        data = GenerateAutoBookingsRequest(days_ahead=7, include_return_rides=False)
        result = await generate_shift_auto_bookings(db, ACCOUNT_ID, data)

        assert result.total_assignments_scanned == 1
        assert result.created >= 1

    @pytest.mark.asyncio
    async def test_include_return_rides_creates_from_work(self):
        """7. include_return_rides=True creates from_work bookings too."""
        from app.models.corporate_shift import CorporateShift, CorporateShiftAssignment

        shift = CorporateShift()
        shift.id = SHIFT_ID
        shift.account_id = ACCOUNT_ID
        shift.days_of_week = [2]  # Wednesday
        shift.shift_start_time = time(6, 0)
        shift.shift_end_time = time(14, 0)

        assignment = CorporateShiftAssignment()
        assignment.id = ASSIGNMENT_ID
        assignment.shift_id = SHIFT_ID
        assignment.member_id = MEMBER_ID
        assignment.auto_request_rides = True
        assignment.is_active = True

        db = AsyncMock()
        execute_result = MagicMock()
        execute_result.all.return_value = [(shift, assignment)]
        db.execute = AsyncMock(return_value=execute_result)
        db.flush = AsyncMock()
        db.commit = AsyncMock()

        data = GenerateAutoBookingsRequest(days_ahead=7, include_return_rides=True)
        result = await generate_shift_auto_bookings(db, ACCOUNT_ID, data)

        # At minimum 2 created (to_work + from_work for Wednesday)
        assert result.created >= 2
        assert result.total_assignments_scanned == 1

    @pytest.mark.asyncio
    async def test_skips_duplicate_on_integrity_error(self):
        """8. IntegrityError on flush → record counted as skipped."""
        from sqlalchemy.exc import IntegrityError
        from app.models.corporate_shift import CorporateShift, CorporateShiftAssignment

        shift = CorporateShift()
        shift.id = SHIFT_ID
        shift.account_id = ACCOUNT_ID
        shift.days_of_week = [2]
        shift.shift_start_time = time(6, 0)
        shift.shift_end_time = time(14, 0)

        assignment = CorporateShiftAssignment()
        assignment.id = ASSIGNMENT_ID
        assignment.shift_id = SHIFT_ID
        assignment.member_id = MEMBER_ID
        assignment.auto_request_rides = True
        assignment.is_active = True

        db = AsyncMock()
        execute_result = MagicMock()
        execute_result.all.return_value = [(shift, assignment)]
        db.execute = AsyncMock(return_value=execute_result)
        db.flush = AsyncMock(side_effect=IntegrityError("dup", {}, None))
        db.rollback = AsyncMock()
        db.commit = AsyncMock()

        data = GenerateAutoBookingsRequest(days_ahead=7, include_return_rides=False)
        result = await generate_shift_auto_bookings(db, ACCOUNT_ID, data)

        assert result.skipped >= 1
        assert result.created == 0

    @pytest.mark.asyncio
    async def test_no_assignments_returns_zeros(self):
        """9. No auto_request_rides assignments → created=0 skipped=0."""
        db = AsyncMock()
        execute_result = MagicMock()
        execute_result.all.return_value = []
        db.execute = AsyncMock(return_value=execute_result)
        db.commit = AsyncMock()

        data = GenerateAutoBookingsRequest(days_ahead=7)
        result = await generate_shift_auto_bookings(db, ACCOUNT_ID, data)

        assert result.created == 0
        assert result.skipped == 0
        assert result.total_assignments_scanned == 0

    @pytest.mark.asyncio
    async def test_no_upcoming_dates_returns_zeros(self):
        """10. Shift with days_of_week=[] → no dates to book."""
        from app.models.corporate_shift import CorporateShift, CorporateShiftAssignment

        shift = CorporateShift()
        shift.id = SHIFT_ID
        shift.account_id = ACCOUNT_ID
        shift.days_of_week = []  # never runs
        shift.shift_start_time = time(6, 0)
        shift.shift_end_time = time(14, 0)

        assignment = CorporateShiftAssignment()
        assignment.id = ASSIGNMENT_ID
        assignment.shift_id = SHIFT_ID
        assignment.member_id = MEMBER_ID
        assignment.auto_request_rides = True
        assignment.is_active = True

        db = AsyncMock()
        execute_result = MagicMock()
        execute_result.all.return_value = [(shift, assignment)]
        db.execute = AsyncMock(return_value=execute_result)
        db.commit = AsyncMock()

        data = GenerateAutoBookingsRequest(days_ahead=7, include_return_rides=False)
        result = await generate_shift_auto_bookings(db, ACCOUNT_ID, data)

        assert result.created == 0
        assert result.total_assignments_scanned == 1


class TestGetShiftAutoBooking:
    """Tests for get_shift_auto_booking."""

    @pytest.mark.asyncio
    async def test_returns_record_when_found(self):
        """11. Returns AutoBookingResponse when record exists."""
        booking = _make_booking()

        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = booking
        db.execute = AsyncMock(return_value=result)

        response = await get_shift_auto_booking(db, BOOKING_ID, ACCOUNT_ID)
        assert response.id == BOOKING_ID
        assert response.status == ShiftAutoBookingStatus.pending

    @pytest.mark.asyncio
    async def test_raises_404_when_not_found(self):
        """12. Raises HTTPException 404 when record not found."""
        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=result)

        with pytest.raises(HTTPException) as exc_info:
            await get_shift_auto_booking(db, BOOKING_ID, ACCOUNT_ID)
        assert exc_info.value.status_code == 404


class TestListShiftAutoBookings:
    """Tests for list_shift_auto_bookings."""

    @pytest.mark.asyncio
    async def test_returns_all_records(self):
        """13. Returns all auto-bookings for account."""
        bookings = [_make_booking(), _make_booking(booking_id=uuid.uuid4())]

        db = AsyncMock()

        count_result = MagicMock()
        count_result.scalar_one.return_value = 2

        rows_result = MagicMock()
        rows_result.scalars.return_value.all.return_value = bookings

        db.execute = AsyncMock(side_effect=[count_result, rows_result])

        response = await list_shift_auto_bookings(db, ACCOUNT_ID)
        assert response.total == 2
        assert len(response.items) == 2

    @pytest.mark.asyncio
    async def test_filters_by_shift_id(self):
        """14. Filters records by shift_id."""
        db = AsyncMock()
        count_result = MagicMock()
        count_result.scalar_one.return_value = 1
        rows_result = MagicMock()
        rows_result.scalars.return_value.all.return_value = [_make_booking()]
        db.execute = AsyncMock(side_effect=[count_result, rows_result])

        response = await list_shift_auto_bookings(db, ACCOUNT_ID, shift_id=SHIFT_ID)
        assert response.total == 1

    @pytest.mark.asyncio
    async def test_filters_by_member_id(self):
        """15. Filters records by member_id."""
        db = AsyncMock()
        count_result = MagicMock()
        count_result.scalar_one.return_value = 0
        rows_result = MagicMock()
        rows_result.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(side_effect=[count_result, rows_result])

        response = await list_shift_auto_bookings(db, ACCOUNT_ID, member_id=999)
        assert response.total == 0

    @pytest.mark.asyncio
    async def test_filters_by_status(self):
        """16. Filters records by status."""
        db = AsyncMock()
        count_result = MagicMock()
        count_result.scalar_one.return_value = 1
        rows_result = MagicMock()
        rows_result.scalars.return_value.all.return_value = [_make_booking()]
        db.execute = AsyncMock(side_effect=[count_result, rows_result])

        response = await list_shift_auto_bookings(
            db, ACCOUNT_ID, booking_status=ShiftAutoBookingStatus.pending
        )
        assert response.total == 1

    @pytest.mark.asyncio
    async def test_filters_by_direction(self):
        """17. Filters records by ride direction."""
        db = AsyncMock()
        count_result = MagicMock()
        count_result.scalar_one.return_value = 1
        rows_result = MagicMock()
        rows_result.scalars.return_value.all.return_value = [_make_booking()]
        db.execute = AsyncMock(side_effect=[count_result, rows_result])

        response = await list_shift_auto_bookings(
            db, ACCOUNT_ID, direction=ShiftAutoBookingDirection.to_work
        )
        assert response.total == 1


class TestListMemberAutoBookings:
    """Tests for list_member_auto_bookings."""

    @pytest.mark.asyncio
    async def test_delegates_to_list(self):
        """18. Delegates to list_shift_auto_bookings with member_id filter."""
        db = AsyncMock()
        count_result = MagicMock()
        count_result.scalar_one.return_value = 1
        rows_result = MagicMock()
        rows_result.scalars.return_value.all.return_value = [_make_booking()]
        db.execute = AsyncMock(side_effect=[count_result, rows_result])

        response = await list_member_auto_bookings(db, ACCOUNT_ID, MEMBER_ID)
        assert response.total == 1


class TestCancelShiftAutoBooking:
    """Tests for cancel_shift_auto_booking."""

    @pytest.mark.asyncio
    async def test_raises_404_when_not_found(self):
        """19. Raises 404 when booking does not exist."""
        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=result)

        with pytest.raises(HTTPException) as exc_info:
            await cancel_shift_auto_booking(db, BOOKING_ID, ACCOUNT_ID)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_raises_409_when_booked(self):
        """20. Raises 409 when booking is already booked."""
        booking = _make_booking(booking_status=ShiftAutoBookingStatus.booked)

        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = booking
        db.execute = AsyncMock(return_value=result)

        with pytest.raises(HTTPException) as exc_info:
            await cancel_shift_auto_booking(db, BOOKING_ID, ACCOUNT_ID)
        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_raises_409_when_already_cancelled(self):
        """21. Raises 409 when booking is already cancelled."""
        booking = _make_booking(booking_status=ShiftAutoBookingStatus.cancelled)

        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = booking
        db.execute = AsyncMock(return_value=result)

        with pytest.raises(HTTPException) as exc_info:
            await cancel_shift_auto_booking(db, BOOKING_ID, ACCOUNT_ID)
        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_sets_status_cancelled_on_pending(self):
        """22. Sets status to cancelled and cancelled_at when pending."""
        booking = _make_booking(booking_status=ShiftAutoBookingStatus.pending)

        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = booking
        db.execute = AsyncMock(return_value=result)
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        response = await cancel_shift_auto_booking(db, BOOKING_ID, ACCOUNT_ID)

        assert booking.status == ShiftAutoBookingStatus.cancelled
        assert booking.cancelled_at is not None
        db.commit.assert_called_once()


class TestProcessShiftAutoBooking:
    """Tests for process_shift_auto_booking."""

    @pytest.mark.asyncio
    async def test_raises_404_when_not_found(self):
        """23. Raises 404 when booking does not exist."""
        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=result)

        with pytest.raises(HTTPException) as exc_info:
            await process_shift_auto_booking(db, BOOKING_ID, ACCOUNT_ID)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_raises_409_when_not_pending(self):
        """24. Raises 409 when booking is not pending."""
        booking = _make_booking(booking_status=ShiftAutoBookingStatus.booked)

        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = booking
        db.execute = AsyncMock(return_value=result)

        with pytest.raises(HTTPException) as exc_info:
            await process_shift_auto_booking(db, BOOKING_ID, ACCOUNT_ID)
        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_marks_failed_when_shift_missing(self):
        """25. Marks booking failed when shift no longer exists."""
        booking = _make_booking()

        db = AsyncMock()
        # First execute: load booking
        booking_result = MagicMock()
        booking_result.scalar_one_or_none.return_value = booking
        # Second execute: load shift
        shift_result = MagicMock()
        shift_result.scalar_one_or_none.return_value = None
        # Third execute: load assignment
        assignment_result = MagicMock()
        assignment_result.scalar_one_or_none.return_value = None

        db.execute = AsyncMock(
            side_effect=[booking_result, shift_result, assignment_result]
        )
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        response = await process_shift_auto_booking(db, BOOKING_ID, ACCOUNT_ID)
        assert booking.status == ShiftAutoBookingStatus.failed
        assert booking.failure_reason is not None

    @pytest.mark.asyncio
    async def test_marks_failed_when_member_missing(self):
        """26. Marks booking failed when member record is missing."""
        from app.models.corporate_shift import CorporateShift, CorporateShiftAssignment

        booking = _make_booking()

        shift = CorporateShift()
        shift.id = SHIFT_ID
        shift.work_location_name = "Main Plant"
        shift.work_address_line1 = "100 Work Ave"
        shift.work_city = "Springfield"
        shift.work_state = "IL"
        shift.work_country = None
        shift.work_postal_code = None
        shift.work_latitude = None
        shift.work_longitude = None
        shift.shift_start_time = time(6, 0)
        shift.shift_end_time = time(14, 0)

        assignment = CorporateShiftAssignment()
        assignment.id = ASSIGNMENT_ID
        assignment.member_id = MEMBER_ID
        assignment.pickup_address_line1 = "200 Home Rd"
        assignment.pickup_address_line2 = None
        assignment.pickup_city = "Springfield"
        assignment.pickup_state = "IL"
        assignment.pickup_country = None
        assignment.pickup_postal_code = None
        assignment.pickup_latitude = None
        assignment.pickup_longitude = None

        db = AsyncMock()
        booking_result = MagicMock()
        booking_result.scalar_one_or_none.return_value = booking
        shift_result = MagicMock()
        shift_result.scalar_one_or_none.return_value = shift
        assignment_result = MagicMock()
        assignment_result.scalar_one_or_none.return_value = assignment
        member_result = MagicMock()
        member_result.scalar_one_or_none.return_value = None  # member missing

        db.execute = AsyncMock(
            side_effect=[booking_result, shift_result, assignment_result, member_result]
        )
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        response = await process_shift_auto_booking(db, BOOKING_ID, ACCOUNT_ID)
        assert booking.status == ShiftAutoBookingStatus.failed

    @pytest.mark.asyncio
    async def test_creates_ride_and_marks_booked_to_work(self):
        """27. Creates Ride and marks booking booked for to_work direction."""
        from app.models.corporate import BusinessAccountMember
        from app.models.corporate_shift import CorporateShift, CorporateShiftAssignment

        booking = _make_booking(direction=ShiftAutoBookingDirection.to_work)

        shift = CorporateShift()
        shift.id = SHIFT_ID
        shift.work_location_name = "Main Plant"
        shift.work_address_line1 = "100 Work Ave"
        shift.work_address_line2 = None
        shift.work_city = "Springfield"
        shift.work_state = "IL"
        shift.work_country = None
        shift.work_postal_code = None
        shift.work_latitude = None
        shift.work_longitude = None
        shift.shift_start_time = time(6, 0)
        shift.shift_end_time = time(14, 0)

        assignment = CorporateShiftAssignment()
        assignment.id = ASSIGNMENT_ID
        assignment.member_id = MEMBER_ID
        assignment.pickup_address_line1 = "200 Home Rd"
        assignment.pickup_address_line2 = None
        assignment.pickup_city = "Springfield"
        assignment.pickup_state = "IL"
        assignment.pickup_country = None
        assignment.pickup_postal_code = None
        assignment.pickup_latitude = None
        assignment.pickup_longitude = None

        member = BusinessAccountMember()
        member.id = MEMBER_ID
        member.user_id = USER_ID

        ride = MagicMock()
        ride.id = 999

        db = AsyncMock()
        booking_result = MagicMock()
        booking_result.scalar_one_or_none.return_value = booking
        shift_result = MagicMock()
        shift_result.scalar_one_or_none.return_value = shift
        assignment_result = MagicMock()
        assignment_result.scalar_one_or_none.return_value = assignment
        member_result = MagicMock()
        member_result.scalar_one_or_none.return_value = member

        db.execute = AsyncMock(
            side_effect=[booking_result, shift_result, assignment_result, member_result]
        )
        db.add = MagicMock()
        db.flush = AsyncMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        # Patch Ride so we can track it
        with patch(f"{_SERVICE}.Ride") as MockRide:
            mock_ride_instance = MagicMock()
            mock_ride_instance.id = 999
            MockRide.return_value = mock_ride_instance

            response = await process_shift_auto_booking(db, BOOKING_ID, ACCOUNT_ID)

        assert booking.status == ShiftAutoBookingStatus.booked
        assert booking.booked_at is not None
        db.commit.assert_called()

    @pytest.mark.asyncio
    async def test_creates_ride_with_reversed_addresses_from_work(self):
        """28. from_work direction reverses pickup/dropoff."""
        from app.models.corporate import BusinessAccountMember
        from app.models.corporate_shift import CorporateShift, CorporateShiftAssignment

        booking = _make_booking(direction=ShiftAutoBookingDirection.from_work)

        shift = CorporateShift()
        shift.id = SHIFT_ID
        shift.work_location_name = "Main Plant"
        shift.work_address_line1 = "100 Work Ave"
        shift.work_address_line2 = None
        shift.work_city = "Springfield"
        shift.work_state = "IL"
        shift.work_country = None
        shift.work_postal_code = None
        shift.work_latitude = None
        shift.work_longitude = None
        shift.shift_start_time = time(6, 0)
        shift.shift_end_time = time(14, 0)

        assignment = CorporateShiftAssignment()
        assignment.id = ASSIGNMENT_ID
        assignment.member_id = MEMBER_ID
        assignment.pickup_address_line1 = "200 Home Rd"
        assignment.pickup_address_line2 = None
        assignment.pickup_city = "Springfield"
        assignment.pickup_state = "IL"
        assignment.pickup_country = None
        assignment.pickup_postal_code = None
        assignment.pickup_latitude = None
        assignment.pickup_longitude = None

        member = BusinessAccountMember()
        member.id = MEMBER_ID
        member.user_id = USER_ID

        db = AsyncMock()
        booking_result = MagicMock()
        booking_result.scalar_one_or_none.return_value = booking
        shift_result = MagicMock()
        shift_result.scalar_one_or_none.return_value = shift
        assignment_result = MagicMock()
        assignment_result.scalar_one_or_none.return_value = assignment
        member_result = MagicMock()
        member_result.scalar_one_or_none.return_value = member

        db.execute = AsyncMock(
            side_effect=[booking_result, shift_result, assignment_result, member_result]
        )
        db.add = MagicMock()
        db.flush = AsyncMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        created_rides = []

        with patch(f"{_SERVICE}.Ride") as MockRide:
            def capture_ride(**kwargs):
                m = MagicMock()
                m.id = 999
                created_rides.append(kwargs)
                return m

            MockRide.side_effect = capture_ride

            await process_shift_auto_booking(db, BOOKING_ID, ACCOUNT_ID)

        # For from_work, pickup is the work location
        assert len(created_rides) == 1
        assert "100 Work Ave" in created_rides[0].get("pickup_address", "")
        assert "200 Home Rd" in created_rides[0].get("dropoff_address", "")


class TestGetShiftAutoBookingSummary:
    """Tests for get_shift_auto_booking_summary."""

    @pytest.mark.asyncio
    async def test_raises_404_when_shift_not_found(self):
        """29. Raises 404 when shift not found in account."""
        db = AsyncMock()
        shift_check = MagicMock()
        shift_check.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=shift_check)

        with pytest.raises(HTTPException) as exc_info:
            await get_shift_auto_booking_summary(db, SHIFT_ID, ACCOUNT_ID)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_returns_correct_counts(self):
        """30. Returns correct aggregate counts by status and direction."""
        from app.models.corporate_shift import CorporateShift

        shift = CorporateShift()
        shift.id = SHIFT_ID

        pending = _make_booking(booking_status=ShiftAutoBookingStatus.pending)
        booked = _make_booking(
            booking_id=uuid.uuid4(),
            booking_status=ShiftAutoBookingStatus.booked,
            direction=ShiftAutoBookingDirection.from_work,
        )
        cancelled = _make_booking(
            booking_id=uuid.uuid4(),
            booking_status=ShiftAutoBookingStatus.cancelled,
        )

        db = AsyncMock()
        shift_check = MagicMock()
        shift_check.scalar_one_or_none.return_value = shift
        rows_result = MagicMock()
        rows_result.scalars.return_value.all.return_value = [pending, booked, cancelled]
        db.execute = AsyncMock(side_effect=[shift_check, rows_result])

        summary = await get_shift_auto_booking_summary(db, SHIFT_ID, ACCOUNT_ID)

        assert summary.shift_id == SHIFT_ID
        assert summary.total == 3
        assert summary.pending == 1
        assert summary.booked == 1
        assert summary.cancelled == 1
        assert summary.to_work_count == 2
        assert summary.from_work_count == 1


class TestListAllPlatform:
    """Tests for list_all_platform."""

    @pytest.mark.asyncio
    async def test_returns_all_without_filter(self):
        """31. Returns all records without account filter."""
        bookings = [_make_booking(), _make_booking(booking_id=uuid.uuid4())]
        db = AsyncMock()
        count_result = MagicMock()
        count_result.scalar_one.return_value = 2
        rows_result = MagicMock()
        rows_result.scalars.return_value.all.return_value = bookings
        db.execute = AsyncMock(side_effect=[count_result, rows_result])

        response = await list_all_platform(db)
        assert response.total == 2

    @pytest.mark.asyncio
    async def test_filters_by_account_id(self):
        """32. Filters records by account_id."""
        db = AsyncMock()
        count_result = MagicMock()
        count_result.scalar_one.return_value = 1
        rows_result = MagicMock()
        rows_result.scalars.return_value.all.return_value = [_make_booking()]
        db.execute = AsyncMock(side_effect=[count_result, rows_result])

        response = await list_all_platform(db, account_id=ACCOUNT_ID)
        assert response.total == 1

    @pytest.mark.asyncio
    async def test_filters_by_status(self):
        """33. Filters records by status."""
        db = AsyncMock()
        count_result = MagicMock()
        count_result.scalar_one.return_value = 0
        rows_result = MagicMock()
        rows_result.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(side_effect=[count_result, rows_result])

        response = await list_all_platform(
            db, booking_status=ShiftAutoBookingStatus.failed
        )
        assert response.total == 0


# ---------------------------------------------------------------------------
# Schema tests  (34–39)
# ---------------------------------------------------------------------------


class TestSchemas:
    """Tests for Pydantic v2 schema validation."""

    def test_generate_request_defaults(self):
        """34. GenerateAutoBookingsRequest defaults to days_ahead=7 and include_return_rides=True."""
        req = GenerateAutoBookingsRequest()
        assert req.days_ahead == 7
        assert req.include_return_rides is True

    def test_generate_request_days_ahead_bounds(self):
        """35. days_ahead must be between 1 and 30."""
        with pytest.raises(ValidationError):
            GenerateAutoBookingsRequest(days_ahead=0)
        with pytest.raises(ValidationError):
            GenerateAutoBookingsRequest(days_ahead=31)
        # boundaries valid
        GenerateAutoBookingsRequest(days_ahead=1)
        GenerateAutoBookingsRequest(days_ahead=30)

    def test_generate_response_construction(self):
        """36. GenerateAutoBookingsResponse can be constructed."""
        resp = GenerateAutoBookingsResponse(created=5, skipped=2, total_assignments_scanned=3)
        assert resp.created == 5
        assert resp.skipped == 2

    def test_auto_booking_response_from_attributes(self):
        """37. AutoBookingResponse.model_validate works from ORM-like object."""
        booking = _make_booking()
        resp = AutoBookingResponse.model_validate(booking)
        assert resp.id == BOOKING_ID
        assert resp.status == ShiftAutoBookingStatus.pending

    def test_auto_booking_list_response(self):
        """38. AutoBookingListResponse wraps items correctly."""
        booking = _make_booking()
        resp_item = AutoBookingResponse.model_validate(booking)
        list_resp = AutoBookingListResponse(total=1, items=[resp_item])
        assert list_resp.total == 1
        assert len(list_resp.items) == 1

    def test_summary_response_construction(self):
        """39. ShiftAutoBookingSummaryResponse can be constructed."""
        summary = ShiftAutoBookingSummaryResponse(
            shift_id=SHIFT_ID,
            total=10,
            pending=3,
            booked=5,
            failed=1,
            skipped=0,
            cancelled=1,
            to_work_count=6,
            from_work_count=4,
        )
        assert summary.total == 10
        assert summary.to_work_count == 6


# ---------------------------------------------------------------------------
# API layer tests  (40–62)
# ---------------------------------------------------------------------------

client = TestClient(app)


def _mock_user(user_id: int = USER_ID, is_admin: bool = False):
    user = MagicMock()
    user.id = user_id
    user.is_admin = is_admin
    return user


def _booking_resp_dict(bid: uuid.UUID = BOOKING_ID) -> dict:
    return {
        "id": str(bid),
        "shift_id": SHIFT_ID,
        "assignment_id": ASSIGNMENT_ID,
        "member_id": MEMBER_ID,
        "account_id": ACCOUNT_ID,
        "shift_date": str(_TODAY),
        "ride_direction": "to_work",
        "scheduled_for": _NOW.isoformat(),
        "status": "pending",
        "ride_id": None,
        "failure_reason": None,
        "booked_at": None,
        "cancelled_at": None,
        "created_at": _NOW.isoformat(),
    }


def _list_resp_dict(items=None) -> dict:
    if items is None:
        items = [_booking_resp_dict()]
    return {"total": len(items), "items": items}


def _dep_overrides(account_id: int = ACCOUNT_ID, is_admin: bool = False):
    """Return dependency override dict for injecting account and optionally admin."""
    from app.api.deps import get_current_user, get_db, require_admin

    async def _user():
        return _mock_user(is_admin=is_admin)

    async def _db():
        return AsyncMock()

    async def _admin():
        return _mock_user(is_admin=True)

    return {
        get_current_user: _user,
        get_db: _db,
        require_admin: _admin,
    }


class TestAPIListMyAutoBookings:
    """API tests: GET /corporate/accounts/me/shift-auto-bookings/my"""

    def test_200_member_can_list(self):
        """40. 200 member can list own auto-bookings."""
        with (
            patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)),
            patch(
                f"{_ROUTER}.list_member_auto_bookings",
                new=AsyncMock(return_value=AutoBookingListResponse(**_list_resp_dict())),
            ),
        ):
            app.dependency_overrides.update(_dep_overrides())
            resp = client.get("/api/v1/corporate/accounts/me/shift-auto-bookings/my")
            app.dependency_overrides.clear()
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    def test_404_no_corporate_account(self):
        """41. 404 when user has no corporate account."""
        with patch(
            f"{_ROUTER}._resolve_account_id",
            new=AsyncMock(side_effect=HTTPException(status_code=404, detail="not found")),
        ):
            app.dependency_overrides.update(_dep_overrides())
            resp = client.get("/api/v1/corporate/accounts/me/shift-auto-bookings/my")
            app.dependency_overrides.clear()
        assert resp.status_code == 404


class TestAPIGenerate:
    """API tests: POST /corporate/accounts/me/shift-auto-bookings/generate"""

    def test_200_admin_can_generate(self):
        """42. 200 admin can trigger generation."""
        with (
            patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)),
            patch(f"{_ROUTER}._require_account_admin", new=AsyncMock()),
            patch(
                f"{_ROUTER}.generate_shift_auto_bookings",
                new=AsyncMock(
                    return_value=GenerateAutoBookingsResponse(
                        created=3, skipped=0, total_assignments_scanned=2
                    )
                ),
            ),
        ):
            app.dependency_overrides.update(_dep_overrides(is_admin=True))
            resp = client.post(
                "/api/v1/corporate/accounts/me/shift-auto-bookings/generate",
                json={"days_ahead": 7, "include_return_rides": True},
            )
            app.dependency_overrides.clear()
        assert resp.status_code == 200
        assert resp.json()["created"] == 3

    def test_403_non_admin_cannot_generate(self):
        """43. 403 non-admin cannot generate."""
        with (
            patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)),
            patch(
                f"{_ROUTER}._require_account_admin",
                new=AsyncMock(
                    side_effect=HTTPException(status_code=403, detail="forbidden")
                ),
            ),
        ):
            app.dependency_overrides.update(_dep_overrides())
            resp = client.post(
                "/api/v1/corporate/accounts/me/shift-auto-bookings/generate",
                json={"days_ahead": 7, "include_return_rides": True},
            )
            app.dependency_overrides.clear()
        assert resp.status_code == 403

    def test_404_no_corporate_account(self):
        """44. 404 when user has no corporate account."""
        with patch(
            f"{_ROUTER}._resolve_account_id",
            new=AsyncMock(side_effect=HTTPException(status_code=404, detail="not found")),
        ):
            app.dependency_overrides.update(_dep_overrides())
            resp = client.post(
                "/api/v1/corporate/accounts/me/shift-auto-bookings/generate",
                json={"days_ahead": 7, "include_return_rides": True},
            )
            app.dependency_overrides.clear()
        assert resp.status_code == 404


class TestAPIGetAutoBooking:
    """API tests: GET /corporate/accounts/me/shift-auto-bookings/{booking_id}"""

    def test_200_member_can_get(self):
        """45. 200 member can get single auto-booking."""
        booking = _make_booking()
        with (
            patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)),
            patch(
                f"{_ROUTER}.get_shift_auto_booking",
                new=AsyncMock(return_value=AutoBookingResponse.model_validate(booking)),
            ),
        ):
            app.dependency_overrides.update(_dep_overrides())
            resp = client.get(
                f"/api/v1/corporate/accounts/me/shift-auto-bookings/{BOOKING_ID}"
            )
            app.dependency_overrides.clear()
        assert resp.status_code == 200

    def test_404_booking_not_found(self):
        """46. 404 when booking does not exist."""
        with (
            patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)),
            patch(
                f"{_ROUTER}.get_shift_auto_booking",
                new=AsyncMock(
                    side_effect=HTTPException(status_code=404, detail="not found")
                ),
            ),
        ):
            app.dependency_overrides.update(_dep_overrides())
            resp = client.get(
                f"/api/v1/corporate/accounts/me/shift-auto-bookings/{BOOKING_ID}"
            )
            app.dependency_overrides.clear()
        assert resp.status_code == 404


class TestAPICancelAutoBooking:
    """API tests: POST /corporate/accounts/me/shift-auto-bookings/{booking_id}/cancel"""

    def test_200_member_can_cancel(self):
        """47. 200 member can cancel pending booking."""
        booking = _make_booking(booking_status=ShiftAutoBookingStatus.cancelled)
        with (
            patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)),
            patch(
                f"{_ROUTER}.cancel_shift_auto_booking",
                new=AsyncMock(return_value=AutoBookingResponse.model_validate(booking)),
            ),
        ):
            app.dependency_overrides.update(_dep_overrides())
            resp = client.post(
                f"/api/v1/corporate/accounts/me/shift-auto-bookings/{BOOKING_ID}/cancel"
            )
            app.dependency_overrides.clear()
        assert resp.status_code == 200
        assert resp.json()["status"] == "cancelled"

    def test_409_cannot_cancel_booked(self):
        """48. 409 when trying to cancel a non-pending booking."""
        with (
            patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)),
            patch(
                f"{_ROUTER}.cancel_shift_auto_booking",
                new=AsyncMock(
                    side_effect=HTTPException(status_code=409, detail="not pending")
                ),
            ),
        ):
            app.dependency_overrides.update(_dep_overrides())
            resp = client.post(
                f"/api/v1/corporate/accounts/me/shift-auto-bookings/{BOOKING_ID}/cancel"
            )
            app.dependency_overrides.clear()
        assert resp.status_code == 409


class TestAPIProcessAutoBooking:
    """API tests: POST /corporate/accounts/me/shift-auto-bookings/{booking_id}/process"""

    def test_200_admin_can_process(self):
        """49. 200 admin can process a pending booking."""
        booking = _make_booking(
            booking_status=ShiftAutoBookingStatus.booked,
            ride_id=999,
            booked_at=_NOW,
        )
        with (
            patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)),
            patch(f"{_ROUTER}._require_account_admin", new=AsyncMock()),
            patch(
                f"{_ROUTER}.process_shift_auto_booking",
                new=AsyncMock(return_value=AutoBookingResponse.model_validate(booking)),
            ),
        ):
            app.dependency_overrides.update(_dep_overrides(is_admin=True))
            resp = client.post(
                f"/api/v1/corporate/accounts/me/shift-auto-bookings/{BOOKING_ID}/process"
            )
            app.dependency_overrides.clear()
        assert resp.status_code == 200
        assert resp.json()["status"] == "booked"

    def test_403_non_admin_cannot_process(self):
        """50. 403 non-admin cannot process."""
        with (
            patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)),
            patch(
                f"{_ROUTER}._require_account_admin",
                new=AsyncMock(
                    side_effect=HTTPException(status_code=403, detail="forbidden")
                ),
            ),
        ):
            app.dependency_overrides.update(_dep_overrides())
            resp = client.post(
                f"/api/v1/corporate/accounts/me/shift-auto-bookings/{BOOKING_ID}/process"
            )
            app.dependency_overrides.clear()
        assert resp.status_code == 403

    def test_409_when_not_pending(self):
        """51. 409 when booking is not pending."""
        with (
            patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)),
            patch(f"{_ROUTER}._require_account_admin", new=AsyncMock()),
            patch(
                f"{_ROUTER}.process_shift_auto_booking",
                new=AsyncMock(
                    side_effect=HTTPException(status_code=409, detail="not pending")
                ),
            ),
        ):
            app.dependency_overrides.update(_dep_overrides(is_admin=True))
            resp = client.post(
                f"/api/v1/corporate/accounts/me/shift-auto-bookings/{BOOKING_ID}/process"
            )
            app.dependency_overrides.clear()
        assert resp.status_code == 409


class TestAPIListAccountAutoBookings:
    """API tests: GET /corporate/accounts/me/shift-auto-bookings"""

    def test_200_admin_can_list(self):
        """52. 200 admin can list all with no filters."""
        with (
            patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)),
            patch(f"{_ROUTER}._require_account_admin", new=AsyncMock()),
            patch(
                f"{_ROUTER}.list_shift_auto_bookings",
                new=AsyncMock(return_value=AutoBookingListResponse(**_list_resp_dict())),
            ),
        ):
            app.dependency_overrides.update(_dep_overrides(is_admin=True))
            resp = client.get("/api/v1/corporate/accounts/me/shift-auto-bookings")
            app.dependency_overrides.clear()
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    def test_200_filters_by_shift_id(self):
        """53. 200 admin filters by shift_id."""
        with (
            patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)),
            patch(f"{_ROUTER}._require_account_admin", new=AsyncMock()),
            patch(
                f"{_ROUTER}.list_shift_auto_bookings",
                new=AsyncMock(
                    return_value=AutoBookingListResponse(**_list_resp_dict())
                ),
            ),
        ):
            app.dependency_overrides.update(_dep_overrides(is_admin=True))
            resp = client.get(
                f"/api/v1/corporate/accounts/me/shift-auto-bookings?shift_id={SHIFT_ID}"
            )
            app.dependency_overrides.clear()
        assert resp.status_code == 200

    def test_200_filters_by_status(self):
        """54. 200 admin filters by status."""
        with (
            patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)),
            patch(f"{_ROUTER}._require_account_admin", new=AsyncMock()),
            patch(
                f"{_ROUTER}.list_shift_auto_bookings",
                new=AsyncMock(
                    return_value=AutoBookingListResponse(total=0, items=[])
                ),
            ),
        ):
            app.dependency_overrides.update(_dep_overrides(is_admin=True))
            resp = client.get(
                "/api/v1/corporate/accounts/me/shift-auto-bookings?status=booked"
            )
            app.dependency_overrides.clear()
        assert resp.status_code == 200

    def test_403_non_admin_cannot_list(self):
        """55. 403 non-admin cannot list."""
        with (
            patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)),
            patch(
                f"{_ROUTER}._require_account_admin",
                new=AsyncMock(
                    side_effect=HTTPException(status_code=403, detail="forbidden")
                ),
            ),
        ):
            app.dependency_overrides.update(_dep_overrides())
            resp = client.get("/api/v1/corporate/accounts/me/shift-auto-bookings")
            app.dependency_overrides.clear()
        assert resp.status_code == 403


class TestAPIShiftAutoBookings:
    """API tests: GET /corporate/accounts/me/shifts/{shift_id}/auto-bookings"""

    def test_200_admin_can_list_shift_scoped(self):
        """56. 200 admin can list auto-bookings for a shift."""
        with (
            patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)),
            patch(f"{_ROUTER}._require_account_admin", new=AsyncMock()),
            patch(
                f"{_ROUTER}.list_shift_auto_bookings",
                new=AsyncMock(return_value=AutoBookingListResponse(**_list_resp_dict())),
            ),
        ):
            app.dependency_overrides.update(_dep_overrides(is_admin=True))
            resp = client.get(
                f"/api/v1/corporate/accounts/me/shifts/{SHIFT_ID}/auto-bookings"
            )
            app.dependency_overrides.clear()
        assert resp.status_code == 200

    def test_403_non_admin_cannot_list(self):
        """57. 403 non-admin cannot list shift-scoped bookings."""
        with (
            patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)),
            patch(
                f"{_ROUTER}._require_account_admin",
                new=AsyncMock(
                    side_effect=HTTPException(status_code=403, detail="forbidden")
                ),
            ),
        ):
            app.dependency_overrides.update(_dep_overrides())
            resp = client.get(
                f"/api/v1/corporate/accounts/me/shifts/{SHIFT_ID}/auto-bookings"
            )
            app.dependency_overrides.clear()
        assert resp.status_code == 403


class TestAPIShiftAutoBookingSummary:
    """API tests: GET /corporate/accounts/me/shifts/{shift_id}/auto-bookings/summary"""

    def test_200_admin_can_get_summary(self):
        """58. 200 admin can get summary stats."""
        summary = ShiftAutoBookingSummaryResponse(
            shift_id=SHIFT_ID,
            total=5,
            pending=2,
            booked=3,
            failed=0,
            skipped=0,
            cancelled=0,
            to_work_count=3,
            from_work_count=2,
        )
        with (
            patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)),
            patch(f"{_ROUTER}._require_account_admin", new=AsyncMock()),
            patch(
                f"{_ROUTER}.get_shift_auto_booking_summary",
                new=AsyncMock(return_value=summary),
            ),
        ):
            app.dependency_overrides.update(_dep_overrides(is_admin=True))
            resp = client.get(
                f"/api/v1/corporate/accounts/me/shifts/{SHIFT_ID}/auto-bookings/summary"
            )
            app.dependency_overrides.clear()
        assert resp.status_code == 200
        assert resp.json()["total"] == 5

    def test_403_non_admin_cannot_get_summary(self):
        """59. 403 non-admin cannot get summary."""
        with (
            patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)),
            patch(
                f"{_ROUTER}._require_account_admin",
                new=AsyncMock(
                    side_effect=HTTPException(status_code=403, detail="forbidden")
                ),
            ),
        ):
            app.dependency_overrides.update(_dep_overrides())
            resp = client.get(
                f"/api/v1/corporate/accounts/me/shifts/{SHIFT_ID}/auto-bookings/summary"
            )
            app.dependency_overrides.clear()
        assert resp.status_code == 403

    def test_404_shift_not_found(self):
        """60. 404 when shift does not exist."""
        with (
            patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)),
            patch(f"{_ROUTER}._require_account_admin", new=AsyncMock()),
            patch(
                f"{_ROUTER}.get_shift_auto_booking_summary",
                new=AsyncMock(
                    side_effect=HTTPException(status_code=404, detail="not found")
                ),
            ),
        ):
            app.dependency_overrides.update(_dep_overrides(is_admin=True))
            resp = client.get(
                f"/api/v1/corporate/accounts/me/shifts/{SHIFT_ID}/auto-bookings/summary"
            )
            app.dependency_overrides.clear()
        assert resp.status_code == 404


class TestAPIPlatformAdmin:
    """API tests: platform-admin endpoints."""

    def test_200_platform_admin_list_all(self):
        """61. 200 platform-admin can list all auto-bookings."""
        with patch(
            f"{_ROUTER}.list_all_platform",
            new=AsyncMock(return_value=AutoBookingListResponse(**_list_resp_dict())),
        ):
            app.dependency_overrides.update(_dep_overrides(is_admin=True))
            resp = client.get("/api/v1/platform/corporate/shift-auto-bookings")
            app.dependency_overrides.clear()
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    def test_200_platform_admin_list_for_account(self):
        """62. 200 platform-admin can list for specific account."""
        with patch(
            f"{_ROUTER}.list_all_platform",
            new=AsyncMock(return_value=AutoBookingListResponse(**_list_resp_dict())),
        ):
            app.dependency_overrides.update(_dep_overrides(is_admin=True))
            resp = client.get(
                f"/api/v1/platform/corporate/accounts/{ACCOUNT_ID}/shift-auto-bookings"
            )
            app.dependency_overrides.clear()
        assert resp.status_code == 200
