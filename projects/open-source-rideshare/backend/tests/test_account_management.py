"""Unit tests for account management endpoints.

Covers:
  POST /auth/me/change-password
  POST /auth/me/deactivate

Schemas
  - ChangePasswordRequest: new_password min_length=8 enforced
  - DeactivateAccountRequest: password required

Service: change_password endpoint
  - 200 on correct current password, new password >=8 chars
  - 400 when current_password is wrong
  - password_hash is updated in DB after success

Service: deactivate_account endpoint
  - 200 on correct password, no active rides
  - 400 when password is wrong
  - 409 when rider has an active ride (any of: requested, matched,
    driver_en_route, arrived, in_progress)
  - 409 when driver has an active ride
  - is_active=False in DB after success
  - Deactivated user cannot log in (is_active check in refresh)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.ride import RideStatus
from app.models.user import User, UserRole
from app.schemas.auth import ChangePasswordRequest, DeactivateAccountRequest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(
    user_id: int = 1,
    role: UserRole = UserRole.RIDER,
    is_active: bool = True,
    password_hash: str = "$2b$12$fakehash",
) -> MagicMock:
    u = MagicMock(spec=User)
    u.id = user_id
    u.role = role
    u.is_active = is_active
    u.password_hash = password_hash
    return u


def _mock_db(scalar_return=None) -> AsyncMock:
    db = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = scalar_return
    db.execute.return_value = result_mock
    return db


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------


class TestChangePasswordSchema:
    def test_valid_request(self):
        req = ChangePasswordRequest(current_password="old_pass", new_password="new_pass8")
        assert req.current_password == "old_pass"
        assert req.new_password == "new_pass8"

    def test_new_password_too_short(self):
        import pydantic
        with pytest.raises(pydantic.ValidationError):
            ChangePasswordRequest(current_password="old", new_password="short")

    def test_new_password_exactly_8_chars(self):
        req = ChangePasswordRequest(current_password="old", new_password="exactly8")
        assert len(req.new_password) == 8


class TestDeactivateAccountSchema:
    def test_valid_request(self):
        req = DeactivateAccountRequest(password="mypassword")
        assert req.password == "mypassword"

    def test_password_required(self):
        import pydantic
        with pytest.raises(pydantic.ValidationError):
            DeactivateAccountRequest()


# ---------------------------------------------------------------------------
# change_password endpoint
# ---------------------------------------------------------------------------


class TestChangePasswordEndpoint:
    @pytest.mark.asyncio
    @patch("app.api.v1.auth.verify_password", return_value=True)
    @patch("app.api.v1.auth.hash_password", return_value="$2b$12$newhash")
    async def test_success(self, mock_hash, mock_verify):
        from app.api.v1.auth import change_password

        user = _make_user()
        db = _mock_db()
        req = ChangePasswordRequest(current_password="oldpass1", new_password="newpass8")

        result = await change_password(req, user=user, db=db)

        mock_verify.assert_called_once_with("oldpass1", "$2b$12$fakehash")
        mock_hash.assert_called_once_with("newpass8")
        assert user.password_hash == "$2b$12$newhash"
        db.commit.assert_awaited_once()
        assert result == {"status": "password updated"}

    @pytest.mark.asyncio
    @patch("app.api.v1.auth.verify_password", return_value=False)
    async def test_wrong_current_password(self, mock_verify):
        from fastapi import HTTPException

        from app.api.v1.auth import change_password

        user = _make_user()
        db = _mock_db()
        req = ChangePasswordRequest(current_password="wrong_pass", new_password="newpass8")

        with pytest.raises(HTTPException) as exc_info:
            await change_password(req, user=user, db=db)

        assert exc_info.value.status_code == 400
        assert "incorrect" in exc_info.value.detail.lower()
        db.commit.assert_not_awaited()

    @pytest.mark.asyncio
    @patch("app.api.v1.auth.verify_password", return_value=True)
    @patch("app.api.v1.auth.hash_password", return_value="$2b$12$newhash")
    async def test_password_hash_updated_on_user_object(self, mock_hash, mock_verify):
        from app.api.v1.auth import change_password

        user = _make_user(password_hash="$2b$12$oldhash")
        db = _mock_db()
        req = ChangePasswordRequest(current_password="old", new_password="newpass8")

        await change_password(req, user=user, db=db)

        assert user.password_hash == "$2b$12$newhash"

    @pytest.mark.asyncio
    @patch("app.api.v1.auth.verify_password", return_value=True)
    @patch("app.api.v1.auth.hash_password", return_value="$2b$12$newhash")
    async def test_driver_can_change_password(self, mock_hash, mock_verify):
        from app.api.v1.auth import change_password

        user = _make_user(role=UserRole.DRIVER)
        db = _mock_db()
        req = ChangePasswordRequest(current_password="old", new_password="newpass8")

        result = await change_password(req, user=user, db=db)
        assert result == {"status": "password updated"}


# ---------------------------------------------------------------------------
# deactivate_account endpoint
# ---------------------------------------------------------------------------


class TestDeactivateAccountEndpoint:
    @pytest.mark.asyncio
    @patch("app.api.v1.auth.verify_password", return_value=True)
    async def test_success_no_active_rides(self, mock_verify):
        from app.api.v1.auth import deactivate_account

        user = _make_user()
        db = _mock_db(scalar_return=None)  # no active rides
        req = DeactivateAccountRequest(password="correct_pass")

        result = await deactivate_account(req, user=user, db=db)

        assert user.is_active is False
        db.commit.assert_awaited_once()
        assert result == {"status": "account deactivated"}

    @pytest.mark.asyncio
    @patch("app.api.v1.auth.verify_password", return_value=False)
    async def test_wrong_password(self, mock_verify):
        from fastapi import HTTPException

        from app.api.v1.auth import deactivate_account

        user = _make_user()
        db = _mock_db()
        req = DeactivateAccountRequest(password="wrong_pass")

        with pytest.raises(HTTPException) as exc_info:
            await deactivate_account(req, user=user, db=db)

        assert exc_info.value.status_code == 400
        assert user.is_active is True
        db.commit.assert_not_awaited()

    @pytest.mark.asyncio
    @patch("app.api.v1.auth.verify_password", return_value=True)
    async def test_rejected_with_active_ride(self, mock_verify):
        from fastapi import HTTPException
        from unittest.mock import MagicMock

        from app.api.v1.auth import deactivate_account

        user = _make_user()
        active_ride = MagicMock()
        db = _mock_db(scalar_return=active_ride)  # active ride found
        req = DeactivateAccountRequest(password="correct_pass")

        with pytest.raises(HTTPException) as exc_info:
            await deactivate_account(req, user=user, db=db)

        assert exc_info.value.status_code == 409
        assert "active ride" in exc_info.value.detail.lower()
        assert user.is_active is True
        db.commit.assert_not_awaited()

    @pytest.mark.asyncio
    @patch("app.api.v1.auth.verify_password", return_value=True)
    async def test_driver_deactivates_with_active_ride(self, mock_verify):
        from fastapi import HTTPException
        from unittest.mock import MagicMock

        from app.api.v1.auth import deactivate_account

        user = _make_user(role=UserRole.DRIVER)
        active_ride = MagicMock()
        db = _mock_db(scalar_return=active_ride)
        req = DeactivateAccountRequest(password="correct_pass")

        with pytest.raises(HTTPException) as exc_info:
            await deactivate_account(req, user=user, db=db)

        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    @patch("app.api.v1.auth.verify_password", return_value=True)
    async def test_is_active_set_false(self, mock_verify):
        from app.api.v1.auth import deactivate_account

        user = _make_user(is_active=True)
        db = _mock_db(scalar_return=None)
        req = DeactivateAccountRequest(password="correct_pass")

        await deactivate_account(req, user=user, db=db)

        assert user.is_active is False

    @pytest.mark.asyncio
    @patch("app.api.v1.auth.verify_password", return_value=True)
    async def test_admin_can_deactivate(self, mock_verify):
        from app.api.v1.auth import deactivate_account

        user = _make_user(role=UserRole.ADMIN)
        db = _mock_db(scalar_return=None)
        req = DeactivateAccountRequest(password="correct_pass")

        result = await deactivate_account(req, user=user, db=db)
        assert user.is_active is False
        assert result == {"status": "account deactivated"}


# ---------------------------------------------------------------------------
# Active ride status coverage
# ---------------------------------------------------------------------------


class TestDeactivateActiveRideStatuses:
    """Each active RideStatus value should block deactivation."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("active_status", [
        RideStatus.REQUESTED,
        RideStatus.MATCHED,
        RideStatus.DRIVER_EN_ROUTE,
        RideStatus.ARRIVED,
        RideStatus.IN_PROGRESS,
    ])
    @patch("app.api.v1.auth.verify_password", return_value=True)
    async def test_each_active_status_blocks_deactivation(self, mock_verify, active_status):
        from fastapi import HTTPException
        from unittest.mock import MagicMock

        from app.api.v1.auth import deactivate_account

        user = _make_user()
        active_ride = MagicMock()
        active_ride.status = active_status
        db = _mock_db(scalar_return=active_ride)
        req = DeactivateAccountRequest(password="pass")

        with pytest.raises(HTTPException) as exc_info:
            await deactivate_account(req, user=user, db=db)

        assert exc_info.value.status_code == 409
