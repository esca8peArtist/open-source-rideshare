"""Unit tests for API dependency injection functions (get_current_user, require_driver, require_admin)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from app.models.user import User, UserRole


def _make_user(
    user_id=1,
    phone="+15551234567",
    name="Test User",
    email="test@example.com",
    role=UserRole.RIDER,
    is_active=True,
):
    user = MagicMock(spec=User)
    user.id = user_id
    user.phone = phone
    user.name = name
    user.email = email
    user.role = role
    user.is_active = is_active
    return user


def _mock_db(scalar_return=None):
    """Create a mock AsyncSession whose execute().scalar_one_or_none() returns *scalar_return*."""
    db = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = scalar_return
    db.execute.return_value = result_mock
    return db


def _make_credentials(token="valid-token"):
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


class TestGetCurrentUser:
    """Tests for get_current_user dependency."""

    @pytest.mark.asyncio
    @patch(
        "app.api.deps.decode_token",
        return_value={"sub": "42", "role": "rider", "type": "access"},
    )
    async def test_returns_active_user(self, mock_decode):
        from app.api.deps import get_current_user

        user = _make_user(user_id=42, is_active=True)
        db = _mock_db(scalar_return=user)
        creds = _make_credentials("good-token")

        result = await get_current_user(credentials=creds, db=db)
        assert result is user
        mock_decode.assert_called_once_with("good-token")

    @pytest.mark.asyncio
    @patch("app.api.deps.decode_token", side_effect=ValueError("bad token"))
    async def test_invalid_token_raises_401(self, mock_decode):
        from app.api.deps import get_current_user

        db = _mock_db()
        creds = _make_credentials("bad-token")

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(credentials=creds, db=db)
        assert exc_info.value.status_code == 401
        assert "invalid token" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    @patch(
        "app.api.deps.decode_token",
        return_value={"sub": "42", "role": "rider", "type": "refresh"},
    )
    async def test_refresh_token_type_raises_401(self, mock_decode):
        from app.api.deps import get_current_user

        db = _mock_db()
        creds = _make_credentials("refresh-token")

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(credentials=creds, db=db)
        assert exc_info.value.status_code == 401
        assert "invalid token type" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    @patch(
        "app.api.deps.decode_token",
        return_value={"sub": "99", "role": "rider", "type": "access"},
    )
    async def test_user_not_found_raises_401(self, mock_decode):
        from app.api.deps import get_current_user

        db = _mock_db(scalar_return=None)
        creds = _make_credentials("orphan-token")

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(credentials=creds, db=db)
        assert exc_info.value.status_code == 401
        assert "user not found" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    @patch(
        "app.api.deps.decode_token",
        return_value={"sub": "42", "role": "rider", "type": "access"},
    )
    async def test_inactive_user_raises_401(self, mock_decode):
        from app.api.deps import get_current_user

        user = _make_user(user_id=42, is_active=False)
        db = _mock_db(scalar_return=user)
        creds = _make_credentials("inactive-user-token")

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(credentials=creds, db=db)
        assert exc_info.value.status_code == 401
        assert "user not found" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    @patch(
        "app.api.deps.decode_token",
        return_value={"sub": "10", "role": "driver", "type": "access"},
    )
    async def test_returns_driver_user(self, mock_decode):
        from app.api.deps import get_current_user

        user = _make_user(user_id=10, role=UserRole.DRIVER, is_active=True)
        db = _mock_db(scalar_return=user)
        creds = _make_credentials("driver-token")

        result = await get_current_user(credentials=creds, db=db)
        assert result.role == UserRole.DRIVER

    @pytest.mark.asyncio
    @patch(
        "app.api.deps.decode_token",
        return_value={"sub": "1", "role": "admin", "type": "access"},
    )
    async def test_returns_admin_user(self, mock_decode):
        from app.api.deps import get_current_user

        user = _make_user(user_id=1, role=UserRole.ADMIN, is_active=True)
        db = _mock_db(scalar_return=user)
        creds = _make_credentials("admin-token")

        result = await get_current_user(credentials=creds, db=db)
        assert result.role == UserRole.ADMIN


class TestRequireDriver:
    """Tests for require_driver dependency."""

    @pytest.mark.asyncio
    async def test_driver_passes(self):
        from app.api.deps import require_driver

        user = _make_user(role=UserRole.DRIVER)
        result = await require_driver(user=user)
        assert result is user

    @pytest.mark.asyncio
    async def test_rider_rejected(self):
        from app.api.deps import require_driver

        user = _make_user(role=UserRole.RIDER)
        with pytest.raises(HTTPException) as exc_info:
            await require_driver(user=user)
        assert exc_info.value.status_code == 403
        assert "driver access required" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_admin_rejected(self):
        from app.api.deps import require_driver

        user = _make_user(role=UserRole.ADMIN)
        with pytest.raises(HTTPException) as exc_info:
            await require_driver(user=user)
        assert exc_info.value.status_code == 403


class TestRequireAdmin:
    """Tests for require_admin dependency."""

    @pytest.mark.asyncio
    async def test_admin_passes(self):
        from app.api.deps import require_admin

        user = _make_user(role=UserRole.ADMIN)
        result = await require_admin(user=user)
        assert result is user

    @pytest.mark.asyncio
    async def test_rider_rejected(self):
        from app.api.deps import require_admin

        user = _make_user(role=UserRole.RIDER)
        with pytest.raises(HTTPException) as exc_info:
            await require_admin(user=user)
        assert exc_info.value.status_code == 403
        assert "admin access required" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_driver_rejected(self):
        from app.api.deps import require_admin

        user = _make_user(role=UserRole.DRIVER)
        with pytest.raises(HTTPException) as exc_info:
            await require_admin(user=user)
        assert exc_info.value.status_code == 403
