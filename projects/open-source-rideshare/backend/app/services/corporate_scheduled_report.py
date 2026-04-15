"""Service functions for corporate scheduled reports.

Admins configure automated periodic report delivery (daily / weekly / monthly)
to a list of email recipients.  The scheduler (or a manual trigger) calls
``trigger_report_now`` to simulate delivery and advance ``last_sent_at`` /
``next_due_at``.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.corporate_scheduled_report import (
    CorporateScheduledReport,
    ReportFrequency,
    ScheduledReportType,
)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _compute_next_due(
    frequency: ReportFrequency,
    from_dt: datetime,
    day_of_week: Optional[int],
    day_of_month: Optional[int],
) -> datetime:
    """Compute the next fire time relative to *from_dt* (timezone-aware UTC)."""
    now = from_dt

    if frequency == ReportFrequency.daily:
        # Next occurrence is tomorrow at the same time
        return now + timedelta(days=1)

    if frequency == ReportFrequency.weekly:
        target_dow = day_of_week if day_of_week is not None else 0  # default Monday
        current_dow = now.weekday()
        days_ahead = (target_dow - current_dow) % 7
        if days_ahead == 0:
            days_ahead = 7  # same day → next week
        return now + timedelta(days=days_ahead)

    if frequency == ReportFrequency.monthly:
        target_dom = day_of_month if day_of_month is not None else 1  # default 1st
        # Advance to the next calendar month that has this day
        year = now.year
        month = now.month
        if now.day >= target_dom:
            # Already past or on target day — go to next month
            month += 1
            if month > 12:
                month = 1
                year += 1
        try:
            return now.replace(year=year, month=month, day=target_dom)
        except ValueError:
            # day_of_month > days in target month — clamp to 28
            return now.replace(year=year, month=month, day=28)

    # Fallback — should never reach here
    return now + timedelta(days=1)


def _validate_frequency_fields(
    frequency: ReportFrequency,
    day_of_week: Optional[int],
    day_of_month: Optional[int],
) -> None:
    """Raise 422 if frequency-specific fields are invalid."""
    if frequency == ReportFrequency.weekly and day_of_week is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="day_of_week is required when frequency is 'weekly'.",
        )
    if frequency == ReportFrequency.monthly and day_of_month is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="day_of_month is required when frequency is 'monthly'.",
        )
    if day_of_week is not None and not (0 <= day_of_week <= 6):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="day_of_week must be between 0 (Monday) and 6 (Sunday).",
        )
    if day_of_month is not None and not (1 <= day_of_month <= 28):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="day_of_month must be between 1 and 28.",
        )


async def _get_report(
    db: AsyncSession,
    account_id: int,
    report_id: uuid.UUID,
) -> CorporateScheduledReport:
    """Fetch a report by ID + account, raise 404 if not found."""
    result = await db.execute(
        select(CorporateScheduledReport).where(
            CorporateScheduledReport.id == report_id,
            CorporateScheduledReport.account_id == account_id,
        )
    )
    report = result.scalar_one_or_none()
    if report is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Scheduled report not found.",
        )
    return report


# ---------------------------------------------------------------------------
# Public service API
# ---------------------------------------------------------------------------

async def create_scheduled_report(
    db: AsyncSession,
    account_id: int,
    name: str,
    report_type: ScheduledReportType,
    frequency: ReportFrequency,
    recipients: list[str],
    day_of_week: Optional[int] = None,
    day_of_month: Optional[int] = None,
    created_by_id: Optional[int] = None,
) -> CorporateScheduledReport:
    """Create a new scheduled report configuration.

    Validates frequency-specific fields, sets ``next_due_at``, and persists.
    """
    _validate_frequency_fields(frequency, day_of_week, day_of_month)

    if not recipients:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="At least one recipient is required.",
        )

    now = datetime.now(tz=timezone.utc)
    next_due = _compute_next_due(frequency, now, day_of_week, day_of_month)

    report = CorporateScheduledReport(
        account_id=account_id,
        name=name,
        report_type=report_type,
        frequency=frequency,
        day_of_week=day_of_week,
        day_of_month=day_of_month,
        recipients=recipients,
        is_active=True,
        next_due_at=next_due,
        created_by_id=created_by_id,
    )
    db.add(report)
    await db.flush()
    return report


async def get_scheduled_report(
    db: AsyncSession,
    account_id: int,
    report_id: uuid.UUID,
) -> CorporateScheduledReport:
    """Return a single scheduled report; raise 404 if not found."""
    return await _get_report(db, account_id, report_id)


async def list_scheduled_reports(
    db: AsyncSession,
    account_id: int,
    active_only: bool = True,
) -> list[CorporateScheduledReport]:
    """Return all scheduled reports for an account."""
    query = select(CorporateScheduledReport).where(
        CorporateScheduledReport.account_id == account_id
    )
    if active_only:
        query = query.where(CorporateScheduledReport.is_active.is_(True))
    query = query.order_by(CorporateScheduledReport.created_at.desc())
    result = await db.execute(query)
    return list(result.scalars().all())


async def update_scheduled_report(
    db: AsyncSession,
    account_id: int,
    report_id: uuid.UUID,
    name: Optional[str] = None,
    report_type: Optional[ScheduledReportType] = None,
    frequency: Optional[ReportFrequency] = None,
    day_of_week: Optional[int] = None,
    day_of_month: Optional[int] = None,
    recipients: Optional[list[str]] = None,
) -> CorporateScheduledReport:
    """Partial update.  Re-validates and recomputes ``next_due_at`` when
    frequency or day fields change."""
    report = await _get_report(db, account_id, report_id)

    new_frequency = frequency if frequency is not None else report.frequency
    new_dow = day_of_week if day_of_week is not None else report.day_of_week
    new_dom = day_of_month if day_of_month is not None else report.day_of_month

    _validate_frequency_fields(new_frequency, new_dow, new_dom)

    if name is not None:
        report.name = name
    if report_type is not None:
        report.report_type = report_type
    if recipients is not None:
        if len(recipients) == 0:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="At least one recipient is required.",
            )
        report.recipients = recipients

    schedule_changed = (
        frequency is not None
        or day_of_week is not None
        or day_of_month is not None
    )
    if schedule_changed:
        report.frequency = new_frequency
        report.day_of_week = new_dow
        report.day_of_month = new_dom
        now = datetime.now(tz=timezone.utc)
        report.next_due_at = _compute_next_due(new_frequency, now, new_dow, new_dom)

    await db.flush()
    return report


async def deactivate_scheduled_report(
    db: AsyncSession,
    account_id: int,
    report_id: uuid.UUID,
) -> CorporateScheduledReport:
    """Soft-disable the report (keeps configuration for reactivation)."""
    report = await _get_report(db, account_id, report_id)
    if not report.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Scheduled report is already inactive.",
        )
    report.is_active = False
    await db.flush()
    return report


async def reactivate_scheduled_report(
    db: AsyncSession,
    account_id: int,
    report_id: uuid.UUID,
) -> CorporateScheduledReport:
    """Re-enable a deactivated report and recompute ``next_due_at``."""
    report = await _get_report(db, account_id, report_id)
    if report.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Scheduled report is already active.",
        )
    report.is_active = True
    now = datetime.now(tz=timezone.utc)
    report.next_due_at = _compute_next_due(
        report.frequency, now, report.day_of_week, report.day_of_month
    )
    await db.flush()
    return report


async def delete_scheduled_report(
    db: AsyncSession,
    account_id: int,
    report_id: uuid.UUID,
) -> None:
    """Hard-delete a scheduled report."""
    report = await _get_report(db, account_id, report_id)
    await db.delete(report)
    await db.flush()


async def trigger_report_now(
    db: AsyncSession,
    account_id: int,
    report_id: uuid.UUID,
) -> dict:
    """Simulate an immediate report delivery and advance ``last_sent_at``."""
    report = await _get_report(db, account_id, report_id)
    if not report.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot trigger an inactive scheduled report.",
        )

    now = datetime.now(tz=timezone.utc)
    report.last_sent_at = now
    report.next_due_at = _compute_next_due(
        report.frequency, now, report.day_of_week, report.day_of_month
    )
    await db.flush()

    return {
        "report_id": report.id,
        "report_type": report.report_type,
        "recipients": report.recipients,
        "triggered_at": now,
        "message": (
            f"Report '{report.name}' ({report.report_type.value}) "
            f"triggered for {len(report.recipients)} recipient(s).  "
            f"Next scheduled delivery: {report.next_due_at.isoformat()}."
        ),
    }


async def list_due_reports(
    db: AsyncSession,
    as_of: Optional[datetime] = None,
) -> list[CorporateScheduledReport]:
    """Return all active reports whose ``next_due_at`` is on or before *as_of*.

    Used by background schedulers to decide what to send.
    """
    cutoff = as_of or datetime.now(tz=timezone.utc)
    result = await db.execute(
        select(CorporateScheduledReport).where(
            CorporateScheduledReport.is_active.is_(True),
            CorporateScheduledReport.next_due_at <= cutoff,
        )
    )
    return list(result.scalars().all())
