"""Post-ride driver safety report service.

Drivers can file a safety report after a COMPLETED ride to flag concerns about
rider behaviour: threats, assault, property damage, fraud, or other incidents.
Reports are assigned PENDING status and routed to admin review.

Unlike panic alerts (in-ride emergencies), safety reports are retrospective —
they capture what happened and feed into rider quality and safety workflows.

Public API:
    create_report(db, driver_id, ride_id, rider_id, category, description,
                  location_lat, location_lng) -> dict
    get_report(db, driver_id, report_id) -> dict | None
    list_driver_reports(db, driver_id, skip, limit) -> tuple[int, list[dict]]
    admin_list_reports(db, status_filter, category_filter, skip, limit) -> tuple[int, list[dict]]
    admin_review_report(db, report_id, admin_id, review_status, admin_notes) -> dict
    get_driver_safety_report_stats(db) -> dict
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.driver_safety_report import DriverReportCategory, DriverReportStatus
from app.services import rider_incident_flag as _incident_flag_svc

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# In-memory store (same pattern as rider_safety_report)
# ---------------------------------------------------------------------------

_driver_safety_reports: dict[str, dict] = {}

MAX_REPORTS_PER_DRIVER_PER_RIDE = 1


def _utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _new_id() -> str:
    return str(uuid.uuid4())


def _reset_store() -> None:
    """Clear all in-memory state.  For use in tests only."""
    _driver_safety_reports.clear()


# ---------------------------------------------------------------------------
# Driver operations
# ---------------------------------------------------------------------------


async def create_report(
    db: AsyncSession,
    driver_id: int,
    ride_id: int,
    rider_id: int,
    category: DriverReportCategory,
    description: str,
    location_lat: Optional[float] = None,
    location_lng: Optional[float] = None,
) -> dict:
    """File a post-ride safety report about a rider.

    One report per driver per ride is permitted.  Raises ValueError if the
    driver has already filed a report for this ride.

    Args:
        db:           Async DB session (unused — in-memory implementation).
        driver_id:    ID of the authenticated driver.
        ride_id:      ID of the completed ride.
        rider_id:     ID of the rider being reported.
        category:     Type of safety concern.
        description:  Driver's account of what happened.
        location_lat: Optional latitude of the incident.
        location_lng: Optional longitude of the incident.

    Returns:
        Newly created safety report dict.

    Raises:
        ValueError: If the driver already filed a report for this ride.
    """
    existing = [
        r for r in _driver_safety_reports.values()
        if r["driver_id"] == driver_id and r["ride_id"] == ride_id
    ]
    if existing:
        raise ValueError(
            f"A safety report for ride {ride_id} has already been filed."
        )

    report_id = _new_id()
    report = {
        "id": report_id,
        "ride_id": ride_id,
        "driver_id": driver_id,
        "rider_id": rider_id,
        "category": category,
        "description": description,
        "status": DriverReportStatus.PENDING,
        "location_lat": location_lat,
        "location_lng": location_lng,
        "filed_at": _utc_now(),
        "reviewed_at": None,
        "reviewed_by": None,
        "admin_notes": None,
    }
    _driver_safety_reports[report_id] = report
    logger.info(
        "Driver safety report filed — driver=%s ride=%s rider=%s category=%s report=%s",
        driver_id, ride_id, rider_id, category.value, report_id,
    )

    # Auto-flag the rider if they've hit the incident threshold.
    await _incident_flag_svc.check_and_flag_rider(
        db=db,
        rider_id=rider_id,
        all_reports=list(_driver_safety_reports.values()),
    )

    return dict(report)


async def get_report(
    db: AsyncSession,
    driver_id: int,
    report_id: str,
) -> Optional[dict]:
    """Retrieve a safety report owned by the given driver.

    Returns None if the report does not exist or belongs to a different driver.

    Args:
        db:        Async DB session (unused).
        driver_id: ID of the authenticated driver.
        report_id: UUID of the report.

    Returns:
        Report dict if found and owned by driver_id, else None.
    """
    report = _driver_safety_reports.get(report_id)
    if report is None or report["driver_id"] != driver_id:
        return None
    return dict(report)


async def list_driver_reports(
    db: AsyncSession,
    driver_id: int,
    skip: int = 0,
    limit: int = 20,
) -> tuple[int, list[dict]]:
    """Return paginated safety reports for a driver, newest-first.

    Args:
        db:        Async DB session (unused).
        driver_id: ID of the authenticated driver.
        skip:      Pagination offset.
        limit:     Maximum records to return.

    Returns:
        (total, items) — total count for this driver and the requested page.
    """
    driver_reports = [
        r for r in _driver_safety_reports.values() if r["driver_id"] == driver_id
    ]
    driver_reports.sort(key=lambda r: r["filed_at"], reverse=True)
    total = len(driver_reports)
    page = driver_reports[skip: skip + limit]
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
    """Return paginated driver safety reports for admin review, newest-first.

    Args:
        db:              Async DB session (unused).
        status_filter:   If set, only return reports with this status string.
        category_filter: If set, only return reports with this category string.
        skip:            Pagination offset.
        limit:           Maximum records to return.

    Returns:
        (total, items) — filtered total and the requested page.
    """
    reports = list(_driver_safety_reports.values())

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
    review_status: DriverReportStatus,
    admin_notes: Optional[str] = None,
) -> dict:
    """Admin reviews a driver safety report, transitioning it to REVIEWED, ESCALATED, or CLOSED.

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
    report = _driver_safety_reports.get(report_id)
    if report is None:
        raise KeyError(f"Driver safety report {report_id} not found.")

    if review_status == DriverReportStatus.PENDING:
        raise ValueError("Cannot set status back to 'pending'.")

    if report["status"] != DriverReportStatus.PENDING:
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
        "Admin %s reviewed driver safety report %s — new status: %s",
        admin_id, report_id, review_status.value,
    )
    return dict(report)


async def get_driver_safety_report_stats(db: AsyncSession) -> dict:
    """Return aggregate statistics across all driver safety reports.

    Computes counts broken down by status and category, the escalation rate,
    rolling counts for the last 7 and 30 days, and average resolution time
    (hours from filed_at to reviewed_at) for resolved reports.

    Args:
        db: Async DB session (unused — in-memory implementation).

    Returns:
        Dict matching the DriverSafetyReportStats schema.
    """
    reports = list(_driver_safety_reports.values())
    total = len(reports)

    by_status: dict[str, int] = {s.value: 0 for s in DriverReportStatus}
    for r in reports:
        by_status[r["status"].value] += 1

    by_category: dict[str, int] = {c.value: 0 for c in DriverReportCategory}
    for r in reports:
        by_category[r["category"].value] += 1

    escalation_rate = (
        by_status[DriverReportStatus.ESCALATED.value] / total if total > 0 else 0.0
    )

    now = _utc_now()
    cutoff_7 = now - timedelta(days=7)
    cutoff_30 = now - timedelta(days=30)
    reports_last_7_days = sum(1 for r in reports if r["filed_at"] >= cutoff_7)
    reports_last_30_days = sum(1 for r in reports if r["filed_at"] >= cutoff_30)

    resolved_statuses = {
        DriverReportStatus.REVIEWED,
        DriverReportStatus.ESCALATED,
        DriverReportStatus.CLOSED,
    }
    resolution_hours = [
        (r["reviewed_at"] - r["filed_at"]).total_seconds() / 3600.0
        for r in reports
        if r["status"] in resolved_statuses and r["reviewed_at"] is not None
    ]
    avg_resolution_hours: Optional[float] = (
        sum(resolution_hours) / len(resolution_hours) if resolution_hours else None
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
