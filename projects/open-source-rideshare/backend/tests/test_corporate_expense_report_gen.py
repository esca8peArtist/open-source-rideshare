"""Tests for corporate expense report generation.

Service tests — member report:
  1.  get_member_expense_report — success, rides present, monthly period
  2.  get_member_expense_report — success, no rides
  3.  get_member_expense_report — success, annual period (month=None)
  4.  get_member_expense_report — non-member → 403
  5.  get_member_expense_report — bad year (< 2000) → 400
  6.  get_member_expense_report — bad year (> 2100) → 400
  7.  get_member_expense_report — bad month (0) → 400
  8.  get_member_expense_report — bad month (13) → 400
  9.  get_member_expense_report — totals computed correctly (multiple rides)
  10. get_member_expense_report — avg_per_ride is 0 when no rides
  11. get_member_expense_report — ride with actual_fare takes precedence over estimated_fare
  12. get_member_expense_report — ride with no actual_fare uses estimated_fare
  13. get_member_expense_report — trip_notes mapped to purpose field
  14. get_member_expense_report — ride status is a string in RideLineItem

Service tests — account report:
  15. get_account_expense_report — success, single member single dept
  16. get_account_expense_report — success, no rides
  17. get_account_expense_report — annual period (month=None)
  18. get_account_expense_report — member with no department → "Unassigned"
  19. get_account_expense_report — by_department sorted alphabetically
  20. get_account_expense_report — by_member sorted alphabetically by name
  21. get_account_expense_report — bad year → 400
  22. get_account_expense_report — bad month → 400
  23. get_account_expense_report — multiple members, totals correct
  24. get_account_expense_report — multiple departments, breakdowns correct

Service tests — CSV export:
  25. export_account_expense_csv — CSV has summary header rows
  26. export_account_expense_csv — CSV has By Member section header
  27. export_account_expense_csv — CSV has By Department section header
  28. export_account_expense_csv — member rows present in CSV
  29. export_account_expense_csv — department rows present in CSV
  30. export_account_expense_csv — no rides produces empty member/dept sections
  31. export_account_expense_csv — period_label in summary row
  32. export_account_expense_csv — bad year propagates 400

Schema tests:
  33. RideLineItem — valid construction
  34. RideLineItem — purpose can be None
  35. MemberExpenseReport — valid construction
  36. MemberExpenseReport — rides defaults to empty list
  37. DeptExpenseSummary — valid construction
  38. MemberExpenseSummary — valid construction
  39. AccountExpenseReport — valid construction
  40. AccountExpenseReport — by_department defaults to empty list
  41. AccountExpenseReport — by_member defaults to empty list

API layer tests (service patched):
  42. GET /corporate/members/me/expense-report → 200 member report
  43. GET /corporate/members/me/expense-report — no account → 404
  44. GET /corporate/members/me/expense-report — service 403 passthrough
  45. GET /admin/corporate/accounts/{id}/expense-report → 200 (corp admin)
  46. GET /admin/corporate/accounts/{id}/expense-report → 200 (platform admin)
  47. GET /admin/corporate/accounts/{id}/expense-report — non-admin → 403
  48. GET /admin/corporate/accounts/{id}/expense-report/csv → 200 (corp admin)
  49. GET /admin/corporate/accounts/{id}/expense-report/csv — non-admin → 403
  50. GET /admin/corporate/accounts/{id}/expense-report/csv → CSV content-disposition header
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.models.corporate import BusinessAccountMember, MemberRole
from app.schemas.corporate_expense_report_gen import (
    AccountExpenseReport,
    DeptExpenseSummary,
    MemberExpenseReport,
    MemberExpenseSummary,
    RideLineItem,
)
from app.services.corporate_expense_report_gen import (
    _effective_fare,
    _period_bounds,
    _period_label,
    _ride_to_line_item,
    export_account_expense_csv,
    get_account_expense_report,
    get_member_expense_report,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

NOW = datetime(2026, 4, 15, 12, 0, 0, tzinfo=timezone.utc)
ACCOUNT_ID = 1
ADMIN_ID = 10
MEMBER_ID = 20
OTHER_USER_ID = 30


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_member(user_id: int, role: MemberRole = MemberRole.MEMBER) -> BusinessAccountMember:
    m = MagicMock(spec=BusinessAccountMember)
    m.account_id = ACCOUNT_ID
    m.user_id = user_id
    m.role = role
    m.is_active = True
    return m


def _make_ride(
    ride_id: int = 1,
    rider_id: int = MEMBER_ID,
    account_id: int = ACCOUNT_ID,
    actual_fare: float | None = 25.00,
    estimated_fare: float = 20.00,
    status="completed",
    trip_notes: str | None = None,
    completed_at: datetime | None = None,
) -> MagicMock:
    r = MagicMock()
    r.id = ride_id
    r.rider_id = rider_id
    r.corporate_account_id = account_id
    r.actual_fare = actual_fare
    r.estimated_fare = estimated_fare
    r.status = status
    r.trip_notes = trip_notes
    r.completed_at = completed_at or NOW
    r.requested_at = NOW
    return r


def _make_user(user_id: int = MEMBER_ID, name: str = "Alice") -> MagicMock:
    u = MagicMock()
    u.id = user_id
    u.name = name
    return u


def _db_member(member):
    """Return mock execute that yields the given member."""
    r = MagicMock()
    r.scalar_one_or_none.return_value = member
    return r


def _db_no_member():
    r = MagicMock()
    r.scalar_one_or_none.return_value = None
    return r


def _db_rides(rides):
    r = MagicMock()
    r.scalars.return_value.all.return_value = rides
    return r


def _db_ride_user_pairs(pairs):
    """Return mock execute result for a (Ride, User) join query."""
    r = MagicMock()
    r.all.return_value = pairs
    return r


def _db_dept_members(pairs):
    """Return mock execute result for dept member rows."""
    r = MagicMock()
    r.all.return_value = pairs
    return r


# ---------------------------------------------------------------------------
# Internal helper unit tests
# ---------------------------------------------------------------------------


def test_period_label_monthly():
    assert _period_label(2026, 4) == "2026-04"


def test_period_label_annual():
    assert _period_label(2026, None) == "2026"


def test_period_bounds_monthly():
    start, end = _period_bounds(2026, 4)
    assert start == datetime(2026, 4, 1, 0, 0, 0, tzinfo=timezone.utc)
    assert end == datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


def test_period_bounds_annual():
    start, end = _period_bounds(2026, None)
    assert start == datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    assert end == datetime(2027, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


def test_period_bounds_december():
    """December must wrap into the next year."""
    start, end = _period_bounds(2026, 12)
    assert end == datetime(2027, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


def test_effective_fare_prefers_actual():
    ride = _make_ride(actual_fare=30.00, estimated_fare=20.00)
    assert _effective_fare(ride) == Decimal("30.00")


def test_effective_fare_falls_back_to_estimated():
    ride = _make_ride(actual_fare=None, estimated_fare=20.00)
    assert _effective_fare(ride) == Decimal("20.00")


def test_effective_fare_zero_when_no_fares():
    ride = _make_ride(actual_fare=None, estimated_fare=None)
    ride.estimated_fare = None
    assert _effective_fare(ride) == Decimal("0")


def test_ride_to_line_item_maps_notes_to_purpose():
    ride = _make_ride(trip_notes="Client meeting", actual_fare=15.00)
    item = _ride_to_line_item(ride)
    assert item.purpose == "Client meeting"


def test_ride_to_line_item_status_string():
    ride = _make_ride(status="completed")
    item = _ride_to_line_item(ride)
    assert item.status == "completed"


# ---------------------------------------------------------------------------
# Service: get_member_expense_report
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_member_report_success_with_rides():
    """1. Success — rides present, monthly period."""
    db = AsyncMock()
    member = _make_member(MEMBER_ID)
    rides = [
        _make_ride(ride_id=1, actual_fare=20.00),
        _make_ride(ride_id=2, actual_fare=30.00),
    ]
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _db_member(member)
        return _db_rides(rides)

    db.execute = fake_execute

    result = await get_member_expense_report(db, MEMBER_ID, ACCOUNT_ID, 2026, 4)

    assert result.member_id == MEMBER_ID
    assert result.period_label == "2026-04"
    assert result.total_rides == 2
    assert result.total_amount_usd == Decimal("50.00")
    assert len(result.rides) == 2


@pytest.mark.asyncio
async def test_member_report_no_rides():
    """2. No rides — all totals zero, empty rides list."""
    db = AsyncMock()
    member = _make_member(MEMBER_ID)
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _db_member(member)
        return _db_rides([])

    db.execute = fake_execute

    result = await get_member_expense_report(db, MEMBER_ID, ACCOUNT_ID, 2026, 4)

    assert result.total_rides == 0
    assert result.total_amount_usd == Decimal("0.00")
    assert result.avg_per_ride_usd == Decimal("0.00")
    assert result.rides == []


@pytest.mark.asyncio
async def test_member_report_annual_period():
    """3. Annual period (month=None) — period_label is '2026'."""
    db = AsyncMock()
    member = _make_member(MEMBER_ID)
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _db_member(member)
        return _db_rides([])

    db.execute = fake_execute

    result = await get_member_expense_report(db, MEMBER_ID, ACCOUNT_ID, 2026, None)

    assert result.period_label == "2026"


@pytest.mark.asyncio
async def test_member_report_non_member_403():
    """4. Non-member → HTTP 403."""
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_db_no_member())

    with pytest.raises(HTTPException) as exc:
        await get_member_expense_report(db, OTHER_USER_ID, ACCOUNT_ID, 2026, 4)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_member_report_bad_year_low():
    """5. year < 2000 → HTTP 400."""
    db = AsyncMock()
    with pytest.raises(HTTPException) as exc:
        await get_member_expense_report(db, MEMBER_ID, ACCOUNT_ID, 1999, 4)
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_member_report_bad_year_high():
    """6. year > 2100 → HTTP 400."""
    db = AsyncMock()
    with pytest.raises(HTTPException) as exc:
        await get_member_expense_report(db, MEMBER_ID, ACCOUNT_ID, 2101, 4)
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_member_report_bad_month_zero():
    """7. month = 0 → HTTP 400."""
    db = AsyncMock()
    with pytest.raises(HTTPException) as exc:
        await get_member_expense_report(db, MEMBER_ID, ACCOUNT_ID, 2026, 0)
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_member_report_bad_month_thirteen():
    """8. month = 13 → HTTP 400."""
    db = AsyncMock()
    with pytest.raises(HTTPException) as exc:
        await get_member_expense_report(db, MEMBER_ID, ACCOUNT_ID, 2026, 13)
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_member_report_totals_multiple_rides():
    """9. Totals computed correctly for multiple rides."""
    db = AsyncMock()
    member = _make_member(MEMBER_ID)
    rides = [
        _make_ride(ride_id=1, actual_fare=10.00),
        _make_ride(ride_id=2, actual_fare=20.00),
        _make_ride(ride_id=3, actual_fare=30.00),
    ]
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _db_member(member)
        return _db_rides(rides)

    db.execute = fake_execute

    result = await get_member_expense_report(db, MEMBER_ID, ACCOUNT_ID, 2026, 4)

    assert result.total_amount_usd == Decimal("60.00")
    assert result.avg_per_ride_usd == Decimal("20.00")


@pytest.mark.asyncio
async def test_member_report_avg_zero_no_rides():
    """10. avg_per_ride_usd is 0 when there are no rides."""
    db = AsyncMock()
    member = _make_member(MEMBER_ID)
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _db_member(member)
        return _db_rides([])

    db.execute = fake_execute

    result = await get_member_expense_report(db, MEMBER_ID, ACCOUNT_ID, 2026, 4)
    assert result.avg_per_ride_usd == Decimal("0.00")


@pytest.mark.asyncio
async def test_member_report_actual_fare_preferred():
    """11. actual_fare takes precedence over estimated_fare."""
    db = AsyncMock()
    member = _make_member(MEMBER_ID)
    ride = _make_ride(actual_fare=50.00, estimated_fare=40.00)
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _db_member(member)
        return _db_rides([ride])

    db.execute = fake_execute

    result = await get_member_expense_report(db, MEMBER_ID, ACCOUNT_ID, 2026, 4)
    assert result.total_amount_usd == Decimal("50.00")


@pytest.mark.asyncio
async def test_member_report_uses_estimated_fare_when_no_actual():
    """12. Uses estimated_fare when actual_fare is None."""
    db = AsyncMock()
    member = _make_member(MEMBER_ID)
    ride = _make_ride(actual_fare=None, estimated_fare=35.00)
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _db_member(member)
        return _db_rides([ride])

    db.execute = fake_execute

    result = await get_member_expense_report(db, MEMBER_ID, ACCOUNT_ID, 2026, 4)
    assert result.total_amount_usd == Decimal("35.00")


@pytest.mark.asyncio
async def test_member_report_trip_notes_as_purpose():
    """13. trip_notes on ride is mapped to RideLineItem.purpose."""
    db = AsyncMock()
    member = _make_member(MEMBER_ID)
    ride = _make_ride(actual_fare=10.00, trip_notes="Conference travel")
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _db_member(member)
        return _db_rides([ride])

    db.execute = fake_execute

    result = await get_member_expense_report(db, MEMBER_ID, ACCOUNT_ID, 2026, 4)
    assert result.rides[0].purpose == "Conference travel"


@pytest.mark.asyncio
async def test_member_report_ride_status_string():
    """14. Ride status is a string in RideLineItem."""
    db = AsyncMock()
    member = _make_member(MEMBER_ID)
    ride = _make_ride(actual_fare=10.00, status="completed")
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _db_member(member)
        return _db_rides([ride])

    db.execute = fake_execute

    result = await get_member_expense_report(db, MEMBER_ID, ACCOUNT_ID, 2026, 4)
    assert isinstance(result.rides[0].status, str)
    assert result.rides[0].status == "completed"


# ---------------------------------------------------------------------------
# Service: get_account_expense_report
# ---------------------------------------------------------------------------


def _make_dept_pair(dept_name: str, user_id: int) -> tuple:
    dept_member = MagicMock()
    dept_member.user_id = user_id
    dept = MagicMock()
    dept.name = dept_name
    dept.account_id = ACCOUNT_ID
    return (dept_member, dept)


@pytest.mark.asyncio
async def test_account_report_single_member_single_dept():
    """15. Success — single member, single dept."""
    db = AsyncMock()
    user = _make_user(MEMBER_ID, "Alice")
    ride = _make_ride(actual_fare=25.00)
    dept_pair = _make_dept_pair("Engineering", MEMBER_ID)
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _db_ride_user_pairs([(ride, user)])
        return _db_dept_members([dept_pair])

    db.execute = fake_execute

    result = await get_account_expense_report(db, ACCOUNT_ID, 2026, 4)

    assert result.account_id == ACCOUNT_ID
    assert result.total_rides == 1
    assert result.total_amount_usd == Decimal("25.00")
    assert len(result.by_member) == 1
    assert result.by_member[0].display_name == "Alice"
    assert len(result.by_department) == 1
    assert result.by_department[0].department_name == "Engineering"


@pytest.mark.asyncio
async def test_account_report_no_rides():
    """16. No rides — all totals zero, empty breakdowns."""
    db = AsyncMock()
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _db_ride_user_pairs([])
        return _db_dept_members([])

    db.execute = fake_execute

    result = await get_account_expense_report(db, ACCOUNT_ID, 2026, 4)

    assert result.total_rides == 0
    assert result.total_amount_usd == Decimal("0.00")
    assert result.by_member == []
    assert result.by_department == []


@pytest.mark.asyncio
async def test_account_report_annual_period():
    """17. Annual period (month=None) — period_label is the year."""
    db = AsyncMock()

    async def fake_execute(stmt):
        return _db_ride_user_pairs([])

    db.execute = fake_execute

    result = await get_account_expense_report(db, ACCOUNT_ID, 2026, None)
    assert result.period_label == "2026"


@pytest.mark.asyncio
async def test_account_report_member_no_dept_unassigned():
    """18. Member with no department membership → 'Unassigned'."""
    db = AsyncMock()
    user = _make_user(MEMBER_ID, "Bob")
    ride = _make_ride(actual_fare=15.00)
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _db_ride_user_pairs([(ride, user)])
        return _db_dept_members([])  # no department memberships

    db.execute = fake_execute

    result = await get_account_expense_report(db, ACCOUNT_ID, 2026, 4)
    dept_names = [d.department_name for d in result.by_department]
    assert "Unassigned" in dept_names


@pytest.mark.asyncio
async def test_account_report_by_department_sorted():
    """19. by_department sorted alphabetically by department name."""
    db = AsyncMock()
    user = _make_user(MEMBER_ID, "Alice")
    ride1 = _make_ride(ride_id=1, actual_fare=10.00)
    ride2 = _make_ride(ride_id=2, actual_fare=20.00)
    dept_pair1 = _make_dept_pair("Zebra", MEMBER_ID)
    dept_pair2 = _make_dept_pair("Alpha", MEMBER_ID)
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _db_ride_user_pairs([(ride1, user), (ride2, user)])
        return _db_dept_members([dept_pair1, dept_pair2])

    db.execute = fake_execute

    result = await get_account_expense_report(db, ACCOUNT_ID, 2026, 4)
    names = [d.department_name for d in result.by_department]
    assert names == sorted(names)


@pytest.mark.asyncio
async def test_account_report_by_member_sorted():
    """20. by_member sorted alphabetically by display_name."""
    db = AsyncMock()
    user_z = _make_user(user_id=2, name="Zara")
    user_a = _make_user(user_id=3, name="Aaron")
    ride_z = _make_ride(ride_id=1, rider_id=2, actual_fare=10.00)
    ride_a = _make_ride(ride_id=2, rider_id=3, actual_fare=20.00)
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _db_ride_user_pairs([(ride_z, user_z), (ride_a, user_a)])
        return _db_dept_members([])

    db.execute = fake_execute

    result = await get_account_expense_report(db, ACCOUNT_ID, 2026, 4)
    names = [m.display_name for m in result.by_member]
    assert names == sorted(names)


@pytest.mark.asyncio
async def test_account_report_bad_year():
    """21. bad year → 400."""
    db = AsyncMock()
    with pytest.raises(HTTPException) as exc:
        await get_account_expense_report(db, ACCOUNT_ID, 1999, 4)
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_account_report_bad_month():
    """22. bad month → 400."""
    db = AsyncMock()
    with pytest.raises(HTTPException) as exc:
        await get_account_expense_report(db, ACCOUNT_ID, 2026, 13)
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_account_report_multiple_members_totals():
    """23. Multiple members — account totals are sum of all members."""
    db = AsyncMock()
    user1 = _make_user(user_id=1, name="Alice")
    user2 = _make_user(user_id=2, name="Bob")
    ride1 = _make_ride(ride_id=1, rider_id=1, actual_fare=100.00)
    ride2 = _make_ride(ride_id=2, rider_id=2, actual_fare=200.00)
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _db_ride_user_pairs([(ride1, user1), (ride2, user2)])
        return _db_dept_members([])

    db.execute = fake_execute

    result = await get_account_expense_report(db, ACCOUNT_ID, 2026, 4)
    assert result.total_rides == 2
    assert result.total_amount_usd == Decimal("300.00")
    assert len(result.by_member) == 2


@pytest.mark.asyncio
async def test_account_report_multiple_departments():
    """24. Multiple departments — breakdowns are correct."""
    db = AsyncMock()
    user1 = _make_user(user_id=1, name="Alice")
    user2 = _make_user(user_id=2, name="Bob")
    ride1 = _make_ride(ride_id=1, rider_id=1, actual_fare=50.00)
    ride2 = _make_ride(ride_id=2, rider_id=2, actual_fare=75.00)
    dept_pair1 = _make_dept_pair("Engineering", 1)
    dept_pair2 = _make_dept_pair("Sales", 2)
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _db_ride_user_pairs([(ride1, user1), (ride2, user2)])
        return _db_dept_members([dept_pair1, dept_pair2])

    db.execute = fake_execute

    result = await get_account_expense_report(db, ACCOUNT_ID, 2026, 4)
    dept_map = {d.department_name: d for d in result.by_department}
    assert "Engineering" in dept_map
    assert "Sales" in dept_map
    assert dept_map["Engineering"].total_amount_usd == Decimal("50.00")
    assert dept_map["Sales"].total_amount_usd == Decimal("75.00")


# ---------------------------------------------------------------------------
# Service: export_account_expense_csv
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_csv_has_summary_header():
    """25. CSV has summary header rows."""
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[
        _db_ride_user_pairs([]),
        _db_dept_members([]),
    ])

    csv_text = await export_account_expense_csv(db, ACCOUNT_ID, 2026, 4)
    assert "Corporate Expense Report" in csv_text


@pytest.mark.asyncio
async def test_csv_has_by_member_section():
    """26. CSV has 'By Member' section header."""
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[
        _db_ride_user_pairs([]),
        _db_dept_members([]),
    ])

    csv_text = await export_account_expense_csv(db, ACCOUNT_ID, 2026, 4)
    assert "By Member" in csv_text


@pytest.mark.asyncio
async def test_csv_has_by_department_section():
    """27. CSV has 'By Department' section header."""
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[
        _db_ride_user_pairs([]),
        _db_dept_members([]),
    ])

    csv_text = await export_account_expense_csv(db, ACCOUNT_ID, 2026, 4)
    assert "By Department" in csv_text


@pytest.mark.asyncio
async def test_csv_member_rows_present():
    """28. Member rows present in CSV."""
    db = AsyncMock()
    user = _make_user(MEMBER_ID, "Carol")
    ride = _make_ride(actual_fare=40.00)
    db.execute = AsyncMock(side_effect=[
        _db_ride_user_pairs([(ride, user)]),
        _db_dept_members([]),
    ])

    csv_text = await export_account_expense_csv(db, ACCOUNT_ID, 2026, 4)
    assert "Carol" in csv_text


@pytest.mark.asyncio
async def test_csv_department_rows_present():
    """29. Department rows present in CSV."""
    db = AsyncMock()
    user = _make_user(MEMBER_ID, "Dave")
    ride = _make_ride(actual_fare=30.00)
    dept_pair = _make_dept_pair("Finance", MEMBER_ID)
    db.execute = AsyncMock(side_effect=[
        _db_ride_user_pairs([(ride, user)]),
        _db_dept_members([dept_pair]),
    ])

    csv_text = await export_account_expense_csv(db, ACCOUNT_ID, 2026, 4)
    assert "Finance" in csv_text


@pytest.mark.asyncio
async def test_csv_no_rides_empty_sections():
    """30. No rides produces empty member/dept data sections."""
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[
        _db_ride_user_pairs([]),
        _db_dept_members([]),
    ])

    csv_text = await export_account_expense_csv(db, ACCOUNT_ID, 2026, 4)
    # Headers should exist but no data rows
    lines = [l.strip() for l in csv_text.splitlines() if l.strip()]
    assert "By Member" in "\n".join(lines)
    assert "By Department" in "\n".join(lines)


@pytest.mark.asyncio
async def test_csv_period_label_in_summary():
    """31. Period label appears in the summary section."""
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[
        _db_ride_user_pairs([]),
        _db_dept_members([]),
    ])

    csv_text = await export_account_expense_csv(db, ACCOUNT_ID, 2026, 4)
    assert "2026-04" in csv_text


@pytest.mark.asyncio
async def test_csv_bad_year_propagates_400():
    """32. Bad year propagates HTTP 400 from underlying service."""
    db = AsyncMock()
    with pytest.raises(HTTPException) as exc:
        await export_account_expense_csv(db, ACCOUNT_ID, 1999, 4)
    assert exc.value.status_code == 400


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


def test_ride_line_item_valid():
    """33. RideLineItem — valid construction."""
    item = RideLineItem(
        ride_id=1,
        date=date(2026, 4, 15),
        amount_usd=Decimal("25.00"),
        purpose="Meeting",
        status="completed",
    )
    assert item.ride_id == 1
    assert item.amount_usd == Decimal("25.00")


def test_ride_line_item_purpose_none():
    """34. RideLineItem — purpose can be None."""
    item = RideLineItem(
        ride_id=2,
        date=date(2026, 4, 15),
        amount_usd=Decimal("10.00"),
        purpose=None,
        status="completed",
    )
    assert item.purpose is None


def test_member_expense_report_valid():
    """35. MemberExpenseReport — valid construction."""
    report = MemberExpenseReport(
        member_id=1,
        period_label="2026-04",
        total_rides=2,
        total_amount_usd=Decimal("50.00"),
        avg_per_ride_usd=Decimal("25.00"),
    )
    assert report.total_rides == 2


def test_member_expense_report_rides_default_empty():
    """36. MemberExpenseReport — rides defaults to empty list."""
    report = MemberExpenseReport(
        member_id=1,
        period_label="2026",
        total_rides=0,
        total_amount_usd=Decimal("0.00"),
        avg_per_ride_usd=Decimal("0.00"),
    )
    assert report.rides == []


def test_dept_expense_summary_valid():
    """37. DeptExpenseSummary — valid construction."""
    summary = DeptExpenseSummary(
        department_name="Engineering",
        total_rides=5,
        total_amount_usd=Decimal("125.00"),
    )
    assert summary.department_name == "Engineering"


def test_member_expense_summary_valid():
    """38. MemberExpenseSummary — valid construction."""
    summary = MemberExpenseSummary(
        member_id=1,
        display_name="Alice",
        total_rides=3,
        total_amount_usd=Decimal("75.00"),
    )
    assert summary.display_name == "Alice"


def test_account_expense_report_valid():
    """39. AccountExpenseReport — valid construction."""
    report = AccountExpenseReport(
        account_id=1,
        period_label="2026-04",
        total_rides=10,
        total_amount_usd=Decimal("500.00"),
    )
    assert report.account_id == 1


def test_account_expense_report_by_department_default_empty():
    """40. AccountExpenseReport — by_department defaults to empty list."""
    report = AccountExpenseReport(
        account_id=1,
        period_label="2026",
        total_rides=0,
        total_amount_usd=Decimal("0.00"),
    )
    assert report.by_department == []


def test_account_expense_report_by_member_default_empty():
    """41. AccountExpenseReport — by_member defaults to empty list."""
    report = AccountExpenseReport(
        account_id=1,
        period_label="2026",
        total_rides=0,
        total_amount_usd=Decimal("0.00"),
    )
    assert report.by_member == []


# ---------------------------------------------------------------------------
# API layer tests (dependency_overrides pattern)
# ---------------------------------------------------------------------------


def _make_member_report() -> MemberExpenseReport:
    return MemberExpenseReport(
        member_id=MEMBER_ID,
        period_label="2026-04",
        total_rides=2,
        total_amount_usd=Decimal("50.00"),
        avg_per_ride_usd=Decimal("25.00"),
        rides=[],
    )


def _make_account_report() -> AccountExpenseReport:
    return AccountExpenseReport(
        account_id=ACCOUNT_ID,
        period_label="2026-04",
        total_rides=5,
        total_amount_usd=Decimal("200.00"),
        by_department=[],
        by_member=[],
    )


def _fake_user(user_id: int = MEMBER_ID, role_value: str = "rider"):
    from app.models.user import User as UserModel
    u = MagicMock(spec=UserModel)
    u.id = user_id
    u.role = MagicMock(value=role_value)
    u.is_active = True
    return u


def _make_fake_db(admin_member_or_none=None):
    """Return an async generator that yields a mock DB session."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = admin_member_or_none

    async def fake_execute(_stmt):
        return result

    async def _db_gen():
        db = AsyncMock()
        db.execute = fake_execute
        yield db

    return _db_gen


@pytest.mark.asyncio
async def test_api_member_report_200():
    """42. GET /corporate/members/me/expense-report → 200."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user, get_db

    report = _make_member_report()
    mock_account = MagicMock()
    mock_account.id = ACCOUNT_ID

    app.dependency_overrides[get_db] = _make_fake_db()
    app.dependency_overrides[get_current_user] = lambda: _fake_user(MEMBER_ID, "rider")

    with (
        patch("app.api.v1.corporate_expense_report_gen.get_user_account", new=AsyncMock(return_value=mock_account)),
        patch("app.api.v1.corporate_expense_report_gen.get_member_expense_report", new=AsyncMock(return_value=report)),
        TestClient(app) as client,
    ):
        resp = client.get("/api/v1/corporate/members/me/expense-report?year=2026&month=4")
    app.dependency_overrides.clear()

    assert resp.status_code == 200
    data = resp.json()
    assert data["member_id"] == MEMBER_ID
    assert data["total_rides"] == 2


@pytest.mark.asyncio
async def test_api_member_report_no_account_404():
    """43. GET member report — no account → 404."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user, get_db

    app.dependency_overrides[get_db] = _make_fake_db()
    app.dependency_overrides[get_current_user] = lambda: _fake_user(OTHER_USER_ID, "rider")

    with (
        patch("app.api.v1.corporate_expense_report_gen.get_user_account", new=AsyncMock(return_value=None)),
        TestClient(app) as client,
    ):
        resp = client.get("/api/v1/corporate/members/me/expense-report?year=2026&month=4")
    app.dependency_overrides.clear()

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_api_member_report_403_passthrough():
    """44. Service 403 passes through the API layer."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user, get_db

    mock_account = MagicMock()
    mock_account.id = ACCOUNT_ID

    async def raise_403(*args, **kwargs):
        raise HTTPException(status_code=403, detail="forbidden")

    app.dependency_overrides[get_db] = _make_fake_db()
    app.dependency_overrides[get_current_user] = lambda: _fake_user(OTHER_USER_ID, "rider")

    with (
        patch("app.api.v1.corporate_expense_report_gen.get_user_account", new=AsyncMock(return_value=mock_account)),
        patch("app.api.v1.corporate_expense_report_gen.get_member_expense_report", new=raise_403),
        TestClient(app) as client,
    ):
        resp = client.get("/api/v1/corporate/members/me/expense-report?year=2026&month=4")
    app.dependency_overrides.clear()

    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_api_account_report_corp_admin_200():
    """45. GET account report → 200 for corp admin."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user, get_db

    report = _make_account_report()
    # Simulate corp admin: DB returns a member row (not None)
    admin_member = MagicMock()

    app.dependency_overrides[get_db] = _make_fake_db(admin_member_or_none=admin_member)
    app.dependency_overrides[get_current_user] = lambda: _fake_user(ADMIN_ID, "member")

    with (
        patch("app.api.v1.corporate_expense_report_gen.get_account_expense_report", new=AsyncMock(return_value=report)),
        TestClient(app) as client,
    ):
        resp = client.get(f"/api/v1/admin/corporate/accounts/{ACCOUNT_ID}/expense-report?year=2026&month=4")
    app.dependency_overrides.clear()

    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_api_account_report_platform_admin_200():
    """46. GET account report → 200 for platform admin (no corp check needed)."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user, get_db

    report = _make_account_report()

    app.dependency_overrides[get_db] = _make_fake_db()
    app.dependency_overrides[get_current_user] = lambda: _fake_user(ADMIN_ID, "admin")

    with (
        patch("app.api.v1.corporate_expense_report_gen.get_account_expense_report", new=AsyncMock(return_value=report)),
        TestClient(app) as client,
    ):
        resp = client.get(f"/api/v1/admin/corporate/accounts/{ACCOUNT_ID}/expense-report?year=2026&month=4")
    app.dependency_overrides.clear()

    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_api_account_report_non_admin_403():
    """47. GET account report — non-admin → 403."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user, get_db

    # DB returns None = not a corp admin
    app.dependency_overrides[get_db] = _make_fake_db(admin_member_or_none=None)
    app.dependency_overrides[get_current_user] = lambda: _fake_user(OTHER_USER_ID, "rider")

    with TestClient(app) as client:
        resp = client.get(f"/api/v1/admin/corporate/accounts/{ACCOUNT_ID}/expense-report?year=2026&month=4")
    app.dependency_overrides.clear()

    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_api_csv_corp_admin_200():
    """48. GET CSV → 200 for corp admin."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user, get_db

    csv_text = "Corporate Expense Report\nAccount ID,1\n"
    admin_member = MagicMock()

    app.dependency_overrides[get_db] = _make_fake_db(admin_member_or_none=admin_member)
    app.dependency_overrides[get_current_user] = lambda: _fake_user(ADMIN_ID, "member")

    with (
        patch("app.api.v1.corporate_expense_report_gen.export_account_expense_csv", new=AsyncMock(return_value=csv_text)),
        TestClient(app) as client,
    ):
        resp = client.get(f"/api/v1/admin/corporate/accounts/{ACCOUNT_ID}/expense-report/csv?year=2026&month=4")
    app.dependency_overrides.clear()

    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_api_csv_non_admin_403():
    """49. GET CSV — non-admin → 403."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user, get_db

    app.dependency_overrides[get_db] = _make_fake_db(admin_member_or_none=None)
    app.dependency_overrides[get_current_user] = lambda: _fake_user(OTHER_USER_ID, "rider")

    with TestClient(app) as client:
        resp = client.get(f"/api/v1/admin/corporate/accounts/{ACCOUNT_ID}/expense-report/csv?year=2026&month=4")
    app.dependency_overrides.clear()

    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_api_csv_content_disposition_header():
    """50. GET CSV → Content-Disposition attachment header present."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user, get_db

    csv_text = "Corporate Expense Report\n"

    app.dependency_overrides[get_db] = _make_fake_db()
    app.dependency_overrides[get_current_user] = lambda: _fake_user(ADMIN_ID, "admin")

    with (
        patch("app.api.v1.corporate_expense_report_gen.export_account_expense_csv", new=AsyncMock(return_value=csv_text)),
        TestClient(app) as client,
    ):
        resp = client.get(f"/api/v1/admin/corporate/accounts/{ACCOUNT_ID}/expense-report/csv?year=2026&month=4")
    app.dependency_overrides.clear()

    assert resp.status_code == 200
    content_disp = resp.headers.get("content-disposition", "")
    assert "attachment" in content_disp
    assert "expense-report-account" in content_disp
