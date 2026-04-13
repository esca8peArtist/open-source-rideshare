from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin
from app.db.database import get_db
from app.models.user import User
from app.schemas.audit import (
    AuditLogListResponse,
    AuditLogResponse,
    AuditStatsResponse,
    ComplianceReportRequest,
    ComplianceReportResponse,
)
from app.services.audit import generate_compliance_report, get_audit_stats, query_audit_logs

router = APIRouter(prefix="/admin/audit", tags=["audit"])


@router.get("/logs", response_model=AuditLogListResponse)
async def list_audit_logs(
    category: str | None = Query(None, description="Filter by category (ride, driver, payment, safety, dispute, verification, account, admin, payout)"),
    severity: str | None = Query(None, description="Filter by severity (info, warning, critical)"),
    event_type: str | None = Query(None, description="Filter by event type"),
    actor_id: int | None = Query(None, description="Filter by actor user ID"),
    ride_id: int | None = Query(None, description="Filter by ride ID"),
    user_id: int | None = Query(None, description="Filter by affected user ID"),
    start_date: datetime | None = Query(None, description="Start of date range (ISO 8601)"),
    end_date: datetime | None = Query(None, description="End of date range (ISO 8601)"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Query the immutable audit log with filtering and pagination."""
    logs, total = await query_audit_logs(
        db,
        category=category,
        severity=severity,
        event_type=event_type,
        actor_id=actor_id,
        ride_id=ride_id,
        user_id=user_id,
        start_date=start_date,
        end_date=end_date,
        page=page,
        page_size=page_size,
    )
    return AuditLogListResponse(
        logs=[AuditLogResponse.model_validate(log) for log in logs],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/stats", response_model=AuditStatsResponse)
async def audit_stats(
    start_date: datetime | None = Query(None),
    end_date: datetime | None = Query(None),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Aggregate audit event statistics by category and severity."""
    stats = await get_audit_stats(db, start_date=start_date, end_date=end_date)
    return AuditStatsResponse(**stats)


@router.post("/compliance-report", response_model=ComplianceReportResponse)
async def compliance_report(
    request: ComplianceReportRequest,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Generate a TNC compliance report for regulatory audits.

    Aggregates all regulated activity (rides, drivers, safety, payments,
    disputes, verifications) for the requested period.
    """
    report = await generate_compliance_report(
        db, start_date=request.start_date, end_date=request.end_date,
    )
    return ComplianceReportResponse(**report)
