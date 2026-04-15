"""Corporate Scheduled Report endpoints.

Enterprise admins configure automated periodic delivery of spending and usage
reports to a list of email recipients.

Admin endpoints (require account membership):
  GET    /corporate/accounts/me/scheduled-reports                         — list reports
  POST   /corporate/accounts/me/scheduled-reports                        — create report
  GET    /corporate/accounts/me/scheduled-reports/{report_id}            — get report
  PUT    /corporate/accounts/me/scheduled-reports/{report_id}            — update report
  POST   /corporate/accounts/me/scheduled-reports/{report_id}/deactivate — deactivate
  POST   /corporate/accounts/me/scheduled-reports/{report_id}/reactivate — reactivate
  DELETE /corporate/accounts/me/scheduled-reports/{report_id}            — hard-delete
  POST   /corporate/accounts/me/scheduled-reports/{report_id}/trigger    — trigger now

Platform-admin endpoints:
  GET  /admin/corporate/accounts/{account_id}/scheduled-reports          — list for any account
  GET  /admin/corporate/scheduled-reports/due                            — list currently-due reports
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, Query, status
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_admin
from app.models.user import User
from app.schemas.corporate_scheduled_report import (
    ScheduledReportCreate,
    ScheduledReportListResponse,
    ScheduledReportResponse,
    ScheduledReportTriggerResponse,
    ScheduledReportUpdate,
)
from app.services.corporate_account_mgmt import get_user_account
from app.services.corporate_scheduled_report import (
    create_scheduled_report,
    deactivate_scheduled_report,
    delete_scheduled_report,
    get_scheduled_report,
    list_due_reports,
    list_scheduled_reports,
    reactivate_scheduled_report,
    trigger_report_now,
    update_scheduled_report,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["corporate-scheduled-reports"])


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _resolve_account_id(db: AsyncSession, user_id: int) -> int:
    account = await get_user_account(db, user_id)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="You are not a member of any corporate account.",
        )
    return account.id


def _to_response(report) -> ScheduledReportResponse:
    return ScheduledReportResponse.model_validate(report)


# ---------------------------------------------------------------------------
# Admin: list reports
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/scheduled-reports",
    response_model=ScheduledReportListResponse,
    summary="Admin: list scheduled reports for my corporate account",
)
async def list_account_scheduled_reports(
    active_only: bool = Query(True, description="When True, only return active reports."),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all scheduled reports configured for the caller's corporate account."""
    account_id = await _resolve_account_id(db, user.id)
    reports = await list_scheduled_reports(db, account_id, active_only=active_only)
    return ScheduledReportListResponse(
        account_id=account_id,
        total=len(reports),
        items=[_to_response(r) for r in reports],
    )


# ---------------------------------------------------------------------------
# Admin: create report
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/accounts/me/scheduled-reports",
    response_model=ScheduledReportResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Admin: create a scheduled report",
)
async def create_account_scheduled_report(
    data: ScheduledReportCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Configure a new automated report delivery schedule.

    ``day_of_week`` (0=Monday … 6=Sunday) is required when ``frequency`` is
    ``weekly``.  ``day_of_month`` (1–28) is required when ``frequency`` is
    ``monthly``.
    """
    account_id = await _resolve_account_id(db, user.id)
    report = await create_scheduled_report(
        db,
        account_id=account_id,
        name=data.name,
        report_type=data.report_type,
        frequency=data.frequency,
        recipients=data.recipients,
        day_of_week=data.day_of_week,
        day_of_month=data.day_of_month,
        created_by_id=user.id,
    )
    await db.commit()
    return _to_response(report)


# ---------------------------------------------------------------------------
# Admin: get report
# ---------------------------------------------------------------------------


@router.get(
    "/corporate/accounts/me/scheduled-reports/{report_id}",
    response_model=ScheduledReportResponse,
    summary="Admin: get a scheduled report by ID",
)
async def get_account_scheduled_report(
    report_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a specific scheduled report record."""
    account_id = await _resolve_account_id(db, user.id)
    report = await get_scheduled_report(db, account_id, report_id)
    return _to_response(report)


# ---------------------------------------------------------------------------
# Admin: update report
# ---------------------------------------------------------------------------


@router.put(
    "/corporate/accounts/me/scheduled-reports/{report_id}",
    response_model=ScheduledReportResponse,
    summary="Admin: update a scheduled report",
)
async def update_account_scheduled_report(
    report_id: uuid.UUID,
    data: ScheduledReportUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Partially update a scheduled report.  All fields are optional.

    Changing ``frequency``, ``day_of_week``, or ``day_of_month`` recomputes
    ``next_due_at`` from now.
    """
    account_id = await _resolve_account_id(db, user.id)
    report = await update_scheduled_report(
        db,
        account_id=account_id,
        report_id=report_id,
        name=data.name,
        report_type=data.report_type,
        frequency=data.frequency,
        day_of_week=data.day_of_week,
        day_of_month=data.day_of_month,
        recipients=data.recipients,
    )
    await db.commit()
    return _to_response(report)


# ---------------------------------------------------------------------------
# Admin: deactivate (soft-disable)
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/accounts/me/scheduled-reports/{report_id}/deactivate",
    response_model=ScheduledReportResponse,
    summary="Admin: deactivate a scheduled report",
)
async def deactivate_account_scheduled_report(
    report_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Pause automated delivery without deleting the configuration."""
    account_id = await _resolve_account_id(db, user.id)
    report = await deactivate_scheduled_report(db, account_id, report_id)
    await db.commit()
    return _to_response(report)


# ---------------------------------------------------------------------------
# Admin: reactivate
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/accounts/me/scheduled-reports/{report_id}/reactivate",
    response_model=ScheduledReportResponse,
    summary="Admin: reactivate a deactivated scheduled report",
)
async def reactivate_account_scheduled_report(
    report_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Resume automated delivery for a previously deactivated report.

    ``next_due_at`` is recomputed from the current time.
    """
    account_id = await _resolve_account_id(db, user.id)
    report = await reactivate_scheduled_report(db, account_id, report_id)
    await db.commit()
    return _to_response(report)


# ---------------------------------------------------------------------------
# Admin: hard-delete
# ---------------------------------------------------------------------------


@router.delete(
    "/corporate/accounts/me/scheduled-reports/{report_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Admin: permanently delete a scheduled report",
)
async def delete_account_scheduled_report(
    report_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Permanently remove a scheduled report configuration."""
    account_id = await _resolve_account_id(db, user.id)
    await delete_scheduled_report(db, account_id, report_id)
    await db.commit()


# ---------------------------------------------------------------------------
# Admin: trigger report now
# ---------------------------------------------------------------------------


@router.post(
    "/corporate/accounts/me/scheduled-reports/{report_id}/trigger",
    response_model=ScheduledReportTriggerResponse,
    summary="Admin: trigger a scheduled report immediately",
)
async def trigger_account_scheduled_report(
    report_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Simulate an immediate delivery of the report to all configured recipients.

    Updates ``last_sent_at`` and advances ``next_due_at``.  Useful for testing
    report configuration before the first scheduled delivery.
    """
    account_id = await _resolve_account_id(db, user.id)
    result = await trigger_report_now(db, account_id, report_id)
    await db.commit()
    return ScheduledReportTriggerResponse(**result)


# ---------------------------------------------------------------------------
# Platform-admin: list reports for any account
# ---------------------------------------------------------------------------


@router.get(
    "/admin/corporate/accounts/{account_id}/scheduled-reports",
    response_model=ScheduledReportListResponse,
    summary="Platform admin: list all scheduled reports for a corporate account",
)
async def platform_admin_list_scheduled_reports(
    account_id: int,
    active_only: bool = Query(False),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return all scheduled reports for any corporate account.

    Requires platform-level admin role.
    """
    reports = await list_scheduled_reports(db, account_id, active_only=active_only)
    return ScheduledReportListResponse(
        account_id=account_id,
        total=len(reports),
        items=[_to_response(r) for r in reports],
    )


# ---------------------------------------------------------------------------
# Platform-admin: list due reports (for background scheduler)
# ---------------------------------------------------------------------------


@router.get(
    "/admin/corporate/scheduled-reports/due",
    response_model=list[ScheduledReportResponse],
    summary="Platform admin: list all scheduled reports currently due for delivery",
)
async def platform_admin_list_due_reports(
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return all active reports whose ``next_due_at`` is now or in the past.

    Intended for the background scheduler to determine what to deliver.
    Requires platform-level admin role.
    """
    reports = await list_due_reports(db)
    return [_to_response(r) for r in reports]
