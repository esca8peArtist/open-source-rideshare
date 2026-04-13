from datetime import datetime

from pydantic import BaseModel, Field


class AuditLogResponse(BaseModel):
    id: int
    timestamp: datetime
    category: str
    severity: str
    event_type: str
    description: str
    actor_id: int | None
    actor_role: str | None
    target_type: str | None
    target_id: int | None
    ride_id: int | None
    user_id: int | None
    metadata_json: str | None
    ip_address: str | None

    model_config = {"from_attributes": True}


class AuditLogListResponse(BaseModel):
    logs: list[AuditLogResponse]
    total: int
    page: int
    page_size: int


class AuditStatsResponse(BaseModel):
    total_events: int
    by_category: dict[str, int]
    by_severity: dict[str, int]
    period_start: datetime
    period_end: datetime


class ComplianceReportResponse(BaseModel):
    """Summary report for TNC regulatory compliance audits."""
    report_period_start: datetime
    report_period_end: datetime
    generated_at: datetime

    total_rides: int
    completed_rides: int
    cancelled_rides: int

    total_drivers: int
    approved_drivers: int
    pending_drivers: int

    sos_incidents: int
    sos_resolved: int

    disputes_filed: int
    disputes_resolved: int

    total_payments_processed: int
    total_payouts_issued: int

    driver_verifications_approved: int
    driver_verifications_rejected: int

    audit_events_logged: int
    critical_events: int

    top_event_types: list[dict[str, int | str]]


class ComplianceReportRequest(BaseModel):
    start_date: datetime
    end_date: datetime
    include_details: bool = Field(False, description="Include per-event breakdown")
