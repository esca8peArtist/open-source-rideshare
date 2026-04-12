"""Comprehensive unit tests for the background check feature.

Covers:
- Model fields and enum values
- Schema validation (order, response, admin response, override)
- Service logic: create_candidate, order_check, get_check_status,
  webhook handling, admin override, auto-approve trigger, signature validation
- Endpoint tests: order, status, webhook, admin list, admin get, admin override

All tests are pure unit tests — no database required.
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.background_check import BackgroundCheck, BackgroundCheckStatus
from app.schemas.background_check import (
    AdminBackgroundCheckResponse,
    AdminOverrideRequest,
    BackgroundCheckResponse,
    OrderBackgroundCheckRequest,
)
from app.services.background_checks import (
    VALID_PACKAGES,
    _parse_checkr_status,
    _verify_webhook_signature,
    admin_override_check,
    create_candidate,
    get_check_status,
    handle_webhook,
    order_check,
)


# ===========================================================================
# Model tests
# ===========================================================================


class TestBackgroundCheckModel:
    def test_status_enum_values(self):
        assert BackgroundCheckStatus.PENDING == "pending"
        assert BackgroundCheckStatus.CLEAR == "clear"
        assert BackgroundCheckStatus.CONSIDER == "consider"
        assert BackgroundCheckStatus.SUSPENDED == "suspended"
        assert BackgroundCheckStatus.DISPUTE == "dispute"
        assert BackgroundCheckStatus.CANCELLED == "cancelled"

    def test_all_status_values_exist(self):
        expected = {"pending", "clear", "consider", "suspended", "dispute", "cancelled"}
        actual = {s.value for s in BackgroundCheckStatus}
        assert actual == expected

    def test_model_tablename(self):
        assert BackgroundCheck.__tablename__ == "background_checks"

    def test_model_has_required_columns(self):
        cols = {c.key for c in BackgroundCheck.__table__.columns}
        required = {
            "id", "driver_profile_id", "checkr_candidate_id", "checkr_check_id",
            "package", "status", "report_url", "ordered_at", "completed_at", "created_at",
            "admin_override_reason", "overridden_by",
        }
        assert required.issubset(cols)

    def test_default_package(self):
        # The default in the column definition
        col_default = BackgroundCheck.__table__.columns["package"].default
        assert col_default is not None

    def test_default_status_is_pending(self):
        col = BackgroundCheck.__table__.columns["status"]
        assert col.default is not None


# ===========================================================================
# Schema tests
# ===========================================================================


class TestOrderBackgroundCheckRequest:
    def test_default_package(self):
        req = OrderBackgroundCheckRequest()
        assert req.package == "driver_pro"

    def test_custom_package(self):
        req = OrderBackgroundCheckRequest(package="motor_vehicle_report")
        assert req.package == "motor_vehicle_report"

    def test_basic_package(self):
        req = OrderBackgroundCheckRequest(package="basic")
        assert req.package == "basic"

    def test_valid_packages_constant(self):
        assert "driver_pro" in VALID_PACKAGES
        assert "motor_vehicle_report" in VALID_PACKAGES
        assert "basic" in VALID_PACKAGES
        assert len(VALID_PACKAGES) == 3

    def test_validate_package_valid(self):
        req = OrderBackgroundCheckRequest(package="driver_pro")
        assert req.validate_package() is True

    def test_validate_package_invalid(self):
        req = OrderBackgroundCheckRequest(package="unknown_package")
        assert req.validate_package() is False


class TestAdminOverrideRequest:
    def test_valid_override(self):
        req = AdminOverrideRequest(status="clear", reason="Manual review passed")
        assert req.status == "clear"
        assert req.reason == "Manual review passed"

    def test_reason_required(self):
        with pytest.raises(Exception):
            AdminOverrideRequest(status="clear", reason="")

    def test_status_required(self):
        with pytest.raises(Exception):
            AdminOverrideRequest(reason="some reason")


class TestBackgroundCheckResponseSchema:
    def test_from_model(self):
        now = datetime.now(timezone.utc)
        check = BackgroundCheck(
            id=1,
            driver_profile_id=5,
            package="driver_pro",
            status=BackgroundCheckStatus.PENDING,
            report_url=None,
            ordered_at=now,
            completed_at=None,
            created_at=now,
        )
        resp = BackgroundCheckResponse.model_validate(check)
        assert resp.id == 1
        assert resp.driver_profile_id == 5
        assert resp.package == "driver_pro"
        assert resp.status == "pending"
        assert resp.report_url is None

    def test_does_not_expose_checkr_ids(self):
        """Driver-facing schema should not include internal Checkr IDs."""
        fields = set(BackgroundCheckResponse.model_fields.keys())
        assert "checkr_candidate_id" not in fields
        assert "checkr_check_id" not in fields

    def test_admin_schema_includes_checkr_ids(self):
        fields = set(AdminBackgroundCheckResponse.model_fields.keys())
        assert "checkr_candidate_id" in fields
        assert "checkr_check_id" in fields


# ===========================================================================
# Service tests — create_candidate
# ===========================================================================


class TestCreateCandidate:
    @pytest.mark.asyncio
    async def test_no_api_key_returns_simulated(self):
        with patch("app.services.background_checks.settings") as mock_settings:
            mock_settings.checkr_api_key = ""
            result = await create_candidate(
                first_name="Jane",
                last_name="Doe",
                email="jane@example.com",
            )
        assert result["simulated"] is True
        assert "id" in result
        assert result["object"] == "candidate"

    @pytest.mark.asyncio
    async def test_simulated_id_contains_email(self):
        with patch("app.services.background_checks.settings") as mock_settings:
            mock_settings.checkr_api_key = ""
            result = await create_candidate(
                first_name="Test",
                last_name="User",
                email="test@openride.coop",
            )
        assert "test_openride.coop" in result["id"]

    @pytest.mark.asyncio
    async def test_with_api_key_calls_checkr(self):
        """When Checkr API key is set and aiohttp is available, calls Checkr."""
        mock_response = MagicMock()
        mock_response.json = AsyncMock(return_value={"id": "cand_abc123", "object": "candidate"})
        mock_response.raise_for_status = MagicMock()

        mock_post_ctx = MagicMock()
        mock_post_ctx.__aenter__ = AsyncMock(return_value=mock_response)
        mock_post_ctx.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.post = MagicMock(return_value=mock_post_ctx)

        mock_aiohttp = MagicMock()
        mock_aiohttp.ClientSession = MagicMock(return_value=mock_session)
        mock_aiohttp.BasicAuth = MagicMock(return_value=("key", ""))

        with patch("app.services.background_checks.settings") as mock_settings, \
             patch.dict("sys.modules", {"aiohttp": mock_aiohttp}):
            mock_settings.checkr_api_key = "test_key"
            result = await create_candidate(
                first_name="John",
                last_name="Smith",
                email="john@test.com",
            )

        assert result["id"] == "cand_abc123"


# ===========================================================================
# Service tests — order_check
# ===========================================================================


class TestOrderCheck:
    @pytest.mark.asyncio
    async def test_invalid_package_raises(self):
        with pytest.raises(ValueError, match="Invalid package"):
            await order_check("cand_123", package="invalid_package")

    @pytest.mark.asyncio
    async def test_no_api_key_returns_simulated(self):
        with patch("app.services.background_checks.settings") as mock_settings:
            mock_settings.checkr_api_key = ""
            result = await order_check("cand_real_123", package="driver_pro")
        assert result["simulated"] is True
        assert result["status"] == "pending"

    @pytest.mark.asyncio
    async def test_simulated_candidate_returns_simulated(self):
        with patch("app.services.background_checks.settings") as mock_settings:
            mock_settings.checkr_api_key = "real_key"
            result = await order_check("sim_candidate_test", package="basic")
        assert result["simulated"] is True

    @pytest.mark.asyncio
    async def test_returns_check_id(self):
        with patch("app.services.background_checks.settings") as mock_settings:
            mock_settings.checkr_api_key = ""
            result = await order_check("cand_xyz", package="motor_vehicle_report")
        assert "id" in result
        assert "cand_xyz" in result["id"]


# ===========================================================================
# Service tests — get_check_status
# ===========================================================================


class TestGetCheckStatus:
    @pytest.mark.asyncio
    async def test_no_api_key_returns_pending(self):
        with patch("app.services.background_checks.settings") as mock_settings:
            mock_settings.checkr_api_key = ""
            result = await get_check_status("check_123")
        assert result["status"] == "pending"
        assert result["simulated"] is True

    @pytest.mark.asyncio
    async def test_sim_check_returns_pending(self):
        with patch("app.services.background_checks.settings") as mock_settings:
            mock_settings.checkr_api_key = "real_key"
            result = await get_check_status("sim_check_abc")
        assert result["status"] == "pending"

    @pytest.mark.asyncio
    async def test_with_api_key_calls_checkr(self):
        """When API key is set and aiohttp is available, calls Checkr."""
        mock_response = MagicMock()
        mock_response.json = AsyncMock(return_value={"id": "check_abc", "status": "clear"})
        mock_response.raise_for_status = MagicMock()

        mock_get_ctx = MagicMock()
        mock_get_ctx.__aenter__ = AsyncMock(return_value=mock_response)
        mock_get_ctx.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.get = MagicMock(return_value=mock_get_ctx)

        mock_aiohttp = MagicMock()
        mock_aiohttp.ClientSession = MagicMock(return_value=mock_session)
        mock_aiohttp.BasicAuth = MagicMock(return_value=("key", ""))

        with patch("app.services.background_checks.settings") as mock_settings, \
             patch.dict("sys.modules", {"aiohttp": mock_aiohttp}):
            mock_settings.checkr_api_key = "test_key"
            result = await get_check_status("check_abc")

        assert result["status"] == "clear"


# ===========================================================================
# Service tests — webhook signature validation
# ===========================================================================


class TestVerifyWebhookSignature:
    def test_no_secret_accepts_all(self):
        with patch("app.services.background_checks.settings") as mock_settings:
            mock_settings.checkr_webhook_secret = ""
            result = _verify_webhook_signature(b"body", "any_signature")
        assert result is True

    def test_valid_signature(self):
        import hashlib
        import hmac as _hmac

        secret = "test_webhook_secret"
        body = b'{"type": "report.completed"}'
        sig = _hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

        with patch("app.services.background_checks.settings") as mock_settings:
            mock_settings.checkr_webhook_secret = secret
            result = _verify_webhook_signature(body, sig)
        assert result is True

    def test_invalid_signature(self):
        with patch("app.services.background_checks.settings") as mock_settings:
            mock_settings.checkr_webhook_secret = "real_secret"
            result = _verify_webhook_signature(b"body", "wrong_signature")
        assert result is False


# ===========================================================================
# Service tests — parse checkr status
# ===========================================================================


class TestParseCheckrStatus:
    def test_clear(self):
        assert _parse_checkr_status("clear") == BackgroundCheckStatus.CLEAR

    def test_consider(self):
        assert _parse_checkr_status("consider") == BackgroundCheckStatus.CONSIDER

    def test_suspended(self):
        assert _parse_checkr_status("suspended") == BackgroundCheckStatus.SUSPENDED

    def test_dispute(self):
        assert _parse_checkr_status("dispute") == BackgroundCheckStatus.DISPUTE

    def test_cancelled(self):
        assert _parse_checkr_status("cancelled") == BackgroundCheckStatus.CANCELLED

    def test_pending(self):
        assert _parse_checkr_status("pending") == BackgroundCheckStatus.PENDING

    def test_unknown_defaults_to_pending(self):
        assert _parse_checkr_status("unknown_status") == BackgroundCheckStatus.PENDING

    def test_case_insensitive(self):
        assert _parse_checkr_status("CLEAR") == BackgroundCheckStatus.CLEAR


# ===========================================================================
# Service tests — handle_webhook
# ===========================================================================


class TestHandleWebhook:
    def _make_check(self, check_id="chk_abc123", status=BackgroundCheckStatus.PENDING):
        check = MagicMock(spec=BackgroundCheck)
        check.id = 1
        check.driver_profile_id = 5
        check.checkr_check_id = check_id
        check.status = status
        check.completed_at = None
        check.report_url = None
        return check

    def _make_db(self, check=None):
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = check
        db.execute = AsyncMock(return_value=mock_result)
        db.flush = AsyncMock()
        return db

    @pytest.mark.asyncio
    async def test_ignores_unknown_event_types(self):
        db = self._make_db()
        payload = {"type": "candidate.created", "data": {"object": {}}}
        with patch("app.services.background_checks._verify_webhook_signature", return_value=True):
            result = await handle_webhook(payload, "sig", b"body", db)
        assert result["status"] == "ignored"

    @pytest.mark.asyncio
    async def test_invalid_signature_returns_invalid(self):
        db = self._make_db()
        payload = {"type": "report.completed", "data": {"object": {"id": "chk_x"}}}
        with patch("app.services.background_checks._verify_webhook_signature", return_value=False):
            result = await handle_webhook(payload, "bad_sig", b"body", db)
        assert result["status"] == "invalid_signature"

    @pytest.mark.asyncio
    async def test_not_found_returns_not_found(self):
        db = self._make_db(check=None)
        payload = {
            "type": "report.completed",
            "data": {"object": {"id": "chk_missing", "status": "clear"}},
        }
        with patch("app.services.background_checks._verify_webhook_signature", return_value=True):
            result = await handle_webhook(payload, "sig", b"body", db)
        assert result["status"] == "not_found"

    @pytest.mark.asyncio
    async def test_clear_status_updates_check(self):
        check = self._make_check(check_id="chk_abc", status=BackgroundCheckStatus.PENDING)
        db = self._make_db(check=check)
        payload = {
            "type": "report.completed",
            "data": {"object": {"id": "chk_abc", "status": "clear", "report_url": "https://checkr.com/report/1"}},
        }
        with patch("app.services.background_checks._verify_webhook_signature", return_value=True), \
             patch("app.services.background_checks._handle_check_completed", new_callable=AsyncMock):
            result = await handle_webhook(payload, "sig", b"body", db)
        assert result["status"] == "ok"
        assert check.status == BackgroundCheckStatus.CLEAR
        assert check.report_url == "https://checkr.com/report/1"

    @pytest.mark.asyncio
    async def test_consider_status_sets_completed_at(self):
        check = self._make_check(check_id="chk_xyz")
        db = self._make_db(check=check)
        payload = {
            "type": "report.completed",
            "data": {"object": {"id": "chk_xyz", "status": "consider"}},
        }
        with patch("app.services.background_checks._verify_webhook_signature", return_value=True), \
             patch("app.services.background_checks._handle_check_completed", new_callable=AsyncMock):
            await handle_webhook(payload, "sig", b"body", db)
        assert check.completed_at is not None


# ===========================================================================
# Service tests — admin override
# ===========================================================================


class TestAdminOverrideCheck:
    def _make_check(self):
        check = MagicMock(spec=BackgroundCheck)
        check.id = 10
        check.driver_profile_id = 3
        check.status = BackgroundCheckStatus.CONSIDER
        check.completed_at = None
        return check

    def _make_db(self, check=None):
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = check
        db.execute = AsyncMock(return_value=mock_result)
        db.flush = AsyncMock()
        return db

    @pytest.mark.asyncio
    async def test_override_to_clear(self):
        check = self._make_check()
        db = self._make_db(check)
        with patch("app.services.background_checks._handle_check_completed", new_callable=AsyncMock):
            result = await admin_override_check(
                db=db,
                check_id=10,
                new_status=BackgroundCheckStatus.CLEAR,
                reason="Manual review passed",
                admin_user_id=99,
            )
        assert result.status == BackgroundCheckStatus.CLEAR
        assert result.admin_override_reason == "Manual review passed"
        assert result.overridden_by == 99

    @pytest.mark.asyncio
    async def test_override_to_cancelled(self):
        check = self._make_check()
        db = self._make_db(check)
        with patch("app.services.background_checks._handle_check_completed", new_callable=AsyncMock):
            result = await admin_override_check(
                db=db,
                check_id=10,
                new_status=BackgroundCheckStatus.CANCELLED,
                reason="Driver withdrew application",
                admin_user_id=99,
            )
        assert result.status == BackgroundCheckStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_invalid_status_raises(self):
        db = self._make_db()
        with pytest.raises(ValueError, match="Admin may only override"):
            await admin_override_check(
                db=db,
                check_id=10,
                new_status=BackgroundCheckStatus.SUSPENDED,
                reason="test",
                admin_user_id=1,
            )

    @pytest.mark.asyncio
    async def test_check_not_found_raises(self):
        db = self._make_db(check=None)
        with pytest.raises(ValueError, match="not found"):
            await admin_override_check(
                db=db,
                check_id=999,
                new_status=BackgroundCheckStatus.CLEAR,
                reason="test",
                admin_user_id=1,
            )

    @pytest.mark.asyncio
    async def test_override_triggers_driver_side_effects(self):
        check = self._make_check()
        db = self._make_db(check)
        with patch("app.services.background_checks._handle_check_completed", new_callable=AsyncMock) as mock_handle:
            await admin_override_check(
                db=db,
                check_id=10,
                new_status=BackgroundCheckStatus.CLEAR,
                reason="Looks good",
                admin_user_id=1,
            )
        mock_handle.assert_called_once()


# ===========================================================================
# Service tests — auto-approve logic
# ===========================================================================


class TestAutoApproveLogic:
    @pytest.mark.asyncio
    async def test_clear_check_triggers_auto_approve_attempt(self):
        """When check is CLEAR, _attempt_auto_approve should be called."""
        from app.services.background_checks import _handle_check_completed

        check = MagicMock(spec=BackgroundCheck)
        check.status = BackgroundCheckStatus.CLEAR
        check.driver_profile_id = 7

        mock_profile = MagicMock()
        mock_profile.is_approved = False
        mock_profile.background_check_status = "pending"

        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_profile
        db.execute = AsyncMock(return_value=mock_result)
        db.flush = AsyncMock()

        with patch("app.services.background_checks._attempt_auto_approve", new_callable=AsyncMock) as mock_approve:
            await _handle_check_completed(db, check)

        mock_approve.assert_called_once()
        assert mock_profile.background_check_status == "clear"

    @pytest.mark.asyncio
    async def test_consider_check_flags_for_review(self):
        from app.services.background_checks import _handle_check_completed

        check = MagicMock(spec=BackgroundCheck)
        check.status = BackgroundCheckStatus.CONSIDER
        check.driver_profile_id = 7

        mock_profile = MagicMock()
        mock_profile.background_check_status = "pending"

        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_profile
        db.execute = AsyncMock(return_value=mock_result)
        db.flush = AsyncMock()

        await _handle_check_completed(db, check)

        assert mock_profile.background_check_status == "consider"

    @pytest.mark.asyncio
    async def test_suspended_check_flags_for_review(self):
        from app.services.background_checks import _handle_check_completed

        check = MagicMock(spec=BackgroundCheck)
        check.status = BackgroundCheckStatus.SUSPENDED
        check.driver_profile_id = 8

        mock_profile = MagicMock()
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_profile
        db.execute = AsyncMock(return_value=mock_result)
        db.flush = AsyncMock()

        await _handle_check_completed(db, check)
        assert mock_profile.background_check_status == "suspended"

    @pytest.mark.asyncio
    async def test_auto_approve_approves_driver_when_all_docs_verified(self):
        from app.services.background_checks import _attempt_auto_approve

        mock_profile = MagicMock()
        mock_profile.is_approved = False

        db = AsyncMock()
        db.flush = AsyncMock()

        with patch(
            "app.services.verification.get_verification_status",
            new_callable=AsyncMock,
            return_value={"all_required_approved": True},
        ), patch(
            "app.services.background_checks.get_verification_status",
            new_callable=AsyncMock,
            return_value={"all_required_approved": True},
            create=True,
        ):
            await _attempt_auto_approve(db, driver_profile_id=5, profile=mock_profile)

        assert mock_profile.is_approved is True

    @pytest.mark.asyncio
    async def test_auto_approve_skips_when_docs_incomplete(self):
        from app.services.background_checks import _attempt_auto_approve

        mock_profile = MagicMock()
        mock_profile.is_approved = False

        db = AsyncMock()
        db.flush = AsyncMock()

        with patch(
            "app.services.verification.get_verification_status",
            new_callable=AsyncMock,
            return_value={"all_required_approved": False},
        ), patch(
            "app.services.background_checks.get_verification_status",
            new_callable=AsyncMock,
            return_value={"all_required_approved": False},
            create=True,
        ):
            await _attempt_auto_approve(db, driver_profile_id=5, profile=mock_profile)

        assert mock_profile.is_approved is False

    @pytest.mark.asyncio
    async def test_auto_approve_skips_already_approved(self):
        from app.services.background_checks import _attempt_auto_approve

        mock_profile = MagicMock()
        mock_profile.is_approved = True  # Already approved

        db = AsyncMock()
        db.flush = AsyncMock()

        with patch(
            "app.services.verification.get_verification_status",
            new_callable=AsyncMock,
            return_value={"all_required_approved": True},
        ), patch(
            "app.services.background_checks.get_verification_status",
            new_callable=AsyncMock,
            return_value={"all_required_approved": True},
            create=True,
        ):
            await _attempt_auto_approve(db, driver_profile_id=5, profile=mock_profile)

        db.flush.assert_not_called()


# ===========================================================================
# Endpoint tests
# ===========================================================================


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.flush = AsyncMock()
    db.add = MagicMock()
    return db


@pytest.fixture
def mock_driver_user():
    user = MagicMock()
    user.id = 1
    user.name = "Jane Driver"
    user.email = "jane@driver.com"
    user.phone = "+15551234567"
    user.role = MagicMock()
    user.role.value = "driver"
    user.is_active = True
    return user


@pytest.fixture
def mock_admin_user():
    user = MagicMock()
    user.id = 99
    user.name = "Admin User"
    user.role = MagicMock()
    user.role.value = "admin"
    user.is_active = True
    return user


@pytest.fixture
def mock_driver_profile():
    profile = MagicMock(spec=type("DriverProfile", (), {"id": 5, "user_id": 1}))
    profile.id = 5
    profile.user_id = 1
    return profile


class TestOrderEndpoint:
    @pytest.mark.asyncio
    async def test_invalid_package_rejected(self, mock_db, mock_driver_user, mock_driver_profile):
        from fastapi.testclient import TestClient
        from app.main import app
        from app.api.deps import require_driver
        from app.db.database import get_db

        app.dependency_overrides[require_driver] = lambda: mock_driver_user
        app.dependency_overrides[get_db] = lambda: mock_db

        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = mock_driver_profile
        mock_db.execute = AsyncMock(return_value=result_mock)

        from httpx import AsyncClient, ASGITransport
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/driver/background-check/order",
                json={"package": "invalid_package"},
                headers={"Authorization": "Bearer fake"},
            )

        assert resp.status_code == 422
        app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_no_driver_profile_returns_404(self, mock_db, mock_driver_user):
        from app.main import app
        from app.api.deps import require_driver
        from app.db.database import get_db

        app.dependency_overrides[require_driver] = lambda: mock_driver_user
        app.dependency_overrides[get_db] = lambda: mock_db

        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=result_mock)

        from httpx import AsyncClient, ASGITransport
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/driver/background-check/order",
                json={"package": "driver_pro"},
                headers={"Authorization": "Bearer fake"},
            )

        assert resp.status_code == 404
        app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_existing_check_returns_409(self, mock_db, mock_driver_user, mock_driver_profile):
        from app.main import app
        from app.api.deps import require_driver
        from app.db.database import get_db

        app.dependency_overrides[require_driver] = lambda: mock_driver_user
        app.dependency_overrides[get_db] = lambda: mock_db

        existing_check = MagicMock()
        existing_check.status = BackgroundCheckStatus.PENDING

        # First execute returns profile, second returns existing check
        results = [
            MagicMock(scalar_one_or_none=MagicMock(return_value=mock_driver_profile)),
            MagicMock(scalar_one_or_none=MagicMock(return_value=existing_check)),
        ]
        mock_db.execute = AsyncMock(side_effect=results)

        from httpx import AsyncClient, ASGITransport
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/driver/background-check/order",
                json={"package": "driver_pro"},
                headers={"Authorization": "Bearer fake"},
            )

        assert resp.status_code == 409
        app.dependency_overrides.clear()


class TestStatusEndpoint:
    @pytest.mark.asyncio
    async def test_no_profile_returns_404(self, mock_db, mock_driver_user):
        from app.main import app
        from app.api.deps import require_driver
        from app.db.database import get_db

        app.dependency_overrides[require_driver] = lambda: mock_driver_user
        app.dependency_overrides[get_db] = lambda: mock_db

        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=result_mock)

        from httpx import AsyncClient, ASGITransport
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/api/v1/driver/background-check",
                headers={"Authorization": "Bearer fake"},
            )

        assert resp.status_code == 404
        app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_no_check_returns_404(self, mock_db, mock_driver_user, mock_driver_profile):
        from app.main import app
        from app.api.deps import require_driver
        from app.db.database import get_db

        app.dependency_overrides[require_driver] = lambda: mock_driver_user
        app.dependency_overrides[get_db] = lambda: mock_db

        results = [
            MagicMock(scalar_one_or_none=MagicMock(return_value=mock_driver_profile)),
            MagicMock(scalar_one_or_none=MagicMock(return_value=None)),
        ]
        mock_db.execute = AsyncMock(side_effect=results)

        from httpx import AsyncClient, ASGITransport
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/api/v1/driver/background-check",
                headers={"Authorization": "Bearer fake"},
            )

        assert resp.status_code == 404
        app.dependency_overrides.clear()


class TestWebhookEndpoint:
    @pytest.mark.asyncio
    async def test_invalid_signature_returns_403(self, mock_db):
        from app.main import app
        from app.db.database import get_db

        app.dependency_overrides[get_db] = lambda: mock_db

        with patch("app.services.background_checks._verify_webhook_signature", return_value=False):
            from httpx import AsyncClient, ASGITransport
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post(
                    "/api/v1/background-checks/webhook",
                    json={"type": "report.completed", "data": {"object": {"id": "chk_x", "status": "clear"}}},
                    headers={"X-Checkr-Signature": "bad_sig"},
                )

        assert resp.status_code == 403
        app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_valid_webhook_returns_ok(self, mock_db):
        from app.main import app
        from app.db.database import get_db
        from app.api.v1 import background_checks as bg_api

        app.dependency_overrides[get_db] = lambda: mock_db

        # Patch handle_webhook at the API module level (where it's imported)
        with patch.object(bg_api, "handle_webhook", new_callable=AsyncMock, return_value={"status": "ok"}):
            from httpx import AsyncClient, ASGITransport
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post(
                    "/api/v1/background-checks/webhook",
                    json={"type": "report.completed", "data": {"object": {"id": "chk_x", "status": "clear"}}},
                    headers={"X-Checkr-Signature": "valid_sig"},
                )

        assert resp.status_code == 200
        app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_invalid_json_returns_400(self, mock_db):
        from app.main import app
        from app.db.database import get_db

        app.dependency_overrides[get_db] = lambda: mock_db

        from httpx import AsyncClient, ASGITransport
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/background-checks/webhook",
                content=b"not json at all!!",
                headers={"Content-Type": "application/json"},
            )

        assert resp.status_code == 400
        app.dependency_overrides.clear()


class TestAdminEndpoints:
    @pytest.mark.asyncio
    async def test_admin_list_requires_admin(self, mock_db):
        from app.main import app
        from app.api.deps import require_admin
        from app.db.database import get_db

        # No override — should fail auth
        app.dependency_overrides[get_db] = lambda: mock_db

        from httpx import AsyncClient, ASGITransport
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/admin/background-checks")

        # Unauthenticated — 403 or 401
        assert resp.status_code in (401, 403)
        app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_admin_list_invalid_status_returns_422(self, mock_db, mock_admin_user):
        from app.main import app
        from app.api.deps import require_admin
        from app.db.database import get_db

        app.dependency_overrides[require_admin] = lambda: mock_admin_user
        app.dependency_overrides[get_db] = lambda: mock_db

        from httpx import AsyncClient, ASGITransport
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/api/v1/admin/background-checks?status=invalid_status",
                headers={"Authorization": "Bearer fake"},
            )

        assert resp.status_code == 422
        app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_admin_get_not_found_returns_404(self, mock_db, mock_admin_user):
        from app.main import app
        from app.api.deps import require_admin
        from app.db.database import get_db

        app.dependency_overrides[require_admin] = lambda: mock_admin_user
        app.dependency_overrides[get_db] = lambda: mock_db

        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=result_mock)

        from httpx import AsyncClient, ASGITransport
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/api/v1/admin/background-checks/999",
                headers={"Authorization": "Bearer fake"},
            )

        assert resp.status_code == 404
        app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_admin_override_invalid_status_returns_422(self, mock_db, mock_admin_user):
        from app.main import app
        from app.api.deps import require_admin
        from app.db.database import get_db

        app.dependency_overrides[require_admin] = lambda: mock_admin_user
        app.dependency_overrides[get_db] = lambda: mock_db

        from httpx import AsyncClient, ASGITransport
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/admin/background-checks/1/override",
                json={"status": "invalid_status", "reason": "test"},
                headers={"Authorization": "Bearer fake"},
            )

        assert resp.status_code == 422
        app.dependency_overrides.clear()
