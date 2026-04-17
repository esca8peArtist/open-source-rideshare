"""Service layer for corporate expense report generation.

Allows corporate members to view their own ride expenses grouped by period,
and admins to generate expense reports for their whole account.

This module reads from existing Ride + CorporateAccount + CorporateMember data
and requires no new database tables.

Public surface
--------------
get_member_expense_report(db, member_id, account_id, year, month=None)
    -> MemberExpenseReport

get_account_expense_report(db, account_id, year, month=None)
    -> AccountExpenseReport

export_account_expense_csv(db, account_id, year, month=None)
    -> str  (CSV text)
"""
from __future__ import annotations

import csv
import io
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.corporate import BusinessAccountMember, MemberRole
from app.models.corporate_department import CorporateDepartment, CorporateDepartmentMember
from app.models.ride import Ride, RideStatus
from app.models.user import User
from app.schemas.corporate_expense_report_gen import (
    AccountExpenseReport,
    DeptExpenseSummary,
    MemberExpenseReport,
    MemberExpenseSummary,
    RideLineItem,
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _period_label(year: int, month: Optional[int]) -> str:
    """Build a human-readable period label."""
    if month is not None:
        return f"{year}-{month:02d}"
    return str(year)


def _period_bounds(year: int, month: Optional[int]) -> tuple[datetime, datetime]:
    """Return UTC start/end datetimes for the given period (inclusive)."""
    if month is not None:
        # Determine last day of the month
        if month == 12:
            next_year, next_month = year + 1, 1
        else:
            next_year, next_month = year, month + 1
        start = datetime(year, month, 1, 0, 0, 0, tzinfo=timezone.utc)
        end = datetime(next_year, next_month, 1, 0, 0, 0, tzinfo=timezone.utc)
    else:
        start = datetime(year, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        end = datetime(year + 1, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    return start, end


def _effective_fare(ride: Ride) -> Decimal:
    """Return the effective fare for a ride (actual > estimated > 0)."""
    raw = getattr(ride, "actual_fare", None) or getattr(ride, "estimated_fare", None) or 0
    return Decimal(str(raw))


async def _require_active_member(
    db: AsyncSession,
    account_id: int,
    user_id: int,
) -> BusinessAccountMember:
    """Return the member row or raise HTTP 403 if the user is not active."""
    result = await db.execute(
        select(BusinessAccountMember).where(
            BusinessAccountMember.account_id == account_id,
            BusinessAccountMember.user_id == user_id,
            BusinessAccountMember.is_active.is_(True),
        )
    )
    member = result.scalar_one_or_none()
    if member is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not an active member of this corporate account.",
        )
    return member


async def _require_corp_admin(
    db: AsyncSession,
    account_id: int,
    user_id: int,
) -> None:
    """Raise HTTP 403 if the user is not an active admin of the corporate account."""
    result = await db.execute(
        select(BusinessAccountMember).where(
            BusinessAccountMember.account_id == account_id,
            BusinessAccountMember.user_id == user_id,
            BusinessAccountMember.role == MemberRole.ADMIN,
            BusinessAccountMember.is_active.is_(True),
        )
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have admin access to this corporate account.",
        )


def _ride_to_line_item(ride: Ride) -> RideLineItem:
    """Convert a Ride ORM object to a RideLineItem schema."""
    # Use completed_at for the date; fall back to requested_at
    ts: Optional[datetime] = getattr(ride, "completed_at", None) or getattr(ride, "requested_at", None)
    ride_date: date = ts.date() if ts is not None else date.today()

    purpose: Optional[str] = getattr(ride, "trip_notes", None)

    raw_status = getattr(ride, "status", None)
    if raw_status is None:
        status_str = "unknown"
    elif isinstance(raw_status, str):
        status_str = raw_status
    else:
        status_str = raw_status.value

    return RideLineItem(
        ride_id=ride.id,
        date=ride_date,
        amount_usd=_effective_fare(ride),
        purpose=purpose,
        status=status_str,
    )


# ---------------------------------------------------------------------------
# Service functions
# ---------------------------------------------------------------------------


async def get_member_expense_report(
    db: AsyncSession,
    member_id: int,
    account_id: int,
    year: int,
    month: Optional[int] = None,
) -> MemberExpenseReport:
    """Return an expense report for a single member over the given period.

    Includes per-ride line items and summary totals.

    Args:
        db: Async database session.
        member_id: The user whose rides to aggregate.
        account_id: Corporate account the member belongs to.
        year: Calendar year to report on.
        month: Optional month (1-12).  If omitted, aggregates the whole year.

    Returns:
        MemberExpenseReport with ride line items and totals.

    Raises:
        HTTP 400: When year or month is out of valid range.
        HTTP 403: When member_id is not an active member of account_id.
    """
    if not 2000 <= year <= 2100:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="year must be between 2000 and 2100.",
        )
    if month is not None and not 1 <= month <= 12:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="month must be between 1 and 12.",
        )

    await _require_active_member(db, account_id, member_id)

    start_dt, end_dt = _period_bounds(year, month)

    rides_result = await db.execute(
        select(Ride).where(
            Ride.rider_id == member_id,
            Ride.corporate_account_id == account_id,
            Ride.requested_at >= start_dt,
            Ride.requested_at < end_dt,
        ).order_by(Ride.requested_at)
    )
    rides = rides_result.scalars().all()

    total_amount = Decimal("0.00")
    line_items: list[RideLineItem] = []

    for ride in rides:
        line_item = _ride_to_line_item(ride)
        line_items.append(line_item)
        total_amount += line_item.amount_usd

    total_rides = len(line_items)
    avg_per_ride = (total_amount / total_rides) if total_rides > 0 else Decimal("0.00")

    return MemberExpenseReport(
        member_id=member_id,
        period_label=_period_label(year, month),
        total_rides=total_rides,
        total_amount_usd=total_amount,
        avg_per_ride_usd=avg_per_ride.quantize(Decimal("0.01")),
        rides=line_items,
    )


async def get_account_expense_report(
    db: AsyncSession,
    account_id: int,
    year: int,
    month: Optional[int] = None,
) -> AccountExpenseReport:
    """Return an aggregated expense report for the whole account.

    Groups ride totals by department and by individual member.

    Args:
        db: Async database session.
        account_id: Corporate account identifier.
        year: Calendar year to report on.
        month: Optional month (1-12).  If omitted, aggregates the whole year.

    Returns:
        AccountExpenseReport with per-department and per-member breakdowns.

    Raises:
        HTTP 400: When year or month is out of valid range.
    """
    if not 2000 <= year <= 2100:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="year must be between 2000 and 2100.",
        )
    if month is not None and not 1 <= month <= 12:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="month must be between 1 and 12.",
        )

    start_dt, end_dt = _period_bounds(year, month)

    # Fetch all rides for this account in the period, joined with the rider User
    rides_result = await db.execute(
        select(Ride, User)
        .join(User, Ride.rider_id == User.id)
        .where(
            Ride.corporate_account_id == account_id,
            Ride.requested_at >= start_dt,
            Ride.requested_at < end_dt,
        )
    )
    ride_rows = rides_result.all()

    # Build per-member aggregation map
    member_map: dict[int, dict] = {}
    total_amount = Decimal("0.00")
    total_rides = 0

    for ride, user in ride_rows:
        fare = _effective_fare(ride)
        total_amount += fare
        total_rides += 1

        uid = user.id
        if uid not in member_map:
            member_map[uid] = {
                "member_id": uid,
                "display_name": user.name or f"User {uid}",
                "total_rides": 0,
                "total_amount_usd": Decimal("0.00"),
            }
        member_map[uid]["total_rides"] += 1
        member_map[uid]["total_amount_usd"] += fare

    by_member = [
        MemberExpenseSummary(**v) for v in sorted(member_map.values(), key=lambda x: x["display_name"])
    ]

    # Build per-department aggregation.
    # A ride is attributed to a department when the rider is a member of that
    # department at report time.  Riders with no department membership fall into
    # an implicit "Unassigned" bucket.
    member_ids = list(member_map.keys())

    # Fetch all department memberships for these members in this account
    dept_member_result = await db.execute(
        select(CorporateDepartmentMember, CorporateDepartment)
        .join(CorporateDepartment, CorporateDepartmentMember.department_id == CorporateDepartment.id)
        .where(
            CorporateDepartment.account_id == account_id,
            CorporateDepartmentMember.user_id.in_(member_ids) if member_ids else False,
        )
    )
    dept_member_rows = dept_member_result.all()

    # Map user_id -> first department name (a user could be in multiple; we
    # credit all matching departments, or if none, "Unassigned")
    user_dept_map: dict[int, list[str]] = {}
    for dm, dept in dept_member_rows:
        user_dept_map.setdefault(dm.user_id, []).append(dept.name)

    dept_agg: dict[str, dict] = {}

    for ride, user in ride_rows:
        fare = _effective_fare(ride)
        dept_names = user_dept_map.get(user.id, ["Unassigned"])
        for dept_name in dept_names:
            if dept_name not in dept_agg:
                dept_agg[dept_name] = {
                    "department_name": dept_name,
                    "total_rides": 0,
                    "total_amount_usd": Decimal("0.00"),
                }
            dept_agg[dept_name]["total_rides"] += 1
            dept_agg[dept_name]["total_amount_usd"] += fare

    by_department = [
        DeptExpenseSummary(**v) for v in sorted(dept_agg.values(), key=lambda x: x["department_name"])
    ]

    return AccountExpenseReport(
        account_id=account_id,
        period_label=_period_label(year, month),
        total_rides=total_rides,
        total_amount_usd=total_amount,
        by_department=by_department,
        by_member=by_member,
    )


async def export_account_expense_csv(
    db: AsyncSession,
    account_id: int,
    year: int,
    month: Optional[int] = None,
) -> str:
    """Export the account expense report as a CSV string.

    The CSV has a summary header, a per-member section, and a per-department
    section separated by blank lines.

    Args:
        db: Async database session.
        account_id: Corporate account identifier.
        year: Calendar year to report on.
        month: Optional month (1-12).  If omitted, exports the whole year.

    Returns:
        CSV-formatted string ready to be returned as a file download.

    Raises:
        HTTP 400: When year or month is out of valid range.
    """
    report = await get_account_expense_report(db, account_id, year, month)

    buf = io.StringIO()
    writer = csv.writer(buf)

    # Summary header
    writer.writerow(["Corporate Expense Report"])
    writer.writerow(["Account ID", report.account_id])
    writer.writerow(["Period", report.period_label])
    writer.writerow(["Total Rides", report.total_rides])
    writer.writerow(["Total Amount (USD)", str(report.total_amount_usd)])
    writer.writerow([])

    # By-member section
    writer.writerow(["By Member"])
    writer.writerow(["Member ID", "Name", "Ride Count", "Total Amount (USD)"])
    for m in report.by_member:
        writer.writerow([m.member_id, m.display_name, m.total_rides, str(m.total_amount_usd)])
    writer.writerow([])

    # By-department section
    writer.writerow(["By Department"])
    writer.writerow(["Department", "Ride Count", "Total Amount (USD)"])
    for d in report.by_department:
        writer.writerow([d.department_name, d.total_rides, str(d.total_amount_usd)])

    return buf.getvalue()
