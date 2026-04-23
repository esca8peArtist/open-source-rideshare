"""Unit tests for POST /auth/me/change-email.

Covers:
  - 200 on correct password, new email not already taken
  - 400 when password is wrong
  - 400 when new_email equals current email
  - 409 when new_email already registered to another user
  - user.email field updated on success
  - schema: new_email validated as a valid email address
  - drivers and admins can change email
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.user import User, UserRole
from app.schemas.auth import ChangeEmailRequest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(
    user_id: int = 1,
    email: str | None = "alice@example.com",
    role: UserRole = UserRole.RIDER,
    is_active: bool = True,
    password_hash: str = "$2b$12$fakehash",
) -> MagicMock:
    u = MagicMock(spec=User)
    u.id = user_id
    u.email = email
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
# ChangeEmailRequest schema
# ---------------------------------------------------------------------------


class TestChangeEmailSchema:
    def test_valid_request(self):
        req = ChangeEmailRequest(password="mypass", new_email="new@example.com")
        assert req.new_email == "new@example.com"

    def test_invalid_email_rejected(self):
        import pydantic
        with pytest.raises(pydantic.ValidationError):
            ChangeEmailRequest(password="mypass", new_email="not-an-email")

    def test_password_required(self):
        import pydantic
        with pytest.raises(pydantic.ValidationError):
            ChangeEmailRequest(new_email="new@example.com")

    def test_new_email_required(self):
        import pydantic
        with pytest.raises(pydantic.ValidationError):
            ChangeEmailRequest(password="mypass")

    def test_domain_normalised_lowercase(self):
        req = ChangeEmailRequest(password="mypass", new_email="New@Example.COM")
        # EmailStr normalises the domain to lowercase per RFC 5321
        assert req.new_email.endswith("@example.com")


# ---------------------------------------------------------------------------
# change_email endpoint
# ---------------------------------------------------------------------------


class TestChangeEmailEndpoint:
    @pytest.mark.asyncio
    @patch("app.api.v1.auth.verify_password", return_value=True)
    async def test_success(self, mock_verify):
        from app.api.v1.auth import change_email

        user = _make_user(email="alice@example.com")
        db = _mock_db(scalar_return=None)  # new email not taken
        req = ChangeEmailRequest(password="correct", new_email="newalice@example.com")

        result = await change_email(req, user=user, db=db)

        assert result == {"status": "email updated"}
        assert user.email == "newalice@example.com"
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    @patch("app.api.v1.auth.verify_password", return_value=False)
    async def test_wrong_password(self, mock_verify):
        from fastapi import HTTPException

        from app.api.v1.auth import change_email

        user = _make_user()
        db = _mock_db()
        req = ChangeEmailRequest(password="wrong", new_email="newalice@example.com")

        with pytest.raises(HTTPException) as exc_info:
            await change_email(req, user=user, db=db)

        assert exc_info.value.status_code == 400
        assert "password" in exc_info.value.detail.lower()
        db.commit.assert_not_awaited()

    @pytest.mark.asyncio
    @patch("app.api.v1.auth.verify_password", return_value=True)
    async def test_same_email_rejected(self, mock_verify):
        from fastapi import HTTPException

        from app.api.v1.auth import change_email

        user = _make_user(email="alice@example.com")
        db = _mock_db()
        req = ChangeEmailRequest(password="correct", new_email="alice@example.com")

        with pytest.raises(HTTPException) as exc_info:
            await change_email(req, user=user, db=db)

        assert exc_info.value.status_code == 400
        assert "same" in exc_info.value.detail.lower()
        db.commit.assert_not_awaited()

    @pytest.mark.asyncio
    @patch("app.api.v1.auth.verify_password", return_value=True)
    async def test_email_already_taken(self, mock_verify):
        from fastapi import HTTPException

        from app.api.v1.auth import change_email

        user = _make_user(email="alice@example.com")
        other_user = MagicMock()
        db = _mock_db(scalar_return=other_user)  # new email already registered
        req = ChangeEmailRequest(password="correct", new_email="taken@example.com")

        with pytest.raises(HTTPException) as exc_info:
            await change_email(req, user=user, db=db)

        assert exc_info.value.status_code == 409
        assert "already in use" in exc_info.value.detail.lower()
        db.commit.assert_not_awaited()

    @pytest.mark.asyncio
    @patch("app.api.v1.auth.verify_password", return_value=True)
    async def test_email_field_updated_on_user(self, mock_verify):
        from app.api.v1.auth import change_email

        user = _make_user(email="old@example.com")
        db = _mock_db(scalar_return=None)
        req = ChangeEmailRequest(password="correct", new_email="new@example.com")

        await change_email(req, user=user, db=db)

        assert user.email == "new@example.com"

    @pytest.mark.asyncio
    @patch("app.api.v1.auth.verify_password", return_value=True)
    async def test_user_with_no_current_email_can_set_one(self, mock_verify):
        from app.api.v1.auth import change_email

        user = _make_user(email=None)
        db = _mock_db(scalar_return=None)
        req = ChangeEmailRequest(password="correct", new_email="fresh@example.com")

        result = await change_email(req, user=user, db=db)

        assert result == {"status": "email updated"}
        assert user.email == "fresh@example.com"

    @pytest.mark.asyncio
    @patch("app.api.v1.auth.verify_password", return_value=True)
    async def test_driver_can_change_email(self, mock_verify):
        from app.api.v1.auth import change_email

        user = _make_user(role=UserRole.DRIVER, email="driver@example.com")
        db = _mock_db(scalar_return=None)
        req = ChangeEmailRequest(password="correct", new_email="newdriver@example.com")

        result = await change_email(req, user=user, db=db)

        assert result == {"status": "email updated"}

    @pytest.mark.asyncio
    @patch("app.api.v1.auth.verify_password", return_value=True)
    async def test_admin_can_change_email(self, mock_verify):
        from app.api.v1.auth import change_email

        user = _make_user(role=UserRole.ADMIN, email="admin@example.com")
        db = _mock_db(scalar_return=None)
        req = ChangeEmailRequest(password="correct", new_email="newadmin@example.com")

        result = await change_email(req, user=user, db=db)

        assert result == {"status": "email updated"}
