"""Unit tests for auth API endpoint handlers (register, login, refresh)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.models.user import User, UserRole
from app.schemas.auth import LoginRequest, RefreshRequest, RegisterRequest


def _make_user(
    user_id=1,
    phone="+15551234567",
    name="Test User",
    email="test@example.com",
    role=UserRole.RIDER,
    is_active=True,
    password_hash="$2b$12$fakehash",
):
    user = MagicMock(spec=User)
    user.id = user_id
    user.phone = phone
    user.name = name
    user.email = email
    user.role = role
    user.is_active = is_active
    user.password_hash = password_hash
    return user


def _mock_db(scalar_return=None):
    """Create a mock AsyncSession whose execute().scalar_one_or_none() returns *scalar_return*."""
    db = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = scalar_return
    db.execute.return_value = result_mock
    return db


class TestRegisterEndpoint:
    """Async tests for POST /auth/register handler."""

    @pytest.mark.asyncio
    @patch("app.services.promos.create_referral_promo", new_callable=AsyncMock)
    @patch("app.models.promo.generate_referral_code", return_value="REF12345")
    @patch("app.api.v1.auth.create_refresh_token", return_value="fake-refresh")
    @patch("app.api.v1.auth.create_access_token", return_value="fake-access")
    @patch("app.api.v1.auth.hash_password", return_value="$2b$12$hashed")
    async def test_register_new_rider(self, mock_hash, mock_access, mock_refresh, mock_gen_ref, mock_create_ref):
        from app.api.v1.auth import register

        db = _mock_db(scalar_return=None)  # no existing user with this phone

        req = RegisterRequest(
            phone="+15559999999",
            name="New Rider",
            password="securepass",
            email="new@example.com",
            role="rider",
        )
        result = await register(req=req, db=db)

        assert result.access_token == "fake-access"
        assert result.refresh_token == "fake-refresh"
        db.add.assert_called_once()
        mock_hash.assert_called_once_with("securepass")

    @pytest.mark.asyncio
    @patch("app.services.promos.create_referral_promo", new_callable=AsyncMock)
    @patch("app.models.promo.generate_referral_code", return_value="REF12345")
    @patch("app.api.v1.auth.create_refresh_token", return_value="fake-refresh")
    @patch("app.api.v1.auth.create_access_token", return_value="fake-access")
    @patch("app.api.v1.auth.hash_password", return_value="$2b$12$hashed")
    async def test_register_new_driver(self, mock_hash, mock_access, mock_refresh, mock_gen_ref, mock_create_ref):
        from app.api.v1.auth import register

        db = _mock_db(scalar_return=None)

        req = RegisterRequest(
            phone="+15558888888",
            name="New Driver",
            password="driverpass",
            role="driver",
        )
        result = await register(req=req, db=db)

        assert result.access_token == "fake-access"
        assert result.refresh_token == "fake-refresh"
        db.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_register_duplicate_phone_raises_400(self):
        from app.api.v1.auth import register

        existing_user = _make_user(phone="+15551111111")
        db = _mock_db(scalar_return=existing_user)

        req = RegisterRequest(
            phone="+15551111111",
            name="Duplicate",
            password="pass123",
        )
        with pytest.raises(HTTPException) as exc_info:
            await register(req=req, db=db)
        assert exc_info.value.status_code == 400
        assert "already registered" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    @patch("app.services.promos.create_referral_promo", new_callable=AsyncMock)
    @patch("app.models.promo.generate_referral_code", return_value="REF12345")
    @patch("app.api.v1.auth.create_refresh_token", return_value="fake-refresh")
    @patch("app.api.v1.auth.create_access_token", return_value="fake-access")
    @patch("app.api.v1.auth.hash_password", return_value="$2b$12$hashed")
    async def test_register_without_email(self, mock_hash, mock_access, mock_refresh, mock_gen_ref, mock_create_ref):
        from app.api.v1.auth import register

        db = _mock_db(scalar_return=None)

        req = RegisterRequest(
            phone="+15557777777",
            name="No Email",
            password="pass123",
        )
        result = await register(req=req, db=db)
        assert result.access_token == "fake-access"
        db.add.assert_called_once()


class TestLoginEndpoint:
    """Async tests for POST /auth/login handler."""

    @pytest.mark.asyncio
    @patch("app.api.v1.auth.create_refresh_token", return_value="login-refresh")
    @patch("app.api.v1.auth.create_access_token", return_value="login-access")
    @patch("app.api.v1.auth.verify_password", return_value=True)
    async def test_login_success(self, mock_verify, mock_access, mock_refresh):
        from app.api.v1.auth import login

        user = _make_user(user_id=42, phone="+15551234567", role=UserRole.RIDER)
        db = _mock_db(scalar_return=user)

        req = LoginRequest(phone="+15551234567", password="correctpass")
        result = await login(req=req, db=db)

        assert result.access_token == "login-access"
        assert result.refresh_token == "login-refresh"
        mock_verify.assert_called_once_with("correctpass", user.password_hash)

    @pytest.mark.asyncio
    @patch("app.api.v1.auth.verify_password", return_value=False)
    async def test_login_wrong_password(self, mock_verify):
        from app.api.v1.auth import login

        user = _make_user()
        db = _mock_db(scalar_return=user)

        req = LoginRequest(phone="+15551234567", password="wrongpass")
        with pytest.raises(HTTPException) as exc_info:
            await login(req=req, db=db)
        assert exc_info.value.status_code == 401
        assert "invalid credentials" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_login_nonexistent_user(self):
        from app.api.v1.auth import login

        db = _mock_db(scalar_return=None)

        req = LoginRequest(phone="+15550000000", password="anypass")
        with pytest.raises(HTTPException) as exc_info:
            await login(req=req, db=db)
        assert exc_info.value.status_code == 401
        assert "invalid credentials" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    @patch("app.api.v1.auth.create_refresh_token", return_value="driver-refresh")
    @patch("app.api.v1.auth.create_access_token", return_value="driver-access")
    @patch("app.api.v1.auth.verify_password", return_value=True)
    async def test_login_driver_role(self, mock_verify, mock_access, mock_refresh):
        from app.api.v1.auth import login

        user = _make_user(user_id=10, role=UserRole.DRIVER)
        db = _mock_db(scalar_return=user)

        req = LoginRequest(phone="+15551234567", password="driverpass")
        result = await login(req=req, db=db)

        assert result.access_token == "driver-access"
        mock_access.assert_called_once_with(user.id, user.role.value)


class TestRefreshEndpoint:
    """Async tests for POST /auth/refresh handler."""

    @pytest.mark.asyncio
    @patch("app.api.v1.auth.create_refresh_token", return_value="new-refresh")
    @patch("app.api.v1.auth.create_access_token", return_value="new-access")
    @patch(
        "app.api.v1.auth.decode_token",
        return_value={"sub": "42", "type": "refresh", "exp": 9999999999},
    )
    async def test_refresh_success(self, mock_decode, mock_access, mock_refresh):
        from app.api.v1.auth import refresh

        user = _make_user(user_id=42, is_active=True)
        db = _mock_db(scalar_return=user)

        req = RefreshRequest(refresh_token="valid-refresh-token")
        result = await refresh(req=req, db=db)

        assert result.access_token == "new-access"
        assert result.refresh_token == "new-refresh"
        mock_decode.assert_called_once_with("valid-refresh-token")

    @pytest.mark.asyncio
    @patch("app.api.v1.auth.decode_token", side_effect=ValueError("Invalid token"))
    async def test_refresh_invalid_token(self, mock_decode):
        from app.api.v1.auth import refresh

        db = _mock_db()

        req = RefreshRequest(refresh_token="garbage-token")
        with pytest.raises(HTTPException) as exc_info:
            await refresh(req=req, db=db)
        assert exc_info.value.status_code == 401
        assert "invalid refresh token" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    @patch(
        "app.api.v1.auth.decode_token",
        return_value={"sub": "42", "type": "access", "exp": 9999999999},
    )
    async def test_refresh_with_access_token_type(self, mock_decode):
        from app.api.v1.auth import refresh

        db = _mock_db()

        req = RefreshRequest(refresh_token="access-token-not-refresh")
        with pytest.raises(HTTPException) as exc_info:
            await refresh(req=req, db=db)
        assert exc_info.value.status_code == 401
        assert "invalid token type" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    @patch(
        "app.api.v1.auth.decode_token",
        return_value={"sub": "99", "type": "refresh", "exp": 9999999999},
    )
    async def test_refresh_user_not_found(self, mock_decode):
        from app.api.v1.auth import refresh

        db = _mock_db(scalar_return=None)  # user doesn't exist

        req = RefreshRequest(refresh_token="valid-but-user-gone")
        with pytest.raises(HTTPException) as exc_info:
            await refresh(req=req, db=db)
        assert exc_info.value.status_code == 401
        assert "user not found" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    @patch(
        "app.api.v1.auth.decode_token",
        return_value={"sub": "42", "type": "refresh", "exp": 9999999999},
    )
    async def test_refresh_inactive_user(self, mock_decode):
        from app.api.v1.auth import refresh

        user = _make_user(user_id=42, is_active=False)
        db = _mock_db(scalar_return=user)

        req = RefreshRequest(refresh_token="valid-refresh-token")
        with pytest.raises(HTTPException) as exc_info:
            await refresh(req=req, db=db)
        assert exc_info.value.status_code == 401
        assert "user not found" in exc_info.value.detail.lower()
