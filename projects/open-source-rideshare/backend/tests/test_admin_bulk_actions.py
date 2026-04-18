"""Unit tests for admin bulk driver action endpoints."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.driver import DriverProfile
from app.models.user import User, UserRole
from app.schemas.admin import BulkActionResult, BulkDriverIdsRequest, BulkDriverSuspendRequest


def _make_user(user_id=1, is_active=True):
    user = MagicMock(spec=User)
    user.id = user_id
    user.role = UserRole.DRIVER
    user.is_active = is_active
    return user


def _make_profile(profile_id=1, user_id=1, is_approved=True, is_online=False):
    profile = MagicMock(spec=DriverProfile)
    profile.id = profile_id
    profile.user_id = user_id
    profile.is_approved = is_approved
    profile.is_online = is_online
    profile.background_check_status = "approved"
    profile.user = _make_user(user_id)
    return profile


def _mock_db():
    db = AsyncMock()
    db.commit = AsyncMock()
    return db


def _scalars_result(items):
    scalars = MagicMock()
    scalars.all.return_value = items
    result = MagicMock()
    result.scalars.return_value = scalars
    result.unique.return_value = result
    return result


def _make_admin():
    admin = MagicMock(spec=User)
    admin.id = 99
    admin.role = UserRole.ADMIN
    return admin


# ---------------------------------------------------------------------------
# bulk_approve_drivers
# ---------------------------------------------------------------------------

class TestBulkApproveDrivers:
    @pytest.mark.asyncio
    @patch("app.services.audit_events.audit_admin_action", new_callable=AsyncMock)
    async def test_approves_all_found(self, mock_audit):
        from app.api.v1.admin import bulk_approve_drivers

        p1 = _make_profile(1, is_approved=False)
        p2 = _make_profile(2, is_approved=False)
        db = _mock_db()
        db.execute = AsyncMock(return_value=_scalars_result([p1, p2]))

        req = BulkDriverIdsRequest(driver_ids=[1, 2])
        result = await bulk_approve_drivers(body=req, admin=_make_admin(), db=db)

        assert result.succeeded == [1, 2]
        assert result.not_found == []
        assert result.total_requested == 2
        assert result.total_succeeded == 2
        assert p1.is_approved is True
        assert p1.background_check_status == "approved"
        assert p2.is_approved is True
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    @patch("app.services.audit_events.audit_admin_action", new_callable=AsyncMock)
    async def test_partial_not_found(self, mock_audit):
        from app.api.v1.admin import bulk_approve_drivers

        p1 = _make_profile(1, is_approved=False)
        db = _mock_db()
        db.execute = AsyncMock(return_value=_scalars_result([p1]))

        req = BulkDriverIdsRequest(driver_ids=[1, 99])
        result = await bulk_approve_drivers(body=req, admin=_make_admin(), db=db)

        assert result.succeeded == [1]
        assert result.not_found == [99]
        assert result.total_requested == 2
        assert result.total_succeeded == 1

    @pytest.mark.asyncio
    @patch("app.services.audit_events.audit_admin_action", new_callable=AsyncMock)
    async def test_all_not_found(self, mock_audit):
        from app.api.v1.admin import bulk_approve_drivers

        db = _mock_db()
        db.execute = AsyncMock(return_value=_scalars_result([]))

        req = BulkDriverIdsRequest(driver_ids=[50, 51])
        result = await bulk_approve_drivers(body=req, admin=_make_admin(), db=db)

        assert result.succeeded == []
        assert result.not_found == [50, 51]
        assert result.total_succeeded == 0

    def test_schema_rejects_empty_list(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            BulkDriverIdsRequest(driver_ids=[])

    def test_schema_rejects_over_100(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            BulkDriverIdsRequest(driver_ids=list(range(101)))


# ---------------------------------------------------------------------------
# bulk_suspend_drivers
# ---------------------------------------------------------------------------

class TestBulkSuspendDrivers:
    @pytest.mark.asyncio
    @patch("app.services.audit_events.audit_admin_action", new_callable=AsyncMock)
    async def test_suspends_all_found(self, mock_audit):
        from app.api.v1.admin import bulk_suspend_drivers

        p1 = _make_profile(1, is_approved=True, is_online=True)
        p2 = _make_profile(2, is_approved=True, is_online=False)
        db = _mock_db()
        db.execute = AsyncMock(return_value=_scalars_result([p1, p2]))

        req = BulkDriverSuspendRequest(driver_ids=[1, 2], reason="Policy violation")
        result = await bulk_suspend_drivers(body=req, admin=_make_admin(), db=db)

        assert result.succeeded == [1, 2]
        assert result.not_found == []
        assert p1.is_approved is False
        assert p1.is_online is False
        assert p1.background_check_status == "suspended"
        assert p1.user.is_active is False
        assert p2.is_approved is False
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    @patch("app.services.audit_events.audit_admin_action", new_callable=AsyncMock)
    async def test_partial_not_found(self, mock_audit):
        from app.api.v1.admin import bulk_suspend_drivers

        p1 = _make_profile(1)
        db = _mock_db()
        db.execute = AsyncMock(return_value=_scalars_result([p1]))

        req = BulkDriverSuspendRequest(driver_ids=[1, 42], reason="Fraud")
        result = await bulk_suspend_drivers(body=req, admin=_make_admin(), db=db)

        assert result.succeeded == [1]
        assert result.not_found == [42]

    def test_schema_requires_reason(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            BulkDriverSuspendRequest(driver_ids=[1])

    def test_schema_rejects_empty_reason(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            BulkDriverSuspendRequest(driver_ids=[1], reason="")


# ---------------------------------------------------------------------------
# bulk_reactivate_drivers
# ---------------------------------------------------------------------------

class TestBulkReactivateDrivers:
    @pytest.mark.asyncio
    @patch("app.services.audit_events.audit_admin_action", new_callable=AsyncMock)
    async def test_reactivates_all_found(self, mock_audit):
        from app.api.v1.admin import bulk_reactivate_drivers

        p1 = _make_profile(1, is_approved=False)
        p2 = _make_profile(2, is_approved=False)
        p1.user.is_active = False
        p2.user.is_active = False
        db = _mock_db()
        db.execute = AsyncMock(return_value=_scalars_result([p1, p2]))

        req = BulkDriverIdsRequest(driver_ids=[1, 2])
        result = await bulk_reactivate_drivers(body=req, admin=_make_admin(), db=db)

        assert result.succeeded == [1, 2]
        assert result.not_found == []
        assert result.total_succeeded == 2
        assert p1.is_approved is True
        assert p1.background_check_status == "approved"
        assert p1.user.is_active is True
        assert p2.is_approved is True
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    @patch("app.services.audit_events.audit_admin_action", new_callable=AsyncMock)
    async def test_partial_not_found(self, mock_audit):
        from app.api.v1.admin import bulk_reactivate_drivers

        p1 = _make_profile(5)
        db = _mock_db()
        db.execute = AsyncMock(return_value=_scalars_result([p1]))

        req = BulkDriverIdsRequest(driver_ids=[5, 6, 7])
        result = await bulk_reactivate_drivers(body=req, admin=_make_admin(), db=db)

        assert result.succeeded == [5]
        assert result.not_found == [6, 7]
        assert result.total_requested == 3
        assert result.total_succeeded == 1


# ---------------------------------------------------------------------------
# BulkActionResult schema
# ---------------------------------------------------------------------------

class TestBulkActionResultSchema:
    def test_fields_present(self):
        r = BulkActionResult(succeeded=[1, 2], not_found=[3], total_requested=3, total_succeeded=2)
        assert r.succeeded == [1, 2]
        assert r.not_found == [3]
        assert r.total_requested == 3
        assert r.total_succeeded == 2
