"""Tests for the corporate member fine-grained permission system.

Covers:
  - PermissionScope enum values
  - _is_currently_active (pure helper)
  - grant_permission (async, mocked DB)
  - revoke_permission (async, mocked DB)
  - get_permission (async, mocked DB)
  - list_member_permissions (async, mocked DB)
  - list_account_permissions (async, mocked DB)
  - has_permission (async, mocked DB)
  - get_members_with_scope (async, mocked DB)
  - get_permission_summary (async, mocked DB)
  - CorporateMemberPermission ORM model structure
  - Pydantic schemas

No live database is used. All DB interactions are mocked with AsyncMock /
MagicMock following the same pattern established in test_cancellation_policies.py.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.models.corporate_member_permission import (
    CorporateMemberPermission,
    PermissionScope,
)
from app.schemas.corporate_member_permission import (
    PermissionCheckResponse,
    PermissionGrantRequest,
    PermissionListResponse,
    PermissionResponse,
    PermissionScopeCount,
    PermissionSummaryResponse,
)
from app.services.corporate_member_permission import (
    _is_currently_active,
    get_members_with_scope,
    get_permission,
    get_permission_summary,
    grant_permission,
    has_permission,
    list_account_permissions,
    list_member_permissions,
    revoke_permission,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_UTC = timezone.utc


def _now() -> datetime:
    return datetime.now(_UTC)


def _make_entry(
    entry_id: int = 1,
    account_id: int = 10,
    member_id: int = 20,
    scope: PermissionScope = PermissionScope.BILLING_ADMIN,
    granted_by_id: int = 5,
    is_active: bool = True,
    expires_at: datetime | None = None,
    notes: str | None = None,
) -> MagicMock:
    """Build a mock CorporateMemberPermission ORM object."""
    entry = MagicMock(spec=CorporateMemberPermission)
    entry.id = entry_id
    entry.account_id = account_id
    entry.member_id = member_id
    entry.permission_scope = scope
    entry.granted_by_id = granted_by_id
    entry.granted_at = _now()
    entry.expires_at = expires_at
    entry.is_active = is_active
    entry.notes = notes
    return entry


def _db_scalar_one(value) -> AsyncMock:
    """Mock DB session whose single execute() returns value via scalar_one_or_none."""
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    db.execute = AsyncMock(return_value=result)
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    return db


def _db_scalars_all(items: list) -> AsyncMock:
    """Mock DB session whose single execute() returns a list via scalars().all()."""
    db = AsyncMock()
    result = MagicMock()
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = items
    result.scalars.return_value = scalars_mock
    db.execute = AsyncMock(return_value=result)
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    return db


def _db_two_scalar_one(first, second) -> AsyncMock:
    """Mock DB session returning two different scalar_one_or_none results in sequence."""
    db = AsyncMock()
    results = []
    for value in (first, second):
        r = MagicMock()
        r.scalar_one_or_none.return_value = value
        results.append(r)
    db.execute = AsyncMock(side_effect=results)
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    return db


# ===========================================================================
# TestPermissionScopeEnum
# ===========================================================================


class TestPermissionScopeEnum:
    """Verify all 7 PermissionScope string values."""

    def test_billing_admin_value(self):
        assert PermissionScope.BILLING_ADMIN.value == "billing_admin"

    def test_hr_admin_value(self):
        assert PermissionScope.HR_ADMIN.value == "hr_admin"

    def test_fleet_manager_value(self):
        assert PermissionScope.FLEET_MANAGER.value == "fleet_manager"

    def test_report_viewer_value(self):
        assert PermissionScope.REPORT_VIEWER.value == "report_viewer"

    def test_booking_approver_value(self):
        assert PermissionScope.BOOKING_APPROVER.value == "booking_approver"

    def test_data_exporter_value(self):
        assert PermissionScope.DATA_EXPORTER.value == "data_exporter"

    def test_sso_admin_value(self):
        assert PermissionScope.SSO_ADMIN.value == "sso_admin"

    def test_all_seven_members(self):
        assert len(PermissionScope) == 7


# ===========================================================================
# TestIsCurrentlyActive
# ===========================================================================


class TestIsCurrentlyActive:
    """Tests for the pure _is_currently_active helper (no async needed)."""

    def test_active_no_expiry_returns_true(self):
        entry = _make_entry(is_active=True, expires_at=None)
        assert _is_currently_active(entry) is True

    def test_revoked_returns_false(self):
        entry = _make_entry(is_active=False, expires_at=None)
        assert _is_currently_active(entry) is False

    def test_expired_in_the_past_returns_false(self):
        past = _now() - timedelta(seconds=1)
        entry = _make_entry(is_active=True, expires_at=past)
        assert _is_currently_active(entry) is False

    def test_expires_in_the_future_returns_true(self):
        future = _now() + timedelta(hours=1)
        entry = _make_entry(is_active=True, expires_at=future)
        assert _is_currently_active(entry) is True

    def test_revoked_and_expired_returns_false(self):
        past = _now() - timedelta(hours=1)
        entry = _make_entry(is_active=False, expires_at=past)
        assert _is_currently_active(entry) is False

    def test_revoked_with_future_expiry_still_returns_false(self):
        # is_active=False takes precedence over a non-expired expires_at
        future = _now() + timedelta(hours=24)
        entry = _make_entry(is_active=False, expires_at=future)
        assert _is_currently_active(entry) is False

    def test_expires_at_exactly_now_returns_false(self):
        # expires_at <= now → inactive
        now = _now()
        entry = _make_entry(is_active=True, expires_at=now - timedelta(microseconds=1))
        assert _is_currently_active(entry) is False


# ===========================================================================
# TestGrantPermission
# ===========================================================================


class TestGrantPermission:
    """Tests for grant_permission (async service with mocked DB)."""

    @pytest.mark.asyncio
    async def test_new_entry_created_when_none_exists(self):
        # _get_row returns None → should create a new entry
        db = _db_scalar_one(None)
        result = await grant_permission(
            db,
            account_id=10,
            member_id=20,
            scope=PermissionScope.BILLING_ADMIN,
            granted_by_id=5,
        )
        db.add.assert_called_once()
        db.flush.assert_awaited_once()
        added = db.add.call_args[0][0]
        assert isinstance(added, CorporateMemberPermission)

    @pytest.mark.asyncio
    async def test_new_entry_has_correct_fields(self):
        db = _db_scalar_one(None)
        await grant_permission(
            db,
            account_id=10,
            member_id=20,
            scope=PermissionScope.HR_ADMIN,
            granted_by_id=5,
            notes="Finance team",
        )
        added = db.add.call_args[0][0]
        assert added.account_id == 10
        assert added.member_id == 20
        assert added.permission_scope == PermissionScope.HR_ADMIN
        assert added.granted_by_id == 5
        assert added.is_active is True
        assert added.notes == "Finance team"

    @pytest.mark.asyncio
    async def test_active_entry_raises_409(self):
        active_entry = _make_entry(is_active=True, expires_at=None)
        db = _db_scalar_one(active_entry)
        with pytest.raises(HTTPException) as exc_info:
            await grant_permission(
                db,
                account_id=10,
                member_id=20,
                scope=PermissionScope.BILLING_ADMIN,
                granted_by_id=5,
            )
        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_active_entry_409_message_mentions_scope(self):
        active_entry = _make_entry(is_active=True, scope=PermissionScope.SSO_ADMIN)
        db = _db_scalar_one(active_entry)
        with pytest.raises(HTTPException) as exc_info:
            await grant_permission(
                db,
                account_id=10,
                member_id=20,
                scope=PermissionScope.SSO_ADMIN,
                granted_by_id=5,
            )
        detail = exc_info.value.detail
        assert "sso_admin" in detail or "SSO_ADMIN" in detail

    @pytest.mark.asyncio
    async def test_revoked_entry_is_reactivated(self):
        revoked_entry = _make_entry(is_active=False)
        db = _db_scalar_one(revoked_entry)
        result = await grant_permission(
            db,
            account_id=10,
            member_id=20,
            scope=PermissionScope.BILLING_ADMIN,
            granted_by_id=7,
            notes="Reactivated",
        )
        assert result is revoked_entry
        assert revoked_entry.is_active is True
        assert revoked_entry.granted_by_id == 7
        assert revoked_entry.notes == "Reactivated"
        db.flush.assert_awaited_once()
        db.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_expired_entry_is_reactivated(self):
        past = _now() - timedelta(hours=1)
        expired_entry = _make_entry(is_active=True, expires_at=past)
        db = _db_scalar_one(expired_entry)
        result = await grant_permission(
            db,
            account_id=10,
            member_id=20,
            scope=PermissionScope.REPORT_VIEWER,
            granted_by_id=5,
            expires_at=None,
        )
        assert result is expired_entry
        assert expired_entry.is_active is True
        assert expired_entry.expires_at is None

    @pytest.mark.asyncio
    async def test_new_entry_with_expiry_set(self):
        future = _now() + timedelta(days=30)
        db = _db_scalar_one(None)
        await grant_permission(
            db,
            account_id=10,
            member_id=20,
            scope=PermissionScope.DATA_EXPORTER,
            granted_by_id=5,
            expires_at=future,
        )
        added = db.add.call_args[0][0]
        assert added.expires_at == future

    @pytest.mark.asyncio
    async def test_returns_new_entry(self):
        db = _db_scalar_one(None)
        result = await grant_permission(
            db,
            account_id=10,
            member_id=20,
            scope=PermissionScope.FLEET_MANAGER,
            granted_by_id=5,
        )
        added = db.add.call_args[0][0]
        assert result is added


# ===========================================================================
# TestRevokePermission
# ===========================================================================


class TestRevokePermission:
    """Tests for revoke_permission (async service with mocked DB)."""

    @pytest.mark.asyncio
    async def test_active_entry_is_deactivated(self):
        entry = _make_entry(is_active=True)
        db = _db_scalar_one(entry)
        result = await revoke_permission(db, account_id=10, permission_id=1)
        assert entry.is_active is False
        db.flush.assert_awaited_once()
        assert result is entry

    @pytest.mark.asyncio
    async def test_not_found_raises_404(self):
        db = _db_scalar_one(None)
        with pytest.raises(HTTPException) as exc_info:
            await revoke_permission(db, account_id=10, permission_id=999)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_already_revoked_raises_404(self):
        entry = _make_entry(is_active=False)
        db = _db_scalar_one(entry)
        with pytest.raises(HTTPException) as exc_info:
            await revoke_permission(db, account_id=10, permission_id=1)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_not_found_detail_message(self):
        db = _db_scalar_one(None)
        with pytest.raises(HTTPException) as exc_info:
            await revoke_permission(db, account_id=10, permission_id=42)
        assert "not found" in exc_info.value.detail.lower() or "revoked" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_flush_called_on_success(self):
        entry = _make_entry(is_active=True)
        db = _db_scalar_one(entry)
        await revoke_permission(db, account_id=10, permission_id=1)
        db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_add_not_called_on_revoke(self):
        entry = _make_entry(is_active=True)
        db = _db_scalar_one(entry)
        await revoke_permission(db, account_id=10, permission_id=1)
        db.add.assert_not_called()


# ===========================================================================
# TestGetPermission
# ===========================================================================


class TestGetPermission:
    """Tests for get_permission (async service with mocked DB)."""

    @pytest.mark.asyncio
    async def test_found_returns_entry(self):
        entry = _make_entry()
        db = _db_scalar_one(entry)
        result = await get_permission(db, account_id=10, permission_id=1)
        assert result is entry

    @pytest.mark.asyncio
    async def test_not_found_raises_404(self):
        db = _db_scalar_one(None)
        with pytest.raises(HTTPException) as exc_info:
            await get_permission(db, account_id=10, permission_id=999)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_not_found_detail_message(self):
        db = _db_scalar_one(None)
        with pytest.raises(HTTPException) as exc_info:
            await get_permission(db, account_id=10, permission_id=1)
        assert "not found" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_execute_called_once(self):
        entry = _make_entry()
        db = _db_scalar_one(entry)
        await get_permission(db, account_id=10, permission_id=1)
        db.execute.assert_awaited_once()


# ===========================================================================
# TestListMemberPermissions
# ===========================================================================


class TestListMemberPermissions:
    """Tests for list_member_permissions (async service with mocked DB)."""

    @pytest.mark.asyncio
    async def test_returns_list_of_entries(self):
        entries = [_make_entry(entry_id=i) for i in range(1, 4)]
        db = _db_scalars_all(entries)
        result = await list_member_permissions(db, account_id=10, member_id=20)
        assert result == entries

    @pytest.mark.asyncio
    async def test_empty_list_returned_when_no_entries(self):
        db = _db_scalars_all([])
        result = await list_member_permissions(db, account_id=10, member_id=20)
        assert result == []

    @pytest.mark.asyncio
    async def test_active_only_true_is_default(self):
        entries = [_make_entry(is_active=True)]
        db = _db_scalars_all(entries)
        result = await list_member_permissions(db, account_id=10, member_id=20)
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_active_only_false_accepted(self):
        entries = [_make_entry(is_active=False), _make_entry(is_active=True)]
        db = _db_scalars_all(entries)
        result = await list_member_permissions(db, account_id=10, member_id=20, active_only=False)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_execute_called_once(self):
        db = _db_scalars_all([])
        await list_member_permissions(db, account_id=10, member_id=20)
        db.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_returns_plain_list_not_coroutine(self):
        entries = [_make_entry()]
        db = _db_scalars_all(entries)
        result = await list_member_permissions(db, account_id=10, member_id=20)
        assert isinstance(result, list)


# ===========================================================================
# TestListAccountPermissions
# ===========================================================================


class TestListAccountPermissions:
    """Tests for list_account_permissions (async service with mocked DB)."""

    @pytest.mark.asyncio
    async def test_returns_list(self):
        entries = [_make_entry(entry_id=i) for i in range(1, 6)]
        db = _db_scalars_all(entries)
        result = await list_account_permissions(db, account_id=10)
        assert result == entries

    @pytest.mark.asyncio
    async def test_empty_list_when_no_entries(self):
        db = _db_scalars_all([])
        result = await list_account_permissions(db, account_id=10)
        assert result == []

    @pytest.mark.asyncio
    async def test_scope_filter_accepted(self):
        entries = [_make_entry(scope=PermissionScope.BILLING_ADMIN)]
        db = _db_scalars_all(entries)
        result = await list_account_permissions(
            db, account_id=10, scope=PermissionScope.BILLING_ADMIN
        )
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_no_scope_filter_returns_all(self):
        entries = [
            _make_entry(entry_id=1, scope=PermissionScope.BILLING_ADMIN),
            _make_entry(entry_id=2, scope=PermissionScope.HR_ADMIN),
        ]
        db = _db_scalars_all(entries)
        result = await list_account_permissions(db, account_id=10, scope=None)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_active_only_false_accepted(self):
        entries = [_make_entry(is_active=False)]
        db = _db_scalars_all(entries)
        result = await list_account_permissions(db, account_id=10, active_only=False)
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_limit_and_offset_accepted(self):
        db = _db_scalars_all([])
        result = await list_account_permissions(db, account_id=10, limit=5, offset=10)
        assert result == []
        db.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_returns_plain_list(self):
        db = _db_scalars_all([])
        result = await list_account_permissions(db, account_id=10)
        assert isinstance(result, list)


# ===========================================================================
# TestHasPermission
# ===========================================================================


class TestHasPermission:
    """Tests for has_permission (async service with mocked DB)."""

    @pytest.mark.asyncio
    async def test_returns_true_when_active_entry_found(self):
        active_entry = _make_entry(is_active=True, expires_at=None)
        db = _db_scalar_one(active_entry)
        result = await has_permission(
            db, account_id=10, member_id=20, scope=PermissionScope.BILLING_ADMIN
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_when_no_entry(self):
        db = _db_scalar_one(None)
        result = await has_permission(
            db, account_id=10, member_id=20, scope=PermissionScope.BILLING_ADMIN
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_when_revoked(self):
        revoked_entry = _make_entry(is_active=False, expires_at=None)
        db = _db_scalar_one(revoked_entry)
        result = await has_permission(
            db, account_id=10, member_id=20, scope=PermissionScope.BILLING_ADMIN
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_when_expired(self):
        past = _now() - timedelta(hours=1)
        expired_entry = _make_entry(is_active=True, expires_at=past)
        db = _db_scalar_one(expired_entry)
        result = await has_permission(
            db, account_id=10, member_id=20, scope=PermissionScope.BILLING_ADMIN
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_returns_true_when_expiry_in_future(self):
        future = _now() + timedelta(hours=24)
        active_entry = _make_entry(is_active=True, expires_at=future)
        db = _db_scalar_one(active_entry)
        result = await has_permission(
            db, account_id=10, member_id=20, scope=PermissionScope.HR_ADMIN
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_returns_bool_not_entry(self):
        active_entry = _make_entry(is_active=True)
        db = _db_scalar_one(active_entry)
        result = await has_permission(
            db, account_id=10, member_id=20, scope=PermissionScope.FLEET_MANAGER
        )
        assert isinstance(result, bool)

    @pytest.mark.asyncio
    async def test_does_not_raise_when_not_found(self):
        db = _db_scalar_one(None)
        # Should return False, not raise
        result = await has_permission(
            db, account_id=10, member_id=20, scope=PermissionScope.SSO_ADMIN
        )
        assert result is False


# ===========================================================================
# TestGetMembersWithScope
# ===========================================================================


class TestGetMembersWithScope:
    """Tests for get_members_with_scope (async service with mocked DB)."""

    @pytest.mark.asyncio
    async def test_returns_entries_for_scope(self):
        entries = [
            _make_entry(entry_id=1, member_id=20, scope=PermissionScope.BOOKING_APPROVER),
            _make_entry(entry_id=2, member_id=21, scope=PermissionScope.BOOKING_APPROVER),
        ]
        db = _db_scalars_all(entries)
        result = await get_members_with_scope(
            db, account_id=10, scope=PermissionScope.BOOKING_APPROVER
        )
        assert result == entries

    @pytest.mark.asyncio
    async def test_empty_list_when_no_members(self):
        db = _db_scalars_all([])
        result = await get_members_with_scope(
            db, account_id=10, scope=PermissionScope.SSO_ADMIN
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_plain_list(self):
        db = _db_scalars_all([])
        result = await get_members_with_scope(
            db, account_id=10, scope=PermissionScope.FLEET_MANAGER
        )
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_execute_called_once(self):
        db = _db_scalars_all([])
        await get_members_with_scope(db, account_id=10, scope=PermissionScope.BILLING_ADMIN)
        db.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_single_member_returned(self):
        entry = _make_entry(entry_id=1, member_id=99, scope=PermissionScope.DATA_EXPORTER)
        db = _db_scalars_all([entry])
        result = await get_members_with_scope(
            db, account_id=10, scope=PermissionScope.DATA_EXPORTER
        )
        assert len(result) == 1
        assert result[0] is entry


# ===========================================================================
# TestGetPermissionSummary
# ===========================================================================


class TestGetPermissionSummary:
    """Tests for get_permission_summary (async service with mocked DB)."""

    def _db_for_summary(self, rows: list[tuple]) -> AsyncMock:
        """Build a mock DB where execute() returns the given (scope, count) rows."""
        db = AsyncMock()
        result = MagicMock()
        # The service iterates directly over rows (not via scalars())
        result.__iter__ = MagicMock(return_value=iter(rows))
        db.execute = AsyncMock(return_value=result)
        return db

    @pytest.mark.asyncio
    async def test_returns_dict_with_correct_keys(self):
        db = self._db_for_summary([])
        summary = await get_permission_summary(db, account_id=10)
        assert "account_id" in summary
        assert "total_active_grants" in summary
        assert "by_scope" in summary

    @pytest.mark.asyncio
    async def test_account_id_preserved(self):
        db = self._db_for_summary([])
        summary = await get_permission_summary(db, account_id=42)
        assert summary["account_id"] == 42

    @pytest.mark.asyncio
    async def test_total_is_sum_of_counts(self):
        rows = [
            (PermissionScope.BILLING_ADMIN, 3),
            (PermissionScope.HR_ADMIN, 5),
            (PermissionScope.SSO_ADMIN, 2),
        ]
        db = self._db_for_summary(rows)
        summary = await get_permission_summary(db, account_id=10)
        assert summary["total_active_grants"] == 10

    @pytest.mark.asyncio
    async def test_total_zero_when_no_grants(self):
        db = self._db_for_summary([])
        summary = await get_permission_summary(db, account_id=10)
        assert summary["total_active_grants"] == 0

    @pytest.mark.asyncio
    async def test_by_scope_is_list(self):
        db = self._db_for_summary([])
        summary = await get_permission_summary(db, account_id=10)
        assert isinstance(summary["by_scope"], list)

    @pytest.mark.asyncio
    async def test_by_scope_entries_have_correct_keys(self):
        rows = [(PermissionScope.BILLING_ADMIN, 4)]
        db = self._db_for_summary(rows)
        summary = await get_permission_summary(db, account_id=10)
        assert len(summary["by_scope"]) == 1
        entry = summary["by_scope"][0]
        assert "permission_scope" in entry
        assert "active_count" in entry

    @pytest.mark.asyncio
    async def test_by_scope_scope_value_preserved(self):
        rows = [(PermissionScope.FLEET_MANAGER, 7)]
        db = self._db_for_summary(rows)
        summary = await get_permission_summary(db, account_id=10)
        assert summary["by_scope"][0]["permission_scope"] == PermissionScope.FLEET_MANAGER

    @pytest.mark.asyncio
    async def test_by_scope_count_value_preserved(self):
        rows = [(PermissionScope.REPORT_VIEWER, 11)]
        db = self._db_for_summary(rows)
        summary = await get_permission_summary(db, account_id=10)
        assert summary["by_scope"][0]["active_count"] == 11

    @pytest.mark.asyncio
    async def test_execute_called_once(self):
        db = self._db_for_summary([])
        await get_permission_summary(db, account_id=10)
        db.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_multiple_scopes_all_in_by_scope(self):
        rows = [
            (PermissionScope.BILLING_ADMIN, 1),
            (PermissionScope.HR_ADMIN, 2),
            (PermissionScope.FLEET_MANAGER, 3),
        ]
        db = self._db_for_summary(rows)
        summary = await get_permission_summary(db, account_id=10)
        assert len(summary["by_scope"]) == 3


# ===========================================================================
# TestCorporateMemberPermissionModel
# ===========================================================================


class TestCorporateMemberPermissionModel:
    """Tests verifying the CorporateMemberPermission ORM table structure."""

    def _cols(self) -> set[str]:
        return {c.name for c in CorporateMemberPermission.__table__.columns}

    def _constraints(self):
        return CorporateMemberPermission.__table__.constraints

    def _indexes(self):
        return CorporateMemberPermission.__table__.indexes

    def test_table_name(self):
        assert CorporateMemberPermission.__tablename__ == "corporate_member_permissions"

    def test_has_id(self):
        assert "id" in self._cols()

    def test_has_account_id(self):
        assert "account_id" in self._cols()

    def test_has_member_id(self):
        assert "member_id" in self._cols()

    def test_has_permission_scope(self):
        assert "permission_scope" in self._cols()

    def test_has_granted_by_id(self):
        assert "granted_by_id" in self._cols()

    def test_has_granted_at(self):
        assert "granted_at" in self._cols()

    def test_has_expires_at(self):
        assert "expires_at" in self._cols()

    def test_has_is_active(self):
        assert "is_active" in self._cols()

    def test_has_notes(self):
        assert "notes" in self._cols()

    def test_unique_constraint_exists(self):
        from sqlalchemy import UniqueConstraint
        constraint_names = {
            c.name for c in self._constraints() if isinstance(c, UniqueConstraint)
        }
        assert "uq_corp_member_permission_account_member_scope" in constraint_names

    def test_unique_constraint_covers_account_member_scope(self):
        from sqlalchemy import UniqueConstraint
        uq = next(
            c for c in self._constraints()
            if isinstance(c, UniqueConstraint)
            and c.name == "uq_corp_member_permission_account_member_scope"
        )
        col_names = {col.name for col in uq.columns}
        assert col_names == {"account_id", "member_id", "permission_scope"}

    def test_index_on_account_id_exists(self):
        idx_names = {idx.name for idx in self._indexes()}
        assert "ix_corp_member_permission_account_id" in idx_names

    def test_index_on_member_id_exists(self):
        idx_names = {idx.name for idx in self._indexes()}
        assert "ix_corp_member_permission_member_id" in idx_names

    def test_partial_index_on_active_exists(self):
        idx_names = {idx.name for idx in self._indexes()}
        assert "ix_corp_member_permission_active" in idx_names

    def test_account_id_has_fk_to_corporate_accounts(self):
        col = CorporateMemberPermission.__table__.columns["account_id"]
        targets = {fk.target_fullname for fk in col.foreign_keys}
        assert "corporate_accounts_v2.id" in targets

    def test_member_id_has_fk_to_users(self):
        col = CorporateMemberPermission.__table__.columns["member_id"]
        targets = {fk.target_fullname for fk in col.foreign_keys}
        assert "users.id" in targets

    def test_granted_by_id_is_nullable(self):
        col = CorporateMemberPermission.__table__.columns["granted_by_id"]
        assert col.nullable is True

    def test_expires_at_is_nullable(self):
        col = CorporateMemberPermission.__table__.columns["expires_at"]
        assert col.nullable is True

    def test_notes_is_nullable(self):
        col = CorporateMemberPermission.__table__.columns["notes"]
        assert col.nullable is True

    def test_notes_max_length_500(self):
        col = CorporateMemberPermission.__table__.columns["notes"]
        assert col.type.length == 500


# ===========================================================================
# TestPermissionSchemas
# ===========================================================================


class TestPermissionSchemas:
    """Pydantic validation tests for corporate member permission schemas."""

    def test_grant_request_requires_member_id(self):
        with pytest.raises(Exception):
            PermissionGrantRequest(permission_scope=PermissionScope.BILLING_ADMIN)

    def test_grant_request_requires_permission_scope(self):
        with pytest.raises(Exception):
            PermissionGrantRequest(member_id=20)

    def test_grant_request_valid_scope(self):
        req = PermissionGrantRequest(
            member_id=20,
            permission_scope=PermissionScope.BILLING_ADMIN,
        )
        assert req.member_id == 20
        assert req.permission_scope == PermissionScope.BILLING_ADMIN

    def test_grant_request_invalid_scope_raises(self):
        with pytest.raises(Exception):
            PermissionGrantRequest(member_id=20, permission_scope="not_a_scope")

    def test_grant_request_expires_at_optional(self):
        req = PermissionGrantRequest(
            member_id=20,
            permission_scope=PermissionScope.HR_ADMIN,
        )
        assert req.expires_at is None

    def test_grant_request_expires_at_set(self):
        future = _now() + timedelta(days=90)
        req = PermissionGrantRequest(
            member_id=20,
            permission_scope=PermissionScope.HR_ADMIN,
            expires_at=future,
        )
        assert req.expires_at == future

    def test_grant_request_notes_optional(self):
        req = PermissionGrantRequest(
            member_id=20,
            permission_scope=PermissionScope.SSO_ADMIN,
        )
        assert req.notes is None

    def test_grant_request_notes_too_long_rejected(self):
        with pytest.raises(Exception):
            PermissionGrantRequest(
                member_id=20,
                permission_scope=PermissionScope.SSO_ADMIN,
                notes="x" * 501,
            )

    def test_grant_request_notes_max_length_accepted(self):
        req = PermissionGrantRequest(
            member_id=20,
            permission_scope=PermissionScope.SSO_ADMIN,
            notes="x" * 500,
        )
        assert len(req.notes) == 500

    def test_permission_response_from_attributes(self):
        assert PermissionResponse.model_config.get("from_attributes") is True

    def test_permission_response_all_fields_present(self):
        now = _now()
        resp = PermissionResponse(
            id=1,
            account_id=10,
            member_id=20,
            permission_scope=PermissionScope.FLEET_MANAGER,
            granted_by_id=5,
            granted_at=now,
            expires_at=None,
            is_active=True,
            notes=None,
        )
        assert resp.id == 1
        assert resp.account_id == 10
        assert resp.member_id == 20
        assert resp.permission_scope == PermissionScope.FLEET_MANAGER
        assert resp.is_active is True
        assert resp.expires_at is None

    def test_permission_list_response_fields(self):
        now = _now()
        item = PermissionResponse(
            id=1,
            account_id=10,
            member_id=20,
            permission_scope=PermissionScope.BILLING_ADMIN,
            granted_by_id=5,
            granted_at=now,
            expires_at=None,
            is_active=True,
            notes=None,
        )
        resp = PermissionListResponse(
            account_id=10,
            total=1,
            items=[item],
        )
        assert resp.account_id == 10
        assert resp.total == 1
        assert len(resp.items) == 1

    def test_permission_list_response_empty_items(self):
        resp = PermissionListResponse(account_id=10, total=0, items=[])
        assert resp.total == 0
        assert resp.items == []

    def test_permission_check_response_fields(self):
        resp = PermissionCheckResponse(
            account_id=10,
            member_id=20,
            permission_scope=PermissionScope.DATA_EXPORTER,
            has_permission=True,
        )
        assert resp.account_id == 10
        assert resp.member_id == 20
        assert resp.permission_scope == PermissionScope.DATA_EXPORTER
        assert resp.has_permission is True

    def test_permission_check_response_false(self):
        resp = PermissionCheckResponse(
            account_id=10,
            member_id=20,
            permission_scope=PermissionScope.BOOKING_APPROVER,
            has_permission=False,
        )
        assert resp.has_permission is False

    def test_permission_summary_response_fields(self):
        scope_count = PermissionScopeCount(
            permission_scope=PermissionScope.BILLING_ADMIN,
            active_count=3,
        )
        resp = PermissionSummaryResponse(
            account_id=10,
            total_active_grants=3,
            by_scope=[scope_count],
        )
        assert resp.account_id == 10
        assert resp.total_active_grants == 3
        assert len(resp.by_scope) == 1

    def test_permission_summary_response_empty_by_scope(self):
        resp = PermissionSummaryResponse(
            account_id=10,
            total_active_grants=0,
            by_scope=[],
        )
        assert resp.by_scope == []

    def test_permission_scope_count_fields(self):
        sc = PermissionScopeCount(
            permission_scope=PermissionScope.REPORT_VIEWER,
            active_count=12,
        )
        assert sc.permission_scope == PermissionScope.REPORT_VIEWER
        assert sc.active_count == 12

    def test_all_scopes_accepted_in_grant_request(self):
        for scope in PermissionScope:
            req = PermissionGrantRequest(member_id=1, permission_scope=scope)
            assert req.permission_scope == scope
