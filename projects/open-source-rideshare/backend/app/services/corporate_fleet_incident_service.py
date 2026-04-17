"""Service layer for Corporate Fleet Incident Reports.

Fleet members log vehicle incidents and fleet admins manage them through
review, resolution, and closure.

Public functions
----------------
create_incident_report          — log a new incident report (member or admin).
get_incident_report             — fetch one report (404 if missing or wrong account).
list_incident_reports           — filtered, paginated list for an account.
update_incident_report          — partial update (admin only, 404).
resolve_incident_report         — set status=resolved with notes and resolved_at (admin).
close_incident_report           — set status=closed from resolved only (admin).
delete_incident_report          — delete a report in reported or resolved status (admin).
get_vehicle_incident_summary    — aggregate stats for a specific vehicle.
get_account_incident_summary    — aggregate stats for an account.
get_platform_admin_incident_overview — aggregate stats across all accounts (platform admin).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import HTTPException, status
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.corporate_fleet_incident import (
    CorporateFleetIncidentReport,
    FleetIncidentSeverity,
    FleetIncidentStatus,
    FleetIncidentType,
)
from app.schemas.corporate_fleet_incident import (
    AccountIncidentSummaryResponse,
    IncidentReportCreate,
    IncidentReportResponse,
    IncidentReportUpdate,
    IncidentSeverityBreakdown,
    IncidentStatusBreakdown,
    IncidentTypeBreakdown,
    PlatformIncidentOverviewResponse,
    VehicleIncidentSummaryResponse,
)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _to_response(row: CorporateFleetIncidentReport) -> IncidentReportResponse:
    return IncidentReportResponse.model_validate(row)


async def _fetch_report(
    db: AsyncSession,
    account_id: int,
    report_id: uuid.UUID,
) -> CorporateFleetIncidentReport:
    """Return an incident report verifying account ownership.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        report_id: UUID of the incident report.

    Returns:
        ``CorporateFleetIncidentReport`` ORM instance.

    Raises:
        HTTPException 404: Report not found or does not belong to this account.
    """
    stmt = select(CorporateFleetIncidentReport).where(
        CorporateFleetIncidentReport.id == report_id,
        CorporateFleetIncidentReport.account_id == account_id,
    )
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Incident report not found.",
        )
    return row


def _build_summary_breakdowns(
    rows: list[CorporateFleetIncidentReport],
) -> tuple[
    list[IncidentTypeBreakdown],
    list[IncidentSeverityBreakdown],
    list[IncidentStatusBreakdown],
    float,
]:
    """Compute per-type, per-severity, per-status breakdowns and total damage.

    Args:
        rows: List of incident report ORM instances.

    Returns:
        Tuple of (by_type, by_severity, by_status, total_damage_estimate).
    """
    type_map: dict[FleetIncidentType, dict] = {}
    severity_map: dict[FleetIncidentSeverity, int] = {}
    status_map: dict[FleetIncidentStatus, int] = {}
    total_damage = 0.0

    for row in rows:
        # by_type
        t = row.incident_type
        if t not in type_map:
            type_map[t] = {"count": 0, "total_damage_estimate": 0.0}
        type_map[t]["count"] += 1
        if row.damage_estimate is not None:
            type_map[t]["total_damage_estimate"] += float(row.damage_estimate)

        # by_severity
        sev = row.severity
        severity_map[sev] = severity_map.get(sev, 0) + 1

        # by_status
        st = row.status
        status_map[st] = status_map.get(st, 0) + 1

        # total damage
        if row.damage_estimate is not None:
            total_damage += float(row.damage_estimate)

    by_type = [
        IncidentTypeBreakdown(
            incident_type=t,
            count=v["count"],
            total_damage_estimate=round(v["total_damage_estimate"], 2),
        )
        for t, v in type_map.items()
    ]
    by_severity = [
        IncidentSeverityBreakdown(severity=sev, count=cnt)
        for sev, cnt in severity_map.items()
    ]
    by_status = [
        IncidentStatusBreakdown(status=st, count=cnt)
        for st, cnt in status_map.items()
    ]

    return by_type, by_severity, by_status, round(total_damage, 2)


# ---------------------------------------------------------------------------
# create_incident_report
# ---------------------------------------------------------------------------


async def create_incident_report(
    db: AsyncSession,
    account_id: int,
    user_id: int,
    data: IncidentReportCreate,
) -> IncidentReportResponse:
    """Log a new fleet vehicle incident report.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        user_id: ID of the user submitting the report.
        data: Incident report creation payload.

    Returns:
        ``IncidentReportResponse`` for the new report.
    """
    report = CorporateFleetIncidentReport(
        id=uuid.uuid4(),
        account_id=account_id,
        vehicle_id=data.vehicle_id,
        reported_by_user_id=user_id,
        incident_type=data.incident_type,
        severity=data.severity,
        status=FleetIncidentStatus.reported,
        incident_date=data.incident_date,
        incident_location=data.incident_location,
        description=data.description,
        damage_estimate=float(data.damage_estimate) if data.damage_estimate is not None else None,
        insurance_claim_number=data.insurance_claim_number,
        police_report_number=data.police_report_number,
        third_party_involved=data.third_party_involved,
        injuries_reported=data.injuries_reported,
    )
    db.add(report)
    await db.commit()
    await db.refresh(report)
    return _to_response(report)


# ---------------------------------------------------------------------------
# get_incident_report
# ---------------------------------------------------------------------------


async def get_incident_report(
    db: AsyncSession,
    account_id: int,
    report_id: uuid.UUID,
) -> IncidentReportResponse:
    """Return a single incident report.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        report_id: UUID of the incident report.

    Returns:
        ``IncidentReportResponse``.

    Raises:
        HTTPException 404: Report not found or wrong account.
    """
    row = await _fetch_report(db, account_id, report_id)
    return _to_response(row)


# ---------------------------------------------------------------------------
# list_incident_reports
# ---------------------------------------------------------------------------


async def list_incident_reports(
    db: AsyncSession,
    account_id: int,
    *,
    vehicle_id: Optional[uuid.UUID] = None,
    status: Optional[FleetIncidentStatus] = None,
    incident_type: Optional[FleetIncidentType] = None,
    limit: int = 50,
    offset: int = 0,
) -> List[IncidentReportResponse]:
    """Return a filtered, paginated list of incident reports for an account.

    Results are ordered by incident_date descending.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        vehicle_id: Optional filter to a specific vehicle.
        status: Optional filter by lifecycle status.
        incident_type: Optional filter by incident type.
        limit: Max records to return (default 50).
        offset: Records to skip (default 0).

    Returns:
        List of ``IncidentReportResponse``.
    """
    conditions = [CorporateFleetIncidentReport.account_id == account_id]
    if vehicle_id is not None:
        conditions.append(CorporateFleetIncidentReport.vehicle_id == vehicle_id)
    if status is not None:
        conditions.append(CorporateFleetIncidentReport.status == status)
    if incident_type is not None:
        conditions.append(CorporateFleetIncidentReport.incident_type == incident_type)

    stmt = (
        select(CorporateFleetIncidentReport)
        .where(and_(*conditions))
        .order_by(CorporateFleetIncidentReport.incident_date.desc())
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return [_to_response(r) for r in rows]


# ---------------------------------------------------------------------------
# update_incident_report
# ---------------------------------------------------------------------------


async def update_incident_report(
    db: AsyncSession,
    account_id: int,
    report_id: uuid.UUID,
    data: IncidentReportUpdate,
) -> IncidentReportResponse:
    """Partially update a fleet incident report.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        report_id: UUID of the incident report.
        data: Fields to update (None values are ignored).

    Returns:
        Updated ``IncidentReportResponse``.

    Raises:
        HTTPException 404: Report not found or wrong account.
    """
    row = await _fetch_report(db, account_id, report_id)

    update_data = data.model_dump(exclude_none=True)

    for field, value in update_data.items():
        if field == "damage_estimate":
            value = float(value) if value is not None else None
        setattr(row, field, value)

    await db.commit()
    await db.refresh(row)
    return _to_response(row)


# ---------------------------------------------------------------------------
# resolve_incident_report
# ---------------------------------------------------------------------------


async def resolve_incident_report(
    db: AsyncSession,
    account_id: int,
    report_id: uuid.UUID,
    resolution_notes: Optional[str] = None,
) -> IncidentReportResponse:
    """Mark an incident report as resolved.

    Sets status to resolved and records resolved_at timestamp.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        report_id: UUID of the incident report.
        resolution_notes: Optional notes on how the incident was resolved.

    Returns:
        Updated ``IncidentReportResponse``.

    Raises:
        HTTPException 404: Report not found or wrong account.
    """
    row = await _fetch_report(db, account_id, report_id)

    row.status = FleetIncidentStatus.resolved
    row.resolved_at = datetime.now(tz=timezone.utc)
    if resolution_notes is not None:
        row.resolution_notes = resolution_notes

    await db.commit()
    await db.refresh(row)
    return _to_response(row)


# ---------------------------------------------------------------------------
# close_incident_report
# ---------------------------------------------------------------------------


async def close_incident_report(
    db: AsyncSession,
    account_id: int,
    report_id: uuid.UUID,
) -> IncidentReportResponse:
    """Close a resolved incident report.

    Only reports with status=resolved may be closed.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        report_id: UUID of the incident report.

    Returns:
        Updated ``IncidentReportResponse``.

    Raises:
        HTTPException 404: Report not found or wrong account.
        HTTPException 409: Report is not in resolved status.
    """
    row = await _fetch_report(db, account_id, report_id)

    if row.status != FleetIncidentStatus.resolved:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Incident report must be in resolved status to close. "
                f"Current status: {row.status.value}."
            ),
        )

    row.status = FleetIncidentStatus.closed
    await db.commit()
    await db.refresh(row)
    return _to_response(row)


# ---------------------------------------------------------------------------
# delete_incident_report
# ---------------------------------------------------------------------------


async def delete_incident_report(
    db: AsyncSession,
    account_id: int,
    report_id: uuid.UUID,
) -> None:
    """Delete an incident report.

    Only reports with status=reported or resolved may be deleted.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        report_id: UUID of the incident report.

    Raises:
        HTTPException 404: Report not found or wrong account.
        HTTPException 409: Report is in under_review or closed status.
    """
    row = await _fetch_report(db, account_id, report_id)

    if row.status not in (
        FleetIncidentStatus.reported,
        FleetIncidentStatus.resolved,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Incident report with status '{row.status.value}' cannot be deleted. "
                "Only reports with status 'reported' or 'resolved' may be deleted."
            ),
        )

    await db.delete(row)
    await db.commit()


# ---------------------------------------------------------------------------
# get_vehicle_incident_summary
# ---------------------------------------------------------------------------


async def get_vehicle_incident_summary(
    db: AsyncSession,
    account_id: int,
    vehicle_id: uuid.UUID,
) -> VehicleIncidentSummaryResponse:
    """Return aggregate incident statistics for a specific fleet vehicle.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        vehicle_id: UUID of the fleet vehicle.

    Returns:
        ``VehicleIncidentSummaryResponse``.
    """
    stmt = select(CorporateFleetIncidentReport).where(
        CorporateFleetIncidentReport.account_id == account_id,
        CorporateFleetIncidentReport.vehicle_id == vehicle_id,
    )
    result = await db.execute(stmt)
    rows = list(result.scalars().all())

    by_type, by_severity, by_status, total_damage = _build_summary_breakdowns(rows)

    return VehicleIncidentSummaryResponse(
        vehicle_id=vehicle_id,
        total=len(rows),
        by_type=by_type,
        by_severity=by_severity,
        by_status=by_status,
        total_damage_estimate=total_damage,
    )


# ---------------------------------------------------------------------------
# get_account_incident_summary
# ---------------------------------------------------------------------------


async def get_account_incident_summary(
    db: AsyncSession,
    account_id: int,
) -> AccountIncidentSummaryResponse:
    """Return account-wide aggregate incident statistics.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.

    Returns:
        ``AccountIncidentSummaryResponse``.
    """
    stmt = select(CorporateFleetIncidentReport).where(
        CorporateFleetIncidentReport.account_id == account_id
    )
    result = await db.execute(stmt)
    rows = list(result.scalars().all())

    by_type, by_severity, by_status, total_damage = _build_summary_breakdowns(rows)

    return AccountIncidentSummaryResponse(
        account_id=account_id,
        total=len(rows),
        by_type=by_type,
        by_severity=by_severity,
        by_status=by_status,
        total_damage_estimate=total_damage,
    )


# ---------------------------------------------------------------------------
# get_platform_admin_incident_overview
# ---------------------------------------------------------------------------


async def get_platform_admin_incident_overview(
    db: AsyncSession,
) -> PlatformIncidentOverviewResponse:
    """Return platform-wide aggregate incident statistics (platform admin only).

    Args:
        db: Async SQLAlchemy session.

    Returns:
        ``PlatformIncidentOverviewResponse``.
    """
    stmt = select(CorporateFleetIncidentReport)
    result = await db.execute(stmt)
    rows = list(result.scalars().all())

    by_type, by_severity, by_status, total_damage = _build_summary_breakdowns(rows)

    accounts_with_incidents = len({r.account_id for r in rows})

    return PlatformIncidentOverviewResponse(
        total=len(rows),
        by_type=by_type,
        by_severity=by_severity,
        by_status=by_status,
        total_damage_estimate=total_damage,
        total_accounts_with_incidents=accounts_with_incidents,
    )
