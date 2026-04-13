"""Service layer for the lost and found feature.

Encapsulates business logic:
- create_report: validate ride ownership if provided, create report
- get_report: enforce ownership (rider/driver see own reports only; admin sees all)
- list_reports_for_user: list reports for a rider or driver
- list_all_reports: admin query with filters
- match_reports: admin links a found report to a lost report (MATCHED status)
- resolve_report: admin closes a report (RETURNED, DONATED, or DISCARDED)

All functions that modify state call db.flush() but leave commit to the caller.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lost_found import LostItemCategory, LostItemReport, LostItemStatus

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Terminal statuses that end the lifecycle of a report
_TERMINAL_STATUSES = {LostItemStatus.RETURNED, LostItemStatus.DONATED, LostItemStatus.DISCARDED}

# Valid resolutions an admin may set when calling resolve_report
RESOLVABLE_STATUSES = {LostItemStatus.RETURNED, LostItemStatus.DONATED, LostItemStatus.DISCARDED}


class LostFoundError(Exception):
    """Business-logic error raised by the lost and found service."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


async def create_report(
    db: AsyncSession,
    reporter_id: int,
    reporter_type: str,
    description: str,
    category: LostItemCategory,
    ride_id: int | None = None,
    color: str | None = None,
    contact_phone: str | None = None,
    contact_email: str | None = None,
) -> LostItemReport:
    """Create a lost or found item report.

    If ride_id is provided the reporter must be a participant (rider or driver)
    in that ride. Raises LostFoundError if the ride does not exist or the
    reporter is not a participant.
    """
    if ride_id is not None:
        from app.models.ride import Ride

        result = await db.execute(select(Ride).where(Ride.id == ride_id))
        ride = result.scalar_one_or_none()
        if not ride:
            raise LostFoundError("Ride not found", status_code=404)
        if ride.rider_id != reporter_id and ride.driver_id != reporter_id:
            raise LostFoundError("You are not a participant in this ride", status_code=403)

    report = LostItemReport(
        ride_id=ride_id,
        reporter_type=reporter_type,
        reporter_id=reporter_id,
        description=description,
        category=category,
        color=color,
        status=LostItemStatus.REPORTED,
        contact_phone=contact_phone,
        contact_email=contact_email,
    )
    db.add(report)
    await db.flush()
    return report


async def get_report(
    db: AsyncSession,
    report_id: int,
    requesting_user_id: int,
    is_admin: bool = False,
) -> LostItemReport:
    """Fetch a single report, enforcing ownership for non-admins.

    Raises LostFoundError(404) if the report does not exist.
    Raises LostFoundError(403) if the requester is not the reporter and not admin.
    """
    result = await db.execute(
        select(LostItemReport).where(LostItemReport.id == report_id)
    )
    report = result.scalar_one_or_none()
    if not report:
        raise LostFoundError("Report not found", status_code=404)
    if not is_admin and report.reporter_id != requesting_user_id:
        raise LostFoundError("Not authorised to view this report", status_code=403)
    return report


async def list_reports_for_user(
    db: AsyncSession,
    reporter_id: int,
    reporter_type: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> list[LostItemReport]:
    """List reports created by a specific user, ordered newest first."""
    filters = [LostItemReport.reporter_id == reporter_id]
    if reporter_type is not None:
        filters.append(LostItemReport.reporter_type == reporter_type)

    result = await db.execute(
        select(LostItemReport)
        .where(and_(*filters))
        .order_by(LostItemReport.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all())


async def list_all_reports(
    db: AsyncSession,
    status_filter: LostItemStatus | None = None,
    category_filter: LostItemCategory | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[LostItemReport]:
    """Admin query: list all reports with optional filters, newest first."""
    filters: list = []

    if status_filter is not None:
        filters.append(LostItemReport.status == status_filter)
    if category_filter is not None:
        filters.append(LostItemReport.category == category_filter)
    if date_from is not None:
        filters.append(LostItemReport.created_at >= date_from)
    if date_to is not None:
        filters.append(LostItemReport.created_at <= date_to)

    query = (
        select(LostItemReport)
        .order_by(LostItemReport.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    if filters:
        query = query.where(and_(*filters))

    result = await db.execute(query)
    return list(result.scalars().all())


async def match_reports(
    db: AsyncSession,
    report_id: int,
    matched_report_id: int,
    admin_id: int,
) -> tuple[LostItemReport, LostItemReport]:
    """Link two reports together and set both to MATCHED status.

    Validates:
    - Both reports exist.
    - Neither report is already in a terminal state.
    - A report cannot be matched to itself.

    Returns the (primary, matched) report pair.
    """
    if report_id == matched_report_id:
        raise LostFoundError("A report cannot be matched to itself", status_code=400)

    # Load both reports
    result_a = await db.execute(
        select(LostItemReport).where(LostItemReport.id == report_id)
    )
    report_a = result_a.scalar_one_or_none()
    if not report_a:
        raise LostFoundError("Report not found", status_code=404)

    result_b = await db.execute(
        select(LostItemReport).where(LostItemReport.id == matched_report_id)
    )
    report_b = result_b.scalar_one_or_none()
    if not report_b:
        raise LostFoundError("Matched report not found", status_code=404)

    for rep in (report_a, report_b):
        if rep.status in _TERMINAL_STATUSES:
            raise LostFoundError(
                f"Report {rep.id} is already resolved and cannot be matched",
                status_code=409,
            )

    report_a.status = LostItemStatus.MATCHED
    report_a.matched_report_id = matched_report_id
    report_a.admin_id = admin_id

    report_b.status = LostItemStatus.MATCHED
    report_b.matched_report_id = report_id
    report_b.admin_id = admin_id

    await db.flush()

    # Notify both reporters of the match — fire-and-forget
    try:
        await _notify_match(db, report_a, report_b)
    except Exception:
        logger.exception("Failed to send match notifications for reports %d / %d", report_id, matched_report_id)

    return report_a, report_b


async def resolve_report(
    db: AsyncSession,
    report_id: int,
    new_status: LostItemStatus,
    admin_id: int,
    resolution_notes: str | None = None,
) -> LostItemReport:
    """Admin closes a report with a terminal status.

    Only MATCHED (or CLAIMED) reports may be resolved into RETURNED.
    Any MATCHED/REPORTED report can be resolved into DONATED or DISCARDED.

    Raises LostFoundError for invalid transitions.
    """
    if new_status not in RESOLVABLE_STATUSES:
        raise LostFoundError(
            f"Status must be one of: {', '.join(s.value for s in RESOLVABLE_STATUSES)}",
            status_code=422,
        )

    result = await db.execute(
        select(LostItemReport).where(LostItemReport.id == report_id)
    )
    report = result.scalar_one_or_none()
    if not report:
        raise LostFoundError("Report not found", status_code=404)

    if report.status in _TERMINAL_STATUSES:
        raise LostFoundError(
            f"Report is already resolved with status '{report.status.value}'",
            status_code=409,
        )

    # RETURNED requires the report to have been MATCHED (or CLAIMED) first
    if new_status == LostItemStatus.RETURNED and report.status == LostItemStatus.REPORTED:
        raise LostFoundError(
            "A report must be matched before it can be marked as returned",
            status_code=409,
        )

    report.status = new_status
    report.admin_id = admin_id
    report.resolved_at = datetime.now(timezone.utc)
    report.resolution_notes = resolution_notes

    await db.flush()
    return report


async def _notify_match(
    db: AsyncSession,
    report_a: LostItemReport,
    report_b: LostItemReport,
) -> None:
    """Log match notification intent for both reporters.

    In a production deployment this would dispatch SMS/push via the
    notification service. The fire-and-forget pattern here mirrors
    how safety.py handles SOS notifications: failures must never
    propagate and block the match operation.
    """
    for report in (report_a, report_b):
        logger.info(
            "Lost-item match notification queued for reporter_id=%d report_id=%d",
            report.reporter_id,
            report.id,
        )
