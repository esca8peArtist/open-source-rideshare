"""Service layer for Corporate Vehicle Incident Reports.

Fleet managers document incidents involving company vehicles — collisions,
vandalism, theft, mechanical failure — and track resolution through a
structured workflow.

Public functions
----------------
create_incident_report  — create a new report in draft status.
get_incident_report     — fetch one report (404 if missing or wrong account).
list_vehicle_incidents  — filtered, paginated incidents for a vehicle.
list_account_incidents  — filtered, paginated incidents across an account.
update_incident_report  — partial update (409 if closed/resolved).
submit_incident         — draft → reported.
mark_under_review       — reported → under_review.
resolve_incident        — under_review → resolved (sets resolved_at).
close_incident          — resolved → closed.
get_incident_summary    — aggregate stats for an account.
list_all_platform       — platform-admin cross-account view.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.corporate_fleet_insurance import CorporateFleetInsurancePolicy
from app.models.corporate_fleet_vehicle import CorporateFleetVehicle
from app.models.corporate_vehicle_incident import (
    CorporateVehicleIncidentReport,
    IncidentStatus,
    IncidentType,
)
from app.schemas.corporate_vehicle_incidents import (
    IncidentReportCreate,
    IncidentReportResponse,
    IncidentReportUpdate,
    IncidentSummaryResponse,
)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_OPEN_STATUSES = {IncidentStatus.draft, IncidentStatus.reported, IncidentStatus.under_review}


def _to_response(row: CorporateVehicleIncidentReport) -> IncidentReportResponse:
    return IncidentReportResponse.model_validate(row)


async def _fetch_vehicle(
    db: AsyncSession,
    account_id: int,
    fleet_vehicle_id: uuid.UUID,
) -> CorporateFleetVehicle:
    """Return a fleet vehicle verifying account ownership.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        fleet_vehicle_id: UUID of the fleet vehicle.

    Returns:
        ``CorporateFleetVehicle`` ORM instance.

    Raises:
        HTTPException 404: Vehicle not found or does not belong to this account.
    """
    stmt = select(CorporateFleetVehicle).where(
        CorporateFleetVehicle.id == fleet_vehicle_id,
        CorporateFleetVehicle.account_id == account_id,
    )
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Fleet vehicle not found for this account.",
        )
    return row


async def _fetch_incident(
    db: AsyncSession,
    account_id: int,
    incident_id: uuid.UUID,
) -> CorporateVehicleIncidentReport:
    """Return an incident report verifying account ownership.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        incident_id: UUID of the incident report.

    Returns:
        ``CorporateVehicleIncidentReport`` ORM instance.

    Raises:
        HTTPException 404: Incident not found or wrong account.
    """
    stmt = select(CorporateVehicleIncidentReport).where(
        CorporateVehicleIncidentReport.id == incident_id,
        CorporateVehicleIncidentReport.account_id == account_id,
    )
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Incident report not found.",
        )
    return row


async def _fetch_insurance_policy(
    db: AsyncSession,
    account_id: int,
    insurance_policy_id: uuid.UUID,
) -> CorporateFleetInsurancePolicy:
    """Return an insurance policy verifying account ownership.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        insurance_policy_id: UUID of the insurance policy.

    Returns:
        ``CorporateFleetInsurancePolicy`` ORM instance.

    Raises:
        HTTPException 404: Policy not found or wrong account.
    """
    stmt = select(CorporateFleetInsurancePolicy).where(
        CorporateFleetInsurancePolicy.id == insurance_policy_id,
        CorporateFleetInsurancePolicy.account_id == account_id,
    )
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Insurance policy not found for this account.",
        )
    return row


# ---------------------------------------------------------------------------
# create_incident_report
# ---------------------------------------------------------------------------


async def create_incident_report(
    db: AsyncSession,
    account_id: int,
    data: IncidentReportCreate,
) -> IncidentReportResponse:
    """Create a new vehicle incident report in draft status.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        data: Incident report creation payload.

    Returns:
        ``IncidentReportResponse`` for the new report.

    Raises:
        HTTPException 404: Fleet vehicle not found for this account.
        HTTPException 409: Fleet vehicle is not active.
        HTTPException 404: Insurance policy not found (when insurance_policy_id provided).
    """
    vehicle = await _fetch_vehicle(db, account_id, data.fleet_vehicle_id)

    if not vehicle.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Fleet vehicle is not active.",
        )

    if data.insurance_policy_id is not None:
        await _fetch_insurance_policy(db, account_id, data.insurance_policy_id)

    report = CorporateVehicleIncidentReport(
        id=uuid.uuid4(),
        account_id=account_id,
        fleet_vehicle_id=data.fleet_vehicle_id,
        incident_type=data.incident_type,
        incident_status=IncidentStatus.draft,
        incident_date=data.incident_date,
        incident_time=data.incident_time,
        incident_location=data.incident_location,
        description=data.description,
        estimated_damage_usd=float(data.estimated_damage_usd)
        if data.estimated_damage_usd is not None
        else None,
        police_report_number=data.police_report_number,
        driver_id=data.driver_id,
        insurance_policy_id=data.insurance_policy_id,
        insurance_claim_number=data.insurance_claim_number,
        witness_info=data.witness_info,
        reported_by_id=data.reported_by_id,
        reviewed_by_id=None,
        resolved_at=None,
        notes=data.notes,
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
    incident_id: uuid.UUID,
) -> IncidentReportResponse:
    """Return a single incident report.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        incident_id: UUID of the incident report.

    Returns:
        ``IncidentReportResponse``.

    Raises:
        HTTPException 404: Incident not found or wrong account.
    """
    row = await _fetch_incident(db, account_id, incident_id)
    return _to_response(row)


# ---------------------------------------------------------------------------
# list_vehicle_incidents
# ---------------------------------------------------------------------------


async def list_vehicle_incidents(
    db: AsyncSession,
    account_id: int,
    fleet_vehicle_id: uuid.UUID,
    *,
    incident_type: Optional[IncidentType] = None,
    incident_status: Optional[IncidentStatus] = None,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    limit: int = 50,
    offset: int = 0,
) -> list[IncidentReportResponse]:
    """Return incident reports for a specific fleet vehicle.

    Results are ordered by incident_date descending (most recent first).

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        fleet_vehicle_id: UUID of the fleet vehicle.
        incident_type: Optional filter by incident category.
        incident_status: Optional filter by workflow status.
        from_date: Optional lower bound on incident_date (inclusive).
        to_date: Optional upper bound on incident_date (inclusive).
        limit: Max records to return (default 50).
        offset: Records to skip (default 0).

    Returns:
        List of ``IncidentReportResponse``.

    Raises:
        HTTPException 404: Vehicle not found for this account.
    """
    await _fetch_vehicle(db, account_id, fleet_vehicle_id)

    conditions = [
        CorporateVehicleIncidentReport.account_id == account_id,
        CorporateVehicleIncidentReport.fleet_vehicle_id == fleet_vehicle_id,
    ]
    if incident_type is not None:
        conditions.append(CorporateVehicleIncidentReport.incident_type == incident_type)
    if incident_status is not None:
        conditions.append(
            CorporateVehicleIncidentReport.incident_status == incident_status
        )
    if from_date is not None:
        conditions.append(CorporateVehicleIncidentReport.incident_date >= from_date)
    if to_date is not None:
        conditions.append(CorporateVehicleIncidentReport.incident_date <= to_date)

    stmt = (
        select(CorporateVehicleIncidentReport)
        .where(and_(*conditions))
        .order_by(CorporateVehicleIncidentReport.incident_date.desc())
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return [_to_response(r) for r in rows]


# ---------------------------------------------------------------------------
# list_account_incidents
# ---------------------------------------------------------------------------


async def list_account_incidents(
    db: AsyncSession,
    account_id: int,
    *,
    incident_type: Optional[IncidentType] = None,
    incident_status: Optional[IncidentStatus] = None,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    limit: int = 50,
    offset: int = 0,
) -> list[IncidentReportResponse]:
    """Return incident reports across all vehicles for an account.

    Results are ordered by incident_date descending (most recent first).

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        incident_type: Optional filter by incident category.
        incident_status: Optional filter by workflow status.
        from_date: Optional lower bound on incident_date (inclusive).
        to_date: Optional upper bound on incident_date (inclusive).
        limit: Max records to return (default 50).
        offset: Records to skip (default 0).

    Returns:
        List of ``IncidentReportResponse``.
    """
    conditions = [CorporateVehicleIncidentReport.account_id == account_id]
    if incident_type is not None:
        conditions.append(CorporateVehicleIncidentReport.incident_type == incident_type)
    if incident_status is not None:
        conditions.append(
            CorporateVehicleIncidentReport.incident_status == incident_status
        )
    if from_date is not None:
        conditions.append(CorporateVehicleIncidentReport.incident_date >= from_date)
    if to_date is not None:
        conditions.append(CorporateVehicleIncidentReport.incident_date <= to_date)

    stmt = (
        select(CorporateVehicleIncidentReport)
        .where(and_(*conditions))
        .order_by(CorporateVehicleIncidentReport.incident_date.desc())
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
    incident_id: uuid.UUID,
    data: IncidentReportUpdate,
) -> IncidentReportResponse:
    """Partially update a vehicle incident report.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        incident_id: UUID of the incident report.
        data: Fields to update (None values are ignored).

    Returns:
        Updated ``IncidentReportResponse``.

    Raises:
        HTTPException 404: Incident not found or wrong account.
        HTTPException 409: Incident is in a terminal status (resolved or closed).
    """
    row = await _fetch_incident(db, account_id, incident_id)

    if row.incident_status in (IncidentStatus.resolved, IncidentStatus.closed):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot update an incident report that is resolved or closed.",
        )

    update_data = data.model_dump(exclude_none=True)
    for field, value in update_data.items():
        if field == "estimated_damage_usd" and value is not None:
            value = float(value)
        setattr(row, field, value)

    await db.commit()
    await db.refresh(row)
    return _to_response(row)


# ---------------------------------------------------------------------------
# submit_incident
# ---------------------------------------------------------------------------


async def submit_incident(
    db: AsyncSession,
    account_id: int,
    incident_id: uuid.UUID,
    reported_by_id: int,
) -> IncidentReportResponse:
    """Move an incident report from draft to reported status.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        incident_id: UUID of the incident report.
        reported_by_id: UUID of the user submitting the report.

    Returns:
        Updated ``IncidentReportResponse``.

    Raises:
        HTTPException 404: Incident not found or wrong account.
        HTTPException 409: Incident is not in draft status.
    """
    row = await _fetch_incident(db, account_id, incident_id)

    if row.incident_status != IncidentStatus.draft:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Incident report must be in draft status to submit.",
        )

    row.incident_status = IncidentStatus.reported
    row.reported_by_id = reported_by_id
    await db.commit()
    await db.refresh(row)
    return _to_response(row)


# ---------------------------------------------------------------------------
# mark_under_review
# ---------------------------------------------------------------------------


async def mark_under_review(
    db: AsyncSession,
    account_id: int,
    incident_id: uuid.UUID,
    reviewed_by_id: int,
) -> IncidentReportResponse:
    """Move an incident report from reported to under_review status.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        incident_id: UUID of the incident report.
        reviewed_by_id: UUID of the admin starting the review.

    Returns:
        Updated ``IncidentReportResponse``.

    Raises:
        HTTPException 404: Incident not found or wrong account.
        HTTPException 409: Incident is not in reported status.
    """
    row = await _fetch_incident(db, account_id, incident_id)

    if row.incident_status != IncidentStatus.reported:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Incident report must be in reported status to mark under review.",
        )

    row.incident_status = IncidentStatus.under_review
    row.reviewed_by_id = reviewed_by_id
    await db.commit()
    await db.refresh(row)
    return _to_response(row)


# ---------------------------------------------------------------------------
# resolve_incident
# ---------------------------------------------------------------------------


async def resolve_incident(
    db: AsyncSession,
    account_id: int,
    incident_id: uuid.UUID,
    reviewed_by_id: int,
    notes: Optional[str] = None,
) -> IncidentReportResponse:
    """Move an incident report from under_review to resolved status.

    Sets ``resolved_at`` to the current UTC time.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        incident_id: UUID of the incident report.
        reviewed_by_id: UUID of the admin resolving the report.
        notes: Optional resolution notes to append.

    Returns:
        Updated ``IncidentReportResponse``.

    Raises:
        HTTPException 404: Incident not found or wrong account.
        HTTPException 409: Incident is not in under_review status.
    """
    row = await _fetch_incident(db, account_id, incident_id)

    if row.incident_status != IncidentStatus.under_review:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Incident report must be under review to resolve.",
        )

    row.incident_status = IncidentStatus.resolved
    row.reviewed_by_id = reviewed_by_id
    row.resolved_at = datetime.now(tz=timezone.utc)
    if notes is not None:
        row.notes = notes
    await db.commit()
    await db.refresh(row)
    return _to_response(row)


# ---------------------------------------------------------------------------
# close_incident
# ---------------------------------------------------------------------------


async def close_incident(
    db: AsyncSession,
    account_id: int,
    incident_id: uuid.UUID,
) -> IncidentReportResponse:
    """Move an incident report from resolved to closed status.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.
        incident_id: UUID of the incident report.

    Returns:
        Updated ``IncidentReportResponse``.

    Raises:
        HTTPException 404: Incident not found or wrong account.
        HTTPException 409: Incident is not in resolved status.
    """
    row = await _fetch_incident(db, account_id, incident_id)

    if row.incident_status != IncidentStatus.resolved:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Incident report must be resolved before closing.",
        )

    row.incident_status = IncidentStatus.closed
    await db.commit()
    await db.refresh(row)
    return _to_response(row)


# ---------------------------------------------------------------------------
# get_incident_summary
# ---------------------------------------------------------------------------


async def get_incident_summary(
    db: AsyncSession,
    account_id: int,
) -> IncidentSummaryResponse:
    """Return aggregate incident statistics for a corporate account.

    Args:
        db: Async SQLAlchemy session.
        account_id: Corporate account ID.

    Returns:
        ``IncidentSummaryResponse`` with counts and damage totals.
    """
    stmt = select(CorporateVehicleIncidentReport).where(
        CorporateVehicleIncidentReport.account_id == account_id
    )
    result = await db.execute(stmt)
    rows = list(result.scalars().all())

    total = len(rows)

    by_status: dict[str, int] = {s.value: 0 for s in IncidentStatus}
    by_type: dict[str, int] = {t.value: 0 for t in IncidentType}

    open_count = 0
    total_damage = 0.0

    for row in rows:
        s_key = (
            row.incident_status.value
            if hasattr(row.incident_status, "value")
            else str(row.incident_status)
        )
        by_status[s_key] = by_status.get(s_key, 0) + 1

        t_key = (
            row.incident_type.value
            if hasattr(row.incident_type, "value")
            else str(row.incident_type)
        )
        by_type[t_key] = by_type.get(t_key, 0) + 1

        if row.incident_status in _OPEN_STATUSES:
            open_count += 1
            if row.estimated_damage_usd is not None:
                total_damage += float(row.estimated_damage_usd)

    return IncidentSummaryResponse(
        total_incidents=total,
        open_count=open_count,
        by_status=by_status,
        by_type=by_type,
        total_estimated_damage_usd=round(total_damage, 2),
    )


# ---------------------------------------------------------------------------
# list_all_platform
# ---------------------------------------------------------------------------


async def list_all_platform(
    db: AsyncSession,
    *,
    account_id: Optional[int] = None,
    incident_type: Optional[IncidentType] = None,
    incident_status: Optional[IncidentStatus] = None,
    limit: int = 50,
    offset: int = 0,
) -> list[IncidentReportResponse]:
    """Return incident reports across all corporate accounts (platform admin).

    Args:
        db: Async SQLAlchemy session.
        account_id: Optional filter to a specific account.
        incident_type: Optional filter by incident category.
        incident_status: Optional filter by workflow status.
        limit: Max records to return (default 50).
        offset: Records to skip (default 0).

    Returns:
        List of ``IncidentReportResponse``.
    """
    conditions = []
    if account_id is not None:
        conditions.append(CorporateVehicleIncidentReport.account_id == account_id)
    if incident_type is not None:
        conditions.append(CorporateVehicleIncidentReport.incident_type == incident_type)
    if incident_status is not None:
        conditions.append(
            CorporateVehicleIncidentReport.incident_status == incident_status
        )

    base = select(CorporateVehicleIncidentReport)
    if conditions:
        base = base.where(and_(*conditions))

    stmt = (
        base.order_by(
            CorporateVehicleIncidentReport.account_id,
            CorporateVehicleIncidentReport.incident_date.desc(),
        )
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return [_to_response(r) for r in rows]
