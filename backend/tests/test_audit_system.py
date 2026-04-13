"""Comprehensive tests for the audit logging and compliance system.

Covers:
- AuditLog model (columns, enums, relationships)
- Audit schemas (response, list, stats, compliance report)
- Audit service (log_event, query_audit_logs, get_audit_stats, generate_compliance_report)
- Audit event dispatchers (all lifecycle event helpers)
- Audit API endpoints (logs, stats, compliance report)
- Router registration in app.main
"""

import json
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.audit import AuditCategory, AuditLog, AuditSeverity
from app.schemas.audit import (
    AuditLogListResponse,
    AuditLogResponse,
    AuditStatsResponse,
    ComplianceReportRequest,
    ComplianceReportResponse,
)


# ===========================================================================
# AuditLog Model Tests
# ===========================================================================


class TestAuditLogModel:
    def test_table_name(self):
        assert AuditLog.__tablename__ == "audit_logs"

    def test_has_required_columns(self):
        cols = {c.name for c in AuditLog.__table__.columns}
        expected = {
            "id", "timestamp", "category", "severity", "event_type",
            "description", "actor_id", "actor_role", "target_type",
            "target_id", "ride_id", "user_id", "metadata_json", "ip_address",
        }
        assert expected.issubset(cols)

    def test_id_is_primary_key(self):
        pk_cols = [c.name for c in AuditLog.__table__.primary_key.columns]
        assert pk_cols == ["id"]

    def test_timestamp_column_exists(self):
        cols = {c.name for c in AuditLog.__table__.columns}
        assert "timestamp" in cols

    def test_category_column_exists(self):
        cols = {c.name for c in AuditLog.__table__.columns}
        assert "category" in cols

    def test_severity_column_exists(self):
        cols = {c.name for c in AuditLog.__table__.columns}
        assert "severity" in cols

    def test_event_type_column_exists(self):
        cols = {c.name for c in AuditLog.__table__.columns}
        assert "event_type" in cols

    def test_description_column_exists(self):
        cols = {c.name for c in AuditLog.__table__.columns}
        assert "description" in cols

    def test_actor_id_is_nullable(self):
        col = AuditLog.__table__.columns["actor_id"]
        assert col.nullable is True

    def test_ride_id_is_nullable(self):
        col = AuditLog.__table__.columns["ride_id"]
        assert col.nullable is True

    def test_metadata_json_is_nullable(self):
        col = AuditLog.__table__.columns["metadata_json"]
        assert col.nullable is True

    def test_ip_address_is_nullable(self):
        col = AuditLog.__table__.columns["ip_address"]
        assert col.nullable is True

    def test_user_id_is_nullable(self):
        col = AuditLog.__table__.columns["user_id"]
        assert col.nullable is True

    def test_target_type_is_nullable(self):
        col = AuditLog.__table__.columns["target_type"]
        assert col.nullable is True

    def test_target_id_is_nullable(self):
        col = AuditLog.__table__.columns["target_id"]
        assert col.nullable is True


# ===========================================================================
# AuditCategory Enum Tests
# ===========================================================================


class TestAuditCategory:
    def test_ride_category(self):
        assert AuditCategory.RIDE == "ride"

    def test_driver_category(self):
        assert AuditCategory.DRIVER == "driver"

    def test_payment_category(self):
        assert AuditCategory.PAYMENT == "payment"

    def test_safety_category(self):
        assert AuditCategory.SAFETY == "safety"

    def test_dispute_category(self):
        assert AuditCategory.DISPUTE == "dispute"

    def test_verification_category(self):
        assert AuditCategory.VERIFICATION == "verification"

    def test_account_category(self):
        assert AuditCategory.ACCOUNT == "account"

    def test_admin_category(self):
        assert AuditCategory.ADMIN == "admin"

    def test_payout_category(self):
        assert AuditCategory.PAYOUT == "payout"

    def test_total_category_count(self):
        assert len(AuditCategory) == 9


class TestAuditSeverity:
    def test_info(self):
        assert AuditSeverity.INFO == "info"

    def test_warning(self):
        assert AuditSeverity.WARNING == "warning"

    def test_critical(self):
        assert AuditSeverity.CRITICAL == "critical"

    def test_total_severity_count(self):
        assert len(AuditSeverity) == 3


# ===========================================================================
# Schema Tests
# ===========================================================================


class TestAuditLogResponseSchema:
    def test_valid_response(self):
        data = AuditLogResponse(
            id=1,
            timestamp=datetime.now(timezone.utc),
            category="ride",
            severity="info",
            event_type="ride_requested",
            description="Ride #1 requested",
            actor_id=10,
            actor_role="rider",
            target_type=None,
            target_id=None,
            ride_id=1,
            user_id=10,
            metadata_json=None,
            ip_address=None,
        )
        assert data.id == 1
        assert data.category == "ride"

    def test_all_fields_nullable(self):
        data = AuditLogResponse(
            id=1,
            timestamp=datetime.now(timezone.utc),
            category="ride",
            severity="info",
            event_type="test",
            description="test",
            actor_id=None,
            actor_role=None,
            target_type=None,
            target_id=None,
            ride_id=None,
            user_id=None,
            metadata_json=None,
            ip_address=None,
        )
        assert data.actor_id is None
        assert data.ride_id is None


class TestAuditLogListResponseSchema:
    def test_list_response(self):
        data = AuditLogListResponse(logs=[], total=0, page=1, page_size=50)
        assert data.total == 0
        assert data.page == 1
        assert data.logs == []


class TestAuditStatsResponseSchema:
    def test_stats_response(self):
        now = datetime.now(timezone.utc)
        data = AuditStatsResponse(
            total_events=100,
            by_category={"ride": 50, "payment": 30, "safety": 20},
            by_severity={"info": 80, "warning": 15, "critical": 5},
            period_start=now - timedelta(days=30),
            period_end=now,
        )
        assert data.total_events == 100
        assert data.by_category["ride"] == 50


class TestComplianceReportResponseSchema:
    def test_compliance_report(self):
        now = datetime.now(timezone.utc)
        data = ComplianceReportResponse(
            report_period_start=now - timedelta(days=30),
            report_period_end=now,
            generated_at=now,
            total_rides=500,
            completed_rides=450,
            cancelled_rides=50,
            total_drivers=100,
            approved_drivers=90,
            pending_drivers=10,
            sos_incidents=5,
            sos_resolved=4,
            disputes_filed=20,
            disputes_resolved=18,
            total_payments_processed=440,
            total_payouts_issued=100,
            driver_verifications_approved=85,
            driver_verifications_rejected=5,
            audit_events_logged=2000,
            critical_events=10,
            top_event_types=[{"event_type": "ride_completed", "count": 450}],
        )
        assert data.total_rides == 500
        assert data.approved_drivers == 90
        assert data.sos_incidents == 5


class TestComplianceReportRequestSchema:
    def test_request_defaults(self):
        now = datetime.now(timezone.utc)
        req = ComplianceReportRequest(
            start_date=now - timedelta(days=30),
            end_date=now,
        )
        assert req.include_details is False

    def test_request_with_details(self):
        now = datetime.now(timezone.utc)
        req = ComplianceReportRequest(
            start_date=now - timedelta(days=30),
            end_date=now,
            include_details=True,
        )
        assert req.include_details is True


# ===========================================================================
# Audit Service — log_event Tests
# ===========================================================================


class TestLogEvent:
    @pytest.fixture
    def mock_db(self):
        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()
        return db

    @pytest.mark.asyncio
    async def test_log_event_creates_entry(self, mock_db):
        from app.services.audit import log_event

        result = await log_event(
            mock_db,
            category="ride",
            event_type="ride_requested",
            description="Test ride requested",
        )
        assert result is not None
        mock_db.add.assert_called_once()
        mock_db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_log_event_sets_category(self, mock_db):
        from app.services.audit import log_event

        result = await log_event(
            mock_db,
            category="safety",
            event_type="sos_triggered",
            description="SOS triggered",
            severity="critical",
        )
        assert result.category == AuditCategory.SAFETY
        assert result.severity == AuditSeverity.CRITICAL

    @pytest.mark.asyncio
    async def test_log_event_with_metadata(self, mock_db):
        from app.services.audit import log_event

        result = await log_event(
            mock_db,
            category="payment",
            event_type="payment_completed",
            description="Payment done",
            metadata={"amount": 25.50, "currency": "USD"},
        )
        assert result is not None
        parsed = json.loads(result.metadata_json)
        assert parsed["amount"] == 25.50
        assert parsed["currency"] == "USD"

    @pytest.mark.asyncio
    async def test_log_event_with_actor(self, mock_db):
        from app.services.audit import log_event

        result = await log_event(
            mock_db,
            category="admin",
            event_type="driver_approved",
            description="Driver approved",
            actor_id=42,
            actor_role="admin",
        )
        assert result.actor_id == 42
        assert result.actor_role == "admin"

    @pytest.mark.asyncio
    async def test_log_event_with_target(self, mock_db):
        from app.services.audit import log_event

        result = await log_event(
            mock_db,
            category="verification",
            event_type="document_approved",
            description="Document approved",
            target_type="driver_document",
            target_id=99,
        )
        assert result.target_type == "driver_document"
        assert result.target_id == 99

    @pytest.mark.asyncio
    async def test_log_event_with_ride_id(self, mock_db):
        from app.services.audit import log_event

        result = await log_event(
            mock_db,
            category="ride",
            event_type="ride_completed",
            description="Ride completed",
            ride_id=123,
        )
        assert result.ride_id == 123

    @pytest.mark.asyncio
    async def test_log_event_with_ip(self, mock_db):
        from app.services.audit import log_event

        result = await log_event(
            mock_db,
            category="admin",
            event_type="settings_changed",
            description="Settings updated",
            ip_address="192.168.1.1",
        )
        assert result.ip_address == "192.168.1.1"

    @pytest.mark.asyncio
    async def test_log_event_never_raises_on_db_error(self, mock_db):
        from app.services.audit import log_event

        mock_db.flush.side_effect = Exception("DB connection lost")
        result = await log_event(
            mock_db,
            category="ride",
            event_type="ride_requested",
            description="Should not raise",
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_log_event_default_severity_is_info(self, mock_db):
        from app.services.audit import log_event

        result = await log_event(
            mock_db,
            category="ride",
            event_type="test",
            description="test",
        )
        assert result.severity == AuditSeverity.INFO

    @pytest.mark.asyncio
    async def test_log_event_no_metadata_is_none(self, mock_db):
        from app.services.audit import log_event

        result = await log_event(
            mock_db,
            category="ride",
            event_type="test",
            description="test",
        )
        assert result.metadata_json is None


# ===========================================================================
# Audit Service — query_audit_logs Tests
# ===========================================================================


class TestQueryAuditLogs:
    @pytest.fixture
    def mock_db(self):
        db = AsyncMock()
        # Simulate empty results
        scalar_result = MagicMock()
        scalar_result.scalar.return_value = 0
        scalars_result = MagicMock()
        scalars_result.all.return_value = []
        db.execute = AsyncMock(side_effect=[scalar_result, scalars_result])
        return db

    @pytest.mark.asyncio
    async def test_query_returns_tuple(self, mock_db):
        from app.services.audit import query_audit_logs

        # Re-mock to return count then rows
        count_result = MagicMock()
        count_result.scalar.return_value = 0
        rows_result = MagicMock()
        rows_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(side_effect=[count_result, rows_result])

        logs, total = await query_audit_logs(mock_db)
        assert total == 0
        assert logs == []

    @pytest.mark.asyncio
    async def test_query_with_category_filter(self, mock_db):
        from app.services.audit import query_audit_logs

        count_result = MagicMock()
        count_result.scalar.return_value = 0
        rows_result = MagicMock()
        rows_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(side_effect=[count_result, rows_result])

        logs, total = await query_audit_logs(mock_db, category="ride")
        assert total == 0

    @pytest.mark.asyncio
    async def test_query_with_severity_filter(self, mock_db):
        from app.services.audit import query_audit_logs

        count_result = MagicMock()
        count_result.scalar.return_value = 0
        rows_result = MagicMock()
        rows_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(side_effect=[count_result, rows_result])

        logs, total = await query_audit_logs(mock_db, severity="critical")
        assert total == 0

    @pytest.mark.asyncio
    async def test_query_with_date_range(self, mock_db):
        from app.services.audit import query_audit_logs

        count_result = MagicMock()
        count_result.scalar.return_value = 0
        rows_result = MagicMock()
        rows_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(side_effect=[count_result, rows_result])

        now = datetime.now(timezone.utc)
        logs, total = await query_audit_logs(
            mock_db,
            start_date=now - timedelta(days=7),
            end_date=now,
        )
        assert total == 0

    @pytest.mark.asyncio
    async def test_query_pagination(self, mock_db):
        from app.services.audit import query_audit_logs

        count_result = MagicMock()
        count_result.scalar.return_value = 100
        rows_result = MagicMock()
        rows_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(side_effect=[count_result, rows_result])

        logs, total = await query_audit_logs(mock_db, page=2, page_size=25)
        assert total == 100

    @pytest.mark.asyncio
    async def test_query_with_actor_id(self, mock_db):
        from app.services.audit import query_audit_logs

        count_result = MagicMock()
        count_result.scalar.return_value = 0
        rows_result = MagicMock()
        rows_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(side_effect=[count_result, rows_result])

        logs, total = await query_audit_logs(mock_db, actor_id=42)
        assert total == 0

    @pytest.mark.asyncio
    async def test_query_with_ride_id(self, mock_db):
        from app.services.audit import query_audit_logs

        count_result = MagicMock()
        count_result.scalar.return_value = 0
        rows_result = MagicMock()
        rows_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(side_effect=[count_result, rows_result])

        logs, total = await query_audit_logs(mock_db, ride_id=99)
        assert total == 0

    @pytest.mark.asyncio
    async def test_query_with_event_type(self, mock_db):
        from app.services.audit import query_audit_logs

        count_result = MagicMock()
        count_result.scalar.return_value = 0
        rows_result = MagicMock()
        rows_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(side_effect=[count_result, rows_result])

        logs, total = await query_audit_logs(mock_db, event_type="ride_completed")
        assert total == 0


# ===========================================================================
# Audit Service — get_audit_stats Tests
# ===========================================================================


class TestGetAuditStats:
    @pytest.mark.asyncio
    async def test_stats_returns_dict(self):
        from app.services.audit import get_audit_stats

        db = AsyncMock()
        # count query
        count_res = MagicMock()
        count_res.scalar.return_value = 42
        # category query
        cat_res = MagicMock()
        cat_res.all.return_value = []
        # severity query
        sev_res = MagicMock()
        sev_res.all.return_value = []
        db.execute = AsyncMock(side_effect=[count_res, cat_res, sev_res])

        result = await get_audit_stats(db)
        assert result["total_events"] == 42
        assert isinstance(result["by_category"], dict)
        assert isinstance(result["by_severity"], dict)

    @pytest.mark.asyncio
    async def test_stats_with_date_range(self):
        from app.services.audit import get_audit_stats

        db = AsyncMock()
        count_res = MagicMock()
        count_res.scalar.return_value = 10
        cat_res = MagicMock()
        cat_res.all.return_value = []
        sev_res = MagicMock()
        sev_res.all.return_value = []
        db.execute = AsyncMock(side_effect=[count_res, cat_res, sev_res])

        now = datetime.now(timezone.utc)
        result = await get_audit_stats(
            db,
            start_date=now - timedelta(days=7),
            end_date=now,
        )
        assert result["total_events"] == 10


# ===========================================================================
# Audit Event Dispatchers Tests
# ===========================================================================


class TestAuditEventDispatchers:
    @pytest.fixture
    def mock_db(self):
        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()
        return db

    @pytest.mark.asyncio
    async def test_audit_ride_requested(self, mock_db):
        from app.services.audit_events import audit_ride_requested

        await audit_ride_requested(
            mock_db, ride_id=1, rider_id=10,
            pickup="123 Main St", dropoff="456 Oak Ave",
        )
        mock_db.add.assert_called_once()
        entry = mock_db.add.call_args[0][0]
        assert entry.event_type == "ride_requested"
        assert entry.category == AuditCategory.RIDE
        assert entry.ride_id == 1

    @pytest.mark.asyncio
    async def test_audit_ride_matched(self, mock_db):
        from app.services.audit_events import audit_ride_matched

        await audit_ride_matched(mock_db, ride_id=1, driver_id=20, rider_id=10)
        mock_db.add.assert_called_once()
        entry = mock_db.add.call_args[0][0]
        assert entry.event_type == "ride_matched"
        assert entry.actor_id == 20

    @pytest.mark.asyncio
    async def test_audit_ride_completed(self, mock_db):
        from app.services.audit_events import audit_ride_completed

        await audit_ride_completed(
            mock_db, ride_id=1, driver_id=20, rider_id=10, fare=25.50,
        )
        mock_db.add.assert_called_once()
        entry = mock_db.add.call_args[0][0]
        assert entry.event_type == "ride_completed"
        assert "25.50" in entry.description
        parsed = json.loads(entry.metadata_json)
        assert parsed["fare"] == 25.50

    @pytest.mark.asyncio
    async def test_audit_ride_cancelled(self, mock_db):
        from app.services.audit_events import audit_ride_cancelled

        await audit_ride_cancelled(
            mock_db, ride_id=1, cancelled_by=10, role="rider", reason="Changed plans",
        )
        mock_db.add.assert_called_once()
        entry = mock_db.add.call_args[0][0]
        assert entry.event_type == "ride_cancelled"
        assert entry.severity == AuditSeverity.WARNING
        assert "Changed plans" in entry.description

    @pytest.mark.asyncio
    async def test_audit_ride_cancelled_no_reason(self, mock_db):
        from app.services.audit_events import audit_ride_cancelled

        await audit_ride_cancelled(
            mock_db, ride_id=1, cancelled_by=10, role="rider",
        )
        entry = mock_db.add.call_args[0][0]
        assert "rider" in entry.description

    @pytest.mark.asyncio
    async def test_audit_sos_triggered(self, mock_db):
        from app.services.audit_events import audit_sos_triggered

        await audit_sos_triggered(mock_db, sos_id=5, user_id=10, ride_id=1)
        entry = mock_db.add.call_args[0][0]
        assert entry.event_type == "sos_triggered"
        assert entry.severity == AuditSeverity.CRITICAL
        assert entry.category == AuditCategory.SAFETY

    @pytest.mark.asyncio
    async def test_audit_sos_resolved(self, mock_db):
        from app.services.audit_events import audit_sos_resolved

        await audit_sos_resolved(mock_db, sos_id=5, resolved_by=99, status="resolved")
        entry = mock_db.add.call_args[0][0]
        assert entry.event_type == "sos_resolved"
        assert entry.severity == AuditSeverity.CRITICAL
        assert entry.actor_role == "admin"

    @pytest.mark.asyncio
    async def test_audit_document_reviewed_approved(self, mock_db):
        from app.services.audit_events import audit_document_reviewed

        await audit_document_reviewed(
            mock_db, document_id=7, driver_profile_id=3,
            reviewer_id=99, decision="approved",
        )
        entry = mock_db.add.call_args[0][0]
        assert entry.event_type == "document_approved"
        assert entry.severity == AuditSeverity.INFO

    @pytest.mark.asyncio
    async def test_audit_document_reviewed_rejected(self, mock_db):
        from app.services.audit_events import audit_document_reviewed

        await audit_document_reviewed(
            mock_db, document_id=7, driver_profile_id=3,
            reviewer_id=99, decision="rejected", reason="Expired license",
        )
        entry = mock_db.add.call_args[0][0]
        assert entry.event_type == "document_rejected"
        assert entry.severity == AuditSeverity.WARNING
        assert "Expired license" in entry.description

    @pytest.mark.asyncio
    async def test_audit_dispute_filed(self, mock_db):
        from app.services.audit_events import audit_dispute_filed

        await audit_dispute_filed(
            mock_db, dispute_id=11, ride_id=1, filed_by=10, dispute_type="fare",
        )
        entry = mock_db.add.call_args[0][0]
        assert entry.event_type == "dispute_filed"
        assert entry.category == AuditCategory.DISPUTE

    @pytest.mark.asyncio
    async def test_audit_dispute_resolved(self, mock_db):
        from app.services.audit_events import audit_dispute_resolved

        await audit_dispute_resolved(
            mock_db, dispute_id=11, ride_id=1, resolved_by=99,
            resolution="resolved_rider_favor", refund_amount=15.00,
        )
        entry = mock_db.add.call_args[0][0]
        assert entry.event_type == "dispute_resolved"
        assert "15.00" in entry.description
        parsed = json.loads(entry.metadata_json)
        assert parsed["refund_amount"] == 15.00

    @pytest.mark.asyncio
    async def test_audit_dispute_resolved_no_refund(self, mock_db):
        from app.services.audit_events import audit_dispute_resolved

        await audit_dispute_resolved(
            mock_db, dispute_id=11, ride_id=1, resolved_by=99,
            resolution="dismissed",
        )
        entry = mock_db.add.call_args[0][0]
        assert "refund" not in entry.description.lower()

    @pytest.mark.asyncio
    async def test_audit_payment_completed(self, mock_db):
        from app.services.audit_events import audit_payment_completed

        await audit_payment_completed(
            mock_db, payment_id=50, ride_id=1, amount=30.00, payment_type="ride_fare",
        )
        entry = mock_db.add.call_args[0][0]
        assert entry.event_type == "payment_completed"
        assert entry.category == AuditCategory.PAYMENT

    @pytest.mark.asyncio
    async def test_audit_payment_refunded(self, mock_db):
        from app.services.audit_events import audit_payment_refunded

        await audit_payment_refunded(
            mock_db, payment_id=50, ride_id=1, amount=30.00, actor_id=99,
        )
        entry = mock_db.add.call_args[0][0]
        assert entry.event_type == "payment_refunded"
        assert entry.severity == AuditSeverity.WARNING
        assert entry.actor_role == "admin"

    @pytest.mark.asyncio
    async def test_audit_payment_refunded_no_actor(self, mock_db):
        from app.services.audit_events import audit_payment_refunded

        await audit_payment_refunded(
            mock_db, payment_id=50, ride_id=1, amount=30.00,
        )
        entry = mock_db.add.call_args[0][0]
        assert entry.actor_id is None
        assert entry.actor_role is None

    @pytest.mark.asyncio
    async def test_audit_payout_completed(self, mock_db):
        from app.services.audit_events import audit_payout_completed

        await audit_payout_completed(
            mock_db, payout_id=77, driver_id=20, amount=150.00,
        )
        entry = mock_db.add.call_args[0][0]
        assert entry.event_type == "payout_completed"
        assert entry.category == AuditCategory.PAYOUT

    @pytest.mark.asyncio
    async def test_audit_admin_action(self, mock_db):
        from app.services.audit_events import audit_admin_action

        await audit_admin_action(
            mock_db, admin_id=99, action="driver_approved",
            description="Driver #3 approved",
            target_type="driver_profile", target_id=3,
        )
        entry = mock_db.add.call_args[0][0]
        assert entry.event_type == "driver_approved"
        assert entry.category == AuditCategory.ADMIN
        assert entry.actor_role == "admin"

    @pytest.mark.asyncio
    async def test_audit_admin_action_with_metadata(self, mock_db):
        from app.services.audit_events import audit_admin_action

        await audit_admin_action(
            mock_db, admin_id=99, action="settings_changed",
            description="Platform settings updated",
            metadata={"setting": "base_fare", "old": 2.50, "new": 3.00},
        )
        entry = mock_db.add.call_args[0][0]
        parsed = json.loads(entry.metadata_json)
        assert parsed["setting"] == "base_fare"

    @pytest.mark.asyncio
    async def test_audit_account_event(self, mock_db):
        from app.services.audit_events import audit_account_event

        await audit_account_event(
            mock_db, user_id=10, event_type="account_created",
            description="New account created",
        )
        entry = mock_db.add.call_args[0][0]
        assert entry.event_type == "account_created"
        assert entry.category == AuditCategory.ACCOUNT

    @pytest.mark.asyncio
    async def test_dispatchers_never_raise(self, mock_db):
        """Audit event dispatchers must never raise even on DB errors."""
        from app.services.audit_events import (
            audit_ride_requested,
            audit_ride_matched,
            audit_ride_completed,
            audit_ride_cancelled,
            audit_sos_triggered,
            audit_sos_resolved,
            audit_document_reviewed,
            audit_dispute_filed,
            audit_dispute_resolved,
            audit_payment_completed,
            audit_payment_refunded,
            audit_payout_completed,
            audit_admin_action,
            audit_account_event,
        )

        mock_db.flush.side_effect = Exception("DB dead")

        # None of these should raise
        await audit_ride_requested(mock_db, ride_id=1, rider_id=10, pickup="A", dropoff="B")
        await audit_ride_matched(mock_db, ride_id=1, driver_id=20, rider_id=10)
        await audit_ride_completed(mock_db, ride_id=1, driver_id=20, rider_id=10, fare=10.0)
        await audit_ride_cancelled(mock_db, ride_id=1, cancelled_by=10, role="rider")
        await audit_sos_triggered(mock_db, sos_id=1, user_id=10, ride_id=1)
        await audit_sos_resolved(mock_db, sos_id=1, resolved_by=99, status="resolved")
        await audit_document_reviewed(mock_db, document_id=1, driver_profile_id=1, reviewer_id=99, decision="approved")
        await audit_dispute_filed(mock_db, dispute_id=1, ride_id=1, filed_by=10, dispute_type="fare")
        await audit_dispute_resolved(mock_db, dispute_id=1, ride_id=1, resolved_by=99, resolution="dismissed")
        await audit_payment_completed(mock_db, payment_id=1, ride_id=1, amount=10.0, payment_type="ride_fare")
        await audit_payment_refunded(mock_db, payment_id=1, ride_id=1, amount=10.0)
        await audit_payout_completed(mock_db, payout_id=1, driver_id=20, amount=100.0)
        await audit_admin_action(mock_db, admin_id=99, action="test", description="test")
        await audit_account_event(mock_db, user_id=10, event_type="test", description="test")


# ===========================================================================
# Router Registration Tests
# ===========================================================================


class TestRouterRegistration:
    def test_audit_router_registered(self):
        from app.main import app

        paths = [r.path for r in app.routes]
        assert any("/admin/audit" in p for p in paths)

    def test_audit_logs_endpoint_exists(self):
        from app.main import app

        paths = [r.path for r in app.routes]
        assert "/api/v1/admin/audit/logs" in paths

    def test_audit_stats_endpoint_exists(self):
        from app.main import app

        paths = [r.path for r in app.routes]
        assert "/api/v1/admin/audit/stats" in paths

    def test_compliance_report_endpoint_exists(self):
        from app.main import app

        paths = [r.path for r in app.routes]
        assert "/api/v1/admin/audit/compliance-report" in paths


class TestAuditModelRegistration:
    def test_audit_log_imported_in_models_init(self):
        from app.models import AuditLog as ImportedAuditLog

        assert ImportedAuditLog is AuditLog


# ===========================================================================
# API Endpoint Behaviour Tests
# ===========================================================================


class TestAuditAPIEndpoints:
    def test_audit_router_tags(self):
        from app.api.v1.audit import router

        assert "audit" in router.tags

    def test_audit_router_prefix(self):
        from app.api.v1.audit import router

        assert router.prefix == "/admin/audit"

    def test_logs_endpoint_has_query_params(self):
        from app.api.v1.audit import list_audit_logs
        import inspect

        sig = inspect.signature(list_audit_logs)
        params = set(sig.parameters.keys())
        assert "category" in params
        assert "severity" in params
        assert "event_type" in params
        assert "page" in params
        assert "page_size" in params

    def test_stats_endpoint_has_date_params(self):
        from app.api.v1.audit import audit_stats
        import inspect

        sig = inspect.signature(audit_stats)
        params = set(sig.parameters.keys())
        assert "start_date" in params
        assert "end_date" in params

    def test_compliance_endpoint_accepts_request_body(self):
        from app.api.v1.audit import compliance_report
        import inspect

        sig = inspect.signature(compliance_report)
        params = set(sig.parameters.keys())
        assert "request" in params


# ===========================================================================
# Edge Cases and Boundary Tests
# ===========================================================================


class TestEdgeCases:
    @pytest.fixture
    def mock_db(self):
        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()
        return db

    @pytest.mark.asyncio
    async def test_log_event_with_all_optional_fields(self, mock_db):
        from app.services.audit import log_event

        result = await log_event(
            mock_db,
            category="ride",
            event_type="ride_requested",
            description="Full event",
            severity="warning",
            actor_id=1,
            actor_role="admin",
            target_type="ride",
            target_id=42,
            ride_id=42,
            user_id=10,
            metadata={"key": "value"},
            ip_address="10.0.0.1",
        )
        assert result is not None
        assert result.actor_id == 1
        assert result.target_type == "ride"
        assert result.ip_address == "10.0.0.1"

    @pytest.mark.asyncio
    async def test_log_event_minimal_fields(self, mock_db):
        from app.services.audit import log_event

        result = await log_event(
            mock_db,
            category="ride",
            event_type="test",
            description="minimal",
        )
        assert result is not None
        assert result.actor_id is None
        assert result.ride_id is None
        assert result.metadata_json is None

    def test_all_categories_are_strings(self):
        for cat in AuditCategory:
            assert isinstance(cat.value, str)

    def test_all_severities_are_strings(self):
        for sev in AuditSeverity:
            assert isinstance(sev.value, str)

    def test_category_values_are_lowercase(self):
        for cat in AuditCategory:
            assert cat.value == cat.value.lower()

    def test_severity_values_are_lowercase(self):
        for sev in AuditSeverity:
            assert sev.value == sev.value.lower()

    @pytest.mark.asyncio
    async def test_metadata_empty_dict_is_none(self, mock_db):
        """Empty dict is falsy, so treated as no metadata — returns None."""
        from app.services.audit import log_event

        result = await log_event(
            mock_db,
            category="ride",
            event_type="test",
            description="empty metadata",
            metadata={},
        )
        assert result.metadata_json is None

    @pytest.mark.asyncio
    async def test_metadata_complex_structure(self, mock_db):
        from app.services.audit import log_event

        result = await log_event(
            mock_db,
            category="ride",
            event_type="test",
            description="complex metadata",
            metadata={"nested": {"key": "val"}, "list": [1, 2, 3]},
        )
        parsed = json.loads(result.metadata_json)
        assert parsed["nested"]["key"] == "val"
        assert parsed["list"] == [1, 2, 3]
