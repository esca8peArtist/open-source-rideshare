"""Corporate Expense Report Aggregation endpoints.

Admin endpoints (require admin role within the corporate account):
  GET  /corporate/{corp_id}/expense-reports
      — list previously generated expense reports (supports date range filter)
  POST /corporate/{corp_id}/expense-reports/generate
      — generate a new aggregated expense report for a date range
  GET  /corporate/{corp_id}/expense-reports/{report_id}
      — get full details of a generated report
  GET  /corporate/{corp_id}/expense-reports/{report_id}/export
      — download the report as a CSV file
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.models.user import User
from app.schemas.corporate_expense_report_aggregate import (
    ExpenseReportGenerateRequest,
    GeneratedExpenseReportDetail,
    GeneratedExpenseReportListResponse,
)
from app.services.corporate_expense_report_service import (
    export_report_csv,
    generate_expense_report,
    get_generated_report,
    list_generated_reports,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["corporate-expense-report-aggregates"])


# ---------------------------------------------------------------------------
# List generated reports
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{corp_id}/expense-reports",
    response_model=GeneratedExpenseReportListResponse,
    summary="List generated expense reports for a corporate account",
)
async def list_expense_reports(
    corp_id: int,
    start_date: Optional[date] = Query(
        None,
        description="Filter: only reports whose period starts on or after this date.",
    ),
    end_date: Optional[date] = Query(
        None,
        description="Filter: only reports whose period ends on or before this date.",
    ),
    skip: int = Query(0, ge=0, description="Pagination offset."),
    limit: int = Query(50, ge=1, le=200, description="Maximum reports to return."),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> GeneratedExpenseReportListResponse:
    """Return a paginated list of previously generated expense reports.

    Only admins of the given corporate account may call this endpoint.
    Optionally filter by the report's date range using ``start_date`` and
    ``end_date`` query parameters.
    """
    return await list_generated_reports(
        db,
        corp_id=corp_id,
        requester_id=user.id,
        start_date=start_date,
        end_date=end_date,
        skip=skip,
        limit=limit,
    )


# ---------------------------------------------------------------------------
# Generate a new report
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/{corp_id}/expense-reports/generate",
    response_model=GeneratedExpenseReportDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Generate a new aggregated expense report",
)
async def generate_report(
    corp_id: int,
    data: ExpenseReportGenerateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> GeneratedExpenseReportDetail:
    """Generate an aggregated expense report covering all rides billed to the
    corporate account between ``start_date`` and ``end_date`` (inclusive).

    The report breaks spending down by member and by ride category.  Only
    admins of the given corporate account may generate reports.
    """
    return await generate_expense_report(
        db,
        corp_id=corp_id,
        requester_id=user.id,
        data=data,
    )


# ---------------------------------------------------------------------------
# Get a single generated report
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{corp_id}/expense-reports/{report_id}",
    response_model=GeneratedExpenseReportDetail,
    summary="Get details of a generated expense report",
)
async def get_expense_report_detail(
    corp_id: int,
    report_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> GeneratedExpenseReportDetail:
    """Return full details of a single generated expense report, including
    per-member and per-category breakdowns.

    Only admins of the given corporate account may view reports.
    """
    return await get_generated_report(
        db,
        corp_id=corp_id,
        report_id=report_id,
        requester_id=user.id,
    )


# ---------------------------------------------------------------------------
# Export a report as CSV
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/{corp_id}/expense-reports/{report_id}/export",
    response_class=PlainTextResponse,
    summary="Export a generated expense report as CSV",
    responses={
        200: {
            "content": {"text/csv": {}},
            "description": "CSV file containing the expense report data.",
        }
    },
)
async def export_expense_report(
    corp_id: int,
    report_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PlainTextResponse:
    """Download a generated expense report as a CSV file.

    The CSV includes a header section with report metadata, followed by
    per-member totals and per-category totals.  Only admins of the given
    corporate account may export reports.
    """
    csv_content = await export_report_csv(
        db,
        corp_id=corp_id,
        report_id=report_id,
        requester_id=user.id,
    )
    filename = f"expense_report_{corp_id}_{report_id}.csv"
    return PlainTextResponse(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
