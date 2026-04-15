"""Service layer for driver incident reporting.

All database interactions for incident creation, retrieval, and admin
review/resolution live here.  Callers (routers) receive plain model
instances or raise HTTPException.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.driver_incident import (
    DriverIncidentReport,
    IncidentSeverity,
    IncidentStatus,
    IncidentType,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _encode_urls(urls: list[str]) -> str:
    """Join URL list into a comma-separated string for storage."""
    return ",".join(u.strip() for u in urls if u.strip())


# ---------------------------------------------------------------------------
# Driver operations
# ---------------------------------------------------------------------------

async def create_incident(
    db: AsyncSession,
    driver_id: int,
    incident_type: IncidentType,
    severity: IncidentSeverity,
    description: str,
    ride_id: Optional[int],
    evidence_urls: list[str],
) -> DriverIncidentReport:
    """Create a new incident report for *driver_id*."""
    report = DriverIncidentReport(
        driver_id=driver_id,
        ride_id=ride_id,
        incident_type=incident_type.value,
        severity=severity.value,
        status=IncidentStatus.submitted.value,
        description=description,
        evidence_urls=_encode_urls(evidence_urls) if evidence_urls else None,
    )
    db.add(report)
    await db.commit()
    await db.refresh(report)
    return report


async def get_driver_incident(
    db: AsyncSession,
    incident_id: int,
    driver_id: int,
) -> DriverIncidentReport:
    """Fetch a specific incident owned by *driver_id*.  Raises 404 if not found."""
    result = await db.execute(
        select(DriverIncidentReport).where(
            DriverIncidentReport.id == incident_id,
            DriverIncidentReport.driver_id == driver_id,
        )
    )
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=404, detail="Incident report not found.")
    return report


async def list_driver_incidents(
    db: AsyncSession,
    driver_id: int,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[DriverIncidentReport], int]:
    """Return paginated incidents for *driver_id*, newest first."""
    q = select(DriverIncidentReport).where(
        DriverIncidentReport.driver_id == driver_id
    )
    total_result = await db.execute(
        select(func.count()).select_from(q.subquery())
    )
    total = total_result.scalar_one()

    result = await db.execute(
        q.order_by(DriverIncidentReport.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all()), total


async def update_driver_incident(
    db: AsyncSession,
    incident_id: int,
    driver_id: int,
    description: Optional[str],
    evidence_urls: Optional[list[str]],
) -> DriverIncidentReport:
    """Driver can update description/evidence while report is still *submitted*."""
    report = await get_driver_incident(db, incident_id, driver_id)

    if report.status != IncidentStatus.submitted.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Report can only be edited while in 'submitted' status.",
        )
    if description is not None:
        report.description = description
    if evidence_urls is not None:
        report.evidence_urls = _encode_urls(evidence_urls) or None

    await db.commit()
    await db.refresh(report)
    return report


# ---------------------------------------------------------------------------
# Admin operations
# ---------------------------------------------------------------------------

async def admin_get_incident(
    db: AsyncSession,
    incident_id: int,
) -> DriverIncidentReport:
    """Admin: fetch any incident by id.  Raises 404 if not found."""
    result = await db.execute(
        select(DriverIncidentReport).where(DriverIncidentReport.id == incident_id)
    )
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=404, detail="Incident report not found.")
    return report


async def admin_list_incidents(
    db: AsyncSession,
    incident_status: Optional[IncidentStatus] = None,
    severity: Optional[IncidentSeverity] = None,
    incident_type: Optional[IncidentType] = None,
    driver_id: Optional[int] = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[DriverIncidentReport], int]:
    """Admin: list all incidents with optional filters, newest first."""
    q = select(DriverIncidentReport)
    if incident_status is not None:
        q = q.where(DriverIncidentReport.status == incident_status.value)
    if severity is not None:
        q = q.where(DriverIncidentReport.severity == severity.value)
    if incident_type is not None:
        q = q.where(DriverIncidentReport.incident_type == incident_type.value)
    if driver_id is not None:
        q = q.where(DriverIncidentReport.driver_id == driver_id)

    total_result = await db.execute(
        select(func.count()).select_from(q.subquery())
    )
    total = total_result.scalar_one()

    result = await db.execute(
        q.order_by(DriverIncidentReport.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all()), total


async def admin_start_review(
    db: AsyncSession,
    incident_id: int,
    admin_id: int,
    admin_note: Optional[str],
) -> DriverIncidentReport:
    """Admin: move a submitted incident to under_review."""
    report = await admin_get_incident(db, incident_id)
    if report.status != IncidentStatus.submitted.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Report is already in '{report.status}' status.",
        )
    report.status = IncidentStatus.under_review.value
    report.reviewed_by_id = admin_id
    report.reviewed_at = _now()
    if admin_note is not None:
        report.admin_note = admin_note
    await db.commit()
    await db.refresh(report)
    return report


async def admin_resolve_incident(
    db: AsyncSession,
    incident_id: int,
    admin_id: int,
    admin_note: Optional[str],
) -> DriverIncidentReport:
    """Admin: resolve an incident."""
    report = await admin_get_incident(db, incident_id)
    if report.status not in (
        IncidentStatus.submitted.value,
        IncidentStatus.under_review.value,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot resolve a report in '{report.status}' status.",
        )
    report.status = IncidentStatus.resolved.value
    report.reviewed_by_id = admin_id
    report.reviewed_at = _now()
    if admin_note is not None:
        report.admin_note = admin_note
    await db.commit()
    await db.refresh(report)
    return report


async def admin_dismiss_incident(
    db: AsyncSession,
    incident_id: int,
    admin_id: int,
    admin_note: Optional[str],
) -> DriverIncidentReport:
    """Admin: dismiss an incident (not actionable / duplicate / bad faith)."""
    report = await admin_get_incident(db, incident_id)
    if report.status not in (
        IncidentStatus.submitted.value,
        IncidentStatus.under_review.value,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot dismiss a report in '{report.status}' status.",
        )
    report.status = IncidentStatus.dismissed.value
    report.reviewed_by_id = admin_id
    report.reviewed_at = _now()
    if admin_note is not None:
        report.admin_note = admin_note
    await db.commit()
    await db.refresh(report)
    return report


async def admin_incident_summary(
    db: AsyncSession,
) -> dict:
    """Aggregate incident statistics for the admin dashboard."""
    result = await db.execute(select(DriverIncidentReport))
    reports = list(result.scalars().all())

    by_status: dict[str, int] = {}
    by_severity: dict[str, int] = {}
    by_type: dict[str, int] = {}

    for r in reports:
        by_status[r.status] = by_status.get(r.status, 0) + 1
        by_severity[r.severity] = by_severity.get(r.severity, 0) + 1
        by_type[r.incident_type] = by_type.get(r.incident_type, 0) + 1

    open_statuses = {IncidentStatus.submitted.value, IncidentStatus.under_review.value}
    open_count = sum(v for k, v in by_status.items() if k in open_statuses)
    critical_open = sum(
        1
        for r in reports
        if r.severity == IncidentSeverity.critical.value and r.status in open_statuses
    )

    return {
        "total": len(reports),
        "by_status": by_status,
        "by_severity": by_severity,
        "by_type": by_type,
        "open_count": open_count,
        "critical_open": critical_open,
    }
