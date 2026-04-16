"""Tests for the Corporate Shift-Based Ride Scheduling feature.

Service layer (async, mocked DB):
  1.  create_shift — creates with is_active=True
  2.  create_shift — 409 when active shift with same name exists
  3.  get_shift — 404 when not found
  4.  get_shift — returns shift when found
  5.  list_shifts — returns all shifts for account
  6.  list_shifts — filters by is_active=True
  7.  list_shifts — filters by is_active=False
  8.  update_shift — 404 when not found
  9.  update_shift — 409 on name collision with another shift
  10. update_shift — partial update writes only supplied fields
  11. deactivate_shift — 404 when not found
  12. deactivate_shift — 409 when already inactive
  13. deactivate_shift — success sets is_active=False
  14. reactivate_shift — 404 when not found
  15. reactivate_shift — 409 when already active
  16. reactivate_shift — success sets is_active=True
  17. delete_shift — 404 when not found
  18. delete_shift — success deletes shift
  19. assign_member — 404 when shift not found
  20. assign_member — 409 when member already has active assignment
  21. assign_member — success creates assignment
  22. get_assignment — 404 when not found
  23. get_assignment — returns assignment when found
  24. update_assignment — 404 when not found
  25. update_assignment — partial update writes only supplied fields
  26. remove_assignment — 404 when not found
  27. remove_assignment — success deletes assignment
  28. list_shift_members — 404 when shift not found
  29. list_shift_members — returns all members
  30. list_shift_members — filters by is_active
  31. get_member_shifts — returns assignments for member in account
  32. get_shift_summary — 404 when not found
  33. get_shift_summary — returns correct member counts
  34. list_all_platform — returns all shifts without account filter
  35. list_all_platform — filters by account_id

Schema validation:
  36. ShiftCreate — name, work_location_name, times required
  37. ShiftCreate — optional fields default correctly
  38. ShiftUpdate — all fields optional
  39. AssignmentCreate — member_id required; defaults correct
  40. AssignmentUpdate — all fields optional
  41. ShiftResponse — from_attributes construction
  42. AssignmentResponse — from_attributes construction
  43. ShiftSummaryResponse — construction

API layer (service functions patched):
  44. GET list — 200 member can list shifts
  45. GET list — 404 when no corporate account
  46. GET my-assignments — 200 member can view own assignments
  47. GET get — 200 member can view shift
  48. GET get — 404 when shift not found
  49. GET summary — 200 member can view shift summary
  50. POST create — 201 admin can create shift
  51. POST create — 403 non-admin cannot create
  52. POST create — 409 duplicate name
  53. PATCH update — 200 admin can update
  54. PATCH update — 403 non-admin cannot update
  55. POST deactivate — 200 admin can deactivate
  56. POST deactivate — 409 already inactive
  57. POST reactivate — 200 admin can reactivate
  58. POST reactivate — 409 already active
  59. DELETE shift — 204 admin can delete
  60. DELETE shift — 403 non-admin cannot delete
  61. POST assign — 201 admin can assign member
  62. POST assign — 403 non-admin cannot assign
  63. POST assign — 409 duplicate assignment
  64. GET members — 200 admin can list shift members
  65. GET members — 403 non-admin cannot list
  66. PATCH assignment — 200 admin can update assignment
  67. DELETE assignment — 204 admin can remove assignment
  68. GET platform all — 200 platform-admin list all shifts
  69. GET platform account — 200 platform-admin list account shifts
"""

from __future__ import annotations

from datetime import datetime, time, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.models.corporate_shift import CorporateShift, CorporateShiftAssignment
from app.schemas.corporate_shift import (
    AssignmentCreate,
    AssignmentListResponse,
    AssignmentResponse,
    AssignmentUpdate,
    ShiftCreate,
    ShiftListResponse,
    ShiftResponse,
    ShiftSummaryResponse,
    ShiftUpdate,
)
from app.services.corporate_shift import (
    assign_member,
    create_shift,
    deactivate_shift,
    delete_shift,
    get_assignment,
    get_member_shifts,
    get_shift,
    get_shift_summary,
    list_all_platform,
    list_shift_members,
    list_shifts,
    reactivate_shift,
    remove_assignment,
    update_assignment,
    update_shift,
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

_SERVICE = "app.services.corporate_shift"
_ROUTER = "app.api.v1.corporate_shifts"

_NOW = datetime(2026, 4, 16, 9, 0, 0, tzinfo=timezone.utc)
_START_TIME = time(6, 0)
_END_TIME = time(14, 0)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_shift(
    shift_id: int = SHIFT_ID,
    account_id: int = ACCOUNT_ID,
    name: str = "Morning Shift",
    description: str | None = None,
    work_location_name: str = "Main Plant",
    shift_start_time: time = _START_TIME,
    shift_end_time: time = _END_TIME,
    days_of_week: list | None = None,
    is_active: bool = True,
    created_by_id: int | None = ADMIN_ID,
) -> CorporateShift:
    """Build a minimal CorporateShift instance for testing."""
    s = CorporateShift()
    s.id = shift_id
    s.account_id = account_id
    s.name = name
    s.description = description
    s.work_location_name = work_location_name
    s.work_address_line1 = None
    s.work_address_line2 = None
    s.work_city = None
    s.work_state = None
    s.work_country = None
    s.work_postal_code = None
    s.work_latitude = None
    s.work_longitude = None
    s.shift_start_time = shift_start_time
    s.shift_end_time = shift_end_time
    s.days_of_week = days_of_week if days_of_week is not None else [0, 1, 2, 3, 4]
    s.is_active = is_active
    s.created_by_id = created_by_id
    s.created_at = _NOW
    s.updated_at = _NOW
    return s


def _make_assignment(
    assignment_id: int = ASSIGNMENT_ID,
    shift_id: int = SHIFT_ID,
    member_id: int = MEMBER_ID,
    is_active: bool = True,
    auto_request_rides: bool = False,
    advance_booking_minutes: int = 60,
    assigned_by_id: int | None = ADMIN_ID,
    notes: str | None = None,
) -> CorporateShiftAssignment:
    """Build a minimal CorporateShiftAssignment instance for testing."""
    a = CorporateShiftAssignment()
    a.id = assignment_id
    a.shift_id = shift_id
    a.member_id = member_id
    a.pickup_address_line1 = None
    a.pickup_address_line2 = None
    a.pickup_city = None
    a.pickup_state = None
    a.pickup_country = None
    a.pickup_postal_code = None
    a.pickup_latitude = None
    a.pickup_longitude = None
    a.auto_request_rides = auto_request_rides
    a.advance_booking_minutes = advance_booking_minutes
    a.is_active = is_active
    a.assigned_by_id = assigned_by_id
    a.notes = notes
    a.created_at = _NOW
    a.updated_at = _NOW
    return a


def _make_shift_response(
    shift_id: int = SHIFT_ID,
    account_id: int = ACCOUNT_ID,
    name: str = "Morning Shift",
    is_active: bool = True,
) -> ShiftResponse:
    return ShiftResponse(
        id=shift_id,
        account_id=account_id,
        name=name,
        description=None,
        work_location_name="Main Plant",
        work_address_line1=None,
        work_address_line2=None,
        work_city=None,
        work_state=None,
        work_country=None,
        work_postal_code=None,
        work_latitude=None,
        work_longitude=None,
        shift_start_time=_START_TIME,
        shift_end_time=_END_TIME,
        days_of_week=[0, 1, 2, 3, 4],
        is_active=is_active,
        created_by_id=ADMIN_ID,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _make_assignment_response(
    assignment_id: int = ASSIGNMENT_ID,
    shift_id: int = SHIFT_ID,
    member_id: int = MEMBER_ID,
    is_active: bool = True,
    auto_request_rides: bool = False,
) -> AssignmentResponse:
    return AssignmentResponse(
        id=assignment_id,
        shift_id=shift_id,
        member_id=member_id,
        pickup_address_line1=None,
        pickup_address_line2=None,
        pickup_city=None,
        pickup_state=None,
        pickup_country=None,
        pickup_postal_code=None,
        pickup_latitude=None,
        pickup_longitude=None,
        auto_request_rides=auto_request_rides,
        advance_booking_minutes=60,
        is_active=is_active,
        assigned_by_id=ADMIN_ID,
        notes=None,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _scalar_result(value) -> MagicMock:
    res = MagicMock()
    res.scalar_one_or_none.return_value = value
    return res


def _scalars_all_result(values: list) -> MagicMock:
    scalars = MagicMock()
    scalars.all.return_value = values
    res = MagicMock()
    res.scalars.return_value = scalars
    return res


def _mock_user(user_id: int = USER_ID) -> MagicMock:
    u = MagicMock()
    u.id = user_id
    return u


# ---------------------------------------------------------------------------
# 1. create_shift — creates with is_active=True
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_create_shift_is_active():
    db = AsyncMock()
    added = []
    db.add = lambda x: added.append(x)

    async def _fake_refresh(obj):
        obj.id = SHIFT_ID
        obj.work_latitude = None
        obj.work_longitude = None
        obj.created_at = _NOW
        obj.updated_at = _NOW

    db.refresh = _fake_refresh
    db.execute.return_value = _scalar_result(None)  # no duplicate

    data = ShiftCreate(
        name="Morning Shift",
        work_location_name="Main Plant",
        shift_start_time=_START_TIME,
        shift_end_time=_END_TIME,
    )
    result = await create_shift(db, ACCOUNT_ID, ADMIN_ID, data)

    assert len(added) == 1
    assert added[0].is_active is True
    assert result.id == SHIFT_ID


# ---------------------------------------------------------------------------
# 2. create_shift — 409 when active shift with same name exists
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_create_shift_409_duplicate_name():
    db = AsyncMock()
    existing_shift = _make_shift()
    db.execute.return_value = _scalar_result(existing_shift)

    data = ShiftCreate(
        name="Morning Shift",
        work_location_name="Main Plant",
        shift_start_time=_START_TIME,
        shift_end_time=_END_TIME,
    )
    with pytest.raises(HTTPException) as exc:
        await create_shift(db, ACCOUNT_ID, ADMIN_ID, data)
    assert exc.value.status_code == 409
    assert "name" in exc.value.detail.lower()


# ---------------------------------------------------------------------------
# 3. get_shift — 404 when not found
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_shift_404_when_not_found():
    db = AsyncMock()
    db.execute.return_value = _scalar_result(None)

    with pytest.raises(HTTPException) as exc:
        await get_shift(db, SHIFT_ID, ACCOUNT_ID)
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# 4. get_shift — returns shift when found
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_shift_returns_shift():
    db = AsyncMock()
    shift = _make_shift()
    db.execute.return_value = _scalar_result(shift)

    result = await get_shift(db, SHIFT_ID, ACCOUNT_ID)

    assert result.id == SHIFT_ID
    assert result.name == "Morning Shift"
    assert result.is_active is True


# ---------------------------------------------------------------------------
# 5. list_shifts — returns all shifts for account
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_list_shifts_returns_all():
    db = AsyncMock()
    s1 = _make_shift(shift_id=1, name="Morning Shift")
    s2 = _make_shift(shift_id=2, name="Night Shift", is_active=False)
    db.execute.return_value = _scalars_all_result([s1, s2])

    result = await list_shifts(db, ACCOUNT_ID)

    assert result.total == 2
    assert len(result.items) == 2


# ---------------------------------------------------------------------------
# 6. list_shifts — filters by is_active=True
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_list_shifts_filters_active():
    db = AsyncMock()
    s1 = _make_shift(shift_id=1, name="Morning Shift", is_active=True)
    db.execute.return_value = _scalars_all_result([s1])

    result = await list_shifts(db, ACCOUNT_ID, is_active=True)

    assert result.total == 1
    assert result.items[0].is_active is True


# ---------------------------------------------------------------------------
# 7. list_shifts — filters by is_active=False
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_list_shifts_filters_inactive():
    db = AsyncMock()
    s1 = _make_shift(shift_id=2, name="Night Shift", is_active=False)
    db.execute.return_value = _scalars_all_result([s1])

    result = await list_shifts(db, ACCOUNT_ID, is_active=False)

    assert result.total == 1
    assert result.items[0].is_active is False


# ---------------------------------------------------------------------------
# 8. update_shift — 404 when not found
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_update_shift_404_when_not_found():
    db = AsyncMock()
    db.execute.return_value = _scalar_result(None)

    data = ShiftUpdate(name="New Name")
    with pytest.raises(HTTPException) as exc:
        await update_shift(db, SHIFT_ID, ACCOUNT_ID, data)
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# 9. update_shift — 409 on name collision with another shift
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_update_shift_409_name_collision():
    db = AsyncMock()
    existing_shift = _make_shift(name="Morning Shift")
    colliding_shift = _make_shift(shift_id=99, name="Afternoon Shift")

    db.execute.side_effect = [
        _scalar_result(existing_shift),  # fetch shift
        _scalar_result(colliding_shift),  # name collision check
    ]

    data = ShiftUpdate(name="Afternoon Shift")
    with pytest.raises(HTTPException) as exc:
        await update_shift(db, SHIFT_ID, ACCOUNT_ID, data)
    assert exc.value.status_code == 409


# ---------------------------------------------------------------------------
# 10. update_shift — partial update writes only supplied fields
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_update_shift_partial_update():
    db = AsyncMock()
    shift = _make_shift(description=None)
    db.execute.return_value = _scalar_result(shift)
    db.refresh = AsyncMock()

    data = ShiftUpdate(description="Updated description")
    await update_shift(db, SHIFT_ID, ACCOUNT_ID, data)

    assert shift.description == "Updated description"
    assert shift.name == "Morning Shift"  # unchanged


# ---------------------------------------------------------------------------
# 11. deactivate_shift — 404 when not found
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_deactivate_shift_404_when_not_found():
    db = AsyncMock()
    db.execute.return_value = _scalar_result(None)

    with pytest.raises(HTTPException) as exc:
        await deactivate_shift(db, SHIFT_ID, ACCOUNT_ID)
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# 12. deactivate_shift — 409 when already inactive
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_deactivate_shift_409_already_inactive():
    db = AsyncMock()
    shift = _make_shift(is_active=False)
    db.execute.return_value = _scalar_result(shift)

    with pytest.raises(HTTPException) as exc:
        await deactivate_shift(db, SHIFT_ID, ACCOUNT_ID)
    assert exc.value.status_code == 409
    assert "inactive" in exc.value.detail.lower()


# ---------------------------------------------------------------------------
# 13. deactivate_shift — success sets is_active=False
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_deactivate_shift_success():
    db = AsyncMock()
    shift = _make_shift(is_active=True)
    db.execute.return_value = _scalar_result(shift)
    db.refresh = AsyncMock()

    result = await deactivate_shift(db, SHIFT_ID, ACCOUNT_ID)

    assert shift.is_active is False


# ---------------------------------------------------------------------------
# 14. reactivate_shift — 404 when not found
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_reactivate_shift_404_when_not_found():
    db = AsyncMock()
    db.execute.return_value = _scalar_result(None)

    with pytest.raises(HTTPException) as exc:
        await reactivate_shift(db, SHIFT_ID, ACCOUNT_ID)
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# 15. reactivate_shift — 409 when already active
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_reactivate_shift_409_already_active():
    db = AsyncMock()
    shift = _make_shift(is_active=True)
    db.execute.return_value = _scalar_result(shift)

    with pytest.raises(HTTPException) as exc:
        await reactivate_shift(db, SHIFT_ID, ACCOUNT_ID)
    assert exc.value.status_code == 409
    assert "active" in exc.value.detail.lower()


# ---------------------------------------------------------------------------
# 16. reactivate_shift — success sets is_active=True
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_reactivate_shift_success():
    db = AsyncMock()
    shift = _make_shift(is_active=False)
    db.execute.return_value = _scalar_result(shift)
    db.refresh = AsyncMock()

    result = await reactivate_shift(db, SHIFT_ID, ACCOUNT_ID)

    assert shift.is_active is True


# ---------------------------------------------------------------------------
# 17. delete_shift — 404 when not found
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_delete_shift_404_when_not_found():
    db = AsyncMock()
    db.execute.return_value = _scalar_result(None)

    with pytest.raises(HTTPException) as exc:
        await delete_shift(db, SHIFT_ID, ACCOUNT_ID)
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# 18. delete_shift — success deletes shift
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_delete_shift_success():
    db = AsyncMock()
    shift = _make_shift()
    db.execute.return_value = _scalar_result(shift)

    await delete_shift(db, SHIFT_ID, ACCOUNT_ID)

    db.delete.assert_called_once_with(shift)
    db.commit.assert_called_once()


# ---------------------------------------------------------------------------
# 19. assign_member — 404 when shift not found
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_assign_member_404_shift_not_found():
    db = AsyncMock()
    db.execute.return_value = _scalar_result(None)

    data = AssignmentCreate(member_id=MEMBER_ID)
    with pytest.raises(HTTPException) as exc:
        await assign_member(db, SHIFT_ID, ACCOUNT_ID, data, ADMIN_ID)
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# 20. assign_member — 409 when member already has active assignment
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_assign_member_409_duplicate_assignment():
    db = AsyncMock()
    shift = _make_shift()
    existing_assignment = _make_assignment()

    db.execute.side_effect = [
        _scalar_result(shift),            # fetch shift
        _scalar_result(existing_assignment),  # duplicate check
    ]

    data = AssignmentCreate(member_id=MEMBER_ID)
    with pytest.raises(HTTPException) as exc:
        await assign_member(db, SHIFT_ID, ACCOUNT_ID, data, ADMIN_ID)
    assert exc.value.status_code == 409
    assert "active assignment" in exc.value.detail.lower()


# ---------------------------------------------------------------------------
# 21. assign_member — success creates assignment
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_assign_member_success():
    db = AsyncMock()
    shift = _make_shift()
    added = []
    db.add = lambda x: added.append(x)

    async def _fake_refresh(obj):
        obj.id = ASSIGNMENT_ID
        obj.pickup_latitude = None
        obj.pickup_longitude = None
        obj.created_at = _NOW
        obj.updated_at = _NOW

    db.refresh = _fake_refresh
    db.execute.side_effect = [
        _scalar_result(shift),   # fetch shift
        _scalar_result(None),    # no duplicate
    ]

    data = AssignmentCreate(
        member_id=MEMBER_ID,
        pickup_city="Chicago",
        auto_request_rides=True,
        advance_booking_minutes=30,
    )
    result = await assign_member(db, SHIFT_ID, ACCOUNT_ID, data, ADMIN_ID)

    assert len(added) == 1
    assert added[0].member_id == MEMBER_ID
    assert added[0].auto_request_rides is True
    assert added[0].advance_booking_minutes == 30
    assert result.id == ASSIGNMENT_ID


# ---------------------------------------------------------------------------
# 22. get_assignment — 404 when not found
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_assignment_404_when_not_found():
    db = AsyncMock()
    db.execute.return_value = _scalar_result(None)

    with pytest.raises(HTTPException) as exc:
        await get_assignment(db, ASSIGNMENT_ID)
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# 23. get_assignment — returns assignment when found
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_assignment_returns_assignment():
    db = AsyncMock()
    assignment = _make_assignment()
    db.execute.return_value = _scalar_result(assignment)

    result = await get_assignment(db, ASSIGNMENT_ID)

    assert result.id == ASSIGNMENT_ID
    assert result.member_id == MEMBER_ID
    assert result.shift_id == SHIFT_ID


# ---------------------------------------------------------------------------
# 24. update_assignment — 404 when not found
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_update_assignment_404_when_not_found():
    db = AsyncMock()
    db.execute.return_value = _scalar_result(None)

    data = AssignmentUpdate(notes="Updated notes")
    with pytest.raises(HTTPException) as exc:
        await update_assignment(db, ASSIGNMENT_ID, data)
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# 25. update_assignment — partial update writes only supplied fields
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_update_assignment_partial_update():
    db = AsyncMock()
    assignment = _make_assignment(notes=None, advance_booking_minutes=60)
    db.execute.return_value = _scalar_result(assignment)
    db.refresh = AsyncMock()

    data = AssignmentUpdate(notes="Park entrance", advance_booking_minutes=45)
    await update_assignment(db, ASSIGNMENT_ID, data)

    assert assignment.notes == "Park entrance"
    assert assignment.advance_booking_minutes == 45
    assert assignment.auto_request_rides is False  # unchanged


# ---------------------------------------------------------------------------
# 26. remove_assignment — 404 when not found
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_remove_assignment_404_when_not_found():
    db = AsyncMock()
    db.execute.return_value = _scalar_result(None)

    with pytest.raises(HTTPException) as exc:
        await remove_assignment(db, ASSIGNMENT_ID)
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# 27. remove_assignment — success deletes assignment
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_remove_assignment_success():
    db = AsyncMock()
    assignment = _make_assignment()
    db.execute.return_value = _scalar_result(assignment)

    await remove_assignment(db, ASSIGNMENT_ID)

    db.delete.assert_called_once_with(assignment)
    db.commit.assert_called_once()


# ---------------------------------------------------------------------------
# 28. list_shift_members — 404 when shift not found
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_list_shift_members_404_when_shift_not_found():
    db = AsyncMock()
    db.execute.side_effect = [
        _scalar_result(None),  # shift not found
    ]

    with pytest.raises(HTTPException) as exc:
        await list_shift_members(db, SHIFT_ID, ACCOUNT_ID)
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# 29. list_shift_members — returns all members
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_list_shift_members_returns_all():
    db = AsyncMock()
    shift = _make_shift()
    a1 = _make_assignment(assignment_id=1, member_id=3, is_active=True)
    a2 = _make_assignment(assignment_id=2, member_id=4, is_active=False)

    db.execute.side_effect = [
        _scalar_result(shift),
        _scalars_all_result([a1, a2]),
    ]

    result = await list_shift_members(db, SHIFT_ID, ACCOUNT_ID)

    assert result.total == 2
    assert len(result.items) == 2


# ---------------------------------------------------------------------------
# 30. list_shift_members — filters by is_active
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_list_shift_members_filters_active():
    db = AsyncMock()
    shift = _make_shift()
    a1 = _make_assignment(assignment_id=1, member_id=3, is_active=True)

    db.execute.side_effect = [
        _scalar_result(shift),
        _scalars_all_result([a1]),
    ]

    result = await list_shift_members(db, SHIFT_ID, ACCOUNT_ID, is_active=True)

    assert result.total == 1
    assert result.items[0].is_active is True


# ---------------------------------------------------------------------------
# 31. get_member_shifts — returns assignments for member in account
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_member_shifts_returns_assignments():
    db = AsyncMock()
    a1 = _make_assignment(assignment_id=1, member_id=MEMBER_ID, shift_id=SHIFT_ID)
    db.execute.return_value = _scalars_all_result([a1])

    result = await get_member_shifts(db, ACCOUNT_ID, MEMBER_ID)

    assert result.total == 1
    assert result.items[0].member_id == MEMBER_ID


# ---------------------------------------------------------------------------
# 32. get_shift_summary — 404 when not found
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_shift_summary_404_when_not_found():
    db = AsyncMock()
    db.execute.return_value = _scalar_result(None)

    with pytest.raises(HTTPException) as exc:
        await get_shift_summary(db, SHIFT_ID, ACCOUNT_ID)
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# 33. get_shift_summary — returns correct member counts
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_shift_summary_correct_counts():
    db = AsyncMock()
    shift = _make_shift()
    a1 = _make_assignment(assignment_id=1, member_id=3, is_active=True, auto_request_rides=True)
    a2 = _make_assignment(assignment_id=2, member_id=4, is_active=True, auto_request_rides=False)
    a3 = _make_assignment(assignment_id=3, member_id=5, is_active=False, auto_request_rides=False)

    db.execute.side_effect = [
        _scalar_result(shift),
        _scalars_all_result([a1, a2, a3]),
    ]

    result = await get_shift_summary(db, SHIFT_ID, ACCOUNT_ID)

    assert result.shift_id == SHIFT_ID
    assert result.name == "Morning Shift"
    assert result.is_active is True
    assert result.total_members == 3
    assert result.active_members == 2
    assert result.inactive_members == 1
    assert result.members_with_auto_request == 1


# ---------------------------------------------------------------------------
# 34. list_all_platform — returns all shifts without account filter
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_list_all_platform_no_filter():
    db = AsyncMock()
    s1 = _make_shift(shift_id=1, account_id=10)
    s2 = _make_shift(shift_id=2, account_id=20)
    db.execute.return_value = _scalars_all_result([s1, s2])

    result = await list_all_platform(db)

    assert result.total == 2


# ---------------------------------------------------------------------------
# 35. list_all_platform — filters by account_id
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_list_all_platform_filters_by_account():
    db = AsyncMock()
    s1 = _make_shift(shift_id=1, account_id=10)
    db.execute.return_value = _scalars_all_result([s1])

    result = await list_all_platform(db, account_id=10)

    assert result.total == 1
    assert result.items[0].account_id == 10


# ---------------------------------------------------------------------------
# Schema validation tests
# ---------------------------------------------------------------------------


def test_shift_create_required_fields():
    """36. ShiftCreate — name, work_location_name, times required."""
    with pytest.raises(ValidationError):
        ShiftCreate()

    with pytest.raises(ValidationError):
        ShiftCreate(
            name="Morning Shift",
            work_location_name="Main Plant",
            # missing shift_start_time and shift_end_time
        )

    valid = ShiftCreate(
        name="Morning Shift",
        work_location_name="Main Plant",
        shift_start_time=_START_TIME,
        shift_end_time=_END_TIME,
    )
    assert valid.name == "Morning Shift"


def test_shift_create_optional_defaults():
    """37. ShiftCreate — optional fields default correctly."""
    data = ShiftCreate(
        name="Morning Shift",
        work_location_name="Main Plant",
        shift_start_time=_START_TIME,
        shift_end_time=_END_TIME,
    )
    assert data.description is None
    assert data.days_of_week == []
    assert data.work_city is None
    assert data.work_country is None


def test_shift_update_all_optional():
    """38. ShiftUpdate — all fields optional."""
    data = ShiftUpdate()
    assert data.name is None
    assert data.work_location_name is None
    assert data.shift_start_time is None
    assert data.shift_end_time is None
    assert data.days_of_week is None


def test_assignment_create_required_and_defaults():
    """39. AssignmentCreate — member_id required; defaults correct."""
    with pytest.raises(ValidationError):
        AssignmentCreate()

    valid = AssignmentCreate(member_id=MEMBER_ID)
    assert valid.member_id == MEMBER_ID
    assert valid.auto_request_rides is False
    assert valid.advance_booking_minutes == 60
    assert valid.notes is None


def test_assignment_update_all_optional():
    """40. AssignmentUpdate — all fields optional."""
    data = AssignmentUpdate()
    assert data.pickup_city is None
    assert data.auto_request_rides is None
    assert data.advance_booking_minutes is None
    assert data.is_active is None


def test_shift_response_from_attributes():
    """41. ShiftResponse — from_attributes construction."""
    resp = _make_shift_response()
    assert resp.id == SHIFT_ID
    assert resp.account_id == ACCOUNT_ID
    assert resp.name == "Morning Shift"
    assert resp.is_active is True
    assert resp.shift_start_time == _START_TIME
    assert resp.shift_end_time == _END_TIME
    assert isinstance(resp.created_at, datetime)


def test_assignment_response_from_attributes():
    """42. AssignmentResponse — from_attributes construction."""
    resp = _make_assignment_response()
    assert resp.id == ASSIGNMENT_ID
    assert resp.shift_id == SHIFT_ID
    assert resp.member_id == MEMBER_ID
    assert resp.is_active is True
    assert resp.auto_request_rides is False
    assert resp.advance_booking_minutes == 60
    assert isinstance(resp.created_at, datetime)


def test_shift_summary_response_construction():
    """43. ShiftSummaryResponse — construction."""
    summary = ShiftSummaryResponse(
        shift_id=SHIFT_ID,
        name="Morning Shift",
        is_active=True,
        total_members=10,
        active_members=8,
        inactive_members=2,
        members_with_auto_request=3,
    )
    assert summary.shift_id == SHIFT_ID
    assert summary.total_members == 10
    assert summary.active_members == 8
    assert summary.members_with_auto_request == 3


# ---------------------------------------------------------------------------
# API layer tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_api_list_shifts_200():
    """44. GET list — 200 member can list shifts."""
    from app.api.v1.corporate_shifts import list_my_shifts

    user = _mock_user(MEMBER_ID)
    db = AsyncMock()
    mock_resp = ShiftListResponse(total=1, items=[_make_shift_response()])

    with (
        patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)),
        patch(f"{_ROUTER}.list_shifts", new=AsyncMock(return_value=mock_resp)),
    ):
        result = await list_my_shifts(is_active=None, user=user, db=db)

    assert result.total == 1
    assert len(result.items) == 1


@pytest.mark.asyncio
async def test_api_list_shifts_404_no_account():
    """45. GET list — 404 when no corporate account."""
    from app.api.v1.corporate_shifts import list_my_shifts

    user = _mock_user(MEMBER_ID)
    db = AsyncMock()

    with patch(
        f"{_ROUTER}._resolve_account_id",
        new=AsyncMock(side_effect=HTTPException(status_code=404, detail="No account")),
    ):
        with pytest.raises(HTTPException) as exc:
            await list_my_shifts(is_active=None, user=user, db=db)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_api_get_my_assignments_200():
    """46. GET my-assignments — 200 member can view own assignments."""
    from app.api.v1.corporate_shifts import get_my_shift_assignments

    user = _mock_user(MEMBER_ID)
    db = AsyncMock()
    mock_resp = AssignmentListResponse(total=1, items=[_make_assignment_response()])

    with (
        patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)),
        patch(f"{_ROUTER}.get_member_shifts", new=AsyncMock(return_value=mock_resp)),
    ):
        result = await get_my_shift_assignments(is_active=None, user=user, db=db)

    assert result.total == 1


@pytest.mark.asyncio
async def test_api_get_shift_200():
    """47. GET get — 200 member can view shift."""
    from app.api.v1.corporate_shifts import get_my_shift

    user = _mock_user(MEMBER_ID)
    db = AsyncMock()
    mock_resp = _make_shift_response()

    with (
        patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)),
        patch(f"{_ROUTER}.get_shift", new=AsyncMock(return_value=mock_resp)),
    ):
        result = await get_my_shift(shift_id=SHIFT_ID, user=user, db=db)

    assert result.id == SHIFT_ID


@pytest.mark.asyncio
async def test_api_get_shift_404():
    """48. GET get — 404 when shift not found."""
    from app.api.v1.corporate_shifts import get_my_shift

    user = _mock_user(MEMBER_ID)
    db = AsyncMock()

    with (
        patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)),
        patch(
            f"{_ROUTER}.get_shift",
            new=AsyncMock(side_effect=HTTPException(status_code=404, detail="Not found")),
        ),
    ):
        with pytest.raises(HTTPException) as exc:
            await get_my_shift(shift_id=SHIFT_ID, user=user, db=db)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_api_get_shift_summary_200():
    """49. GET summary — 200 member can view shift summary."""
    from app.api.v1.corporate_shifts import get_my_shift_summary

    user = _mock_user(MEMBER_ID)
    db = AsyncMock()
    mock_resp = ShiftSummaryResponse(
        shift_id=SHIFT_ID,
        name="Morning Shift",
        is_active=True,
        total_members=5,
        active_members=4,
        inactive_members=1,
        members_with_auto_request=2,
    )

    with (
        patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)),
        patch(f"{_ROUTER}.get_shift_summary", new=AsyncMock(return_value=mock_resp)),
    ):
        result = await get_my_shift_summary(shift_id=SHIFT_ID, user=user, db=db)

    assert result.shift_id == SHIFT_ID
    assert result.total_members == 5


@pytest.mark.asyncio
async def test_api_create_shift_201():
    """50. POST create — 201 admin can create shift."""
    from app.api.v1.corporate_shifts import create_my_shift

    user = _mock_user(ADMIN_ID)
    db = AsyncMock()
    data = ShiftCreate(
        name="Morning Shift",
        work_location_name="Main Plant",
        shift_start_time=_START_TIME,
        shift_end_time=_END_TIME,
    )
    mock_resp = _make_shift_response()

    with (
        patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)),
        patch(f"{_ROUTER}._require_account_admin", new=AsyncMock(return_value=None)),
        patch(f"{_ROUTER}.create_shift", new=AsyncMock(return_value=mock_resp)),
    ):
        result = await create_my_shift(data=data, user=user, db=db)

    assert result.id == SHIFT_ID
    assert result.is_active is True


@pytest.mark.asyncio
async def test_api_create_shift_403_non_admin():
    """51. POST create — 403 non-admin cannot create."""
    from app.api.v1.corporate_shifts import create_my_shift

    user = _mock_user(MEMBER_ID)
    db = AsyncMock()
    data = ShiftCreate(
        name="Morning Shift",
        work_location_name="Main Plant",
        shift_start_time=_START_TIME,
        shift_end_time=_END_TIME,
    )

    with (
        patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)),
        patch(
            f"{_ROUTER}._require_account_admin",
            new=AsyncMock(side_effect=HTTPException(status_code=403, detail="Forbidden")),
        ),
    ):
        with pytest.raises(HTTPException) as exc:
            await create_my_shift(data=data, user=user, db=db)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_api_create_shift_409_duplicate():
    """52. POST create — 409 duplicate name."""
    from app.api.v1.corporate_shifts import create_my_shift

    user = _mock_user(ADMIN_ID)
    db = AsyncMock()
    data = ShiftCreate(
        name="Morning Shift",
        work_location_name="Main Plant",
        shift_start_time=_START_TIME,
        shift_end_time=_END_TIME,
    )

    with (
        patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)),
        patch(f"{_ROUTER}._require_account_admin", new=AsyncMock(return_value=None)),
        patch(
            f"{_ROUTER}.create_shift",
            new=AsyncMock(
                side_effect=HTTPException(
                    status_code=409,
                    detail="An active shift with this name already exists.",
                )
            ),
        ),
    ):
        with pytest.raises(HTTPException) as exc:
            await create_my_shift(data=data, user=user, db=db)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_api_update_shift_200():
    """53. PATCH update — 200 admin can update."""
    from app.api.v1.corporate_shifts import update_my_shift

    user = _mock_user(ADMIN_ID)
    db = AsyncMock()
    data = ShiftUpdate(description="Updated")
    mock_resp = _make_shift_response()

    with (
        patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)),
        patch(f"{_ROUTER}._require_account_admin", new=AsyncMock(return_value=None)),
        patch(f"{_ROUTER}.update_shift", new=AsyncMock(return_value=mock_resp)),
    ):
        result = await update_my_shift(shift_id=SHIFT_ID, data=data, user=user, db=db)

    assert result.id == SHIFT_ID


@pytest.mark.asyncio
async def test_api_update_shift_403_non_admin():
    """54. PATCH update — 403 non-admin cannot update."""
    from app.api.v1.corporate_shifts import update_my_shift

    user = _mock_user(MEMBER_ID)
    db = AsyncMock()
    data = ShiftUpdate(description="Updated")

    with (
        patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)),
        patch(
            f"{_ROUTER}._require_account_admin",
            new=AsyncMock(side_effect=HTTPException(status_code=403, detail="Forbidden")),
        ),
    ):
        with pytest.raises(HTTPException) as exc:
            await update_my_shift(shift_id=SHIFT_ID, data=data, user=user, db=db)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_api_deactivate_shift_200():
    """55. POST deactivate — 200 admin can deactivate."""
    from app.api.v1.corporate_shifts import deactivate_my_shift

    user = _mock_user(ADMIN_ID)
    db = AsyncMock()
    mock_resp = _make_shift_response(is_active=False)

    with (
        patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)),
        patch(f"{_ROUTER}._require_account_admin", new=AsyncMock(return_value=None)),
        patch(f"{_ROUTER}.deactivate_shift", new=AsyncMock(return_value=mock_resp)),
    ):
        result = await deactivate_my_shift(shift_id=SHIFT_ID, user=user, db=db)

    assert result.is_active is False


@pytest.mark.asyncio
async def test_api_deactivate_shift_409_already_inactive():
    """56. POST deactivate — 409 already inactive."""
    from app.api.v1.corporate_shifts import deactivate_my_shift

    user = _mock_user(ADMIN_ID)
    db = AsyncMock()

    with (
        patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)),
        patch(f"{_ROUTER}._require_account_admin", new=AsyncMock(return_value=None)),
        patch(
            f"{_ROUTER}.deactivate_shift",
            new=AsyncMock(
                side_effect=HTTPException(status_code=409, detail="Already inactive.")
            ),
        ),
    ):
        with pytest.raises(HTTPException) as exc:
            await deactivate_my_shift(shift_id=SHIFT_ID, user=user, db=db)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_api_reactivate_shift_200():
    """57. POST reactivate — 200 admin can reactivate."""
    from app.api.v1.corporate_shifts import reactivate_my_shift

    user = _mock_user(ADMIN_ID)
    db = AsyncMock()
    mock_resp = _make_shift_response(is_active=True)

    with (
        patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)),
        patch(f"{_ROUTER}._require_account_admin", new=AsyncMock(return_value=None)),
        patch(f"{_ROUTER}.reactivate_shift", new=AsyncMock(return_value=mock_resp)),
    ):
        result = await reactivate_my_shift(shift_id=SHIFT_ID, user=user, db=db)

    assert result.is_active is True


@pytest.mark.asyncio
async def test_api_reactivate_shift_409_already_active():
    """58. POST reactivate — 409 already active."""
    from app.api.v1.corporate_shifts import reactivate_my_shift

    user = _mock_user(ADMIN_ID)
    db = AsyncMock()

    with (
        patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)),
        patch(f"{_ROUTER}._require_account_admin", new=AsyncMock(return_value=None)),
        patch(
            f"{_ROUTER}.reactivate_shift",
            new=AsyncMock(
                side_effect=HTTPException(status_code=409, detail="Already active.")
            ),
        ),
    ):
        with pytest.raises(HTTPException) as exc:
            await reactivate_my_shift(shift_id=SHIFT_ID, user=user, db=db)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_api_delete_shift_204():
    """59. DELETE shift — 204 admin can delete."""
    from app.api.v1.corporate_shifts import delete_my_shift

    user = _mock_user(ADMIN_ID)
    db = AsyncMock()

    with (
        patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)),
        patch(f"{_ROUTER}._require_account_admin", new=AsyncMock(return_value=None)),
        patch(f"{_ROUTER}.delete_shift", new=AsyncMock(return_value=None)),
    ):
        result = await delete_my_shift(shift_id=SHIFT_ID, user=user, db=db)

    assert result is None


@pytest.mark.asyncio
async def test_api_delete_shift_403_non_admin():
    """60. DELETE shift — 403 non-admin cannot delete."""
    from app.api.v1.corporate_shifts import delete_my_shift

    user = _mock_user(MEMBER_ID)
    db = AsyncMock()

    with (
        patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)),
        patch(
            f"{_ROUTER}._require_account_admin",
            new=AsyncMock(side_effect=HTTPException(status_code=403, detail="Forbidden")),
        ),
    ):
        with pytest.raises(HTTPException) as exc:
            await delete_my_shift(shift_id=SHIFT_ID, user=user, db=db)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_api_assign_member_201():
    """61. POST assign — 201 admin can assign member."""
    from app.api.v1.corporate_shifts import assign_shift_member

    user = _mock_user(ADMIN_ID)
    db = AsyncMock()
    data = AssignmentCreate(member_id=MEMBER_ID)
    mock_resp = _make_assignment_response()

    with (
        patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)),
        patch(f"{_ROUTER}._require_account_admin", new=AsyncMock(return_value=None)),
        patch(f"{_ROUTER}.assign_member", new=AsyncMock(return_value=mock_resp)),
    ):
        result = await assign_shift_member(shift_id=SHIFT_ID, data=data, user=user, db=db)

    assert result.id == ASSIGNMENT_ID
    assert result.member_id == MEMBER_ID


@pytest.mark.asyncio
async def test_api_assign_member_403_non_admin():
    """62. POST assign — 403 non-admin cannot assign."""
    from app.api.v1.corporate_shifts import assign_shift_member

    user = _mock_user(MEMBER_ID)
    db = AsyncMock()
    data = AssignmentCreate(member_id=MEMBER_ID)

    with (
        patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)),
        patch(
            f"{_ROUTER}._require_account_admin",
            new=AsyncMock(side_effect=HTTPException(status_code=403, detail="Forbidden")),
        ),
    ):
        with pytest.raises(HTTPException) as exc:
            await assign_shift_member(shift_id=SHIFT_ID, data=data, user=user, db=db)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_api_assign_member_409_duplicate():
    """63. POST assign — 409 duplicate assignment."""
    from app.api.v1.corporate_shifts import assign_shift_member

    user = _mock_user(ADMIN_ID)
    db = AsyncMock()
    data = AssignmentCreate(member_id=MEMBER_ID)

    with (
        patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)),
        patch(f"{_ROUTER}._require_account_admin", new=AsyncMock(return_value=None)),
        patch(
            f"{_ROUTER}.assign_member",
            new=AsyncMock(
                side_effect=HTTPException(
                    status_code=409,
                    detail="Member already has an active assignment.",
                )
            ),
        ),
    ):
        with pytest.raises(HTTPException) as exc:
            await assign_shift_member(shift_id=SHIFT_ID, data=data, user=user, db=db)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_api_list_shift_members_200():
    """64. GET members — 200 admin can list shift members."""
    from app.api.v1.corporate_shifts import list_my_shift_members

    user = _mock_user(ADMIN_ID)
    db = AsyncMock()
    mock_resp = AssignmentListResponse(total=2, items=[
        _make_assignment_response(assignment_id=1, member_id=3),
        _make_assignment_response(assignment_id=2, member_id=4),
    ])

    with (
        patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)),
        patch(f"{_ROUTER}._require_account_admin", new=AsyncMock(return_value=None)),
        patch(f"{_ROUTER}.list_shift_members", new=AsyncMock(return_value=mock_resp)),
    ):
        result = await list_my_shift_members(shift_id=SHIFT_ID, is_active=None, user=user, db=db)

    assert result.total == 2
    assert len(result.items) == 2


@pytest.mark.asyncio
async def test_api_list_shift_members_403_non_admin():
    """65. GET members — 403 non-admin cannot list."""
    from app.api.v1.corporate_shifts import list_my_shift_members

    user = _mock_user(MEMBER_ID)
    db = AsyncMock()

    with (
        patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)),
        patch(
            f"{_ROUTER}._require_account_admin",
            new=AsyncMock(side_effect=HTTPException(status_code=403, detail="Forbidden")),
        ),
    ):
        with pytest.raises(HTTPException) as exc:
            await list_my_shift_members(shift_id=SHIFT_ID, is_active=None, user=user, db=db)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_api_update_assignment_200():
    """66. PATCH assignment — 200 admin can update assignment."""
    from app.api.v1.corporate_shifts import update_shift_assignment

    user = _mock_user(ADMIN_ID)
    db = AsyncMock()
    data = AssignmentUpdate(notes="Park at gate B")
    mock_resp = _make_assignment_response()

    with (
        patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)),
        patch(f"{_ROUTER}._require_account_admin", new=AsyncMock(return_value=None)),
        patch(f"{_ROUTER}.update_assignment", new=AsyncMock(return_value=mock_resp)),
    ):
        result = await update_shift_assignment(
            assignment_id=ASSIGNMENT_ID, data=data, user=user, db=db
        )

    assert result.id == ASSIGNMENT_ID


@pytest.mark.asyncio
async def test_api_remove_assignment_204():
    """67. DELETE assignment — 204 admin can remove assignment."""
    from app.api.v1.corporate_shifts import remove_shift_assignment

    user = _mock_user(ADMIN_ID)
    db = AsyncMock()

    with (
        patch(f"{_ROUTER}._resolve_account_id", new=AsyncMock(return_value=ACCOUNT_ID)),
        patch(f"{_ROUTER}._require_account_admin", new=AsyncMock(return_value=None)),
        patch(f"{_ROUTER}.remove_assignment", new=AsyncMock(return_value=None)),
    ):
        result = await remove_shift_assignment(
            assignment_id=ASSIGNMENT_ID, user=user, db=db
        )

    assert result is None


@pytest.mark.asyncio
async def test_api_platform_list_all_shifts_200():
    """68. GET platform all — 200 platform-admin list all shifts."""
    from app.api.v1.corporate_shifts import admin_list_all_shifts

    admin = _mock_user(USER_ID)
    db = AsyncMock()
    mock_resp = ShiftListResponse(total=3, items=[
        _make_shift_response(shift_id=1, account_id=10),
        _make_shift_response(shift_id=2, account_id=20),
        _make_shift_response(shift_id=3, account_id=30),
    ])

    with patch(f"{_ROUTER}.list_all_platform", new=AsyncMock(return_value=mock_resp)):
        result = await admin_list_all_shifts(account_id=None, _admin=admin, db=db)

    assert result.total == 3


@pytest.mark.asyncio
async def test_api_platform_list_account_shifts_200():
    """69. GET platform account — 200 platform-admin list account shifts."""
    from app.api.v1.corporate_shifts import admin_list_account_shifts

    admin = _mock_user(USER_ID)
    db = AsyncMock()
    mock_resp = ShiftListResponse(total=1, items=[_make_shift_response(account_id=ACCOUNT_ID)])

    with patch(f"{_ROUTER}.list_shifts", new=AsyncMock(return_value=mock_resp)):
        result = await admin_list_account_shifts(
            account_id=ACCOUNT_ID, is_active=None, _admin=admin, db=db
        )

    assert result.total == 1
    assert result.items[0].account_id == ACCOUNT_ID
