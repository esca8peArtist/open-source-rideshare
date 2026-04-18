"""Post-ride rider safety report service.

Riders can file a safety report after a COMPLETED ride to flag concerns about
driver behaviour, vehicle condition, routing, or other incidents.  Reports are
assigned PENDING status and routed to admin review.

Unlike panic alerts (in-ride emergencies), safety reports are retrospective —
they capture what happened and feed into driver quality and safety workflows.

Public API:
    create_report(db, rider_id, ride_id, driver_id, category, description,
                  location_lat, location_lng) -> dict
    get_report(db, rider_id, report_id) -> dict | None
    list_rider_reports(db, rider_id, skip, limit) -> tuple[int, list[dict]]
    admin_list_reports(db, status_filter, category_filter, skip, limit) -> tuple[int, list[dict]]
    admin_review_report(db, report_id, admin_id, review_status, admin_notes) -> dict
    get_safety_report_stats(db) -> dict
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.rider_safety_report import SafetyReportCategory, SafetyReportStatus

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# In-memory store (same pattern as other services)
# ---------------------------------------------------------------------------

_safety_reports: dict[str, dict] = {}

# One report per rider per ride — prevents spam
MAX_REPORTS_PER_RIDER_PER_RIDE = 1


def _utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _new_id() -> str:
    return str(uuid.uuid4())


def _reset_store() -> None:
    """Clear all in-memory state.  For use in tests only."""
    _safety_reports.clear()


# ---------------------------------------------------------------------------
# Rider operations
# ---------------------------------------------------------------------------


async def create_report(
    db: AsyncSession,
    rider_id: int,
    ride_id: int,
    driver_id: int,
    category: SafetyReportCategory,
    description: str,
    location_lat: Optional[float] = None,
    location_lng: Optional[float] = None,
) -> dict:
    """File a post-ride safety report.

    One report per rider per ride is permitted.  If the rider has already
    filed a report for this ride, raises ValueError.

    Args:
        db:           Async DB session (unused — in-memory implementation).
        rider_id:     ID of the authenticated rider.
        ride_id:      ID of the completed ride.
        driver_id:    ID of the driver on the ride.
        category:     Type of safety concern.
        description:  Rider's account of what happened.
        location_lat: Optional latitude of the incident.
        location_lng: Optional longitude of the incident.

    Returns:
        Newly created safety report dict.

    Raises:
        ValueError: If the rider already filed a report for this ride.
    """
    existing = [
        r for r in _safety_reports.values()
        if r["rider_id"] == rider_id and r["ride_id"] == ride_id
    ]
    if existing:
        raise ValueError(
            f"A safety report for ride {ride_id} has already been filed."
        )

    report_id = _new_id()
    report = {
        "id": report_id,
        "ride_id": ride_id,
        "rider_id": rider_id,
        "driver_id": driver_id,
        "category": category,
        "description": description,
        "status": SafetyReportStatus.PENDING,
        "location_lat": location_lat,
        "location_lng": location_lng,
        "filed_at": _utc_now(),
        "reviewed_at": None,
        "reviewed_by": None,
        "admin_notes": None,
    }
    _safety_reports[report_id] = report
    logger.info(
        "Safety report filed — rider=%s ride=%s driver=%s category=%s report=%s",
        rider_id, ride_id, driver_id, category.value, report_id,
    )
    return dict(report)


async def get_report(
    db: AsyncSession,
    rider_id: int,
    report_id: str,
) -> Optional[dict]:
    """Retrieve a safety report owned by the given rider.

    Returns None if the report does not exist or belongs to a different rider.
    Callers should raise HTTP 404 in either case.

    Args:
        db:        Async DB session (unused).
        rider_id:  ID of the authenticated rider.
        report_id: UUID of the report.

    Returns:
        Report dict if found and owned by rider_id, else None.
    """
    report = _safety_reports.get(report_id)
    if report is None or report["rider_id"] != rider_id:
        return None
    return dict(report)


async def list_rider_reports(
    db: AsyncSession,
    rider_id: int,
    skip: int = 0,
    limit: int = 20,
) -> tuple[int, list[dict]]:
    """Return paginated safety reports for a rider, newest-first.

    Args:
        db:       Async DB session (unused).
        rider_id: ID of the authenticated rider.
        skip:     Pagination offset.
        limit:    Maximum records to return.

    Returns:
        (total, items) — total count for this rider and the requested page.
    """
    rider_reports = [
        r for r in _safety_reports.values() if r["rider_id"] == rider_id
    ]
    rider_reports.sort(key=lambda r: r["filed_at"], reverse=True)
    total = len(rider_reports)
    page = rider_reports[skip: skip + limit]
    return total, [dict(r) for r in page]


# ---------------------------------------------------------------------------
# Admin operations
# ---------------------------------------------------------------------------


async def admin_list_reports(
    db: AsyncSession,
    status_filter: Optional[str] = None,
    category_filter: Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
) -> tuple[int, list[dict]]:
    """Return paginated safety reports for admin review, newest-first.

    Args:
        db:              Async DB session (unused).
        status_filter:   If set, only return reports with this status string.
        category_filter: If set, only return reports with this category string.
        skip:            Pagination offset.
        limit:           Maximum records to return.

    Returns:
        (total, items) — filtered total and the requested page.
    """
    reports = list(_safety_reports.values())

    if status_filter:
        reports = [r for r in reports if r["status"].value == status_filter]
    if category_filter:
        reports = [r for r in reports if r["category"].value == category_filter]

    reports.sort(key=lambda r: r["filed_at"], reverse=True)
    total = len(reports)
    page = reports[skip: skip + limit]
    return total, [dict(r) for r in page]


async def admin_review_report(
    db: AsyncSession,
    report_id: str,
    admin_id: int,
    review_status: SafetyReportStatus,
    admin_notes: Optional[str] = None,
) -> dict:
    """Admin reviews a safety report, setting it to REVIEWED, ESCALATED, or CLOSED.

    Args:
        db:            Async DB session (unused).
        report_id:     UUID of the report to review.
        admin_id:      ID of the admin performing the review.
        review_status: New status — must be REVIEWED, ESCALATED, or CLOSED.
        admin_notes:   Optional notes on the review outcome.

    Returns:
        Updated report dict.

    Raises:
        KeyError:   If the report does not exist.
        ValueError: If review_status is PENDING (invalid transition) or the
                    report has already been reviewed/closed.
    """
    report = _safety_reports.get(report_id)
    if report is None:
        raise KeyError(f"Safety report {report_id} not found.")

    if review_status == SafetyReportStatus.PENDING:
        raise ValueError("Cannot set status back to 'pending'.")

    if report["status"] != SafetyReportStatus.PENDING:
        raise ValueError(
            f"Report is already in status '{report['status'].value}'. "
            "Only PENDING reports can be reviewed."
        )

    now = _utc_now()
    report["status"] = review_status
    report["reviewed_at"] = now
    report["reviewed_by"] = admin_id
    report["admin_notes"] = admin_notes
    logger.info(
        "Admin %s reviewed safety report %s — new status: %s",
        admin_id, report_id, review_status.value,
    )
    return dict(report)


async def get_safety_report_stats(db: AsyncSession) -> dict:
    """Return aggregate statistics across all safety reports.

    Computes counts broken down by status and category, the escalation rate,
    rolling counts for the last 7 and 30 days, and average resolution time
    (hours from filed_at to reviewed_at) for resolved reports.

    Args:
        db: Async DB session (unused — in-memory implementation).

    Returns:
        Dict matching the SafetyReportStats schema.
    """
    reports = list(_safety_reports.values())
    total = len(reports)

    # Counts by status
    by_status: dict[str, int] = {s.value: 0 for s in SafetyReportStatus}
    for r in reports:
        by_status[r["status"].value] += 1

    # Counts by category
    by_category: dict[str, int] = {c.value: 0 for c in SafetyReportCategory}
    for r in reports:
        by_category[r["category"].value] += 1

    # Escalation rate
    escalation_rate = (
        by_status[SafetyReportStatus.ESCALATED.value] / total if total > 0 else 0.0
    )

    # Rolling window counts
    now = _utc_now()
    cutoff_7 = now - timedelta(days=7)
    cutoff_30 = now - timedelta(days=30)
    reports_last_7_days = sum(
        1 for r in reports if r["filed_at"] >= cutoff_7
    )
    reports_last_30_days = sum(
        1 for r in reports if r["filed_at"] >= cutoff_30
    )

    # Average resolution hours (REVIEWED, ESCALATED, CLOSED)
    resolved_statuses = {
        SafetyReportStatus.REVIEWED,
        SafetyReportStatus.ESCALATED,
        SafetyReportStatus.CLOSED,
    }
    resolution_hours = [
        (r["reviewed_at"] - r["filed_at"]).total_seconds() / 3600.0
        for r in reports
        if r["status"] in resolved_statuses and r["reviewed_at"] is not None
    ]
    avg_resolution_hours: Optional[float] = (
        sum(resolution_hours) / len(resolution_hours)
        if resolution_hours
        else None
    )

    return {
        "total_reports": total,
        "by_status": by_status,
        "by_category": by_category,
        "escalation_rate": escalation_rate,
        "reports_last_7_days": reports_last_7_days,
        "reports_last_30_days": reports_last_30_days,
        "avg_resolution_hours": avg_resolution_hours,
    }
