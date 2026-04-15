"""Corporate Expense Report endpoints.

Member endpoints (any active account member):
  POST   /corporate/accounts/me/expense-reports                   — submit
  GET    /corporate/accounts/me/expense-reports                   — list my reports
  GET    /corporate/accounts/me/expense-reports/{id}              — get report
  DELETE /corporate/accounts/me/expense-reports/{id}/withdraw     — withdraw

Admin endpoints (require ADMIN role within the account):
  GET  /corporate/accounts/me/expense-reports/all                 — list all
  POST /corporate/accounts/me/expense-reports/{id}/review         — review

Platform-admin endpoints:
  GET /admin/corporate/accounts/{account_id}/expense-reports      — list all
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query, status
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import func, select

from app.api.deps import get_current_user, get_db, require_admin
from app.models.corporate_expense_report import CorporateExpenseReport
from app.models.user import User
from app.schemas.corporate_expense_report import (
    ExpenseReportCreate,
    ExpenseReportListResponse,
    ExpenseReportResponse,
    ExpenseReportReview,
)
from app.services.corporate_account_mgmt import get_user_account
from app.services.corporate_expense_report import (
    _report_to_response,
    get_expense_report,
    list_account_expense_reports,
    list_my_expense_reports,
    review_expense_report,
    submit_expense_report,
    withdraw_expense_report,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["corporate-expense-reports"])


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------


async def _resolve_account_id(db: AsyncSession, user_id: int) -> int:
    account = await get_user_account(db, user_id)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="You are not a member of any corporate account.",
        )
    return account.id


# ---------------------------------------------------------------------------
# Member: submit expense report
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/accounts/me/expense-reports",
    response_model=ExpenseReportResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit an expense report for reimbursement",
)
async def submit_my_expense_report(
    data: ExpenseReportCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Submit a ride or manual expense for corporate reimbursement.

    Any active account member may submit. If ride_id is provided, the ride
    must belong to the submitter.
    """
    account_id = await _resolve_account_id(db, user.id)
    result = await submit_expense_report(db, account_id, user.id, data)
    await db.commit()
    return result


# ---------------------------------------------------------------------------
# Member: list own expense reports
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/expense-reports",
    response_model=ExpenseReportListResponse,
    summary="List my expense reports",
)
async def list_my_reports(
    status_filter: str | None = Query(None, description="Filter by status."),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a paginated list of the current user's expense reports."""
    account_id = await _resolve_account_id(db, user.id)
    return await list_my_expense_reports(
        db, account_id, user.id, status_filter=status_filter, skip=skip, limit=limit
    )


# ---------------------------------------------------------------------------
# Admin: list all account expense reports
# Note: this route MUST be declared before /{report_id} to avoid shadowing
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/expense-reports/all",
    response_model=ExpenseReportListResponse,
    summary="Admin: list all expense reports in the account",
)
async def list_all_reports(
    status_filter: str | None = Query(None, description="Filter by status."),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a paginated list of all expense reports in the account.

    Requires ADMIN role within the account.
    """
    account_id = await _resolve_account_id(db, user.id)
    return await list_account_expense_reports(
        db, account_id, user.id, status_filter=status_filter, skip=skip, limit=limit
    )


# ---------------------------------------------------------------------------
# Member/Admin: get a single expense report
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/expense-reports/{report_id}",
    response_model=ExpenseReportResponse,
    summary="Get an expense report by ID",
)
async def get_my_expense_report(
    report_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a single expense report.

    The submitter or any account admin may view the report.
    """
    account_id = await _resolve_account_id(db, user.id)
    return await get_expense_report(db, account_id, report_id, user.id)


# ---------------------------------------------------------------------------
# Member: withdraw an expense report
# ---------------------------------------------------------------------------


@router.delete(
    "/corporate/accounts/me/expense-reports/{report_id}/withdraw",
    response_model=ExpenseReportResponse,
    summary="Withdraw a pending expense report",
)
async def withdraw_my_expense_report(
    report_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Withdraw a pending expense report.

    Only the original submitter may withdraw, and only while the report is
    still pending.
    """
    account_id = await _resolve_account_id(db, user.id)
    result = await withdraw_expense_report(db, account_id, report_id, user.id)
    await db.commit()
    return result


# ---------------------------------------------------------------------------
# Admin: review (approve / reject) an expense report
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/accounts/me/expense-reports/{report_id}/review",
    response_model=ExpenseReportResponse,
    summary="Admin: approve or reject an expense report",
)
async def review_my_expense_report(
    report_id: int,
    data: ExpenseReportReview,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Approve or reject a pending expense report.

    Requires ADMIN role within the account.
    """
    account_id = await _resolve_account_id(db, user.id)
    result = await review_expense_report(db, account_id, report_id, user.id, data)
    await db.commit()
    return result


# ---------------------------------------------------------------------------
# Platform-admin: list expense reports for any account
# ---------------------------------------------------------------------------


@router.get(
    "/admin/corporate/accounts/{account_id}/expense-reports",
    response_model=ExpenseReportListResponse,
    summary="Platform admin: list all expense reports for any corporate account",
)
async def platform_admin_list_expense_reports(
    account_id: int,
    status_filter: str | None = Query(None, description="Filter by status."),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return expense reports for any corporate account.

    Requires platform-level admin role.
    """
    q = select(CorporateExpenseReport).where(
        CorporateExpenseReport.account_id == account_id
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
