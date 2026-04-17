"""Corporate expense report generation endpoints.

Member endpoints (any active account member):
  GET /corporate/members/me/expense-report?year=2026&month=4
      — the authenticated member's own expense report for the period

Admin endpoints (require ADMIN role within the corporate account):
  GET /admin/corporate/accounts/{account_id}/expense-report?year=2026&month=4
      — aggregated expense report for an account (by dept + by member)
  GET /admin/corporate/accounts/{account_id}/expense-report/csv?year=2026&month=4
      — CSV download of the account expense report

Platform admin endpoints share the same admin routes; platform-level admins
are not restricted to a single account.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.models.user import User
from app.schemas.corporate_expense_report_gen import AccountExpenseReport, MemberExpenseReport
from app.services.corporate_account_mgmt import get_user_account
from app.services.corporate_expense_report_gen import (
    export_account_expense_csv,
    get_account_expense_report,
    get_member_expense_report,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["corporate-expense-report-gen"])


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------


async def _resolve_account_id(db: AsyncSession, user_id: int) -> int:
    """Return the corporate account ID for the current user or raise HTTP 404."""
    account = await get_user_account(db, user_id)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="You are not a member of any corporate account.",
        )
    return account.id


# ---------------------------------------------------------------------------
# Member: own expense report
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/members/me/expense-report",
    response_model=MemberExpenseReport,
    summary="Get my corporate expense report for a period",
)
async def get_my_expense_report(
    year: int = Query(..., ge=2000, le=2100, description="Calendar year (e.g. 2026)."),
    month: int | None = Query(
        None, ge=1, le=12, description="Month number 1-12.  Omit for a full-year report."
    ),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the current user's corporate rides aggregated for the given period.

    Any active corporate account member may call this endpoint for their own
    expenses.  The response includes per-ride line items and period totals.
    """
    account_id = await _resolve_account_id(db, user.id)
    return await get_member_expense_report(db, user.id, account_id, year, month)


# ---------------------------------------------------------------------------
# Admin: account-level expense report
# ---------------------------------------------------------------------------


@router.get(
    "/admin/corporate/accounts/{account_id}/expense-report",
    response_model=AccountExpenseReport,
    summary="Admin: get account expense report aggregated by dept and member",
)
async def get_account_report(
    account_id: int,
    year: int = Query(..., ge=2000, le=2100, description="Calendar year (e.g. 2026)."),
    month: int | None = Query(
        None, ge=1, le=12, description="Month number 1-12.  Omit for a full-year report."
    ),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the aggregated expense report for a corporate account.

    Accessible by:
    - Corporate account admins (ADMIN role within the account).
    - Platform admins (UserRole.ADMIN).

    The response breaks down spend by department and by individual member.
    """
    from app.models.corporate import BusinessAccountMember, MemberRole
    from sqlalchemy import select

    # Allow platform admins unrestricted access; otherwise require corp admin
    if user.role.value != "admin":
        admin_result = await db.execute(
            select(BusinessAccountMember).where(
                BusinessAccountMember.account_id == account_id,
                BusinessAccountMember.user_id == user.id,
                BusinessAccountMember.role == MemberRole.ADMIN,
                BusinessAccountMember.is_active.is_(True),
            )
        )
        if admin_result.scalar_one_or_none() is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have admin access to this corporate account.",
            )

    return await get_account_expense_report(db, account_id, year, month)


# ---------------------------------------------------------------------------
# Admin: CSV export
# ---------------------------------------------------------------------------


@router.get(
    "/admin/corporate/accounts/{account_id}/expense-report/csv",
    response_class=PlainTextResponse,
    summary="Admin: download account expense report as CSV",
)
async def get_account_report_csv(
    account_id: int,
    year: int = Query(..., ge=2000, le=2100, description="Calendar year (e.g. 2026)."),
    month: int | None = Query(
        None, ge=1, le=12, description="Month number 1-12.  Omit for a full-year report."
    ),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Download the account expense report as a CSV file.

    Accessible by:
    - Corporate account admins (ADMIN role within the account).
    - Platform admins (UserRole.ADMIN).

    Returns a ``text/plain`` response with CSV content and a
    ``Content-Disposition`` attachment header so browsers prompt a download.
    """
    from app.models.corporate import BusinessAccountMember, MemberRole
    from sqlalchemy import select

    # Allow platform admins unrestricted access; otherwise require corp admin
    if user.role.value != "admin":
        admin_result = await db.execute(
            select(BusinessAccountMember).where(
                BusinessAccountMember.account_id == account_id,
                BusinessAccountMember.user_id == user.id,
                BusinessAccountMember.role == MemberRole.ADMIN,
                BusinessAccountMember.is_active.is_(True),
            )
        )
        if admin_result.scalar_one_or_none() is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have admin access to this corporate account.",
            )

    csv_content = await export_account_expense_csv(db, account_id, year, month)

    from app.services.corporate_expense_report_gen import _period_label
    period = _period_label(year, month)
    filename = f"expense-report-account-{account_id}-{period}.csv"

    return PlainTextResponse(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
