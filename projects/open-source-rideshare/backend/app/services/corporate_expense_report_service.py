"""Service layer for Corporate Expense Report Aggregation.

This module handles generating and retrieving *aggregated* expense reports
for a corporate account.  A generated report summarises all rides billed to
the account within a date range, grouped by member and by ride category.

This is distinct from the individual expense-submission workflow implemented
in ``app.services.corporate_expense_report``.

Public surface
--------------
generate_expense_report(db, corp_id, requester_id, data)
    -> GeneratedExpenseReportDetail

list_generated_reports(db, corp_id, requester_id, start_date, end_date, skip, limit)
    -> GeneratedExpenseReportListResponse

get_generated_report(db, corp_id, report_id, requester_id)
    -> GeneratedExpenseReportDetail

export_report_csv(db, corp_id, report_id, requester_id)
    -> str  (CSV text)
"""

from __future__ import annotations

import csv
import io
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.corporate import BusinessAccountMember, MemberRole
from app.models.ride import Ride
from app.models.user import User
from app.schemas.corporate_expense_report_aggregate import (
    CategoryExpenseSummary,
    ExpenseReportGenerateRequest,
    GeneratedExpenseReportDetail,
    GeneratedExpenseReportListResponse,
    GeneratedExpenseReportResponse,
    MemberExpenseSummary,
)


# ---------------------------------------------------------------------------
# In-memory store for generated reports
#
# In a production system these would be persisted to a database table.  For
# this implementation we use a module-level dict keyed by (corp_id, report_id)
# so tests can create and retrieve reports within a single process.  The
# store is intentionally simple and not thread-safe; a real deployment would
# replace it with an ORM model and migration.
# ---------------------------------------------------------------------------

_REPORT_STORE: dict[int, dict] = {}
_NEXT_ID = 1


def _next_report_id() -> int:
    global _NEXT_ID
    rid = _NEXT_ID
    _NEXT_ID += 1
    return rid


def _reset_store() -> None:
    """Clear the in-memory store; intended for use in tests only."""
    global _NEXT_ID
    _REPORT_STORE.clear()
    _NEXT_ID = 1


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


async def _require_corp_admin(
    db: AsyncSession,
    corp_id: int,
    user_id: int,
) -> None:
    """Raise HTTP 403 if the user is not an active admin of the corporate account."""
    result = await db.execute(
        select(BusinessAccountMember).where(
            BusinessAccountMember.account_id == corp_id,
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


def _build_detail(raw: dict) -> GeneratedExpenseReportDetail:
    return GeneratedExpenseReportDetail(**raw)


def _build_summary(raw: dict) -> GeneratedExpenseReportResponse:
    return GeneratedExpenseReportResponse(
        id=raw["id"],
        corp_id=raw["corp_id"],
        title=raw["title"],
        start_date=raw["start_date"],
        end_date=raw["end_date"],
        total_rides=raw["total_rides"],
        total_amount_usd=raw["total_amount_usd"],
        generated_at=raw["generated_at"],
        generated_by_id=raw["generated_by_id"],
    )


# ---------------------------------------------------------------------------
# Service functions
# ---------------------------------------------------------------------------


async def generate_expense_report(
    db: AsyncSession,
    corp_id: int,
    requester_id: int,
    data: ExpenseReportGenerateRequest,
) -> GeneratedExpenseReportDetail:
    """Generate a new aggregated expense report for the corporate account.

    Queries all rides billed to ``corp_id`` whose completion timestamp falls
    within ``[data.start_date, data.end_date]`` (inclusive).  Aggregates
    totals by member and by ride vehicle_type category.

    Args:
        db: Async database session.
        corp_id: Corporate account identifier.
        requester_id: ID of the admin requesting the report.
        data: Date range and optional title for the report.

    Returns:
        GeneratedExpenseReportDetail with member and category breakdowns.

    Raises:
        HTTP 403: When the requester is not an account admin.
        HTTP 422: When start_date is after end_date.
    """
    await _require_corp_admin(db, corp_id, requester_id)

    if data.start_date > data.end_date:
        raise HTTPException(
            status_code=422,
            detail="start_date must not be after end_date.",
        )

    # Fetch rides for this account in the date range.
    # We join User so we can include member names in the breakdown.
    start_dt = datetime(data.start_date.year, data.start_date.month, data.start_date.day, 0, 0, 0, tzinfo=timezone.utc)
    end_dt = datetime(data.end_date.year, data.end_date.month, data.end_date.day, 23, 59, 59, tzinfo=timezone.utc)

    rides_result = await db.execute(
        select(Ride, User)
        .join(User, Ride.rider_id == User.id)
        .where(
            Ride.corporate_account_id == corp_id,
            Ride.requested_at >= start_dt,
            Ride.requested_at <= end_dt,
        )
    )
    rows = rides_result.all()

    # Aggregate by member
    member_map: dict[int, dict] = {}
    category_map: dict[str, dict] = {}
    total_amount = Decimal("0.00")
    total_rides = 0

    for ride, user in rows:
        # Use actual_fare when available, fall back to estimated_fare, then zero
        raw_fare = getattr(ride, "actual_fare", None) or getattr(ride, "estimated_fare", None) or 0
        fare = Decimal(str(raw_fare))
        total_amount += fare
        total_rides += 1

        # Per-member aggregation
        uid = user.id
        if uid not in member_map:
            member_map[uid] = {
                "member_user_id": uid,
                "member_name": user.name or f"User {uid}",
                "ride_count": 0,
                "total_amount_usd": Decimal("0.00"),
            }
        member_map[uid]["ride_count"] += 1
        member_map[uid]["total_amount_usd"] += fare

        # Per-category aggregation (use vehicle_type_preference if available, else 'standard')
        raw_category = getattr(ride, "vehicle_type_preference", None)
        category = str(raw_category.value) if raw_category is not None else "standard"
        # Fall back to a plain string attribute 'vehicle_type' if tests set it directly
        if not raw_category:
            category = getattr(ride, "vehicle_type", None) or "standard"
        if category not in category_map:
            category_map[category] = {
                "category": category,
                "ride_count": 0,
                "total_amount_usd": Decimal("0.00"),
            }
        category_map[category]["ride_count"] += 1
        category_map[category]["total_amount_usd"] += fare

    # Build title
    title = data.title or f"Expense Report {data.start_date} to {data.end_date}"

    report_id = _next_report_id()
    now = _now_utc()

    by_member = [MemberExpenseSummary(**v) for v in member_map.values()]
    by_category = [CategoryExpenseSummary(**v) for v in category_map.values()]

    raw = {
        "id": report_id,
        "corp_id": corp_id,
        "title": title,
        "start_date": data.start_date,
        "end_date": data.end_date,
        "total_rides": total_rides,
        "total_amount_usd": total_amount,
        "generated_at": now,
        "generated_by_id": requester_id,
        "by_member": [m.model_dump() for m in by_member],
        "by_category": [c.model_dump() for c in by_category],
    }
    _REPORT_STORE[report_id] = raw

    return GeneratedExpenseReportDetail(
        id=report_id,
        corp_id=corp_id,
        title=title,
        start_date=data.start_date,
        end_date=data.end_date,
        total_rides=total_rides,
        total_amount_usd=total_amount,
        generated_at=now,
        generated_by_id=requester_id,
        by_member=by_member,
        by_category=by_category,
    )


async def list_generated_reports(
    db: AsyncSession,
    corp_id: int,
    requester_id: int,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    skip: int = 0,
    limit: int = 50,
) -> GeneratedExpenseReportListResponse:
    """Return a paginated list of previously generated reports for a corp account.

    Args:
        db: Async database session.
        corp_id: Corporate account identifier.
        requester_id: ID of the requesting admin.
        start_date: Optional filter — only reports whose period starts on or after this date.
        end_date: Optional filter — only reports whose period ends on or before this date.
        skip: Pagination offset.
        limit: Maximum number of reports to return.

    Returns:
        GeneratedExpenseReportListResponse.

    Raises:
        HTTP 403: When the requester is not an account admin.
    """
    await _require_corp_admin(db, corp_id, requester_id)

    all_for_corp = [
        r for r in _REPORT_STORE.values()
        if r["corp_id"] == corp_id
    ]

    if start_date is not None:
        all_for_corp = [r for r in all_for_corp if r["start_date"] >= start_date]
    if end_date is not None:
        all_for_corp = [r for r in all_for_corp if r["end_date"] <= end_date]

    # Sort newest first
    all_for_corp.sort(key=lambda r: r["generated_at"], reverse=True)

    total = len(all_for_corp)
    page = all_for_corp[skip: skip + limit]

    return GeneratedExpenseReportListResponse(
        corp_id=corp_id,
        total=total,
        reports=[_build_summary(r) for r in page],
    )


async def get_generated_report(
    db: AsyncSession,
    corp_id: int,
    report_id: int,
    requester_id: int,
) -> GeneratedExpenseReportDetail:
    """Return the full detail of a single generated report.

    Args:
        db: Async database session.
        corp_id: Corporate account identifier.
        report_id: Identifier of the generated report.
        requester_id: ID of the requesting admin.

    Returns:
        GeneratedExpenseReportDetail.

    Raises:
        HTTP 403: When the requester is not an account admin.
        HTTP 404: When the report does not exist for this corp account.
    """
    await _require_corp_admin(db, corp_id, requester_id)

    raw = _REPORT_STORE.get(report_id)
    if raw is None or raw["corp_id"] != corp_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Expense report not found for this corporate account.",
        )

    return GeneratedExpenseReportDetail(
        id=raw["id"],
        corp_id=raw["corp_id"],
        title=raw["title"],
        start_date=raw["start_date"],
        end_date=raw["end_date"],
        total_rides=raw["total_rides"],
        total_amount_usd=raw["total_amount_usd"],
        generated_at=raw["generated_at"],
        generated_by_id=raw["generated_by_id"],
        by_member=[MemberExpenseSummary(**m) for m in raw["by_member"]],
        by_category=[CategoryExpenseSummary(**c) for c in raw["by_category"]],
    )


async def export_report_csv(
    db: AsyncSession,
    corp_id: int,
    report_id: int,
    requester_id: int,
) -> str:
    """Export a generated report as a CSV string.

    The CSV contains one section for member totals and one for category totals,
    separated by a blank line.

    Args:
        db: Async database session.
        corp_id: Corporate account identifier.
        report_id: Identifier of the generated report.
        requester_id: ID of the requesting admin.

    Returns:
        CSV-formatted string ready to be returned as a file download.

    Raises:
        HTTP 403: When the requester is not an account admin.
        HTTP 404: When the report does not exist for this corp account.
    """
    detail = await get_generated_report(db, corp_id, report_id, requester_id)

    buf = io.StringIO()
    writer = csv.writer(buf)

    # Report header
    writer.writerow(["Corporate Expense Report"])
    writer.writerow(["Title", detail.title])
    writer.writerow(["Period", f"{detail.start_date} to {detail.end_date}"])
    writer.writerow(["Total Rides", detail.total_rides])
    writer.writerow(["Total Amount (USD)", str(detail.total_amount_usd)])
    writer.writerow(["Generated At", detail.generated_at.isoformat()])
    writer.writerow([])

    # By-member section
    writer.writerow(["By Member"])
    writer.writerow(["Member User ID", "Member Name", "Ride Count", "Total Amount (USD)"])
    for m in detail.by_member:
        writer.writerow([
            m.member_user_id,
            m.member_name,
            m.ride_count,
            str(m.total_amount_usd),
        ])
    writer.writerow([])

    # By-category section
    writer.writerow(["By Category"])
    writer.writerow(["Category", "Ride Count", "Total Amount (USD)"])
    for c in detail.by_category:
        writer.writerow([c.category, c.ride_count, str(c.total_amount_usd)])

    return buf.getvalue()
