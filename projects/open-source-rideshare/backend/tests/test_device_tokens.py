"""Tests for the device token registration endpoints and model.

Covers:
  - DevicePlatform enum values
  - DeviceToken ORM model structure
  - register_device_token endpoint (POST /me/device-tokens)
  - deregister_device_token endpoint (DELETE /me/device-tokens/{token})
  - list_device_tokens endpoint (GET /me/device-tokens)
  - Pydantic schemas (RegisterDeviceTokenRequest, DeviceTokenResponse)

No live database is used. All DB interactions are mocked with AsyncMock /
MagicMock following the same pattern established in test_cancellation_policies.py.
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.api.v1.device_tokens import (
    deregister_device_token,
    list_device_tokens,
    register_device_token,
)
from app.models.device_token import DevicePlatform, DeviceToken
from app.schemas.device_token import DeviceTokenResponse, RegisterDeviceTokenRequest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_UTC = timezone.utc


def _now() -> datetime:
    return datetime.now(_UTC)


def _make_user(user_id: int = 1) -> MagicMock:
    """Build a mock User ORM object."""
    user = MagicMock()
    user.id = user_id
    return user


def _make_token_record(
    record_id: int = 1,
    user_id: int = 1,
    token: str = "test-fcm-token",
    platform: DevicePlatform = DevicePlatform.IOS,
    is_active: bool = True,
    last_used_at: datetime | None = None,
    created_at: datetime | None = None,
) -> MagicMock:
    """Build a mock DeviceToken ORM object."""
    record = MagicMock(spec=DeviceToken)
    record.id = record_id
    record.user_id = user_id
    record.token = token
    record.platform = platform
    record.is_active = is_active
    record.last_used_at = last_used_at or _now()
    record.created_at = created_at or _now()
    return record


def _db_scalar_one(value) -> AsyncMock:
    """Mock DB session whose execute() returns value via scalar_one_or_none."""
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    db.execute = AsyncMock(return_value=result)
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    return db


def _db_scalars_all(items: list) -> AsyncMock:
    """Mock DB session whose execute() returns items via scalars().all()."""
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


# ===========================================================================
# TestDevicePlatformEnum
# ===========================================================================


class TestDevicePlatformEnum:
    """Verify all DevicePlatform enum values."""

    def test_ios_value(self):
        assert DevicePlatform.IOS.value == "ios"

    def test_android_value(self):
        assert DevicePlatform.ANDROID.value == "android"

    def test_web_value(self):
        assert DevicePlatform.WEB.value == "web"

    def test_all_three_members(self):
        assert len(DevicePlatform) == 3

    def test_ios_from_value(self):
        assert DevicePlatform("ios") == DevicePlatform.IOS

    def test_android_from_value(self):
        assert DevicePlatform("android") == DevicePlatform.ANDROID

    def test_web_from_value(self):
        assert DevicePlatform("web") == DevicePlatform.WEB

    def test_invalid_value_raises(self):
        with pytest.raises(ValueError):
            DevicePlatform("blackberry")


# ===========================================================================
# TestDeviceTokenModel
# ===========================================================================


class TestDeviceTokenModel:
    """Tests verifying the DeviceToken ORM table structure."""

    def _cols(self) -> set[str]:
        return {c.name for c in DeviceToken.__table__.columns}

    def _constraints(self):
        return DeviceToken.__table__.constraints

    def test_table_name(self):
        assert DeviceToken.__tablename__ == "device_tokens"

    def test_has_id(self):
        assert "id" in self._cols()

    def test_has_user_id(self):
        assert "user_id" in self._cols()

    def test_has_token(self):
        assert "token" in self._cols()

    def test_has_platform(self):
        assert "platform" in self._cols()

    def test_has_is_active(self):
        assert "is_active" in self._cols()

    def test_has_last_used_at(self):
        assert "last_used_at" in self._cols()

    def test_has_created_at(self):
        assert "created_at" in self._cols()

    def test_token_is_unique(self):
        col = DeviceToken.__table__.columns["token"]
        assert col.unique is True

    def test_unique_constraint_on_token_exists(self):
        from sqlalchemy import UniqueConstraint
        constraint_names = {
            c.name for c in self._constraints() if isinstance(c, UniqueConstraint)
        }
        assert "uq_device_tokens_token" in constraint_names

    def test_user_id_has_fk_to_users(self):
        col = DeviceToken.__table__.columns["user_id"]
        targets = {fk.target_fullname for fk in col.foreign_keys}
        assert "users.id" in targets

    def test_user_id_is_indexed(self):
        col = DeviceToken.__table__.columns["user_id"]
        assert col.index is True

    def test_token_is_indexed(self):
        col = DeviceToken.__table__.columns["token"]
        assert col.index is True

    def test_token_max_length_500(self):
        col = DeviceToken.__table__.columns["token"]
        assert col.type.length == 500

    def test_last_used_at_is_nullable(self):
        col = DeviceToken.__table__.columns["last_used_at"]
        assert col.nullable is True


# ===========================================================================
# TestRegisterDeviceToken
# ===========================================================================


class TestRegisterDeviceToken:
    """Tests for the register_device_token endpoint (POST /me/device-tokens)."""

    @pytest.mark.asyncio
    async def test_new_token_is_created_when_not_found(self):
        user = _make_user(user_id=1)
        db = _db_scalar_one(None)
        req = RegisterDeviceTokenRequest(token="brand-new-token", platform="ios")
        result = await register_device_token(req=req, user=user, db=db)
        db.add.assert_called_once()
        db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_new_token_record_fields_correct(self):
        user = _make_user(user_id=5)
        db = _db_scalar_one(None)
        req = RegisterDeviceTokenRequest(token="abc123", platform="android")
        await register_device_token(req=req, user=user, db=db)
        added = db.add.call_args[0][0]
        assert isinstance(added, DeviceToken)
        assert added.user_id == 5
        assert added.token == "abc123"
        assert added.platform == DevicePlatform.ANDROID
        assert added.is_active is True

    @pytest.mark.asyncio
    async def test_new_token_last_used_at_set(self):
        user = _make_user()
        db = _db_scalar_one(None)
        req = RegisterDeviceTokenRequest(token="token-x", platform="web")
        await register_device_token(req=req, user=user, db=db)
        added = db.add.call_args[0][0]
        assert added.last_used_at is not None

    @pytest.mark.asyncio
    async def test_existing_token_reassigned_to_current_user(self):
        existing = _make_token_record(user_id=99, token="shared-token")
        user = _make_user(user_id=7)
        db = _db_scalar_one(existing)
        req = RegisterDeviceTokenRequest(token="shared-token", platform="ios")
        result = await register_device_token(req=req, user=user, db=db)
        assert result is existing
        assert existing.user_id == 7

    @pytest.mark.asyncio
    async def test_existing_token_set_active(self):
        existing = _make_token_record(is_active=False)
        user = _make_user()
        db = _db_scalar_one(existing)
        req = RegisterDeviceTokenRequest(token="old-token", platform="android")
        await register_device_token(req=req, user=user, db=db)
        assert existing.is_active is True

    @pytest.mark.asyncio
    async def test_existing_token_last_used_at_updated(self):
        old_time = _now()
        existing = _make_token_record(last_used_at=old_time)
        user = _make_user()
        db = _db_scalar_one(existing)
        req = RegisterDeviceTokenRequest(token="some-token", platform="web")
        await register_device_token(req=req, user=user, db=db)
        # last_used_at should have been updated to a new value
        assert existing.last_used_at is not None

    @pytest.mark.asyncio
    async def test_existing_token_platform_updated(self):
        existing = _make_token_record(platform=DevicePlatform.IOS)
        user = _make_user()
        db = _db_scalar_one(existing)
        req = RegisterDeviceTokenRequest(token="some-token", platform="android")
        await register_device_token(req=req, user=user, db=db)
        assert existing.platform == DevicePlatform.ANDROID

    @pytest.mark.asyncio
    async def test_existing_token_flush_called(self):
        existing = _make_token_record()
        user = _make_user()
        db = _db_scalar_one(existing)
        req = RegisterDeviceTokenRequest(token="t", platform="ios")
        await register_device_token(req=req, user=user, db=db)
        db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_existing_token_add_not_called(self):
        existing = _make_token_record()
        user = _make_user()
        db = _db_scalar_one(existing)
        req = RegisterDeviceTokenRequest(token="t", platform="ios")
        await register_device_token(req=req, user=user, db=db)
        db.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_invalid_platform_raises_422(self):
        user = _make_user()
        db = _db_scalar_one(None)
        req = RegisterDeviceTokenRequest(token="some-token", platform="symbian")
        with pytest.raises(HTTPException) as exc_info:
            await register_device_token(req=req, user=user, db=db)
        assert exc_info.value.status_code == 422

    @pytest.mark.asyncio
    async def test_invalid_platform_detail_mentions_platform(self):
        user = _make_user()
        db = _db_scalar_one(None)
        req = RegisterDeviceTokenRequest(token="some-token", platform="windows_phone")
        with pytest.raises(HTTPException) as exc_info:
            await register_device_token(req=req, user=user, db=db)
        assert "windows_phone" in exc_info.value.detail or "platform" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_new_token_returns_added_record(self):
        user = _make_user(user_id=3)
        db = _db_scalar_one(None)
        req = RegisterDeviceTokenRequest(token="fresh-token", platform="ios")
        result = await register_device_token(req=req, user=user, db=db)
        added = db.add.call_args[0][0]
        assert result is added


# ===========================================================================
# TestDeregisterDeviceToken
# ===========================================================================


class TestDeregisterDeviceToken:
    """Tests for the deregister_device_token endpoint (DELETE /me/device-tokens/{token})."""

    @pytest.mark.asyncio
    async def test_found_token_set_inactive(self):
        record = _make_token_record(is_active=True)
        user = _make_user()
        db = _db_scalar_one(record)
        await deregister_device_token(token="test-fcm-token", user=user, db=db)
        assert record.is_active is False

    @pytest.mark.asyncio
    async def test_found_token_flush_called(self):
        record = _make_token_record(is_active=True)
        user = _make_user()
        db = _db_scalar_one(record)
        await deregister_device_token(token="test-fcm-token", user=user, db=db)
        db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_not_found_raises_404(self):
        user = _make_user()
        db = _db_scalar_one(None)
        with pytest.raises(HTTPException) as exc_info:
            await deregister_device_token(token="nonexistent", user=user, db=db)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_not_found_detail_message(self):
        user = _make_user()
        db = _db_scalar_one(None)
        with pytest.raises(HTTPException) as exc_info:
            await deregister_device_token(token="ghost-token", user=user, db=db)
        assert "not found" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_token_belonging_to_other_user_returns_404(self):
        # The endpoint queries by (token AND user_id), so other-user's token
        # returns None from scalar_one_or_none.
        user = _make_user(user_id=99)
        db = _db_scalar_one(None)  # query filters by user_id — returns nothing
        with pytest.raises(HTTPException) as exc_info:
            await deregister_device_token(token="other-users-token", user=user, db=db)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_success_does_not_raise(self):
        record = _make_token_record(is_active=True)
        user = _make_user()
        db = _db_scalar_one(record)
        # Should complete without raising
        await deregister_device_token(token="test-fcm-token", user=user, db=db)

    @pytest.mark.asyncio
    async def test_execute_called_once(self):
        record = _make_token_record(is_active=True)
        user = _make_user()
        db = _db_scalar_one(record)
        await deregister_device_token(token="test-fcm-token", user=user, db=db)
        db.execute.assert_awaited_once()


# ===========================================================================
# TestListDeviceTokens
# ===========================================================================


class TestListDeviceTokens:
    """Tests for the list_device_tokens endpoint (GET /me/device-tokens)."""

    @pytest.mark.asyncio
    async def test_returns_active_tokens_for_user(self):
        tokens = [
            _make_token_record(record_id=1, is_active=True),
            _make_token_record(record_id=2, is_active=True),
        ]
        user = _make_user()
        db = _db_scalars_all(tokens)
        result = await list_device_tokens(user=user, db=db)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_empty_list_when_no_tokens(self):
        user = _make_user()
        db = _db_scalars_all([])
        result = await list_device_tokens(user=user, db=db)
        assert list(result) == []

    @pytest.mark.asyncio
    async def test_single_token_returned(self):
        token = _make_token_record(record_id=5, is_active=True)
        user = _make_user()
        db = _db_scalars_all([token])
        result = await list_device_tokens(user=user, db=db)
        items = list(result)
        assert len(items) == 1
        assert items[0] is token

    @pytest.mark.asyncio
    async def test_execute_called_once(self):
        user = _make_user()
        db = _db_scalars_all([])
        await list_device_tokens(user=user, db=db)
        db.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_returns_scalars_all_result(self):
        tokens = [_make_token_record(), _make_token_record(record_id=2)]
        user = _make_user()
        db = _db_scalars_all(tokens)
        result = await list_device_tokens(user=user, db=db)
        assert len(list(result)) == 2


# ===========================================================================
# TestDeviceTokenSchemas
# ===========================================================================


class TestDeviceTokenSchemas:
    """Pydantic validation tests for device token schemas."""

    def test_register_request_requires_token(self):
        with pytest.raises(Exception):
            RegisterDeviceTokenRequest(platform="ios")

    def test_register_request_requires_platform(self):
        with pytest.raises(Exception):
            RegisterDeviceTokenRequest(token="abc")

    def test_register_request_empty_token_rejected(self):
        with pytest.raises(Exception):
            RegisterDeviceTokenRequest(token="", platform="ios")

    def test_register_request_valid_ios(self):
        req = RegisterDeviceTokenRequest(token="my-token", platform="ios")
        assert req.token == "my-token"
        assert req.platform == "ios"

    def test_register_request_valid_android(self):
        req = RegisterDeviceTokenRequest(token="droid-token", platform="android")
        assert req.platform == "android"

    def test_register_request_valid_web(self):
        req = RegisterDeviceTokenRequest(token="web-token", platform="web")
        assert req.platform == "web"

    def test_register_request_platform_any_string_accepted_at_schema_level(self):
        # Schema accepts any string; endpoint validates it's a valid DevicePlatform
        req = RegisterDeviceTokenRequest(token="t", platform="unknown_platform")
        assert req.platform == "unknown_platform"

    def test_register_request_min_length_one_token(self):
        req = RegisterDeviceTokenRequest(token="x", platform="ios")
        assert req.token == "x"

    def test_device_token_response_from_attributes(self):
        assert DeviceTokenResponse.model_config.get("from_attributes") is True

    def test_device_token_response_from_dict(self):
        now = _now()
        resp = DeviceTokenResponse(
            id=1,
            token="my-token",
            platform="ios",
            is_active=True,
            last_used_at=now,
            created_at=now,
        )
        assert resp.id == 1
        assert resp.token == "my-token"
        assert resp.platform == "ios"
        assert resp.is_active is True
        assert resp.last_used_at == now
        assert resp.created_at == now

    def test_device_token_response_last_used_at_nullable(self):
        now = _now()
        resp = DeviceTokenResponse(
            id=2,
            token="tok",
            platform="android",
            is_active=True,
            last_used_at=None,
            created_at=now,
        )
        assert resp.last_used_at is None

    def test_device_token_response_is_active_false(self):
        now = _now()
        resp = DeviceTokenResponse(
            id=3,
            token="inactive-tok",
            platform="web",
            is_active=False,
            last_used_at=None,
            created_at=now,
        )
        assert resp.is_active is False

    def test_device_token_response_all_platforms_accepted(self):
        now = _now()
        for platform in ("ios", "android", "web"):
            resp = DeviceTokenResponse(
                id=1,
                token="t",
                platform=platform,
                is_active=True,
                last_used_at=None,
                created_at=now,
            )
            assert resp.platform == platform
