"""Tests for the Corporate Recurring Ride Schedules feature.

Service layer (async, mocked DB):
  1.  create_recurring_ride — creates schedule with all fields
  2.  create_recurring_ride — creates with minimal required fields
  3.  create_recurring_ride — stores account_id and member_id correctly
  4.  create_recurring_ride — 409 on duplicate name for same member+account
  5.  create_recurring_ride — different members can use same name
  6.  get_recurring_ride — returns schedule when found
  7.  get_recurring_ride — 404 when not found
  8.  get_recurring_ride — 404 when belongs to different member
  9.  list_recurring_rides — returns member's schedules sorted by name
  10. list_recurring_rides — filter is_active=True returns only active
  11. list_recurring_rides — filter is_active=False returns only inactive
  12. list_recurring_rides — empty list when member has no schedules
  13. update_recurring_ride — partial update writes only supplied fields
  14. update_recurring_ride — name update persisted correctly
  15. update_recurring_ride — 404 when not found
  16. update_recurring_ride — 409 on name collision with different schedule
  17. activate_recurring_ride — sets is_active=True
  18. activate_recurring_ride — 404 when not found
  19. activate_recurring_ride — 409 when already active
  20. deactivate_recurring_ride — sets is_active=False
  21. deactivate_recurring_ride — 404 when not found
  22. deactivate_recurring_ride — 409 when already inactive
  23. delete_recurring_ride — hard-deletes inactive schedule
  24. delete_recurring_ride — 404 when not found
  25. delete_recurring_ride — 409 when active
  26. record_booking_attempt — creates booking with pending status
  27. record_booking_attempt — creates booking with booked status and ride_id
  28. record_booking_attempt — creates failed booking with failure_reason
  29. record_booking_attempt — 404 when schedule not found
  30. list_booking_history — returns newest first
  31. list_booking_history — respects limit and offset
  32. list_booking_history — returns empty list when no bookings
  33. list_booking_history — 404 when schedule not found or wrong member
  34. list_account_recurring_rides — returns all schedules for account
  35. list_account_recurring_rides — includes schedules from multiple members
  36. list_account_recurring_rides — filter is_active
  37. list_all_platform — returns all schedules across accounts
  38. list_all_platform — filters by account_id

Schema validation:
  39. RecurringRideCreate — valid daily schedule accepted
  40. RecurringRideCreate — valid weekly schedule accepted
  41. RecurringRideCreate — valid monthly schedule accepted
  42. RecurringRideCreate — blank name rejected
  43. RecurringRideCreate — blank pickup_address rejected
  44. RecurringRideCreate — invalid scheduled_time format rejected
  45. RecurringRideCreate — scheduled_time invalid hour rejected
  46. RecurringRideCreate — days_of_week out of range rejected
  47. RecurringRideCreate — days_of_week required for weekly recurrence
  48. RecurringRideCreate — day_of_month required for monthly recurrence
  49. RecurringRideCreate — day_of_month out of range rejected
  50. RecurringRideCreate — advance_booking_minutes must be positive
  51. RecurringRideUpdate — all fields optional
  52. RecurringRideUpdate — blank name rejected when supplied
  53. RecurringRideResponse — from_attributes construction
  54. RecurringRideBookingResponse — from_attributes construction

API layer (service functions patched):
  55. POST /recurring-rides (member) — 201 creates schedule
  56. POST /recurring-rides (member) — 409 on duplicate name
  57. POST /recurring-rides (member) — 404 when not in account
  58. GET /recurring-rides (member) — 200 returns list
  59. GET /recurring-rides (member) — 404 when not in account
  60. GET /recurring-rides/{id} (member) — 200 returns schedule
  61. GET /recurring-rides/{id} (member) — 404 not found
  62. PUT /recurring-rides/{id} (member) — 200 updates schedule
  63. PUT /recurring-rides/{id} (member) — 409 on duplicate name
  64. POST /recurring-rides/{id}/activate (member) — 200 activates
  65. POST /recurring-rides/{id}/activate (member) — 409 already active
  66. POST /recurring-rides/{id}/deactivate (member) — 200 deactivates
  67. POST /recurring-rides/{id}/deactivate (member) — 409 already inactive
  68. DELETE /recurring-rides/{id} (member) — 204 deletes
  69. DELETE /recurring-rides/{id} (member) — 409 when active
  70. GET /recurring-rides/{id}/bookings (member) — 200 returns booking history
  71. GET /admin/recurring-rides (admin) — 200 returns all for account
  72. GET /admin/recurring-rides (admin) — 403 non-admin blocked
  73. GET /admin/recurring-rides/active (admin) — 200 returns active schedules
  74. GET /platform/recurring-rides/all — 200 platform-admin lists all
  75. GET /platform/recurring-rides/account/{id} — 200 lists for account
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.corporate_recurring_ride import (
    CorporateRecurringRide,
    CorporateRecurringRideBooking,
    RecurrenceType,
    RecurringRideBookingStatus,
)
from app.schemas.corporate_recurring_ride import (
    RecurringRideBookingListResponse,
    RecurringRideBookingResponse,
    RecurringRideCreate,
    RecurringRideListResponse,
    RecurringRideResponse,
    RecurringRideUpdate,
)
from app.services.corporate_recurring_ride import (
    activate_recurring_ride,
    create_recurring_ride,
    deactivate_recurring_ride,
    delete_recurring_ride,
    get_recurring_ride,
    list_account_recurring_rides,
    list_all_platform,
    list_booking_history,
    list_recurring_rides,
    record_booking_attempt,
    update_recurring_ride,
)


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

NOW = datetime(2026, 4, 16, 10, 0, 0, tzinfo=timezone.utc)
NOW_2 = datetime(2026, 4, 16, 11, 0, 0, tzinfo=timezone.utc)

ACCOUNT_ID = 5
OTHER_ACCOUNT_ID = 6
MEMBER_ID = 11
OTHER_MEMBER_ID = 12
RIDE_ID = uuid.uuid4()
OTHER_RIDE_ID = uuid.uuid4()
BOOKING_ID = uuid.uuid4()


def _make_ride(
    id: uuid.UUID = RIDE_ID,
    account_id: int = ACCOUNT_ID,
    member_id: int = MEMBER_ID,
    name: str = "Daily Commute",
    pickup_address: str = "123 Home St, Springfield",
    dropoff_address: str = "456 Office Ave, Springfield",
    recurrence_type: RecurrenceType = RecurrenceType.daily,
    days_of_week: list | None = None,
    day_of_month: int | None = None,
    scheduled_time: str = "08:30",
    advance_booking_minutes: int = 60,
    vehicle_type: str | None = None,
    is_active: bool = True,
    cost_center_id: int | None = None,
    trip_purpose_id: int | None = None,
    notes: str | None = None,
) -> CorporateRecurringRide:
    r = CorporateRecurringRide()
    r.id = id
    r.account_id = account_id
    r.member_id = member_id
    r.name = name
    r.pickup_address = pickup_address
    r.pickup_lat = None
    r.pickup_lng = None
    r.dropoff_address = dropoff_address
    r.dropoff_lat = None
    r.dropoff_lng = None
    r.vehicle_type = vehicle_type
    r.recurrence_type = recurrence_type
    r.days_of_week = days_of_week
    r.day_of_month = day_of_month
    r.scheduled_time = scheduled_time
    r.advance_booking_minutes = advance_booking_minutes
    r.cost_center_id = cost_center_id
    r.trip_purpose_id = trip_purpose_id
    r.notes = notes
    r.is_active = is_active
    r.created_at = NOW
    r.updated_at = NOW
    return r


def _make_inactive_ride(**kwargs) -> CorporateRecurringRide:
    return _make_ride(is_active=False, **kwargs)


def _make_weekly_ride(**kwargs) -> CorporateRecurringRide:
    return _make_ride(
        recurrence_type=RecurrenceType.weekly,
        days_of_week=[0, 1, 2, 3, 4],  # Mon–Fri
        **kwargs,
    )


def _make_monthly_ride(**kwargs) -> CorporateRecurringRide:
    return _make_ride(
        recurrence_type=RecurrenceType.monthly,
        day_of_month=1,
        **kwargs,
    )


def _make_booking(
    id: uuid.UUID = BOOKING_ID,
    recurring_ride_id: uuid.UUID = RIDE_ID,
    account_id: int = ACCOUNT_ID,
    member_id: int = MEMBER_ID,
    ride_id: int | None = None,
    scheduled_for: datetime = NOW,
    status: RecurringRideBookingStatus = RecurringRideBookingStatus.pending,
    failure_reason: str | None = None,
) -> CorporateRecurringRideBooking:
    b = CorporateRecurringRideBooking()
    b.id = id
    b.recurring_ride_id = recurring_ride_id
    b.account_id = account_id
    b.member_id = member_id
    b.ride_id = ride_id
    b.scheduled_for = scheduled_for
    b.status = status
    b.failure_reason = failure_reason
    b.created_at = NOW
    return b


def _async_result(value: Any):
    """Return a MagicMock representing the result of ``await db.execute(...)``.

    Using MagicMock (not AsyncMock) ensures that calling ``.scalar_one_or_none()``
    returns the value synchronously rather than returning a coroutine.
    """
    mock = MagicMock()
    mock.scalar_one_or_none.return_value = value
    mock.scalars.return_value.all.return_value = (
        value if isinstance(value, list) else []
    )
    return mock


def _async_list(items: list):
    """Return a MagicMock representing an execute result with a list of rows."""
    mock = MagicMock()
    mock.scalars.return_value.all.return_value = items
    mock.scalar_one_or_none.return_value = None
    return mock


def _make_db(execute_returns=None, refresh_fn=None):
    """Build a minimal AsyncSession mock."""
    db = AsyncMock()
    if execute_returns is not None:
        if isinstance(execute_returns, list):
            db.execute.side_effect = execute_returns
        else:
            db.execute.return_value = execute_returns
    if refresh_fn is not None:
        db.refresh.side_effect = refresh_fn
    return db


# ---------------------------------------------------------------------------
# Service layer tests
# ---------------------------------------------------------------------------


class TestCreateRecurringRide:
    """Tests 1–5: create_recurring_ride."""

    @pytest.mark.asyncio
    async def test_creates_with_all_fields(self):
        data = RecurringRideCreate(
            name="Daily Commute",
            pickup_address="123 Home St",
            dropoff_address="456 Office Ave",
            recurrence_type=RecurrenceType.daily,
            scheduled_time="08:30",
            advance_booking_minutes=45,
            vehicle_type="sedan",
            notes="Please use the front entrance",
        )

        db = AsyncMock()
        db.add = MagicMock()
        no_existing = MagicMock()
        no_existing.scalar_one_or_none.return_value = None
        db.execute.return_value = no_existing

        async def _refresh(obj):
            obj.id = RIDE_ID
            obj.created_at = NOW
            obj.updated_at = NOW

        db.refresh = AsyncMock(side_effect=_refresh)

        result = await create_recurring_ride(db, ACCOUNT_ID, MEMBER_ID, data)

        assert result.name == "Daily Commute"
        assert result.advance_booking_minutes == 45
        db.add.assert_called_once()
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_creates_with_minimal_fields(self):
        data = RecurringRideCreate(
            name="Minimal",
            pickup_address="A",
            dropoff_address="B",
            recurrence_type=RecurrenceType.daily,
            scheduled_time="09:00",
        )

        db = AsyncMock()
        db.add = MagicMock()
        no_existing = MagicMock()
        no_existing.scalar_one_or_none.return_value = None
        db.execute.return_value = no_existing

        async def _refresh(obj):
            obj.id = RIDE_ID
            obj.created_at = NOW
            obj.updated_at = NOW

        db.refresh = AsyncMock(side_effect=_refresh)

        result = await create_recurring_ride(db, ACCOUNT_ID, MEMBER_ID, data)
        assert result.id == RIDE_ID

    @pytest.mark.asyncio
    async def test_stores_account_and_member_ids(self):
        data = RecurringRideCreate(
            name="Commute",
            pickup_address="Home",
            dropoff_address="Office",
            recurrence_type=RecurrenceType.daily,
            scheduled_time="07:45",
        )
        db = AsyncMock()
        db.add = MagicMock()
        no_existing = MagicMock()
        no_existing.scalar_one_or_none.return_value = None
        db.execute.return_value = no_existing

        async def _refresh(obj):
            obj.id = RIDE_ID
            obj.created_at = NOW
            obj.updated_at = NOW

        db.refresh = AsyncMock(side_effect=_refresh)

        result = await create_recurring_ride(db, ACCOUNT_ID, MEMBER_ID, data)
        assert result.account_id == ACCOUNT_ID
        assert result.member_id == MEMBER_ID

    @pytest.mark.asyncio
    async def test_409_on_duplicate_name_for_same_member(self):
        existing_ride = _make_ride()
        data = RecurringRideCreate(
            name="Daily Commute",
            pickup_address="A",
            dropoff_address="B",
            recurrence_type=RecurrenceType.daily,
            scheduled_time="08:30",
        )
        db = _make_db(execute_returns=_async_result(existing_ride))

        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await create_recurring_ride(db, ACCOUNT_ID, MEMBER_ID, data)
        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_different_members_can_use_same_name(self):
        # Query returns None → no conflict for OTHER_MEMBER_ID
        data = RecurringRideCreate(
            name="Daily Commute",
            pickup_address="A",
            dropoff_address="B",
            recurrence_type=RecurrenceType.daily,
            scheduled_time="08:30",
        )
        db = AsyncMock()
        db.add = MagicMock()
        no_existing = MagicMock()
        no_existing.scalar_one_or_none.return_value = None
        db.execute.return_value = no_existing

        async def _refresh(obj):
            obj.id = OTHER_RIDE_ID
            obj.created_at = NOW
            obj.updated_at = NOW

        db.refresh = AsyncMock(side_effect=_refresh)

        result = await create_recurring_ride(db, ACCOUNT_ID, OTHER_MEMBER_ID, data)
        assert result.member_id == OTHER_MEMBER_ID


class TestGetRecurringRide:
    """Tests 6–8: get_recurring_ride."""

    @pytest.mark.asyncio
    async def test_returns_ride_when_found(self):
        ride = _make_ride()
        db = _make_db(execute_returns=_async_result(ride))
        result = await get_recurring_ride(db, RIDE_ID, ACCOUNT_ID, MEMBER_ID)
        assert result.id == RIDE_ID

    @pytest.mark.asyncio
    async def test_404_when_not_found(self):
        db = _make_db(execute_returns=_async_result(None))
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await get_recurring_ride(db, RIDE_ID, ACCOUNT_ID, MEMBER_ID)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_404_when_belongs_to_different_member(self):
        # The ride belongs to MEMBER_ID but we query with OTHER_MEMBER_ID
        db = _make_db(execute_returns=_async_result(None))
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await get_recurring_ride(db, RIDE_ID, ACCOUNT_ID, OTHER_MEMBER_ID)
        assert exc_info.value.status_code == 404


class TestListRecurringRides:
    """Tests 9–12: list_recurring_rides."""

    @pytest.mark.asyncio
    async def test_returns_member_rides_sorted_by_name(self):
        rides = [
            _make_ride(id=uuid.uuid4(), name="Airport Run"),
            _make_ride(id=uuid.uuid4(), name="Daily Commute"),
        ]
        db = _make_db(execute_returns=_async_list(rides))
        result = await list_recurring_rides(db, ACCOUNT_ID, MEMBER_ID)
        assert result.total == 2
        assert result.items[0].name == "Airport Run"

    @pytest.mark.asyncio
    async def test_filter_is_active_true(self):
        active = _make_ride()
        db = _make_db(execute_returns=_async_list([active]))
        result = await list_recurring_rides(
            db, ACCOUNT_ID, MEMBER_ID, is_active=True
        )
        assert result.total == 1
        assert result.items[0].is_active is True

    @pytest.mark.asyncio
    async def test_filter_is_active_false(self):
        inactive = _make_inactive_ride()
        db = _make_db(execute_returns=_async_list([inactive]))
        result = await list_recurring_rides(
            db, ACCOUNT_ID, MEMBER_ID, is_active=False
        )
        assert result.total == 1
        assert result.items[0].is_active is False

    @pytest.mark.asyncio
    async def test_empty_list_when_no_schedules(self):
        db = _make_db(execute_returns=_async_list([]))
        result = await list_recurring_rides(db, ACCOUNT_ID, MEMBER_ID)
        assert result.total == 0
        assert result.items == []


class TestUpdateRecurringRide:
    """Tests 13–16: update_recurring_ride."""

    @pytest.mark.asyncio
    async def test_partial_update_writes_supplied_fields(self):
        ride = _make_ride()
        data = RecurringRideUpdate(scheduled_time="09:00")
        db = _make_db(execute_returns=_async_result(ride))
        db.commit = AsyncMock()
        db.refresh = AsyncMock()
        result = await update_recurring_ride(
            db, RIDE_ID, ACCOUNT_ID, MEMBER_ID, data
        )
        assert ride.scheduled_time == "09:00"

    @pytest.mark.asyncio
    async def test_name_update_persisted(self):
        ride = _make_ride()
        data = RecurringRideUpdate(name="Updated Name")
        # First call: get the ride; no collision
        no_collision = _async_result(None)
        db = AsyncMock()
        db.execute.side_effect = [_async_result(ride), no_collision]
        db.commit = AsyncMock()
        db.refresh = AsyncMock()
        result = await update_recurring_ride(
            db, RIDE_ID, ACCOUNT_ID, MEMBER_ID, data
        )
        assert ride.name == "Updated Name"

    @pytest.mark.asyncio
    async def test_404_when_not_found(self):
        data = RecurringRideUpdate(scheduled_time="10:00")
        db = _make_db(execute_returns=_async_result(None))
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await update_recurring_ride(db, RIDE_ID, ACCOUNT_ID, MEMBER_ID, data)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_409_on_name_collision_with_different_schedule(self):
        ride = _make_ride()
        other_ride = _make_ride(id=OTHER_RIDE_ID, name="Airport Run")
        data = RecurringRideUpdate(name="Airport Run")
        db = AsyncMock()
        db.execute.side_effect = [_async_result(ride), _async_result(other_ride)]
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await update_recurring_ride(db, RIDE_ID, ACCOUNT_ID, MEMBER_ID, data)
        assert exc_info.value.status_code == 409


class TestActivateDeactivateRecurringRide:
    """Tests 17–22: activate/deactivate."""

    @pytest.mark.asyncio
    async def test_activate_sets_is_active_true(self):
        ride = _make_inactive_ride()
        db = _make_db(execute_returns=_async_result(ride))
        db.commit = AsyncMock()
        db.refresh = AsyncMock()
        await activate_recurring_ride(db, RIDE_ID, ACCOUNT_ID, MEMBER_ID)
        assert ride.is_active is True

    @pytest.mark.asyncio
    async def test_activate_404_when_not_found(self):
        db = _make_db(execute_returns=_async_result(None))
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await activate_recurring_ride(db, RIDE_ID, ACCOUNT_ID, MEMBER_ID)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_activate_409_when_already_active(self):
        ride = _make_ride(is_active=True)
        db = _make_db(execute_returns=_async_result(ride))
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await activate_recurring_ride(db, RIDE_ID, ACCOUNT_ID, MEMBER_ID)
        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_deactivate_sets_is_active_false(self):
        ride = _make_ride(is_active=True)
        db = _make_db(execute_returns=_async_result(ride))
        db.commit = AsyncMock()
        db.refresh = AsyncMock()
        await deactivate_recurring_ride(db, RIDE_ID, ACCOUNT_ID, MEMBER_ID)
        assert ride.is_active is False

    @pytest.mark.asyncio
    async def test_deactivate_404_when_not_found(self):
        db = _make_db(execute_returns=_async_result(None))
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await deactivate_recurring_ride(db, RIDE_ID, ACCOUNT_ID, MEMBER_ID)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_deactivate_409_when_already_inactive(self):
        ride = _make_inactive_ride()
        db = _make_db(execute_returns=_async_result(ride))
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await deactivate_recurring_ride(db, RIDE_ID, ACCOUNT_ID, MEMBER_ID)
        assert exc_info.value.status_code == 409


class TestDeleteRecurringRide:
    """Tests 23–25: delete_recurring_ride."""

    @pytest.mark.asyncio
    async def test_hard_deletes_inactive_schedule(self):
        ride = _make_inactive_ride()
        db = _make_db(execute_returns=_async_result(ride))
        db.delete = AsyncMock()
        db.commit = AsyncMock()
        await delete_recurring_ride(db, RIDE_ID, ACCOUNT_ID, MEMBER_ID)
        db.delete.assert_awaited_once_with(ride)
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_404_when_not_found(self):
        db = _make_db(execute_returns=_async_result(None))
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await delete_recurring_ride(db, RIDE_ID, ACCOUNT_ID, MEMBER_ID)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_409_when_active(self):
        ride = _make_ride(is_active=True)
        db = _make_db(execute_returns=_async_result(ride))
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await delete_recurring_ride(db, RIDE_ID, ACCOUNT_ID, MEMBER_ID)
        assert exc_info.value.status_code == 409


class TestRecordBookingAttempt:
    """Tests 26–29: record_booking_attempt."""

    @pytest.mark.asyncio
    async def test_creates_pending_booking(self):
        ride = _make_ride()
        db = AsyncMock()
        db.add = MagicMock()
        ride_result = MagicMock()
        ride_result.scalar_one_or_none.return_value = ride
        db.execute.return_value = ride_result

        async def _refresh(obj):
            obj.id = BOOKING_ID
            obj.created_at = NOW

        db.refresh = AsyncMock(side_effect=_refresh)

        result = await record_booking_attempt(
            db,
            RIDE_ID,
            ACCOUNT_ID,
            MEMBER_ID,
            scheduled_for=NOW,
        )

        assert result.status == RecurringRideBookingStatus.pending
        db.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_creates_booked_booking_with_ride_id(self):
        ride = _make_ride()
        db = AsyncMock()
        db.add = MagicMock()
        ride_result = MagicMock()
        ride_result.scalar_one_or_none.return_value = ride
        db.execute.return_value = ride_result

        async def _refresh(obj):
            obj.id = BOOKING_ID
            obj.created_at = NOW

        db.refresh = AsyncMock(side_effect=_refresh)

        result = await record_booking_attempt(
            db,
            RIDE_ID,
            ACCOUNT_ID,
            MEMBER_ID,
            scheduled_for=NOW,
            status=RecurringRideBookingStatus.booked,
            linked_ride_id=999,
        )

        assert result.status == RecurringRideBookingStatus.booked
        assert result.ride_id == 999

    @pytest.mark.asyncio
    async def test_creates_failed_booking_with_reason(self):
        ride = _make_ride()
        db = AsyncMock()
        db.add = MagicMock()
        ride_result = MagicMock()
        ride_result.scalar_one_or_none.return_value = ride
        db.execute.return_value = ride_result

        async def _refresh(obj):
            obj.id = BOOKING_ID
            obj.created_at = NOW

        db.refresh = AsyncMock(side_effect=_refresh)

        result = await record_booking_attempt(
            db,
            RIDE_ID,
            ACCOUNT_ID,
            MEMBER_ID,
            scheduled_for=NOW,
            status=RecurringRideBookingStatus.failed,
            failure_reason="No drivers available",
        )

        assert result.status == RecurringRideBookingStatus.failed
        assert result.failure_reason == "No drivers available"

    @pytest.mark.asyncio
    async def test_404_when_schedule_not_found(self):
        db = _make_db(execute_returns=_async_result(None))
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await record_booking_attempt(
                db, RIDE_ID, ACCOUNT_ID, MEMBER_ID, scheduled_for=NOW
            )
        assert exc_info.value.status_code == 404


class TestListBookingHistory:
    """Tests 30–33: list_booking_history."""

    @pytest.mark.asyncio
    async def test_returns_newest_first(self):
        ride = _make_ride()
        b1 = _make_booking(id=uuid.uuid4(), scheduled_for=NOW)
        b2 = _make_booking(id=uuid.uuid4(), scheduled_for=NOW_2)

        db = AsyncMock()
        # First call: ownership check; second call: bookings list
        db.execute.side_effect = [_async_result(ride), _async_list([b2, b1])]
        result = await list_booking_history(
            db, RIDE_ID, ACCOUNT_ID, MEMBER_ID
        )
        assert result.total == 2
        assert result.items[0].scheduled_for == NOW_2

    @pytest.mark.asyncio
    async def test_respects_limit_and_offset(self):
        ride = _make_ride()
        bookings = [_make_booking(id=uuid.uuid4()) for _ in range(3)]

        db = AsyncMock()
        db.execute.side_effect = [_async_result(ride), _async_list(bookings[:2])]
        result = await list_booking_history(
            db, RIDE_ID, ACCOUNT_ID, MEMBER_ID, limit=2, offset=0
        )
        assert result.total == 2

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_bookings(self):
        ride = _make_ride()
        db = AsyncMock()
        db.execute.side_effect = [_async_result(ride), _async_list([])]
        result = await list_booking_history(
            db, RIDE_ID, ACCOUNT_ID, MEMBER_ID
        )
        assert result.total == 0
        assert result.items == []

    @pytest.mark.asyncio
    async def test_404_when_schedule_not_found(self):
        db = _make_db(execute_returns=_async_result(None))
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await list_booking_history(db, RIDE_ID, ACCOUNT_ID, MEMBER_ID)
        assert exc_info.value.status_code == 404


class TestListAccountRecurringRides:
    """Tests 34–36: list_account_recurring_rides."""

    @pytest.mark.asyncio
    async def test_returns_all_for_account(self):
        r1 = _make_ride(id=uuid.uuid4(), member_id=MEMBER_ID)
        r2 = _make_ride(id=uuid.uuid4(), member_id=OTHER_MEMBER_ID)
        db = _make_db(execute_returns=_async_list([r1, r2]))
        result = await list_account_recurring_rides(db, ACCOUNT_ID)
        assert result.total == 2

    @pytest.mark.asyncio
    async def test_includes_rides_from_multiple_members(self):
        rides = [
            _make_ride(id=uuid.uuid4(), member_id=MEMBER_ID, name="A"),
            _make_ride(id=uuid.uuid4(), member_id=OTHER_MEMBER_ID, name="B"),
        ]
        db = _make_db(execute_returns=_async_list(rides))
        result = await list_account_recurring_rides(db, ACCOUNT_ID)
        member_ids = {r.member_id for r in result.items}
        assert MEMBER_ID in member_ids
        assert OTHER_MEMBER_ID in member_ids

    @pytest.mark.asyncio
    async def test_filter_is_active(self):
        active = _make_ride()
        db = _make_db(execute_returns=_async_list([active]))
        result = await list_account_recurring_rides(db, ACCOUNT_ID, is_active=True)
        assert result.total == 1
        assert result.items[0].is_active is True


class TestListAllPlatform:
    """Tests 37–38: list_all_platform."""

    @pytest.mark.asyncio
    async def test_returns_all_schedules(self):
        rides = [
            _make_ride(id=uuid.uuid4(), account_id=ACCOUNT_ID),
            _make_ride(id=uuid.uuid4(), account_id=OTHER_ACCOUNT_ID),
        ]
        db = _make_db(execute_returns=_async_list(rides))
        result = await list_all_platform(db)
        assert result.total == 2

    @pytest.mark.asyncio
    async def test_filters_by_account_id(self):
        ride = _make_ride(account_id=ACCOUNT_ID)
        db = _make_db(execute_returns=_async_list([ride]))
        result = await list_all_platform(db, account_id=ACCOUNT_ID)
        assert result.total == 1
        assert result.items[0].account_id == ACCOUNT_ID


# ---------------------------------------------------------------------------
# Schema validation tests
# ---------------------------------------------------------------------------


class TestSchemaValidation:
    """Tests 39–54."""

    def test_valid_daily_schedule(self):
        data = RecurringRideCreate(
            name="Daily Commute",
            pickup_address="Home",
            dropoff_address="Office",
            recurrence_type=RecurrenceType.daily,
            scheduled_time="08:30",
        )
        assert data.recurrence_type == RecurrenceType.daily

    def test_valid_weekly_schedule(self):
        data = RecurringRideCreate(
            name="Weekly Meeting",
            pickup_address="Home",
            dropoff_address="Office",
            recurrence_type=RecurrenceType.weekly,
            days_of_week=[1, 3],  # Tue, Thu
            scheduled_time="09:00",
        )
        assert data.days_of_week == [1, 3]

    def test_valid_monthly_schedule(self):
        data = RecurringRideCreate(
            name="Monthly Off-Site",
            pickup_address="Home",
            dropoff_address="Venue",
            recurrence_type=RecurrenceType.monthly,
            day_of_month=15,
            scheduled_time="10:00",
        )
        assert data.day_of_month == 15

    def test_blank_name_rejected(self):
        with pytest.raises(Exception):
            RecurringRideCreate(
                name="  ",
                pickup_address="Home",
                dropoff_address="Office",
                recurrence_type=RecurrenceType.daily,
                scheduled_time="08:00",
            )

    def test_blank_pickup_address_rejected(self):
        with pytest.raises(Exception):
            RecurringRideCreate(
                name="Test",
                pickup_address="   ",
                dropoff_address="Office",
                recurrence_type=RecurrenceType.daily,
                scheduled_time="08:00",
            )

    def test_invalid_time_format_rejected(self):
        with pytest.raises(Exception):
            RecurringRideCreate(
                name="Test",
                pickup_address="A",
                dropoff_address="B",
                recurrence_type=RecurrenceType.daily,
                scheduled_time="8:30",  # missing leading zero
            )

    def test_invalid_hour_rejected(self):
        with pytest.raises(Exception):
            RecurringRideCreate(
                name="Test",
                pickup_address="A",
                dropoff_address="B",
                recurrence_type=RecurrenceType.daily,
                scheduled_time="25:00",
            )

    def test_days_of_week_out_of_range_rejected(self):
        with pytest.raises(Exception):
            RecurringRideCreate(
                name="Test",
                pickup_address="A",
                dropoff_address="B",
                recurrence_type=RecurrenceType.weekly,
                days_of_week=[0, 7],  # 7 is invalid
                scheduled_time="08:00",
            )

    def test_days_of_week_required_for_weekly(self):
        with pytest.raises(Exception):
            RecurringRideCreate(
                name="Test",
                pickup_address="A",
                dropoff_address="B",
                recurrence_type=RecurrenceType.weekly,
                scheduled_time="08:00",
                # days_of_week omitted
            )

    def test_day_of_month_required_for_monthly(self):
        with pytest.raises(Exception):
            RecurringRideCreate(
                name="Test",
                pickup_address="A",
                dropoff_address="B",
                recurrence_type=RecurrenceType.monthly,
                scheduled_time="08:00",
                # day_of_month omitted
            )

    def test_day_of_month_out_of_range_rejected(self):
        with pytest.raises(Exception):
            RecurringRideCreate(
                name="Test",
                pickup_address="A",
                dropoff_address="B",
                recurrence_type=RecurrenceType.monthly,
                day_of_month=32,
                scheduled_time="08:00",
            )

    def test_advance_booking_minutes_must_be_positive(self):
        with pytest.raises(Exception):
            RecurringRideCreate(
                name="Test",
                pickup_address="A",
                dropoff_address="B",
                recurrence_type=RecurrenceType.daily,
                scheduled_time="08:00",
                advance_booking_minutes=0,
            )

    def test_update_all_fields_optional(self):
        data = RecurringRideUpdate()
        assert data.name is None
        assert data.scheduled_time is None
        assert data.days_of_week is None

    def test_update_blank_name_rejected(self):
        with pytest.raises(Exception):
            RecurringRideUpdate(name="")

    def test_ride_response_from_attributes(self):
        ride = _make_ride()
        resp = RecurringRideResponse(
            id=ride.id,
            account_id=ride.account_id,
            member_id=ride.member_id,
            name=ride.name,
            pickup_address=ride.pickup_address,
            dropoff_address=ride.dropoff_address,
            recurrence_type=ride.recurrence_type,
            scheduled_time=ride.scheduled_time,
            advance_booking_minutes=ride.advance_booking_minutes,
            is_active=ride.is_active,
            created_at=ride.created_at,
            updated_at=ride.updated_at,
        )
        assert resp.id == RIDE_ID
        assert resp.recurrence_type == RecurrenceType.daily

    def test_booking_response_from_attributes(self):
        booking = _make_booking()
        resp = RecurringRideBookingResponse(
            id=booking.id,
            recurring_ride_id=booking.recurring_ride_id,
            account_id=booking.account_id,
            member_id=booking.member_id,
            scheduled_for=booking.scheduled_for,
            status=booking.status,
            created_at=booking.created_at,
        )
        assert resp.status == RecurringRideBookingStatus.pending
        assert resp.ride_id is None


# ---------------------------------------------------------------------------
# API layer tests
# ---------------------------------------------------------------------------

_RIDE_RESPONSE = RecurringRideResponse(
    id=RIDE_ID,
    account_id=ACCOUNT_ID,
    member_id=MEMBER_ID,
    name="Daily Commute",
    pickup_address="123 Home St",
    dropoff_address="456 Office Ave",
    recurrence_type=RecurrenceType.daily,
    scheduled_time="08:30",
    advance_booking_minutes=60,
    is_active=True,
    created_at=NOW,
    updated_at=NOW,
)

_LIST_RESPONSE = RecurringRideListResponse(
    items=[_RIDE_RESPONSE], total=1
)

_BOOKING_LIST_RESPONSE = RecurringRideBookingListResponse(
    items=[
        RecurringRideBookingResponse(
            id=BOOKING_ID,
            recurring_ride_id=RIDE_ID,
            account_id=ACCOUNT_ID,
            member_id=MEMBER_ID,
            scheduled_for=NOW,
            status=RecurringRideBookingStatus.booked,
            created_at=NOW,
        )
    ],
    total=1,
)


def _make_user(is_admin: bool = False):
    user = MagicMock()
    user.id = 99
    user.is_admin = is_admin
    return user


def _mock_account_and_member(account_id: int = ACCOUNT_ID, member_id: int = MEMBER_ID):
    """Patch _resolve_account_and_member to return fixed IDs."""
    return patch(
        "app.api.v1.corporate_recurring_rides._resolve_account_and_member",
        new=AsyncMock(return_value=(account_id, member_id)),
    )


def _mock_account_only(account_id: int = ACCOUNT_ID):
    """Patch _resolve_account_id to return fixed ID."""
    return patch(
        "app.api.v1.corporate_recurring_rides._resolve_account_id",
        new=AsyncMock(return_value=account_id),
    )


def _mock_require_admin(raises: bool = False):
    if raises:
        from fastapi import HTTPException
        return patch(
            "app.api.v1.corporate_recurring_rides._require_account_admin",
            new=AsyncMock(
                side_effect=HTTPException(status_code=403, detail="Forbidden")
            ),
        )
    return patch(
        "app.api.v1.corporate_recurring_rides._require_account_admin",
        new=AsyncMock(return_value=None),
    )


class TestAPIEndpoints:
    """Tests 55–75: API layer."""

    @pytest.fixture
    def client(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.api.v1.corporate_recurring_rides import router
        from app.api.deps import get_current_user, get_db, require_admin

        app = FastAPI()
        app.include_router(router, prefix="/api/v1")

        user = _make_user()
        admin_user = _make_user(is_admin=True)
        fake_db = AsyncMock()

        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_db] = lambda: fake_db
        app.dependency_overrides[require_admin] = lambda: admin_user

        return TestClient(app)

    # ---- create ----

    def test_post_creates_schedule_201(self, client):
        with (
            _mock_account_and_member(),
            patch(
                "app.api.v1.corporate_recurring_rides.create_recurring_ride",
                new=AsyncMock(return_value=_RIDE_RESPONSE),
            ),
        ):
            resp = client.post(
                "/api/v1/corporate/recurring-rides",
                json={
                    "name": "Daily Commute",
                    "pickup_address": "Home",
                    "dropoff_address": "Office",
                    "recurrence_type": "daily",
                    "scheduled_time": "08:30",
                },
            )
        assert resp.status_code == 201
        assert resp.json()["name"] == "Daily Commute"

    def test_post_409_on_duplicate_name(self, client):
        from fastapi import HTTPException
        with (
            _mock_account_and_member(),
            patch(
                "app.api.v1.corporate_recurring_rides.create_recurring_ride",
                new=AsyncMock(
                    side_effect=HTTPException(status_code=409, detail="Conflict")
                ),
            ),
        ):
            resp = client.post(
                "/api/v1/corporate/recurring-rides",
                json={
                    "name": "Daily Commute",
                    "pickup_address": "A",
                    "dropoff_address": "B",
                    "recurrence_type": "daily",
                    "scheduled_time": "08:00",
                },
            )
        assert resp.status_code == 409

    def test_post_404_when_not_in_account(self, client):
        from fastapi import HTTPException
        with patch(
            "app.api.v1.corporate_recurring_rides._resolve_account_and_member",
            new=AsyncMock(
                side_effect=HTTPException(status_code=404, detail="Not found")
            ),
        ):
            resp = client.post(
                "/api/v1/corporate/recurring-rides",
                json={
                    "name": "Test",
                    "pickup_address": "A",
                    "dropoff_address": "B",
                    "recurrence_type": "daily",
                    "scheduled_time": "08:00",
                },
            )
        assert resp.status_code == 404

    # ---- list ----

    def test_get_list_200(self, client):
        with (
            _mock_account_and_member(),
            patch(
                "app.api.v1.corporate_recurring_rides.list_recurring_rides",
                new=AsyncMock(return_value=_LIST_RESPONSE),
            ),
        ):
            resp = client.get("/api/v1/corporate/recurring-rides")
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    def test_get_list_404_not_in_account(self, client):
        from fastapi import HTTPException
        with patch(
            "app.api.v1.corporate_recurring_rides._resolve_account_and_member",
            new=AsyncMock(
                side_effect=HTTPException(status_code=404, detail="Not member")
            ),
        ):
            resp = client.get("/api/v1/corporate/recurring-rides")
        assert resp.status_code == 404

    # ---- get specific ----

    def test_get_specific_200(self, client):
        with (
            _mock_account_and_member(),
            patch(
                "app.api.v1.corporate_recurring_rides.get_recurring_ride",
                new=AsyncMock(return_value=_RIDE_RESPONSE),
            ),
        ):
            resp = client.get(f"/api/v1/corporate/recurring-rides/{RIDE_ID}")
        assert resp.status_code == 200

    def test_get_specific_404(self, client):
        from fastapi import HTTPException
        with (
            _mock_account_and_member(),
            patch(
                "app.api.v1.corporate_recurring_rides.get_recurring_ride",
                new=AsyncMock(
                    side_effect=HTTPException(status_code=404, detail="Not found")
                ),
            ),
        ):
            resp = client.get(f"/api/v1/corporate/recurring-rides/{RIDE_ID}")
        assert resp.status_code == 404

    # ---- update ----

    def test_put_updates_200(self, client):
        with (
            _mock_account_and_member(),
            patch(
                "app.api.v1.corporate_recurring_rides.update_recurring_ride",
                new=AsyncMock(return_value=_RIDE_RESPONSE),
            ),
        ):
            resp = client.put(
                f"/api/v1/corporate/recurring-rides/{RIDE_ID}",
                json={"scheduled_time": "09:00"},
            )
        assert resp.status_code == 200

    def test_put_409_on_duplicate_name(self, client):
        from fastapi import HTTPException
        with (
            _mock_account_and_member(),
            patch(
                "app.api.v1.corporate_recurring_rides.update_recurring_ride",
                new=AsyncMock(
                    side_effect=HTTPException(status_code=409, detail="Conflict")
                ),
            ),
        ):
            resp = client.put(
                f"/api/v1/corporate/recurring-rides/{RIDE_ID}",
                json={"name": "Other Name"},
            )
        assert resp.status_code == 409

    # ---- activate ----

    def test_post_activate_200(self, client):
        inactive = _RIDE_RESPONSE.model_copy(update={"is_active": True})
        with (
            _mock_account_and_member(),
            patch(
                "app.api.v1.corporate_recurring_rides.activate_recurring_ride",
                new=AsyncMock(return_value=inactive),
            ),
        ):
            resp = client.post(
                f"/api/v1/corporate/recurring-rides/{RIDE_ID}/activate"
            )
        assert resp.status_code == 200
        assert resp.json()["is_active"] is True

    def test_post_activate_409_already_active(self, client):
        from fastapi import HTTPException
        with (
            _mock_account_and_member(),
            patch(
                "app.api.v1.corporate_recurring_rides.activate_recurring_ride",
                new=AsyncMock(
                    side_effect=HTTPException(status_code=409, detail="Already active")
                ),
            ),
        ):
            resp = client.post(
                f"/api/v1/corporate/recurring-rides/{RIDE_ID}/activate"
            )
        assert resp.status_code == 409

    # ---- deactivate ----

    def test_post_deactivate_200(self, client):
        deactivated = _RIDE_RESPONSE.model_copy(update={"is_active": False})
        with (
            _mock_account_and_member(),
            patch(
                "app.api.v1.corporate_recurring_rides.deactivate_recurring_ride",
                new=AsyncMock(return_value=deactivated),
            ),
        ):
            resp = client.post(
                f"/api/v1/corporate/recurring-rides/{RIDE_ID}/deactivate"
            )
        assert resp.status_code == 200
        assert resp.json()["is_active"] is False

    def test_post_deactivate_409_already_inactive(self, client):
        from fastapi import HTTPException
        with (
            _mock_account_and_member(),
            patch(
                "app.api.v1.corporate_recurring_rides.deactivate_recurring_ride",
                new=AsyncMock(
                    side_effect=HTTPException(
                        status_code=409, detail="Already inactive"
                    )
                ),
            ),
        ):
            resp = client.post(
                f"/api/v1/corporate/recurring-rides/{RIDE_ID}/deactivate"
            )
        assert resp.status_code == 409

    # ---- delete ----

    def test_delete_204(self, client):
        with (
            _mock_account_and_member(),
            patch(
                "app.api.v1.corporate_recurring_rides.delete_recurring_ride",
                new=AsyncMock(return_value=None),
            ),
        ):
            resp = client.delete(
                f"/api/v1/corporate/recurring-rides/{RIDE_ID}"
            )
        assert resp.status_code == 204

    def test_delete_409_when_active(self, client):
        from fastapi import HTTPException
        with (
            _mock_account_and_member(),
            patch(
                "app.api.v1.corporate_recurring_rides.delete_recurring_ride",
                new=AsyncMock(
                    side_effect=HTTPException(status_code=409, detail="Active")
                ),
            ),
        ):
            resp = client.delete(
                f"/api/v1/corporate/recurring-rides/{RIDE_ID}"
            )
        assert resp.status_code == 409

    # ---- bookings ----

    def test_get_bookings_200(self, client):
        with (
            _mock_account_and_member(),
            patch(
                "app.api.v1.corporate_recurring_rides.list_booking_history",
                new=AsyncMock(return_value=_BOOKING_LIST_RESPONSE),
            ),
        ):
            resp = client.get(
                f"/api/v1/corporate/recurring-rides/{RIDE_ID}/bookings"
            )
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    # ---- admin ----

    def test_admin_list_all_200(self, client):
        with (
            _mock_account_only(),
            _mock_require_admin(raises=False),
            patch(
                "app.api.v1.corporate_recurring_rides.list_account_recurring_rides",
                new=AsyncMock(return_value=_LIST_RESPONSE),
            ),
        ):
            resp = client.get("/api/v1/corporate/admin/recurring-rides")
        assert resp.status_code == 200

    def test_admin_list_403_non_admin(self, client):
        with (
            _mock_account_only(),
            _mock_require_admin(raises=True),
        ):
            resp = client.get("/api/v1/corporate/admin/recurring-rides")
        assert resp.status_code == 403

    def test_admin_list_active_200(self, client):
        with (
            _mock_account_only(),
            _mock_require_admin(raises=False),
            patch(
                "app.api.v1.corporate_recurring_rides.list_account_recurring_rides",
                new=AsyncMock(return_value=_LIST_RESPONSE),
            ),
        ):
            resp = client.get("/api/v1/corporate/admin/recurring-rides/active")
        assert resp.status_code == 200

    # ---- platform-admin ----

    def test_platform_list_all_200(self, client):
        with patch(
            "app.api.v1.corporate_recurring_rides.list_all_platform",
            new=AsyncMock(return_value=_LIST_RESPONSE),
        ):
            resp = client.get(
                "/api/v1/platform-admin/corporate/recurring-rides/all"
            )
        assert resp.status_code == 200

    def test_platform_list_for_account_200(self, client):
        with patch(
            "app.api.v1.corporate_recurring_rides.list_account_recurring_rides",
            new=AsyncMock(return_value=_LIST_RESPONSE),
        ):
            resp = client.get(
                f"/api/v1/platform-admin/corporate/recurring-rides/account/{ACCOUNT_ID}"
            )
        assert resp.status_code == 200
