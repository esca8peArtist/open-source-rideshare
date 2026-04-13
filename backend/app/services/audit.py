"""Audit logging service — append-only event recording for compliance.

Usage from any service or endpoint:

    from app.services.audit import log_event

    await log_event(
        db, category="ride", event_type="ride_completed",
        description="Ride #42 completed", ride_id=42,
        actor_id=driver.id, actor_role="driver",
    )

The service never raises — audit failures must not break business operations.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditCategory, AuditLog, AuditSeverity

logger = logging.getLogger(__name__)


async def log_event(
    db: AsyncSession,
    *,
    category: str,
    event_type: str,
    description: str,
    severity: str = "info",
    actor_id: int | None = None,
    actor_role: str | None = None,
    target_type: str | None = None,
    target_id: int | None = None,
    ride_id: int | None = None,
    user_id: int | None = None,
    metadata: dict[str, Any] | None = None,
    ip_address: str | None = None,
) -> AuditLog | None:
    """Append an audit event.  Never raises — logs errors instead."""
    try:
        entry = AuditLog(
            category=AuditCategory(category),
            severity=AuditSeverity(severity),
            event_type=event_type,
            description=description,
            actor_id=actor_id,
            actor_role=actor_role,
            target_type=target_type,
            target_id=target_id,
            ride_id=ride_id,
            user_id=user_id,
            metadata_json=json.dumps(metadata) if metadata else None,
            ip_address=ip_address,
        )
        db.add(entry)
        await db.flush()
        return entry
    except Exception:
        logger.exception("Failed to write audit log entry: %s/%s", category, event_type)
        return None


async def query_audit_logs(
    db: AsyncSession,
    *,
    category: str | None = None,
    severity: str | None = None,
    event_type: str | None = None,
    actor_id: int | None = None,
    ride_id: int | None = None,
    user_id: int | None = None,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    page: int = 1,
    page_size: int = 50,
) -> tuple[list[AuditLog], int]:
    """Query audit logs with filtering and pagination."""
    q = select(AuditLog)
    count_q = select(func.count(AuditLog.id))

    if category:
        q = q.where(AuditLog.category == AuditCategory(category))
        count_q = count_q.where(AuditLog.category == AuditCategory(category))
    if severity:
        q = q.where(AuditLog.severity == AuditSeverity(severity))
        count_q = count_q.where(AuditLog.severity == AuditSeverity(severity))
    if event_type:
        q = q.where(AuditLog.event_type == event_type)
        count_q = count_q.where(AuditLog.event_type == event_type)
    if actor_id is not None:
        q = q.where(AuditLog.actor_id == actor_id)
        count_q = count_q.where(AuditLog.actor_id == actor_id)
    if ride_id is not None:
        q = q.where(AuditLog.ride_id == ride_id)
        count_q = count_q.where(AuditLog.ride_id == ride_id)
    if user_id is not None:
        q = q.where(AuditLog.user_id == user_id)
        count_q = count_q.where(AuditLog.user_id == user_id)
    if start_date:
        q = q.where(AuditLog.timestamp >= start_date)
        count_q = count_q.where(AuditLog.timestamp >= start_date)
    if end_date:
        q = q.where(AuditLog.timestamp <= end_date)
        count_q = count_q.where(AuditLog.timestamp <= end_date)

    total = (await db.execute(count_q)).scalar() or 0
    offset = (page - 1) * page_size
    q = q.order_by(AuditLog.timestamp.desc()).offset(offset).limit(page_size)
    rows = (await db.execute(q)).scalars().all()
    return list(rows), total


async def get_audit_stats(
    db: AsyncSession,
    *,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
) -> dict:
    """Aggregate audit event statistics."""
    base = select(AuditLog.id)
    if start_date:
        base = base.where(AuditLog.timestamp >= start_date)
    if end_date:
        base = base.where(AuditLog.timestamp <= end_date)

    # Total count
    count_q = select(func.count(AuditLog.id))
    if start_date:
        count_q = count_q.where(AuditLog.timestamp >= start_date)
    if end_date:
        count_q = count_q.where(AuditLog.timestamp <= end_date)
    total = (await db.execute(count_q)).scalar() or 0

    # By category
    cat_q = (
        select(AuditLog.category, func.count(AuditLog.id))
        .group_by(AuditLog.category)
    )
    if start_date:
        cat_q = cat_q.where(AuditLog.timestamp >= start_date)
    if end_date:
        cat_q = cat_q.where(AuditLog.timestamp <= end_date)
    cat_rows = (await db.execute(cat_q)).all()
    by_category = {str(row[0].value) if hasattr(row[0], 'value') else str(row[0]): row[1] for row in cat_rows}

    # By severity
    sev_q = (
        select(AuditLog.severity, func.count(AuditLog.id))
        .group_by(AuditLog.severity)
    )
    if start_date:
        sev_q = sev_q.where(AuditLog.timestamp >= start_date)
    if end_date:
        sev_q = sev_q.where(AuditLog.timestamp <= end_date)
    sev_rows = (await db.execute(sev_q)).all()
    by_severity = {str(row[0].value) if hasattr(row[0], 'value') else str(row[0]): row[1] for row in sev_rows}

    now = datetime.now(timezone.utc)
    return {
        "total_events": total,
        "by_category": by_category,
        "by_severity": by_severity,
        "period_start": start_date or datetime.min.replace(tzinfo=timezone.utc),
        "period_end": end_date or now,
    }


async def generate_compliance_report(
    db: AsyncSession,
    *,
    start_date: datetime,
    end_date: datetime,
) -> dict:
    """Generate a TNC compliance report covering all regulated activities."""
    from app.models.ride import Ride, RideStatus
    from app.models.driver import DriverProfile
    from app.models.safety import SOSAlert, SOSStatus
    from app.models.feedback import Dispute, DisputeStatus
    from app.models.payment import Payment, PaymentStatus
    from app.models.payout import DriverPayout
    from app.models.verification import DriverDocument, VerificationStatus

    now = datetime.now(timezone.utc)
    time_filter = lambda col: [col >= start_date, col <= end_date]

    # Ride stats
    total_rides = (await db.execute(
        select(func.count(Ride.id)).where(*time_filter(Ride.created_at))
    )).scalar() or 0

    completed_rides = (await db.execute(
        select(func.count(Ride.id)).where(
            *time_filter(Ride.created_at),
            Ride.status == RideStatus.COMPLETED,
        )
    )).scalar() or 0

    cancelled_rides = (await db.execute(
        select(func.count(Ride.id)).where(
            *time_filter(Ride.created_at),
            Ride.status == RideStatus.CANCELLED,
        )
    )).scalar() or 0

    # Driver stats
    total_drivers = (await db.execute(
        select(func.count(DriverProfile.id))
    )).scalar() or 0

    approved_drivers = (await db.execute(
        select(func.count(DriverProfile.id)).where(
            DriverProfile.is_approved == True,  # noqa: E712
        )
    )).scalar() or 0

    pending_drivers = (await db.execute(
        select(func.count(DriverProfile.id)).where(
            DriverProfile.is_approved == False,  # noqa: E712
        )
    )).scalar() or 0

    # SOS stats
    sos_incidents = (await db.execute(
        select(func.count(SOSAlert.id)).where(*time_filter(SOSAlert.created_at))
    )).scalar() or 0

    sos_resolved = (await db.execute(
        select(func.count(SOSAlert.id)).where(
            *time_filter(SOSAlert.created_at),
            SOSAlert.status == SOSStatus.RESOLVED,
        )
    )).scalar() or 0

    # Dispute stats
    disputes_filed = (await db.execute(
        select(func.count(Dispute.id)).where(*time_filter(Dispute.created_at))
    )).scalar() or 0

    disputes_resolved = (await db.execute(
        select(func.count(Dispute.id)).where(
            *time_filter(Dispute.created_at),
            Dispute.status.in_([
                DisputeStatus.RESOLVED_RIDER_FAVOR,
                DisputeStatus.RESOLVED_DRIVER_FAVOR,
                DisputeStatus.RESOLVED_PARTIAL,
            ]),
        )
    )).scalar() or 0

    # Payment stats
    total_payments = (await db.execute(
        select(func.count(Payment.id)).where(
            *time_filter(Payment.created_at),
            Payment.status == PaymentStatus.COMPLETED,
        )
    )).scalar() or 0

    # Payout stats
    total_payouts = (await db.execute(
        select(func.count(DriverPayout.id)).where(*time_filter(DriverPayout.created_at))
    )).scalar() or 0

    # Verification stats
    verifications_approved = (await db.execute(
        select(func.count(DriverDocument.id)).where(
            *time_filter(DriverDocument.submitted_at),
            DriverDocument.status == VerificationStatus.APPROVED,
        )
    )).scalar() or 0

    verifications_rejected = (await db.execute(
        select(func.count(DriverDocument.id)).where(
            *time_filter(DriverDocument.submitted_at),
            DriverDocument.status == VerificationStatus.REJECTED,
        )
    )).scalar() or 0

    # Audit log stats for the period
    audit_total = (await db.execute(
        select(func.count(AuditLog.id)).where(*time_filter(AuditLog.timestamp))
    )).scalar() or 0

    critical_events = (await db.execute(
        select(func.count(AuditLog.id)).where(
            *time_filter(AuditLog.timestamp),
            AuditLog.severity == AuditSeverity.CRITICAL,
        )
    )).scalar() or 0

    # Top event types
    top_q = (
        select(AuditLog.event_type, func.count(AuditLog.id).label("cnt"))
        .where(*time_filter(AuditLog.timestamp))
        .group_by(AuditLog.event_type)
        .order_by(func.count(AuditLog.id).desc())
        .limit(10)
    )
    top_rows = (await db.execute(top_q)).all()
    top_event_types = [{"event_type": row[0], "count": row[1]} for row in top_rows]

    return {
        "report_period_start": start_date,
        "report_period_end": end_date,
        "generated_at": now,
        "total_rides": total_rides,
        "completed_rides": completed_rides,
        "cancelled_rides": cancelled_rides,
        "total_drivers": total_drivers,
        "approved_drivers": approved_drivers,
        "pending_drivers": pending_drivers,
        "sos_incidents": sos_incidents,
        "sos_resolved": sos_resolved,
        "disputes_filed": disputes_filed,
        "disputes_resolved": disputes_resolved,
        "total_payments_processed": total_payments,
        "total_payouts_issued": total_payouts,
        "driver_verifications_approved": verifications_approved,
        "driver_verifications_rejected": verifications_rejected,
        "audit_events_logged": audit_total,
        "critical_events": critical_events,
        "top_event_types": top_event_types,
    }
