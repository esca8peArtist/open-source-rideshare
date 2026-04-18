"""Unit tests for driver status history endpoints.

GET /admin/drivers/{driver_id}/status-history
GET /admin/drivers/status-changes

Coverage
--------
Schemas
  - DriverStatusChangeEntry: all fields populated
  - DriverStatusChangeEntry: None admin_id and None reason
  - RecentDriverStatusChangeEntry: includes driver_id field
  - DriverStatusHistoryResponse: serializes correctly
  - RecentDriverStatusChangesResponse: serializes correctly

Per-driver history (admin_get_driver_status_history)
  - Empty history (driver exists, no status changes) -> total=0, items=[]
  - Single approved entry -> action="approved", reason=None
  - Single suspended entry with reason -> action="suspended", reason="violation"
  - Mixed history (approved -> suspended -> reactivated) -> newest-first order
  - 404 when driver profile not found
  - Pagination: skip/limit passed through
  - bulk_driver_approved -> action="approved"
  - bulk_driver_suspended -> action="suspended" with reason

Recent status changes (admin_get_recent_driver_status_changes)
  - Empty result -> total=0, items=[]
  - Multiple changes across different drivers -> includes driver_id in each entry
  - days parameter passed through correctly
  - Default days=7 when not specified
  - Pagination works
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from app.schemas.admin import (
    DriverStatusChangeEntry,
    DriverStatusHistoryResponse,
    RecentDriverStatusChangeEntry,
    RecentDriverStatusChangesResponse,
)

NOW = datetime(2026, 4, 18, 12, 0, 0, tzinfo=timezone.utc)
EARLIER = datetime(2026, 4, 17, 10, 0, 0, tzinfo=timezone.utc)
EARLIEST = datetime(2026, 4, 16, 8, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_admin(admin_id=99):
    from app.models.user import User, UserRole
    a = MagicMock(spec=User)
    a.id = admin_id
    a.role = UserRole.ADMIN
    return a


def _make_audit_log(
    log_id=1,
    event_type="driver_approved",
    target_id=10,
    actor_id=99,
    timestamp=NOW,
    description="Driver profile #10 approved",
    metadata_json=None,
):
    from app.models.audit import AuditLog
    log = MagicMock(spec=AuditLog)
    log.id = log_id
    log.event_type = event_type
    log.target_type = "driver_profile"
    log.target_id = target_id
    log.actor_id = actor_id
    log.timestamp = timestamp
    log.description = description
    log.metadata_json = metadata_json
    return log


def _make_driver_profile(profile_id=10):
    from app.models.driver import DriverProfile
    p = MagicMock(spec=DriverProfile)
    p.id = profile_id
    return p


def _scalar_result(value):
    r = MagicMock()
    r.scalar.return_value = value
    r.scalar_one_or_none.return_value = value
    return r


def _scalars_result(items):
    scalars = MagicMock()
    scalars.all.return_value = items
    r = MagicMock()
    r.scalars.return_value = scalars
    return r


def _mock_db(side_effects):
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=side_effects)
    return db


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------

class TestSchemas:
    def test_driver_status_change_entry_all_fields(self):
        entry = DriverStatusChangeEntry(
            id=1,
            timestamp=NOW,
            event_type="driver_suspended",
            action="suspended",
            admin_id=99,
            reason="policy violation",
            description="Driver profile #10 suspended: policy violation",
        )
        assert entry.id == 1
        assert entry.action == "suspended"
        assert entry.admin_id == 99
        assert entry.reason == "policy violation"

    def test_driver_status_change_entry_nullable_fields(self):
        entry = DriverStatusChangeEntry(
            id=2,
            timestamp=NOW,
            event_type="driver_approved",
            action="approved",
            admin_id=None,
            reason=None,
            description="Driver profile #10 approved",
        )
        assert entry.admin_id is None
        assert entry.reason is None

    def test_recent_driver_status_change_entry_has_driver_id(self):
        entry = RecentDriverStatusChangeEntry(
            id=3,
            timestamp=NOW,
            event_type="bulk_driver_reactivated",
            action="reactivated",
            driver_id=42,
            admin_id=99,
            reason=None,
            description="Bulk reactivated",
        )
        assert entry.driver_id == 42

    def test_driver_status_history_response_serializes(self):
        resp = DriverStatusHistoryResponse(
            driver_id=10,
            total=1,
            items=[
                DriverStatusChangeEntry(
                    id=1,
                    timestamp=NOW,
                    event_type="driver_approved",
                    action="approved",
                    admin_id=99,
                    reason=None,
                    description="Driver profile #10 approved",
                )
            ],
        )
        data = resp.model_dump()
        assert data["driver_id"] == 10
        assert data["total"] == 1
        assert len(data["items"]) == 1

    def test_recent_driver_status_changes_response_serializes(self):
        resp = RecentDriverStatusChangesResponse(
            total=0,
            items=[],
        )
        data = resp.model_dump()
        assert data["total"] == 0
        assert data["items"] == []


# ---------------------------------------------------------------------------
# Per-driver history tests
# ---------------------------------------------------------------------------

class TestAdminGetDriverStatusHistory:
    @pytest.mark.asyncio
    async def test_empty_history_driver_exists(self):
        from app.api.v1.admin import admin_get_driver_status_history

        db = _mock_db([
            _scalar_result(_make_driver_profile(10)),  # profile lookup
            _scalar_result(0),                          # count
            _scalars_result([]),                        # logs
        ])

        result = await admin_get_driver_status_history(
            driver_id=10, skip=0, limit=50, _admin=_make_admin(), db=db,
        )

        assert result.driver_id == 10
        assert result.total == 0
        assert result.items == []

    @pytest.mark.asyncio
    async def test_single_approved_entry(self):
        from app.api.v1.admin import admin_get_driver_status_history

        log = _make_audit_log(
            log_id=1, event_type="driver_approved", target_id=10,
            actor_id=99, timestamp=NOW,
            description="Driver profile #10 approved",
        )

        db = _mock_db([
            _scalar_result(_make_driver_profile(10)),
            _scalar_result(1),
            _scalars_result([log]),
        ])

        result = await admin_get_driver_status_history(
            driver_id=10, skip=0, limit=50, _admin=_make_admin(), db=db,
        )

        assert result.total == 1
        item = result.items[0]
        assert item.id == 1
        assert item.event_type == "driver_approved"
        assert item.action == "approved"
        assert item.admin_id == 99
        assert item.reason is None

    @pytest.mark.asyncio
    async def test_suspended_entry_with_reason(self):
        from app.api.v1.admin import admin_get_driver_status_history

        log = _make_audit_log(
            log_id=2, event_type="driver_suspended", target_id=10,
            actor_id=99, timestamp=NOW,
            description="Driver profile #10 suspended: violation",
            metadata_json=json.dumps({"reason": "violation"}),
        )

        db = _mock_db([
            _scalar_result(_make_driver_profile(10)),
            _scalar_result(1),
            _scalars_result([log]),
        ])

        result = await admin_get_driver_status_history(
            driver_id=10, skip=0, limit=50, _admin=_make_admin(), db=db,
        )

        item = result.items[0]
        assert item.action == "suspended"
        assert item.reason == "violation"

    @pytest.mark.asyncio
    async def test_mixed_history_newest_first(self):
        from app.api.v1.admin import admin_get_driver_status_history

        # Logs returned from DB already sorted newest-first by the query
        reactivated = _make_audit_log(
            log_id=3, event_type="bulk_driver_reactivated", target_id=10,
            timestamp=NOW, description="Reactivated",
        )
        suspended = _make_audit_log(
            log_id=2, event_type="driver_suspended", target_id=10,
            timestamp=EARLIER, description="Suspended",
            metadata_json=json.dumps({"reason": "late"}),
        )
        approved = _make_audit_log(
            log_id=1, event_type="driver_approved", target_id=10,
            timestamp=EARLIEST, description="Approved",
        )

        db = _mock_db([
            _scalar_result(_make_driver_profile(10)),
            _scalar_result(3),
            _scalars_result([reactivated, suspended, approved]),
        ])

        result = await admin_get_driver_status_history(
            driver_id=10, skip=0, limit=50, _admin=_make_admin(), db=db,
        )

        assert result.total == 3
        assert result.items[0].action == "reactivated"
        assert result.items[1].action == "suspended"
        assert result.items[1].reason == "late"
        assert result.items[2].action == "approved"

    @pytest.mark.asyncio
    async def test_404_when_driver_not_found(self):
        from fastapi import HTTPException
        from app.api.v1.admin import admin_get_driver_status_history

        db = _mock_db([
            _scalar_result(None),  # profile lookup returns None
        ])

        with pytest.raises(HTTPException) as exc_info:
            await admin_get_driver_status_history(
                driver_id=999, skip=0, limit=50, _admin=_make_admin(), db=db,
            )

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_pagination_skip_limit(self):
        from app.api.v1.admin import admin_get_driver_status_history

        db = _mock_db([
            _scalar_result(_make_driver_profile(10)),
            _scalar_result(20),   # total = 20 entries
            _scalars_result([]),   # page 2 offset=10 limit=10 → empty (beyond range)
        ])

        result = await admin_get_driver_status_history(
            driver_id=10, skip=10, limit=10, _admin=_make_admin(), db=db,
        )

        assert result.total == 20
        assert result.items == []

    @pytest.mark.asyncio
    async def test_bulk_driver_approved_maps_to_approved(self):
        from app.api.v1.admin import admin_get_driver_status_history

        log = _make_audit_log(
            log_id=5, event_type="bulk_driver_approved", target_id=10,
            description="Bulk approved",
        )

        db = _mock_db([
            _scalar_result(_make_driver_profile(10)),
            _scalar_result(1),
            _scalars_result([log]),
        ])

        result = await admin_get_driver_status_history(
            driver_id=10, skip=0, limit=50, _admin=_make_admin(), db=db,
        )

        assert result.items[0].action == "approved"

    @pytest.mark.asyncio
    async def test_bulk_driver_suspended_with_reason(self):
        from app.api.v1.admin import admin_get_driver_status_history

        log = _make_audit_log(
            log_id=6, event_type="bulk_driver_suspended", target_id=10,
            description="Bulk suspended",
            metadata_json=json.dumps({"reason": "fraud", "succeeded": [10]}),
        )

        db = _mock_db([
            _scalar_result(_make_driver_profile(10)),
            _scalar_result(1),
            _scalars_result([log]),
        ])

        result = await admin_get_driver_status_history(
            driver_id=10, skip=0, limit=50, _admin=_make_admin(), db=db,
        )

        item = result.items[0]
        assert item.action == "suspended"
        assert item.reason == "fraud"


# ---------------------------------------------------------------------------
# Recent status changes tests
# ---------------------------------------------------------------------------

class TestAdminGetRecentDriverStatusChanges:
    @pytest.mark.asyncio
    async def test_empty_result(self):
        from app.api.v1.admin import admin_get_recent_driver_status_changes

        db = _mock_db([
            _scalar_result(0),    # count
            _scalars_result([]),  # logs
        ])

        result = await admin_get_recent_driver_status_changes(
            days=7, skip=0, limit=50, _admin=_make_admin(), db=db,
        )

        assert result.total == 0
        assert result.items == []

    @pytest.mark.asyncio
    async def test_multiple_changes_across_drivers(self):
        from app.api.v1.admin import admin_get_recent_driver_status_changes

        log1 = _make_audit_log(
            log_id=1, event_type="driver_approved", target_id=10,
            actor_id=99, timestamp=NOW, description="Driver #10 approved",
        )
        log2 = _make_audit_log(
            log_id=2, event_type="driver_suspended", target_id=20,
            actor_id=99, timestamp=EARLIER,
            description="Driver #20 suspended",
            metadata_json=json.dumps({"reason": "no-show"}),
        )

        db = _mock_db([
            _scalar_result(2),
            _scalars_result([log1, log2]),
        ])

        result = await admin_get_recent_driver_status_changes(
            days=7, skip=0, limit=50, _admin=_make_admin(), db=db,
        )

        assert result.total == 2
        assert result.items[0].driver_id == 10
        assert result.items[0].action == "approved"
        assert result.items[1].driver_id == 20
        assert result.items[1].action == "suspended"
        assert result.items[1].reason == "no-show"

    @pytest.mark.asyncio
    async def test_days_parameter_accepted(self):
        """days=30 should be accepted without error."""
        from app.api.v1.admin import admin_get_recent_driver_status_changes

        db = _mock_db([
            _scalar_result(0),
            _scalars_result([]),
        ])

        result = await admin_get_recent_driver_status_changes(
            days=30, skip=0, limit=50, _admin=_make_admin(), db=db,
        )

        assert result.total == 0

    @pytest.mark.asyncio
    async def test_default_days_is_7(self):
        """Calling with no days argument uses default=7 without error."""
        from app.api.v1.admin import admin_get_recent_driver_status_changes
        import inspect

        sig = inspect.signature(admin_get_recent_driver_status_changes)
        days_default = sig.parameters["days"].default

        # FastAPI Query objects store the default in .default
        actual_default = days_default.default if hasattr(days_default, "default") else days_default
        assert actual_default == 7

    @pytest.mark.asyncio
    async def test_pagination_skip_and_limit(self):
        from app.api.v1.admin import admin_get_recent_driver_status_changes

        db = _mock_db([
            _scalar_result(100),  # total = 100
            _scalars_result([]),   # second page empty
        ])

        result = await admin_get_recent_driver_status_changes(
            days=7, skip=50, limit=50, _admin=_make_admin(), db=db,
        )

        assert result.total == 100
        assert result.items == []

    @pytest.mark.asyncio
    async def test_bulk_reactivated_action_mapping(self):
        from app.api.v1.admin import admin_get_recent_driver_status_changes

        log = _make_audit_log(
            log_id=7, event_type="bulk_driver_reactivated", target_id=15,
            description="Bulk reactivated",
        )

        db = _mock_db([
            _scalar_result(1),
            _scalars_result([log]),
        ])

        result = await admin_get_recent_driver_status_changes(
            days=7, skip=0, limit=50, _admin=_make_admin(), db=db,
        )

        item = result.items[0]
        assert item.driver_id == 15
        assert item.action == "reactivated"
        assert item.reason is None
