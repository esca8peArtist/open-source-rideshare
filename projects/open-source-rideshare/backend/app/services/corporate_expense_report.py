"""Service layer for Corporate Expense Reports.

Employees submit rides (or manual expenses) for corporate reimbursement.
Admins review and approve or reject each report.

Public surface
--------------
submit_expense_report(db, account_id, user_id, data)
get_expense_report(db, account_id, report_id, requesting_user_id)
list_my_expense_reports(db, account_id, user_id, status_filter, skip, limit)
list_account_expense_reports(db, account_id, user_id, status_filter, skip, limit)
review_expense_report(db, account_id, report_id, reviewer_id, data)
withdraw_expense_report(db, account_id, report_id, user_id)
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.corporate import BusinessAccountMember, MemberRole
from app.models.corporate_cost_center import CorporateCostCenter
from app.models.corporate_expense_report import CorporateExpenseReport, ExpenseStatus
from app.models.corporate_trip_purpose import CorporateTripPurpose
from app.models.ride import Ride
from app.schemas.corporate_expense_report import (
    ExpenseReportCreate,
    ExpenseReportListResponse,
    ExpenseReportResponse,
    ExpenseReportReview,
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _report_to_response(report: CorporateExpenseReport) -> ExpenseReportResponse:
    return ExpenseReportResponse(
        id=report.id,
        account_id=report.account_id,
        submitted_by_id=report.submitted_by_id,
        ride_id=report.ride_id,
        amount_usd=report.amount_usd,
        description=report.description,
        cost_center_id=report.cost_center_id,
        trip_purpose_id=report.trip_purpose_id,
        receipt_url=report.receipt_url,
        status=report.status if isinstance(report.status, str) else report.status.value,
        reviewed_by_id=report.reviewed_by_id,
        reviewed_at=report.reviewed_at,
        review_note=report.review_note,
        submitted_at=report.submitted_at or _now_utc(),
        created_at=report.created_at or _now_utc(),
    )


async def _require_admin(
    db: AsyncSession,
    account_id: int,
    user_id: int,
) -> BusinessAccountMember:
    """Return the member row or raise HTTP 403 if not an account admin."""
    result = await db.execute(
        select(BusinessAccountMember).where(
            BusinessAccountMember.account_id == account_id,
            BusinessAccountMember.user_id == user_id,
            BusinessAccountMember.role == MemberRole.ADMIN,
            BusinessAccountMember.is_active.is_(True),
        )
    )
    member = result.scalar_one_or_none()
    if member is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have admin access to this corporate account.",
        )
    return member


async def _require_member(
    db: AsyncSession,
    account_id: int,
    user_id: int,
) -> BusinessAccountMember:
    """Return the member row or raise HTTP 403 if not an active member."""
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


async def _get_report(
    db: AsyncSession,
    account_id: int,
    report_id: int,
) -> CorporateExpenseReport:
    """Return the expense report or raise HTTP 404 if not found in this account."""
    result = await db.execute(
        select(CorporateExpenseReport).where(
            CorporateExpenseReport.id == report_id,
            CorporateExpenseReport.account_id == account_id,
        )
    )
    report = result.scalar_one_or_none()
    if report is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Expense report not found in this account.",
        )
    return report


# ---------------------------------------------------------------------------
# Service functions
# ---------------------------------------------------------------------------


async def submit_expense_report(
    db: AsyncSession,
    account_id: int,
    user_id: int,
    data: ExpenseReportCreate,
) -> ExpenseReportResponse:
    """Submit a new expense report for reimbursement.

    Args:
        db: Database session.
        account_id: Corporate account identifier.
        user_id: ID of the submitting employee.
        data: Expense report payload.

    Returns:
        ExpenseReportResponse for the newly created report.

    Raises:
        HTTP 403: When the user is not an active account member, or when
            ride_id is provided but belongs to a different user.
        HTTP 404: When ride_id, cost_center_id, or trip_purpose_id is
            provided but not found / not valid for this account.
    """
    await _require_member(db, account_id, user_id)

    # Validate ride ownership if provided
    if data.ride_id is not None:
        ride_result = await db.execute(
            select(Ride).where(Ride.id == data.ride_id)
        )
        ride = ride_result.scalar_one_or_none()
        if ride is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Ride not found.",
            )
        if ride.rider_id != user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only expense rides you took yourself.",
            )

    # Validate cost center belongs to this account
    if data.cost_center_id is not None:
        cc_result = await db.execute(
            select(CorporateCostCenter).where(
                CorporateCostCenter.id == data.cost_center_id,
                CorporateCostCenter.account_id == account_id,
            )
        )
        if cc_result.scalar_one_or_none() is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Cost center not found in this account.",
            )

    # Validate trip purpose belongs to this account and is active
    if data.trip_purpose_id is not None:
        tp_result = await db.execute(
            select(CorporateTripPurpose).where(
                CorporateTripPurpose.id == data.trip_purpose_id,
                CorporateTripPurpose.account_id == account_id,
                CorporateTripPurpose.is_active.is_(True),
            )
        )
        if tp_result.scalar_one_or_none() is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Trip purpose not found or inactive in this account.",
            )

    report = CorporateExpenseReport(
        account_id=account_id,
        submitted_by_id=user_id,
        ride_id=data.ride_id,
        amount_usd=data.amount_usd,
        description=data.description,
        cost_center_id=data.cost_center_id,
        trip_purpose_id=data.trip_purpose_id,
        receipt_url=data.receipt_url,
        status=ExpenseStatus.PENDING,
    )
    db.add(report)
    await db.flush()
    return _report_to_response(report)


async def get_expense_report(
    db: AsyncSession,
    account_id: int,
    report_id: int,
    requesting_user_id: int,
) -> ExpenseReportResponse:
    """Return a single expense report.

    The submitter or any account admin may view the report.

    Args:
        db: Database session.
        account_id: Corporate account identifier.
        report_id: Expense report identifier.
        requesting_user_id: ID of the user making the request.

    Returns:
        ExpenseReportResponse.

    Raises:
        HTTP 403: When the requester is neither the submitter nor an admin.
        HTTP 404: When the report is not found in this account.
    """
    report = await _get_report(db, account_id, report_id)

    if report.submitted_by_id != requesting_user_id:
        # Must be an admin
        admin_result = await db.execute(
            select(BusinessAccountMember).where(
                BusinessAccountMember.account_id == account_id,
                BusinessAccountMember.user_id == requesting_user_id,
                BusinessAccountMember.role == MemberRole.ADMIN,
                BusinessAccountMember.is_active.is_(True),
            )
        )
        if admin_result.scalar_one_or_none() is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to view this expense report.",
            )

    return _report_to_response(report)


async def list_my_expense_reports(
    db: AsyncSession,
    account_id: int,
    user_id: int,
    status_filter: Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
) -> ExpenseReportListResponse:
    """Return paginated expense reports for the requesting employee.

    Args:
        db: Database session.
        account_id: Corporate account identifier.
        user_id: ID of the requesting employee.
        status_filter: Optional status string to filter by.
        skip: Pagination offset.
        limit: Maximum rows to return.

    Returns:
        ExpenseReportListResponse scoped to the requesting user's reports.
    """
    q = select(CorporateExpenseReport).where(
        CorporateExpenseReport.account_id == account_id,
        CorporateExpenseReport.submitted_by_id == user_id,
    )
    if status_filter is not None:
        q = q.where(CorporateExpenseReport.status == status_filter)

    total_result = await db.execute(
        select(func.count()).select_from(q.subquery())
    )
    total = total_result.scalar_one() or 0

    page_result = await db.execute(
        q.order_by(CorporateExpenseReport.submitted_at.desc()).offset(skip).limit(limit)
    )
    reports = page_result.scalars().all()

    return ExpenseReportListResponse(
        account_id=account_id,
        total=total,
        reports=[_report_to_response(r) for r in reports],
    )


async def list_account_expense_reports(
    db: AsyncSession,
    account_id: int,
    user_id: int,
    status_filter: Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
) -> ExpenseReportListResponse:
    """Return all expense reports for the account (admin only).

    Args:
        db: Database session.
        account_id: Corporate account identifier.
        user_id: ID of the requesting admin.
        status_filter: Optional status string to filter by.
        skip: Pagination offset.
        limit: Maximum rows to return.

    Returns:
        ExpenseReportListResponse with all account reports.

    Raises:
        HTTP 403: When the user is not an account admin.
    """
    await _require_admin(db, account_id, user_id)

    q = select(CorporateExpenseReport).where(
        CorporateExpenseReport.account_id == account_id,
    )
    if status_filter is not None:
        q = q.where(CorporateExpenseReport.status == status_filter)

    total_result = await db.execute(
        select(func.count()).select_from(q.subquery())
    )
    total = total_result.scalar_one() or 0

    page_result = await db.execute(
        q.order_by(CorporateExpenseReport.submitted_at.desc()).offset(skip).limit(limit)
    )
    reports = page_result.scalars().all()

    return ExpenseReportListResponse(
        account_id=account_id,
        total=total,
        reports=[_report_to_response(r) for r in reports],
    )


async def review_expense_report(
    db: AsyncSession,
    account_id: int,
    report_id: int,
    reviewer_id: int,
    data: ExpenseReportReview,
) -> ExpenseReportResponse:
    """Approve or reject a pending expense report (admin only).

    Args:
        db: Database session.
        account_id: Corporate account identifier.
        report_id: Expense report identifier.
        reviewer_id: ID of the reviewing admin.
        data: Review decision payload.

    Returns:
        Updated ExpenseReportResponse.

    Raises:
        HTTP 403: When the reviewer is not an account admin.
        HTTP 404: When the report is not found.
        HTTP 409: When the report is not in pending status.
    """
    await _require_admin(db, account_id, reviewer_id)
    report = await _get_report(db, account_id, report_id)

    if report.status != ExpenseStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only pending expense reports can be reviewed.",
        )

    report.status = ExpenseStatus(data.action)
    report.reviewed_by_id = reviewer_id
    report.reviewed_at = _now_utc()
    report.review_note = data.review_note

    await db.flush()
    return _report_to_response(report)


async def withdraw_expense_report(
    db: AsyncSession,
    account_id: int,
    report_id: int,
    user_id: int,
) -> ExpenseReportResponse:
    """Withdraw a pending expense report (submitter only).

    Args:
        db: Database session.
        account_id: Corporate account identifier.
        report_id: Expense report identifier.
        user_id: ID of the requesting user (must be the original submitter).

    Returns:
        Updated ExpenseReportResponse with status=withdrawn.

    Raises:
        HTTP 403: When the user is not the original submitter.
        HTTP 404: When the report is not found.
        HTTP 409: When the report is not in pending status.
    """
    report = await _get_report(db, account_id, report_id)

    if report.submitted_by_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only withdraw your own expense reports.",
        )

    if report.status != ExpenseStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only pending expense reports can be withdrawn.",
        )

    report.status = ExpenseStatus.WITHDRAWN
    await db.flush()
    return _report_to_response(report)
